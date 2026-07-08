import asyncio

import pytest

from app.config import settings
from app.models import Scene
from app.pipeline import voice as voice_mod
from app.pipeline.voice import build_tts_payload, resolve_voice_id
from app.utils.log import PipelineLog


def test_xai_tts_payload_uses_language_and_voice_id_without_elevenlabs_options(monkeypatch):
    monkeypatch.setattr(settings, "tts_model", "xai/tts-v1")
    monkeypatch.setattr(settings, "tts_voice_id_female", "Eve")

    payload = build_tts_payload("Hello world", resolve_voice_id("female"))

    assert payload == {
        "model": "xai/tts-v1",
        "text": "Hello world",
        "language": "en",
        "voice_id": "eve",
    }


def test_xai_tts_payload_uses_daniel_for_male_voice(monkeypatch):
    monkeypatch.setattr(settings, "tts_model", "xai/tts-v1")
    monkeypatch.setattr(settings, "tts_voice_id_male", "Daniel")

    payload = build_tts_payload("Hello world", resolve_voice_id("male"))

    assert payload == {
        "model": "xai/tts-v1",
        "text": "Hello world",
        "language": "en",
        "voice_id": "96819d0bd28d",
    }


def test_xai_tts_payload_preserves_custom_voice_id(monkeypatch):
    monkeypatch.setattr(settings, "tts_model", "xai/tts-v1")

    payload = build_tts_payload("Hello world", "customVoice_ABC")

    assert payload["voice_id"] == "customVoice_ABC"


def test_elevenlabs_v3_payload_matches_atlas_schema(monkeypatch):
    monkeypatch.setattr(settings, "tts_model", "elevenlabs/v3/text-to-speech")
    monkeypatch.setattr(settings, "tts_voice_id_male", "iP95p4xoKVk53GoZ742B")

    payload = build_tts_payload("Hello world", resolve_voice_id("male"))

    # Atlas elevenlabs/v3 schema: ONLY these params — similarity_boost,
    # speed, output_format and language are rejected/ignored
    assert payload == {
        "model": "elevenlabs/v3/text-to-speech",
        "text": "Hello world",
        "voice": "iP95p4xoKVk53GoZ742B",   # Chris — internal id, not the name
        "stability": 0.5,
        "apply_text_normalization": "auto",
    }


def test_elevenlabs_v3_second_voice_slot_is_adam(monkeypatch):
    monkeypatch.setattr(settings, "tts_model", "elevenlabs/v3/text-to-speech")
    monkeypatch.setattr(settings, "tts_voice_id_female", "pNInz6obpgDQGcFmaJgB")

    payload = build_tts_payload("Hello world", resolve_voice_id("female"))
    assert payload["voice"] == "pNInz6obpgDQGcFmaJgB"  # Adam (Male, en-US)


@pytest.mark.anyio
async def test_elevenlabs_provider_dispatches_to_direct_sdk(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "tts_provider", "elevenlabs")
    monkeypatch.setattr(settings, "tts_voice_id_male", "iP95p4xoKVk53GoZ742B")
    calls = {}

    async def fake_eleven_tts(text, voice_id):
        calls["args"] = (text, voice_id)
        return b"mp3-bytes"

    async def fail_atlas_tts(payload, *, timeout):
        raise AssertionError("atlas must not be called when provider=elevenlabs")

    async def fake_probe(path):
        return 3.2

    monkeypatch.setattr(voice_mod.eleven, "tts", fake_eleven_tts)
    monkeypatch.setattr(voice_mod.atlas, "tts", fail_atlas_tts)
    monkeypatch.setattr(voice_mod, "probe_duration", fake_probe)

    (tmp_path / "audio").mkdir()
    scene = Scene(id=1, beat_id=1, narration="[pause] Hello there world.",
                  cast=[], location="loc_x", camera="wide",
                  time_of_day="dawn", weather="mist")
    entry = await voice_mod._tts_one(scene, tmp_path, PipelineLog(tmp_path),
                                     resolve_voice_id("male"),
                                     asyncio.Semaphore(1))

    # allowed audio tag rides through to v3; voice id resolved from the slot
    assert calls["args"] == ("[pause] Hello there world.", "iP95p4xoKVk53GoZ742B")
    assert (tmp_path / "audio" / "scene_001.mp3").read_bytes() == b"mp3-bytes"
    assert entry.duration_sec == 3.2
