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


def test_elevenlabs_payload_keeps_provider_options(monkeypatch):
    monkeypatch.setattr(settings, "tts_model", "elevenlabs-v3")

    payload = build_tts_payload("Hello world", "Jessica")

    assert payload["model"] == "elevenlabs-v3"
    assert payload["voice"] == "Jessica"
    assert payload["output_format"] == "mp3_44100_128"
    assert payload["stability"] == 0.5
