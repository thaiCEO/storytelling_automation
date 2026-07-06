# Story Automation — AI Cinematic Storytelling Video Pipeline

Automated pipeline that turns a structured topic input into a finished 7-minute
YouTube storytelling video: AI-written script → AI images → AI voiceover →
synced & rendered MP4.

## Tech Stack

| Layer | Technology |
|---|---|
| Backend API | **Python 3.11+ / FastAPI** (async), Pydantic v2 for validation |
| Frontend UI | **Nuxt 4** (Vue 3, Composition API) + Tailwind CSS |
| AI Gateway | **Atlas Cloud** (single API key for all models) |
| LLM (story engine) | Claude Sonnet via Atlas Cloud |
| Image generation | User-selectable: GPT Image 2, Nano Banana 2, Flux Schnell, or auto-hybrid (see image-pipeline skill) |
| Voice (TTS) | Configured TTS model (`xai/tts-v1` by default) |
| Video assembly | FFmpeg + ffprobe (installed on VPS) |
| Storage | Local VPS filesystem `/stories/{story_id}/` (optionally R2/S3 later) |
| Job status | Background tasks + SSE/polling from Nuxt progress page |

## Pipeline Order (never change this order)

```
INPUT (structured topic, Level-2 schema)
  → [1] story-engine   (4 LLM passes → script.json)
  → [2] asset-bible    (built inside pass 2; supports user-uploaded reference images)
  → [3] image-pipeline (user model, 16:9 YouTube or 9:16 TikTok/Reels per video_format)
  → [4] voice-pipeline (configured TTS model, per-scene MP3 + real durations)
  → [4.5] subtitles    (SRT/ASS from narration + real timings, $0)
  → [4.75] hook-video   (optional Seedance 2.0 Mini 10-15s intro)
  → [5] sync-render    (Ken Burns + subtitle burn-in + FFmpeg → final.mp4,
                        1920x1080 youtube / 1080x1920 tiktok)
```

## Skill Files (read the relevant one BEFORE working on that stage)

| Skill | Path | Covers |
|---|---|---|
| Project structure | `skills/project-structure.md` | Folder layout, .env, state machine, error conventions — **read first for any new work** |
| Story engine | `skills/story-engine.md` | 4-pass prompts (Premise → Bible → Beats → Scenes), input schema, validation |
| Asset bible | `skills/asset-bible.md` | Characters/locations/objects schema, visual DNA rules, **user-uploaded reference images** |
| Image pipeline | `skills/image-pipeline.md` | GPT Image 2 calls, prompt builder, **16:9 YouTube output**, retries |
| Voice pipeline | `skills/voice-pipeline.md` | TTS calls, audio tags, ffprobe duration extraction |
| Subtitles | `skills/subtitles.md` | SRT/ASS generation from narration + timings, styling, FFmpeg burn-in |
| Sync & render | `skills/sync-render.md` | Duration math, Ken Burns motion, FFmpeg assembly, export settings |

Rules for Claude when coding in this repo:

1. Always read `skills/project-structure.md` plus the skill for the stage
   being worked on before writing code.
2. Scene timing source of truth = **real audio duration from ffprobe**, never
   the LLM's `duration_estimate_sec`.
3. All image prompts are built by code from the Asset Bible (`visual_dna`
   injection). Never let the LLM write final image prompts free-hand.
4. Every external API call needs retry (max 2) + timeout + structured logging.
5. Keep cost per video ≈ $2. Log per-stage cost into `stories/{id}/cost.json`.
6. English-only narration for now (`language: "en"`); UI copy may be Khmer.

## Environment (.env)

```env
ATLAS_API_KEY=
ATLAS_BASE_URL=https://api.atlascloud.ai
LLM_MODEL=claude-sonnet            # via Atlas Cloud LLM endpoint
IMAGE_MODEL_GPT=openai/gpt-image-2/text-to-image
IMAGE_EDIT_MODEL_GPT=openai/gpt-image-2/edit
IMAGE_MODEL_NB2=google/nano-banana-2/text-to-image
IMAGE_MODEL_FLUX=black-forest-labs/flux-schnell
IMAGE_EDIT_MODEL_FLUX=black-forest-labs/flux-2-pro/edit
IMAGE_MODEL_DEFAULT=auto            # auto | gpt-image-2 | nano-banana-2 | flux-schnell (per-story override from UI)
HOOK_VIDEO_MODEL=bytedance/seedance-2.0-mini/reference-to-video
HOOK_DURATION_SEC=12                # used only when the per-story hook option is enabled
TTS_MODEL=xai/tts-v1               # xAI TTS v1 API by xAI; verify exact Atlas model ID
TTS_VOICE_ID=                      # LOCKED brand voice, never change per video
TTS_VOICE_ID_FEMALE=Eve            # Eve (Female, Multilingual)
STORIES_DIR=/var/www/story-automation/stories
FFMPEG_BIN=ffmpeg
FFPROBE_BIN=ffprobe
```

## Frontend (Nuxt 4) pages

- `/create` — Level-2 structured input form (hero textarea, genre chips,
  ending chips, duration slider **1–15 min** with live cost estimate (GET /api/estimate), **image style cards
  (cartoon 3D / anime / cinematic realistic)**, **video format cards
  (YouTube 16:9 / TikTok-Reels 9:16)**, optional **Seedance 2.0 Mini hook video** toggle,
  **reference image boxes
  (character / location / object — name + one preview picture per box;
  characters support front/side/back/pose/expression views)**, Advanced
  accordion incl. **image model radio (auto / GPT Image 2 / Nano Banana 2 / Flux Schnell)**
  with live cost, style presets, Surprise Me). POSTs to `POST /api/stories`.
- `/stories/{id}` — progress stepper (Story ✓ → Images n/N → Voice → Sync →
  Render) via SSE or 3s polling of `GET /api/stories/{id}/status`.
- `/stories/{id}/result` — video player + download + cost breakdown.
