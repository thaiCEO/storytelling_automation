---
name: voice-pipeline
description: Generate per-scene English narration audio with the configured TTS provider and extract real durations with ffprobe. Use this skill whenever working on TTS calls, audio tags, voice selection, narration audio files, duration extraction, silence padding, or voice cost tracking.
---

# Voice Pipeline (Stage 4)

Converts each scene's `narration` into an MP3 with the configured TTS
provider, then measures **real duration** with ffprobe — the single source
of truth for video timing.

## Provider selection (`TTS_PROVIDER` in .env)

- `elevenlabs` (current) — the official `elevenlabs` Python SDK direct to
  ElevenLabs (`clients/eleven.py`): `AsyncElevenLabs.text_to_speech.convert(
  text, voice_id, model_id=ELEVENLABS_MODEL_ID, output_format=
  "mp3_44100_128")`, own retry ×2 + 60s timeout wrapper. Needs
  `ELEVENLABS_API_KEY`. Cost logs with PRICES["elevenlabs-direct"]
  (subscription credits — indicative).
- `atlas` (fallback) — Atlas Cloud `generateAudio` with `TTS_MODEL`
  (payload shapes below).

## Voice rules

- `TTS_VOICE_ID` / `TTS_VOICE_ID_MALE` / `TTS_VOICE_ID_FEMALE` in .env are the **locked brand voices**. Never change them per
  video; channel consistency depends on it. Pick once from the Voice Library
  matching `narrator_style` (e.g. deep, measured, documentary).
- Current locked voices: MALE slot = Adam `pNInz6obpgDQGcFmaJgB` (default),
  second ("FEMALE") slot = Chris `iP95p4xoKVk53GoZ742B` (both Male en-US —
  the two slots are just the two UI picks; ElevenLabs premade ids work on
  both providers).
- Language: English narration is still the app contract (`language: "en"`).
- `ELEVENLABS_MODEL_ID=eleven_v3` — only the v3 family understands audio
  tags; for any other model id `clients/eleven.py` strips ALL tags before
  sending (older models read them aloud).

## Audio tags (already inserted by story engine)

Allowed set: `[whispers] [excited] [sad] [pause] [intense]`.
Pass narration text through unchanged — tags are interpreted by v3, they are
not spoken. Strip any tag NOT in the allowed set before sending (defense
against LLM drift).

## API call (per scene)

Exact request shape depends on the selected Atlas Cloud TTS model schema
(check the model page once at setup). For `xai/tts-v1`, send:

```python
{
  "model": TTS_MODEL,             # Atlas model ID for the configured TTS provider
  "text": scene.narration,        # with audio tags
  "language": "en",
  "voice_id": TTS_VOICE_ID        # e.g. "eve" for the Eve display name
}
```

ElevenLabs-only tuning fields (`stability`, `similarity_boost`, `speed`,
`output_format`) are added by code only when `TTS_MODEL` contains `"eleven"`;
that path still uses the ElevenLabs `voice` field.

- Save to `stories/{id}/audio/scene_{id:03}.mp3`.
- Concurrency 3, timeout 45 s, 2 retries with backoff (same pattern as
  image-pipeline).

## Duration extraction (critical)

```bash
ffprobe -v error -show_entries format=duration \
        -of default=noprint_wrappers=1:nokey=1 scene_001.mp3
```

Write results into the manifest — sync-render reads ONLY these numbers:

```json
stories/{id}/audio/manifest.json
[
  {"scene_id": 1, "path": "audio/scene_001.mp3",
   "duration_sec": 5.87, "chars": 52}
]
```

Never use `duration_estimate_sec` from script.json for timing. It exists only
for pre-generation cost/pacing estimates.

## Quality checks before hand-off

1. Every scene has an MP3 and a positive duration.
2. Flag any scene with duration > 12 s (narration too long — likely an LLM
   word-count violation that slipped validation) → surface warning in UI.
3. Total duration within ±15% of `duration_minutes * 60`; otherwise warn.
4. Loudness: normalize later in sync-render (`loudnorm`), not here — keep raw
   files untouched for re-renders.
