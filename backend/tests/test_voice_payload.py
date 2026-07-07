from app.config import settings
from app.pipeline.voice import build_tts_payload, resolve_voice_id


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
