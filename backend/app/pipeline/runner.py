"""Pipeline orchestrator + state machine (stories/{id}/state.json).

created -> story_running -> story_done -> images_running -> images_done
        -> voice_running -> voice_done -> subtitles_running -> subtitles_done
        -> hook_running -> hook_done -> render_running -> done ;
        any stage -> failed_{stage}

Stages are strictly ordered and resumable: each stage skips outputs that
already exist, so re-running a failed story continues, never restarts.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..config import settings
from ..models import Bible, Script, StoryInput, StoryState
from ..utils.log import PipelineLog, logger
from .hook import run_hook_pipeline
from .images import run_image_pipeline
from .render import run_render
from .story_engine import run_story_engine
from .subtitles import run_subtitles
from .voice import run_voice_pipeline

_running: set[str] = set()  # one runner per story at a time


def load_state(story_dir: Path) -> StoryState:
    path = story_dir / "state.json"
    if path.exists():
        # utf-8-sig tolerates BOM-prefixed files from Windows editors/tools
        return StoryState.model_validate_json(path.read_text(encoding="utf-8-sig"))
    return StoryState()


def save_state(story_dir: Path, state: StoryState) -> None:
    state.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    (story_dir / "state.json").write_text(state.model_dump_json(indent=2),
                                          encoding="utf-8")


def load_input(story_dir: Path) -> StoryInput:
    return StoryInput.model_validate_json(
        (story_dir / "input.json").read_text(encoding="utf-8"))


def sweep_orphaned_runs() -> None:
    """Server (re)start: background tasks never survive a restart (e.g.
    uvicorn --reload), so any story still in a *_running state is orphaned —
    park it as failed_{stage} so POST /retry can resume it."""
    for state_path in settings.stories_dir.glob("*/state.json"):
        story_dir = state_path.parent
        try:
            state = load_state(story_dir)
        except Exception as exc:
            # one corrupt state.json must never take the whole server down
            logger.warning("sweep: skipping unreadable state.json in %s: %s",
                           story_dir.name, exc)
            continue
        if not state.state.endswith("_running"):
            continue
        stage = state.state.removesuffix("_running")
        state.state = f"failed_{stage}"
        state.error = "server restarted while this stage was running — retry to resume"
        state.retryable = True
        save_state(story_dir, state)
        PipelineLog(story_dir).event("runner", "orphaned_run_parked",
                                     detail=f"{stage}: server restart")
        logger.info("parked orphaned run %s at stage %s", story_dir.name, stage)


async def run_pipeline(story_id: str) -> None:
    if story_id in _running:
        logger.info("runner already active for %s — skipping", story_id)
        return
    _running.add(story_id)
    try:
        await _run(story_id)
    finally:
        _running.discard(story_id)


async def _run(story_id: str) -> None:
    story_dir = settings.story_dir(story_id)
    log = PipelineLog(story_dir)
    inp = load_input(story_dir)
    state = load_state(story_dir)
    if state.state == "done":
        return

    stage = "story"

    def update(new_state: str, done: int = 0, total: int = 0) -> None:
        state.state = new_state
        state.progress_done = done
        state.progress_total = total
        state.error = None
        save_state(story_dir, state)

    async def progress(done: int, total: int) -> None:
        state.progress_done = done
        state.progress_total = total
        save_state(story_dir, state)

    try:
        # [1] story engine (4 passes, includes [2] asset bible)
        update("story_running")
        script = await run_story_engine(story_dir, inp)
        update("story_done")

        bible = Bible.model_validate_json(
            (story_dir / "bible.json").read_text(encoding="utf-8"))

        # [3] images
        stage = "images"
        update("images_running", 0, len(script.scenes))
        await run_image_pipeline(story_dir, inp, script, bible, on_progress=progress)
        update("images_done")

        # [4] voice
        stage = "voice"
        update("voice_running", 0, len(script.scenes))
        _, warnings = await run_voice_pipeline(
            story_dir, script, inp.duration_minutes,
            narrator_voice=inp.narrator_voice, on_progress=progress)
        state.warnings = warnings
        update("voice_done")

        # [4.5] subtitles ($0 — always writes srt; burn-in decided at render)
        stage = "subtitles"
        update("subtitles_running")
        run_subtitles(story_dir, script, inp.video_format)
        update("subtitles_done")

        # [4.75] Seedance short hook from a one-frame storyboard
        stage = "hook"
        update("hook_running", 0, 1)
        await run_hook_pipeline(story_dir, inp, script, bible, on_progress=progress)
        update("hook_done")

        # [5] sync + render
        stage = "render"
        update("render_running", 0, len(script.scenes))
        await run_render(story_dir, inp, script, on_progress=progress)
        update("done")
        log.event("runner", "done")

    except Exception as exc:  # never crash the server — park in failed_{stage}
        logger.exception("pipeline failed for %s at stage %s", story_id, stage)
        state.state = f"failed_{stage}"
        state.error = str(exc)[:1000]
        state.retryable = True
        save_state(story_dir, state)
        log.event("runner", "failed", detail=f"{stage}: {exc}")
