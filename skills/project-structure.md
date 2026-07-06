---
name: project-structure
description: Master reference for the story-automation repo — folder layout, pipeline state machine, FastAPI endpoints, .env config, error and logging conventions, and cost tracking. Read this skill FIRST for any new coding task in this project, before opening the stage-specific skill.
---

# Project Structure (master)

## Repo layout

```
story-automation/
├── CLAUDE.md                    ← tech stack + skill index (read it)
├── skills/                      ← the 6 skill md files (story-engine.md, asset-bible.md, ...)
├── backend/                     ← Python 3.11 / FastAPI
│   ├── app/
│   │   ├── main.py              ← FastAPI app + routers
│   │   ├── models.py            ← Pydantic: StoryInput, Script, Bible...
│   │   ├── pipeline/
│   │   │   ├── runner.py        ← orchestrates stages, state machine
│   │   │   ├── story_engine.py  ← 4 LLM passes + validation
│   │   │   ├── images.py        ← GPT Image 2 loop
│   │   │   ├── voice.py         ← ElevenLabs v3 loop + ffprobe
│   │   │   └── render.py        ← sync + FFmpeg assembly
│   │   ├── clients/atlas.py     ← single Atlas Cloud HTTP client (httpx)
│   │   └── utils/{ffmpeg.py, cost.py, log.py}
│   └── requirements.txt         ← fastapi, uvicorn, httpx, pydantic, pillow
├── frontend/                    ← Nuxt 4 + Tailwind
│   ├── pages/{create.vue, stories/[id].vue, stories/[id]/result.vue}
│   ├── components/{GenreChips, EndingChips, DurationSlider,
│   │               AdvancedAccordion, StylePresets, ProgressStepper}.vue
│   └── composables/useStoryApi.ts
└── stories/{story_id}/          ← runtime artifacts (gitignored)
    ├── input.json  premise.json  bible.json  beats.json  script.json
    ├── images/  audio/  subtitles/  output/
    ├── cost.json  state.json  pipeline.log
```

## Pipeline state machine (`state.json`)

```
created → story_running → story_done
        → images_running (progress: n/N) → images_done
        → voice_running  (progress: n/N) → voice_done
        → subtitles_running → subtitles_done
        → hook_running (optional, progress: 1/1) → hook_done
        → render_running → done
any stage → failed_{stage} (with error + retryable flag)
```

- `runner.py` executes stages strictly in order; each stage is resumable —
  it skips scenes whose output file already exists (idempotent by file
  presence). Re-running a failed story continues, never restarts.
- UI polls `GET /api/stories/{id}/status` (or SSE) → returns state + progress
  counters + per-stage cost so far.

## FastAPI endpoints

```
GET  /api/estimate?duration_minutes=&image_model=&tts_model=&hook_enabled=   ← live cost estimate for the UI (no story created)
POST /api/stories                     ← Level-2 input → creates story, starts runner (BackgroundTasks)
POST /api/stories/{id}/references    ← multipart upload → Atlas uploadMedia → url
GET  /api/stories/{id}/status        ← state machine + progress
GET  /api/stories/{id}/bible         ← Asset Bible (roles + relationships) for the graph page; 409 until Pass 2 done
POST /api/stories/{id}/retry         ← resume from failed stage
GET  /api/stories/{id}/result        ← final.mp4 path + cost.json + thumbnail
```

## Conventions (all stages)

1. **External calls:** httpx.AsyncClient, timeout per stage skill, 2 retries
   exponential backoff, then structured failure — never crash the runner.
2. **Logging:** one line per event to `pipeline.log`:
   `ts | stage | scene_id | event | detail | cost_usd`.
3. **Cost tracking:** every API response appends to `cost.json`
   (`{stage, units, usd}`). Warn in UI if actuals exceed the pre-run
   estimate by >50%.

## Cost estimate formula (`GET /api/estimate` — single source of truth)

Used by the UI duration slider (1–15 min) and model selectors. Keep unit
prices in one `PRICES` dict; re-verify against Atlas model pages at setup.

```python
scenes = duration_minutes * 10
words  = duration_minutes * 150
chars  = words * 6.3                      # avg English chars/word incl. spaces

llm    = duration_minutes * 0.07          # 4 passes, Sonnet, scales ~linearly
tts    = chars / 1000 * PRICES.get(tts_model, PRICES["elevenlabs-v3"]) # verify current TTS pricing

img_price = {
  "gpt-image-2":  scenes * 0.008,
  "nano-banana-2": scenes * 0.056,
  "auto": scenes * (0.7 * 0.056 + 0.3 * 0.008),   # 70% cast / 30% landscape
}[image_model]

hook = 0
if hook_enabled:
    hook = 12 * PRICES["seedance-2.0-mini"] + PRICES["hook_storyboard_llm"]

retry_buffer = 1.15
total = round((llm + tts + img_price + hook) * retry_buffer, 2)
# → return {total, breakdown: {llm, images, tts, hook}, scenes, words}
```

Reference points (v3 TTS): 1 min ≈ $0.30 (gpt) / $0.75 (auto);
7 min ≈ $1.9 (gpt) / $4.2 (auto); 15 min ≈ $4.0 (gpt) / $9.0 (auto).
UI shows total + breakdown, updating live as the slider or model changes.
4. **Secrets:** only via .env (see CLAUDE.md); never log the API key.
5. **Idempotency:** output files are the checkpoint. Delete a file to force
   regeneration of just that scene.
6. **Stage skills:** before editing any stage, read its md file in skills/:
   story-engine / asset-bible / image-pipeline / voice-pipeline / sync-render.
