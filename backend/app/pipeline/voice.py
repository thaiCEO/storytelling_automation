"""Stage 4 — Voice Pipeline: per-scene TTS MP3s + real ffprobe durations.

Real duration from ffprobe is the single source of truth for video timing —
never the LLM's duration_estimate_sec. See skills/voice-pipeline.md.
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from ..clients.atlas import atlas
from ..config import settings
from ..models import ALLOWED_AUDIO_TAGS, AudioManifestEntry, Scene, Script
from ..utils.cost import PRICES, add_cost
from ..utils.ffmpeg import probe_duration
from ..utils.log import PipelineLog

CONCURRENCY = 3
TIMEOUT = 45
XAI_TTS_LANGUAGE = "en"
XAI_VOICE_ALIASES = {
    "eve": "eve",
    "ara": "ara",
    "leo": "leo",
    "rex": "rex",
    "sal": "sal",
    "grace": "f8cf5c2c78d4",
    "daniel": "96819d0bd28d",
    "claire": "79f3a8b96d43",
    "james": "78a495fdbb39",
}


def resolve_voice_id(narrator_voice: str) -> str:
    """male/female -> the matching LOCKED brand voice id from .env.
    Falls back to the legacy single TTS_VOICE_ID if the gender id is unset."""
    by_gender = {"male": settings.tts_voice_id_male,
                 "female": settings.tts_voice_id_female}
    voice_id = (by_gender.get(narrator_voice, "") or settings.tts_voice_id).strip()
    if not voice_id:
        raise RuntimeError(
            f"no TTS voice configured for '{narrator_voice}' — set "
            "TTS_VOICE_ID_MALE / TTS_VOICE_ID_FEMALE (or TTS_VOICE_ID) in .env")
    return voice_id


def _is_xai_tts_model(model: str) -> bool:
    return model.lower().startswith("xai/tts")


def _xai_voice_id(voice_id: str) -> str:
    normalized = voice_id.strip()
    return XAI_VOICE_ALIASES.get(normalized.lower(), normalized)


def sanitize_narration(text: str) -> str:
    """Strip any audio tag NOT in the allowed set (defense against LLM drift)."""
    def keep(match: re.Match) -> str:
        return match.group(0) if match.group(0) in ALLOWED_AUDIO_TAGS else ""
    return re.sub(r"\[[^\]]*\]", keep, text).strip()


def build_tts_payload(text: str, voice_id: str) -> dict:
    """Atlas generateAudio payload.

    ElevenLabs and xAI use different voice/language field names, so keep their
    payload shapes separate.
    """
    model = settings.tts_model
    if _is_xai_tts_model(model):
        return {
            "model": model,
            "text": text,
            "language": XAI_TTS_LANGUAGE,
            "voice_id": _xai_voice_id(voice_id),
        }

    payload = {
        "model": model,
        "text": text,
        "voice": voice_id,
    }
    if "eleven" in model.lower():
        # Atlas elevenlabs/v3/text-to-speech schema (verified 2026-07-07):
        # only voice / stability / apply_text_normalization are accepted —
        # similarity_boost, speed, output_format and language are NOT.
        # "voice" takes the internal id (e.g. Chris iP95p4xoKVk53GoZ742B),
        # never the display name.
        payload.update({
            "stability": 0.5,
            "apply_text_normalization": "auto",
        })
    return payload


async def _tts_one(scene: Scene, story_dir: Path, log: PipelineLog,
                   voice_id: str, sem: asyncio.Semaphore) -> AudioManifestEntry:
    out = story_dir / "audio" / f"scene_{scene.id:03}.mp3"
    text = sanitize_narration(scene.narration)

    if not out.exists():  # idempotent by file presence
        async with sem:
            payload = build_tts_payload(text, voice_id)
            content = await atlas.tts(payload, timeout=TIMEOUT)
            out.write_bytes(content)
            usd = len(text) / 1000 * PRICES.get(settings.tts_model, PRICES["elevenlabs-v3"])
            add_cost(story_dir, "tts", f"scene:{scene.id} chars:{len(text)}", usd)
            log.event("voice", "generated", detail=f"chars:{len(text)}",
                      scene_id=scene.id, cost_usd=usd)

    duration = await probe_duration(out)
    if duration <= 0:
        raise RuntimeError(f"scene {scene.id}: non-positive audio duration")
    return AudioManifestEntry(scene_id=scene.id, path=f"audio/{out.name}",
                              duration_sec=round(duration, 3), chars=len(text))


async def run_voice_pipeline(story_dir: Path, script: Script,
                             duration_minutes: int,
                             narrator_voice: str = "male",
                             on_progress=None) -> tuple[list[AudioManifestEntry], list[str]]:
    """Generate all narration MP3s; write audio/manifest.json.

    Returns (manifest_entries, warnings). Warnings surface in the UI but do
    not fail the stage.
    """
    log = PipelineLog(story_dir)
    (story_dir / "audio").mkdir(parents=True, exist_ok=True)

    voice_id = resolve_voice_id(narrator_voice)
    log.event("voice", "voice_selected", detail=f"{narrator_voice}")
    sem = asyncio.Semaphore(CONCURRENCY)
    done = 0

    async def worker(scene: Scene) -> AudioManifestEntry:
        nonlocal done
        entry = await _tts_one(scene, story_dir, log, voice_id, sem)
        done += 1
        if on_progress:
            await on_progress(done, len(script.scenes))
        return entry

    results = await asyncio.gather(*(worker(s) for s in script.scenes),
                                   return_exceptions=True)
    entries: list[AudioManifestEntry] = []
    failed: list[str] = []
    for scene, res in zip(script.scenes, results):
        if isinstance(res, Exception):
            # str() of NotImplementedError/CancelledError is empty — keep the
            # class name so failures are never blank in the log/UI
            reason = str(res) or type(res).__name__
            failed.append(f"scene {scene.id}: {reason}")
            log.event("voice", "tts_failed", detail=reason, scene_id=scene.id)
        else:
            entries.append(res)
    if failed:
        raise RuntimeError(f"{len(failed)} TTS call(s) failed: " + "; ".join(failed[:5]))

    entries.sort(key=lambda e: e.scene_id)

    # quality checks before hand-off (warnings, not failures).
    # deep-pacing scenes legitimately run 20-32s — only flag runaways
    warnings: list[str] = []
    for e in entries:
        if e.duration_sec > 40:
            warnings.append(
                f"scene {e.scene_id}: narration {e.duration_sec:.1f}s > 40s "
                "(exceeds even deep pacing — likely word-count violation)")
    total = sum(e.duration_sec for e in entries)
    target = duration_minutes * 60
    if abs(total - target) > target * 0.15:
        warnings.append(
            f"total narration {total:.0f}s outside ±15% of target {target}s")
    for w in warnings:
        log.event("voice", "warning", detail=w)

    manifest = story_dir / "audio" / "manifest.json"
    manifest.write_text(
        json.dumps([e.model_dump() for e in entries], indent=2), encoding="utf-8")
    log.event("voice", "manifest_written",
              detail=f"{len(entries)} clips, total {total:.1f}s")
    return entries, warnings
