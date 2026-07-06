"""Stage 4.75 - short Seedance hook from a one-frame storyboard.

Builds one storyboard frame from the finished story assets, asks Seedance 2.0
Mini for a 10-15 second audio/video hook, then normalizes the clip so render.py
can prepend it to the final story export.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..clients.atlas import atlas, parse_llm_json
from ..config import settings
from ..models import Bible, Scene, Script, StoryInput
from ..utils import ffmpeg
from ..utils.cost import PRICES, add_cost
from ..utils.log import PipelineLog
from .formats import FORMATS, FormatSpec
from .timeline import FPS

VIDEO_EXPORT_ARGS = [
    "-c:v", "libx264", "-preset", "slow", "-crf", "18",
    "-pix_fmt", "yuv420p", "-r", str(FPS),
    "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
]

HOOK_STORYBOARD_SYSTEM = """You are a trailer editor creating a short hook
for the beginning of a cinematic storytelling video.
Respond ONLY with valid JSON, no markdown fences.

Rules:
- Write all output in English.
- Select ONE visually strong moment from the finished story that will make a
  10-15 second opening hook.
- Prefer a moment with the main character visible and able to speak.
- Do not spoil the ending. Tease the central danger or mystery.
- dialogue: one exact spoken line, 6-14 words, natural English, no quotes.
- visual: one storyboard-frame description grounded in the story assets.
- motion: describe camera motion, character movement, and audio beats.

Output:
{
  "key_scene_id": 1,
  "summary": "one sentence describing why this is the hook",
  "speaker": "character name or Narrator",
  "dialogue": "short spoken line",
  "visual": "single-frame storyboard visual",
  "motion": "10-15 second motion and audio direction"
}"""


def _strip_tags(text: str) -> str:
    return re.sub(r"\[[^\]]+\]", "", text).strip()


def _duration() -> int:
    return min(15, max(10, int(settings.hook_duration_sec)))


def _load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _scene_by_id(script: Script, scene_id: int | str | None) -> Scene:
    try:
        sid = int(scene_id) if scene_id is not None else -1
    except (TypeError, ValueError):
        sid = -1
    return next((s for s in script.scenes if s.id == sid), script.scenes[0])


def _compact_scene(scene: Scene, bible: Bible) -> dict[str, Any]:
    def name(asset_id: str) -> str:
        asset = bible.get(asset_id)
        return asset.name if asset else asset_id

    return {
        "id": scene.id,
        "beat_id": scene.beat_id,
        "narration": _strip_tags(scene.narration),
        "cast": [name(c) for c in scene.cast],
        "location": name(scene.location),
        "props": [name(p) for p in scene.props],
        "camera": scene.camera,
        "time_of_day": scene.time_of_day,
        "weather": scene.weather,
        "character_state": scene.character_state,
    }


def _fallback_storyboard(script: Script, bible: Bible) -> dict[str, Any]:
    scene = next((s for s in script.scenes if s.cast), script.scenes[0])
    speaker = "Narrator"
    if scene.cast:
        asset = bible.get(scene.cast[0])
        speaker = asset.name if asset else scene.cast[0]
    return {
        "key_scene_id": scene.id,
        "summary": "The opening hook teases the central threat.",
        "speaker": speaker,
        "dialogue": "Something is coming, and we are not ready.",
        "visual": _strip_tags(scene.narration),
        "motion": "A slow push-in, tense silence, then the speaker delivers the line.",
    }


def _coerce_storyboard(data: dict[str, Any], script: Script, bible: Bible) -> dict[str, Any]:
    fallback = _fallback_storyboard(script, bible)
    scene = _scene_by_id(script, data.get("key_scene_id"))
    dialogue = str(data.get("dialogue") or fallback["dialogue"]).strip()
    dialogue = re.sub(r"[\r\n\"“”]", "", dialogue)
    if not dialogue or re.search(r"[\u1780-\u17FF]", dialogue):
        dialogue = fallback["dialogue"]
    words = dialogue.split()
    if len(words) > 14:
        dialogue = " ".join(words[:14])
    return {
        "key_scene_id": scene.id,
        "summary": str(data.get("summary") or fallback["summary"]).strip(),
        "speaker": str(data.get("speaker") or fallback["speaker"]).strip(),
        "dialogue": dialogue,
        "visual": str(data.get("visual") or fallback["visual"]).strip(),
        "motion": str(data.get("motion") or fallback["motion"]).strip(),
    }


async def _build_storyboard(story_dir: Path, script: Script, bible: Bible) -> dict[str, Any]:
    path = story_dir / "hook" / "storyboard.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))

    premise = _load_json(story_dir / "premise.json", {})
    beats = _load_json(story_dir / "beats.json", {})
    scenes = [_compact_scene(s, bible) for s in script.scenes]
    user = json.dumps({
        "premise": premise,
        "beats": beats.get("beats", [])[:12],
        "bible": bible.model_dump(),
        "scenes": scenes,
    }, ensure_ascii=False)
    raw = await atlas.chat(HOOK_STORYBOARD_SYSTEM, user, temperature=0.5, max_tokens=1200)
    parsed = parse_llm_json(raw)
    data = _coerce_storyboard(parsed if isinstance(parsed, dict) else {}, script, bible)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    add_cost(story_dir, "hook", "storyboard_llm", PRICES["hook_storyboard_llm"])
    return data


async def _prepare_storyboard_frame(story_dir: Path, storyboard: dict[str, Any]) -> str:
    """Copy the selected generated scene still into hook/storyboard.png and upload it."""
    path = story_dir / "hook" / "storyboard.json"
    frame = story_dir / "hook" / "storyboard.png"
    if storyboard.get("storyboard_url"):
        return storyboard["storyboard_url"]

    manifest = _load_json(story_dir / "images" / "manifest.json", [])
    by_id = {int(e["scene_id"]): e for e in manifest}
    entry = by_id.get(int(storyboard["key_scene_id"])) or (manifest[0] if manifest else None)
    if not entry:
        raise RuntimeError("hook storyboard needs at least one generated scene image")

    source = story_dir / entry["path"]
    if not frame.exists():
        frame.write_bytes(source.read_bytes())

    url = await atlas.upload_media(frame.read_bytes(), frame.name, "image/png")
    storyboard["storyboard_url"] = url
    path.write_text(json.dumps(storyboard, indent=2), encoding="utf-8")
    return url


def _reference_urls(story_dir: Path, scene: Scene, bible: Bible, storyboard_url: str) -> list[str]:
    refs: list[str] = [storyboard_url]
    anchors = _load_json(story_dir / "images" / "anchors.json", {})
    sheets = _load_json(story_dir / "images" / "refsheet.json", {})

    for asset_id in scene.cast + [scene.location] + scene.props:
        asset = bible.get(asset_id)
        if asset and asset.reference_image_url:
            refs.append(asset.reference_image_url)
        if asset_id in anchors:
            refs.append(anchors[asset_id])
        refs.extend(sheets.get(asset_id, [])[:2])

    return list(dict.fromkeys(refs))[:9]


def _seedance_prompt(inp: StoryInput, storyboard: dict[str, Any], scene: Scene,
                     bible: Bible) -> str:
    cast_names = []
    for cid in scene.cast:
        asset = bible.get(cid)
        cast_names.append(asset.name if asset else cid)
    cast = ", ".join(cast_names) if cast_names else "the central character"
    duration = _duration()
    return (
        f"Create a {duration}-second cinematic opening hook for this {inp.genre} story. "
        "Use reference image 1 as the storyboard frame and preserve its character "
        "identity, setting, lighting, and composition. "
        f"Visible subject: {cast}. Storyboard visual: {storyboard['visual']}. "
        f"Motion direction: {storyboard['motion']}. "
        f"The speaker is {storyboard['speaker']} and must say this exact English line "
        f"with natural lip movement: \"{storyboard['dialogue']}\". "
        "Generate native synchronized audio: clear spoken dialogue, cinematic ambience, "
        "subtle impact sound design. No subtitles, no captions, no on-screen text, "
        "no watermark. End on a tense unresolved beat so the main story can begin."
    )


async def _normalize_hook(raw: Path, out: Path, fmt: FormatSpec) -> Path:
    if out.exists():
        return out

    streams = await ffmpeg.probe_streams(raw)
    duration = await ffmpeg.probe_duration(raw)
    vf = (
        f"scale={fmt.width}:{fmt.height}:force_original_aspect_ratio=increase,"
        f"crop={fmt.width}:{fmt.height},fps={FPS},setsar=1"
    )
    if "codec_type=audio" in streams:
        args = [
            "-i", str(raw),
            "-map", "0:v:0", "-map", "0:a:0",
            "-vf", vf,
            "-af", "aformat=sample_rates=44100:channel_layouts=stereo,loudnorm=I=-14:TP=-1.5:LRA=11",
            *VIDEO_EXPORT_ARGS, str(out),
        ]
    else:
        args = [
            "-i", str(raw),
            "-f", "lavfi", "-t", f"{duration:.3f}",
            "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-map", "0:v:0", "-map", "1:a:0",
            "-vf", vf, "-shortest",
            *VIDEO_EXPORT_ARGS, str(out),
        ]
    await ffmpeg.run(args, timeout=900, cwd=out.parent)
    return out


async def run_hook_pipeline(story_dir: Path, inp: StoryInput, script: Script,
                            bible: Bible, on_progress=None) -> Path | None:
    if not settings.hook_enabled or not inp.hook_enabled:
        return None

    log = PipelineLog(story_dir)
    hook_dir = story_dir / "hook"
    hook_dir.mkdir(parents=True, exist_ok=True)
    fmt = FORMATS[inp.video_format]
    out = hook_dir / "hook.mp4"
    if out.exists():
        if on_progress:
            await on_progress(1, 1)
        return out

    storyboard = await _build_storyboard(story_dir, script, bible)
    scene = _scene_by_id(script, storyboard["key_scene_id"])
    storyboard_url = await _prepare_storyboard_frame(story_dir, storyboard)
    refs = _reference_urls(story_dir, scene, bible, storyboard_url)

    raw = hook_dir / "seedance_raw.mp4"
    if not raw.exists():
        payload = {
            "model": settings.hook_video_model,
            "prompt": _seedance_prompt(inp, storyboard, scene, bible),
            "reference_images": refs,
            "duration": _duration(),
            "resolution": settings.hook_resolution,
            "ratio": fmt.nb2_aspect,
            "bitrate_mode": settings.hook_bitrate_mode,
            "generate_audio": True,
            "seed": settings.hook_seed,
            "watermark": False,
            "return_last_frame": False,
        }
        (hook_dir / "seedance_payload.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8")
        log.event("hook", "seedance_start", detail=f"{_duration()}s refs:{len(refs)}")
        raw.write_bytes(await atlas.generate_video(payload, timeout=1200))
        usd = _duration() * PRICES["seedance-2.0-mini"]
        add_cost(story_dir, "hook", f"seedance:{_duration()}s", usd)
        log.event("hook", "seedance_done", detail=settings.hook_video_model, cost_usd=usd)

    await _normalize_hook(raw, out, fmt)
    duration = await ffmpeg.probe_duration(out)
    if not 9.5 <= duration <= 15.5:
        log.event("hook", "warning", detail=f"hook duration {duration:.1f}s outside 10-15s")
    if on_progress:
        await on_progress(1, 1)
    log.event("hook", "done", detail=str(out))
    return out
