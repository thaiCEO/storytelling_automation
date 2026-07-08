"""Cost tracking + the single-source-of-truth estimate formula.

Unit prices live in PRICES only — re-verify against Atlas model pages
(promo pricing changes). See skills/project-structure.md.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

PRICES = {
    "gpt-image-2": 0.008,        # per image
    "nano-banana-2": 0.056,      # per image
    "flux-schnell": 0.038,       # per image (estimate blend; real logging
                                 #   uses the per-endpoint keys below)
    # exact Atlas endpoint prices (verified 2026-07-07) — flat per run,
    # independent of the requested size
    "black-forest-labs/flux-schnell": 0.003,
    "black-forest-labs/flux-2-pro/edit": 0.03,
    "grok-imagine": 0.022,       # per image (xAI Grok Imagine)
    "seedance-2.0-mini": 0.056,  # per generated video second
    # per 1k characters — verified on the Atlas model page 2026-07-07
    "elevenlabs/v3/text-to-speech": 0.003,
    "elevenlabs-v3": 0.003,      # fallback key for unknown TTS models
    # direct ElevenLabs SDK (TTS_PROVIDER=elevenlabs): billed as
    # subscription credits — 0.10/1k is indicative; adjust to your plan
    "elevenlabs-direct": 0.10,
    "xai/tts-v1": 0.015,         # per 1k characters
    "llm_per_minute": 0.07,      # 4 Sonnet passes, scales ~linearly
    "hook_storyboard_llm": 0.02, # one compact storyboard pass
}

DEFAULT_HOOK_DURATION_SEC = 12

RETRY_BUFFER = 1.15
_lock = Lock()


def estimate(duration_minutes: int, image_model: str = "auto",
             tts_model: str | None = None, hook_enabled: bool = False) -> dict:
    from ..config import settings

    scenes = duration_minutes * 10
    words = duration_minutes * 150
    chars = words * 6.3  # avg English chars/word incl. spaces

    llm = duration_minutes * PRICES["llm_per_minute"]
    if settings.tts_provider == "elevenlabs" and tts_model is None:
        tts_price = PRICES["elevenlabs-direct"]
    else:
        effective_tts_model = tts_model or settings.tts_model
        tts_price = PRICES.get(effective_tts_model, PRICES["elevenlabs-v3"])
    tts = chars / 1000 * tts_price

    img_price = {
        "gpt-image-2": scenes * PRICES["gpt-image-2"],
        "nano-banana-2": scenes * PRICES["nano-banana-2"],
        "flux-schnell": scenes * PRICES["flux-schnell"],
        "grok-imagine": scenes * PRICES["grok-imagine"],
        # 70% cast scenes (NB2) / 30% landscape (GPT)
        "auto": scenes * (0.7 * PRICES["nano-banana-2"] + 0.3 * PRICES["gpt-image-2"]),
    }[image_model]
    hook = 0.0
    if hook_enabled:
        hook_duration = min(15, max(10, int(settings.hook_duration_sec or DEFAULT_HOOK_DURATION_SEC)))
        hook = hook_duration * PRICES["seedance-2.0-mini"] + PRICES["hook_storyboard_llm"]

    total = round((llm + tts + img_price + hook) * RETRY_BUFFER, 2)
    return {
        "total": total,
        "breakdown": {
            "llm": round(llm, 2),
            "images": round(img_price, 2),
            "tts": round(tts, 2),
            "hook": round(hook, 2),
        },
        "scenes": scenes,
        "words": words,
    }


def add_cost(story_dir: Path, stage: str, units: str, usd: float) -> None:
    """Append one entry to stories/{id}/cost.json."""
    path = Path(story_dir) / "cost.json"
    with _lock:
        entries = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        entries.append({
            "stage": stage,
            "units": units,
            "usd": round(usd, 5),
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        path.write_text(json.dumps(entries, indent=2), encoding="utf-8")


def totals(story_dir: Path) -> dict:
    path = Path(story_dir) / "cost.json"
    if not path.exists():
        return {"total": 0.0, "by_stage": {}}
    by_stage: dict[str, float] = {}
    for e in json.loads(path.read_text(encoding="utf-8")):
        by_stage[e["stage"]] = round(by_stage.get(e["stage"], 0.0) + e["usd"], 5)
    return {"total": round(sum(by_stage.values()), 4), "by_stage": by_stage}
