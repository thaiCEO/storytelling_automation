"""FastAPI app — endpoints per skills/project-structure.md."""
from __future__ import annotations

import json
import io
import uuid
from pathlib import Path

from fastapi import (BackgroundTasks, FastAPI, File, Form, HTTPException,
                     UploadFile)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError

from .clients.atlas import AtlasError, atlas
from .config import settings
from .models import (Bible, ReferenceImage, StoryInput, StoryState, UserPrefs,
                     canonical_view)
from .pipeline.runner import (load_state, run_pipeline, save_state,
                              sweep_orphaned_runs)
from .utils import cost as cost_util

app = FastAPI(title="Story Automation")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # dev; restrict to the Nuxt origin in production
    allow_methods=["*"],
    allow_headers=["*"],
)

settings.stories_dir.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=settings.stories_dir), name="media")


SHEET_FILENAME_KEYWORDS = (
    "character sheet", "character_sheet", "turnaround", "refsheet",
    "model sheet", "model_sheet", "reference sheet", "reference_sheet",
    "multi-view", "multiview",
)


def _looks_like_character_sheet_upload(
    kind: str, view: str, filename: str | None, content: bytes
) -> bool:
    if kind != "character" or canonical_view(view) != "ref_front":
        return False

    name = (filename or "").lower()
    if any(keyword in name for keyword in SHEET_FILENAME_KEYWORDS):
        return True

    try:
        with Image.open(io.BytesIO(content)) as img:
            width, height = img.size
    except (UnidentifiedImageError, OSError):
        return False

    # Character sheets are commonly wide collages with multiple poses/views.
    return width >= 1000 and height >= 500 and width / max(height, 1) >= 1.55


class StoryCreate(StoryInput):
    # autostart=False lets the UI upload reference images first, then
    # kick the pipeline off via POST /api/stories/{id}/retry
    autostart: bool = True


def _story_dir(story_id: str) -> Path:
    d = settings.story_dir(story_id)
    if not d.exists():
        raise HTTPException(404, f"story {story_id} not found")
    return d


@app.get("/api/estimate")
def estimate(duration_minutes: int = 7, image_model: str = "auto",
             tts_model: str | None = None, hook_enabled: bool = False):
    """Live cost estimate for the UI — no story created."""
    if not 1 <= duration_minutes <= 15:
        raise HTTPException(422, "duration_minutes must be 1-15")
    if image_model not in ("auto", "gpt-image-2", "nano-banana-2", "flux-schnell", "grok-imagine"):
        raise HTTPException(422, f"unknown image_model '{image_model}'")
    return cost_util.estimate(duration_minutes, image_model, tts_model, hook_enabled)


@app.post("/api/stories", status_code=201)
def create_story(body: StoryCreate, background: BackgroundTasks):
    story_id = uuid.uuid4().hex[:12]
    story_dir = settings.story_dir(story_id)
    story_dir.mkdir(parents=True)

    inp = StoryInput.model_validate(body.model_dump(exclude={"autostart"}))
    (story_dir / "input.json").write_text(inp.model_dump_json(indent=2),
                                          encoding="utf-8")
    (story_dir / "estimate.json").write_text(
        json.dumps(cost_util.estimate(
            inp.duration_minutes, inp.image_model,
            hook_enabled=inp.hook_enabled,
        )),
        encoding="utf-8")
    save_state(story_dir, StoryState(state="created"))

    if body.autostart:
        background.add_task(run_pipeline, story_id)
    return {"story_id": story_id, "state": "created", "autostart": body.autostart}


@app.post("/api/stories/{story_id}/references")
async def upload_reference(story_id: str, kind: str = Form(...),
                           name: str = Form(""), view: str = Form("front"),
                           mode: str = Form("world"), role: str = Form(""),
                           is_character_sheet: bool = Form(False),
                           rights_confirmed: bool = Form(False),
                           file: UploadFile = File(...)):
    """Multipart upload -> Atlas uploadMedia -> public url stored on the input.

    kind: character | location | object; name: user-given asset name (e.g.
    "KAIRA"); view: front (master identity) | side | back | pose | expression;
    mode (locations only): world = photo defines the world aesthetic, scenes
    vary | exact = same spot locked in every scene.
    """
    story_dir = _story_dir(story_id)
    if not rights_confirmed:
        raise HTTPException(422, "you must confirm you own/have rights to this image")
    if file.content_type not in ("image/jpeg", "image/png"):
        raise HTTPException(422, "JPG/PNG only")
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(422, "file exceeds 10 MB")

    try:
        url = await atlas.upload_media(content, file.filename or "reference.png",
                                       file.content_type)
    except AtlasError as e:
        raise HTTPException(502, f"reference upload failed: {e}") from e
    except Exception as e:
        raise HTTPException(500, f"reference upload failed unexpectedly: {e}") from e

    sheet = is_character_sheet or _looks_like_character_sheet_upload(
        kind, view, file.filename, content)

    try:
        ref = ReferenceImage(kind=kind, name=name.strip(), view=view,
                             mode=mode, role=role.strip(), url=url,
                             is_character_sheet=sheet)
    except ValidationError as e:
        raise HTTPException(422, str(e))

    input_path = story_dir / "input.json"
    inp = StoryInput.model_validate_json(input_path.read_text(encoding="utf-8"))
    inp.reference_images.append(ref)
    input_path.write_text(inp.model_dump_json(indent=2), encoding="utf-8")
    return ref.model_dump()


# -------- app-level user preferences (default narrator voice, saved on VPS)
PREFS_PATH = settings.stories_dir / "_settings.json"


def _load_prefs() -> UserPrefs:
    if PREFS_PATH.exists():
        return UserPrefs.model_validate_json(PREFS_PATH.read_text(encoding="utf-8"))
    return UserPrefs()


@app.get("/api/settings")
def get_settings():
    """Saved defaults the /create form pre-fills from."""
    return _load_prefs().model_dump()


@app.put("/api/settings")
def update_settings(body: UserPrefs):
    """Persist defaults (e.g. narrator voice) for future videos."""
    PREFS_PATH.write_text(body.model_dump_json(indent=2), encoding="utf-8")
    return body.model_dump()


@app.get("/api/stories/{story_id}/status")
def status(story_id: str):
    story_dir = _story_dir(story_id)
    state = load_state(story_dir)
    costs = cost_util.totals(story_dir)
    est_path = story_dir / "estimate.json"
    estimate = json.loads(est_path.read_text(encoding="utf-8")) if est_path.exists() else None
    over_budget = bool(
        estimate and costs["total"] > estimate["total"] * 1.5)  # warn >50% over
    return {
        "story_id": story_id,
        "state": state.state,
        "progress": {"done": state.progress_done, "total": state.progress_total},
        "error": state.error,
        "retryable": state.retryable,
        "warnings": state.warnings,
        "cost": costs,
        "estimate": estimate,
        "over_budget": over_budget,
    }


@app.get("/api/stories/{story_id}/bible")
def get_bible(story_id: str):
    """Asset Bible — available as soon as Pass 2 finishes, before images."""
    story_dir = _story_dir(story_id)
    state = load_state(story_dir)
    path = story_dir / "bible.json"
    if not path.exists():
        raise HTTPException(409, f"bible not generated yet (state: {state.state})")
    # round-trip through the model so pre-role bibles gain defaults
    # (utf-8-sig also accepts BOM-prefixed files from Windows editors)
    bible = Bible.model_validate_json(path.read_text(encoding="utf-8-sig"))
    title = None
    premise_path = story_dir / "premise.json"
    if premise_path.exists():
        title = json.loads(premise_path.read_text(encoding="utf-8")).get("title")
    return {"story_id": story_id, "title": title, "state": state.state,
            "bible": bible.model_dump()}


@app.post("/api/stories/{story_id}/retry")
def retry(story_id: str, background: BackgroundTasks):
    """Resume from the failed stage (stages skip already-finished outputs)."""
    story_dir = _story_dir(story_id)
    state = load_state(story_dir)
    if state.state == "done":
        raise HTTPException(409, "story already done")
    if not (state.state.startswith("failed_") or state.state == "created"):
        raise HTTPException(409, f"story is busy ({state.state})")
    background.add_task(run_pipeline, story_id)
    return {"story_id": story_id, "resumed_from": state.state}


@app.get("/api/stories/{story_id}/result")
def result(story_id: str):
    story_dir = _story_dir(story_id)
    state = load_state(story_dir)
    if state.state != "done":
        raise HTTPException(409, f"story not finished (state: {state.state})")
    base = f"/media/{story_id}/output"
    return {
        "story_id": story_id,
        "video_url": f"{base}/final.mp4",
        "thumbnail_url": f"{base}/thumbnail.png",
        "srt_url": f"{base}/subs.srt" if (story_dir / "output" / "subs.srt").exists() else None,
        "cost": cost_util.totals(story_dir),
        "warnings": state.warnings,
    }


@app.on_event("startup")
def startup() -> None:
    # no background task survives a restart — free orphaned *_running
    # stories so the retry endpoint stops rejecting them as busy
    sweep_orphaned_runs()


@app.on_event("shutdown")
async def shutdown() -> None:
    await atlas.aclose()
