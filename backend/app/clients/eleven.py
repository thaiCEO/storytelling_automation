"""Direct ElevenLabs TTS client (official SDK) — used when
TTS_PROVIDER=elevenlabs; Atlas generateAudio remains the fallback provider.

Conventions match clients/atlas.py: every call gets a timeout + 2 retries
with exponential backoff, and the API key is never logged.
"""
from __future__ import annotations

import asyncio
import re

from ..config import settings

MAX_RETRIES = 2   # retries after the first attempt
BACKOFF = (2, 8)  # seconds before retry 1 / retry 2
TIMEOUT = 60      # wall-clock cap per attempt (convert + download)
OUTPUT_FORMAT = "mp3_44100_128"


class ElevenLabsError(RuntimeError):
    pass


_client = None


def _get_client():
    global _client
    if _client is None:
        if not settings.elevenlabs_api_key:
            raise ElevenLabsError(
                "ELEVENLABS_API_KEY is not set — fill it in .env at the repo root")
        from elevenlabs.client import AsyncElevenLabs
        _client = AsyncElevenLabs(api_key=settings.elevenlabs_api_key)
    return _client


def _prepare_text(text: str) -> str:
    """Only the eleven_v3 family understands [whispers]/[pause]... audio
    tags — older models read them aloud, so strip every tag for those."""
    if settings.elevenlabs_model_id.startswith("eleven_v3"):
        return text
    return re.sub(r"\s*\[[^\]]*\]\s*", " ", text).strip()


async def _convert_once(text: str, voice_id: str) -> bytes:
    stream = _get_client().text_to_speech.convert(
        text=text,
        voice_id=voice_id,
        model_id=settings.elevenlabs_model_id,
        output_format=OUTPUT_FORMAT,
    )
    chunks = [chunk async for chunk in stream]
    content = b"".join(chunks)
    if not content:
        raise ElevenLabsError("ElevenLabs returned empty audio")
    return content


async def tts(text: str, voice_id: str) -> bytes:
    """Text -> MP3 bytes with retry (2) + timeout, mirroring atlas.tts."""
    text = _prepare_text(text)
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            return await asyncio.wait_for(_convert_once(text, voice_id), TIMEOUT)
        except Exception as exc:  # SDK ApiError, timeout, transport...
            last_exc = exc
            if attempt < MAX_RETRIES:
                await asyncio.sleep(BACKOFF[attempt])
    raise ElevenLabsError(
        f"elevenlabs tts failed after {MAX_RETRIES + 1} attempts: "
        f"{type(last_exc).__name__}: {last_exc}") from last_exc
