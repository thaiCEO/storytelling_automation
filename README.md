# Story Automation — AI Cinematic Storytelling Video Pipeline

Structured topic input → AI script (Claude Sonnet, 4 passes) → AI images
(GPT Image 2 / Nano Banana 2 / Flux Schnell) → AI voiceover (configured TTS model) → subtitles →
Seedance 2.0 Mini short hook → synced & rendered 1080p MP4, ready for YouTube.

See [CLAUDE.md](CLAUDE.md) for architecture and `skills/` for per-stage specs.

## Setup

1. **Secrets** — copy `.env.example` to `.env` and fill in:
   - `ATLAS_API_KEY` — your Atlas Cloud API key (one key for all models)
   - `TTS_VOICE_ID_FEMALE` — current female voice is `Eve`
   - `TTS_MODEL` — verify the exact TTS model ID on your Atlas dashboard
   - `HOOK_VIDEO_MODEL` — defaults to `bytedance/seedance-2.0-mini/reference-to-video`
2. **Backend** (Python 3.11+, FFmpeg + ffprobe on PATH):

   ```bash
   cd backend
   pip install -r requirements.txt
   uvicorn app.main:app --reload --port 8000
   ```

3. **Frontend** (Node 20+):

   ```bash
   cd frontend
   npm install
   npm run dev        # http://localhost:3000 — proxies /api and /media to :8000
   ```

## Usage

Open `http://localhost:3000/create`, describe your story (10–50 words),
pick genre / ending / duration / image style, and generate. Progress is
polled at `/stories/{id}`; the final video + cost breakdown lands at
`/stories/{id}/result`.

Runtime artifacts per story: `stories/{story_id}/` (script, images, audio,
subtitles, hook storyboard/Seedance clip, output/final.mp4, cost.json,
pipeline.log, state.json).
A failed story resumes from the failed stage — finished scenes are never
regenerated (delete a file to force just that scene).

## First-run checklist

- Start with a **1-minute** story (~$0.30 with gpt-image-2) to validate your
  Atlas key, TTS voice, and render chain end-to-end.
- Verify current model pricing on the Atlas model pages and update `PRICES`
  in `backend/app/utils/cost.py` if promo rates changed.
- The TTS endpoint path (`backend/app/clients/atlas.py`, `TTS_PATH`) follows
  the Atlas prediction API convention — confirm it against the selected TTS
  model page on your dashboard once.
- Replace the placeholder style-card images in `frontend/public/styles/`
  with real generated samples when convenient.
- Optional: drop background music files at `assets/music/{genre}.mp3`
  (e.g. `sci-fi.mp3`) — they loop under narration with sidechain ducking.
