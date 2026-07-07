---
name: story-engine
description: Generate the full story script for a storytelling video using a 4-pass LLM workflow (Premise → Asset Bible → Beat Sheet → Scene JSON). Use this skill whenever creating, modifying, or debugging story generation, script JSON, narration text, beats, hooks, pacing, word-count targeting, or the structured topic input schema.
---

# Story Engine (Stage 1)

Turns a structured topic input into a validated `script.json` using **4
sequential LLM passes** on Claude Sonnet via Atlas Cloud. Never generate a
full story in one call — quality collapses.

## Input Schema (Level 2 — structured)

```json
{
  "topic": "string, required, 10–50 words, must contain a conflict",
  "genre": "sci-fi | fantasy | horror | drama | thriller | mystery",
  "tone": "string (default: 'emotional, cinematic')",
  "target_audience": "string (default: '18-35 general')",
  "duration_minutes": 7,          // integer 1-15 (UI slider), validated by Pydantic ge=1 le=15
  "visual_style": "string (default: 'cinematic, moody lighting, film grain')",
  "narrator_style": "string (default: 'deep, measured, documentary-like')",
  "ending": "happy | tragic | bittersweet | twist | open",
  "language": "en",
  "image_style": "cartoon_3d | anime | storybook_2d | cinematic_realistic",
  "image_model": "gpt-image-2 | nano-banana-2 | flux-schnell | auto",
  "subtitles": "burned | off",   // default "burned" — see skills/subtitles.md
  "reference_images": [
    {"asset_hint": "main character", "url": "https://.../upload.png"}
  ]
}
```

- Missing fields → fill with defaults, pass the literal string `"auto"` to the
  LLM for anything the user left open.
- `image_style` and `image_model` are REQUIRED UI selections (see
  `skills/image-pipeline.md`). `image_style` overrides the `visual_style`
  default: the matching style anchor from `STYLE_PRESETS` becomes the base of
  the Bible's `style` string.
- `reference_images` is optional — user-uploaded photos of a character,
  location, or object. They are forwarded to the Asset Bible pass (see
  `skills/asset-bible.md`). A character reference may carry an optional
  `role` (protagonist/villain/minion…).
- `relationship_hints` is optional — edges the user drew on `/create`
  (`{source, target, type, label}` keyed by asset NAME). Pass 2 is told to
  honor them, then `apply_user_hints()` force-wires them into the bible by
  fuzzy name match before `normalize_bible()` canonicalizes and dedupes.

## Word / Scene Math (drives everything)

- `duration_minutes` is user-set, **1–15 minutes** (Pydantic: ge=1, le=15).
  All targets below scale linearly from it — never hard-code 7.
- English narration ≈ **150 words/minute** → `word_target = duration_minutes
  * 150` (accept ±10%). E.g. 1 min = 150 words, 7 min = 1,050, 15 min = 2,250.
- Scene = one image + one narration segment ≈ 5–8 s → **55–75 scenes is WRONG**
  for a slideshow with Ken Burns; use **15–20 beats expanded to 60–85 scenes
  only if 1 image per sentence**. Default: **~70 scenes @ ~15 words each**
  (≈ 6 s per scene). `scene_count = duration_minutes * 10`
  (1 min = 10 scenes … 15 min = 150 scenes).
- Beats also scale: `beat_count = max(5, round(duration_minutes * 2.5))`
  capped at 30 — update the Pass 3 prompt's "15-20 beats" line to inject this
  number dynamically.
- Per scene: `duration_estimate_sec = word_count / 2.5` (estimate only — real
  timing comes from ffprobe in voice-pipeline).

## Pass 1 — Premise

System prompt (verbatim):

```
You are a professional story developer for cinematic YouTube storytelling
videos. Given the user's structured input, develop a story premise.
Respond ONLY with valid JSON, no markdown fences.

Rules:
- Honor every field the user provided. Fields marked "auto" are yours to
  decide — choose what makes the strongest story.
- The story must fit the target duration narrated at ~150 words/minute.
- Structure: 3 acts — Setup (20%), Conflict (60%), Resolution (20%).
- The opening must hook a viewer within the first 15 seconds.
- The ending must match the requested ending type.

Output:
{
  "title": "...",
  "logline": "one-sentence summary with clear conflict",
  "hook": "the opening moment, 2-3 sentences",
  "act_1_setup": "...",
  "act_2_conflict": "...",
  "act_3_resolution": "...",
  "emotional_arc": "how the viewer should feel act by act",
  "themes": ["..."]
}
```

## Pass 2 — Asset Bible

Delegated to `skills/asset-bible.md`. Input = premise JSON +
`reference_images` from the user. Output = `bible.json` — including a `role`
per character (protagonist … villain/villain_lieutenant/minion) and a
top-level `relationships` array (character↔character and character→object
edges). Output is soft-validated by `normalize_bible()` (unknown roles →
`supporting`, invalid edges dropped, warnings logged as `bible_normalized`).
Max 6 characters (fewest needed; 2–4 typical).

## Pass 3 — Beat Sheet

System prompt (verbatim):

```
You are a story editor breaking a premise into beats for a {duration_minutes}
-minute narrated video. Respond ONLY with valid JSON.

Rules:
- Produce 15-20 beats. Each beat is ONE emotional moment.
- Beat 1 IS the hook: start in motion, no slow build-up.
- Place a mini-cliffhanger or open question every 60-90 seconds of runtime.
- Every beat must reference only asset IDs that exist in the provided Bible.
- Respect character roles and the relationships array: enemies drive the
  conflict, subordinates act on their leader's orders, owned objects appear
  with their owners.
- Distribute acts: ~20% setup beats, ~60% conflict, ~20% resolution.

Input: the premise JSON and the Asset Bible JSON (provided below).

Output:
{
  "beats": [
    {
      "id": 1,
      "act": 1,
      "summary": "...",
      "emotion": "dread | wonder | grief | hope | ...",
      "cast": ["char_..."],
      "location": "loc_...",
      "props": ["obj_..."],
      "is_cliffhanger": false
    }
  ]
}
```

## Pass 4 — Scene JSON (final script)

System prompt (abridged — the authoritative prompt is `PASS4_SYSTEM` in
`backend/app/pipeline/story_engine.py`):

```
You are a screenwriter converting beats into narrated scenes for a
slideshow-style cinematic video. Respond ONLY with valid JSON.

Rules:
- Aim for about {scene_count} scenes; FEWER is correct with deep scenes
  (never more than +5, never fewer than 60% of target).
- Total narration word count: {word_target} words (±10%).
- VARY THE PACING — every scene gets a "pacing" tier:
  * "quick"    = 8-15 words (~5s): punchy reveals, reactions. ~20% of scenes.
  * "standard" = 18-30 words (~8-12s): the default.
  * "deep"     = 45-80 words (~20-32s): pivotal moments ONLY (discovery,
    twist, emotional core), 1-2 per 10 scenes, never two in a row.
- Every "deep" scene MUST include "shots": 2-5 of {"camera", "focus"} — one
  per ~12-18 words, different angles/details of the SAME location and moment
  so the screen changes every ~5-8s while one narration plays. No two
  consecutive shots share a camera. quick/standard scenes omit shots.
- Each scene lists cast / location / props by Bible ID ONLY. Do not write
  visual descriptions — code builds image prompts from the Bible.
- camera: wide | medium | close-up | over-shoulder | aerial | detail.
  Never the same camera value on two consecutive scenes when either is
  close-up. Open on a wide or aerial.
- time_of_day and weather must stay continuous unless the story moves.
- character_state: 2-4 words describing physical/emotional state
  (e.g. "exhausted, bleeding", "calm, resolute").

Output:
{
  "scenes": [
    {
      "id": 1,
      "beat_id": 1,
      "narration": "[intense] The city had been silent for 500 years.",
      "cast": ["char_rot"],
      "location": "loc_ruins",
      "props": [],
      "camera": "aerial",
      "time_of_day": "dusk",
      "weather": "orange haze",
      "character_state": "alert, wary",
      "pacing": "quick",
      "shots": [],
      "duration_estimate_sec": 6
    },
    {
      "id": 2, "...": "a deep scene adds:",
      "pacing": "deep",
      "shots": [
        {"camera": "wide", "focus": "crater rim under orange sky"},
        {"camera": "close-up", "focus": "his trembling scarred hands"},
        {"camera": "detail", "focus": "blade humming with energy"}
      ]
    }
  ]
}
```

## Validation (run after Pass 4; on failure, one repair retry)

1. JSON parses; all required keys present (Pydantic model `Script`).
2. Total words within ±10% of target.
3. Scene count within 60%…+5 of `scene_count` (deep scenes shrink the count).
4. Every `cast`/`location`/`props` ID exists in `bible.json`.
5. No two consecutive close-ups; scene 1 camera ∈ {wide, aerial}.
6. Audio tags only from the allowed list, ≤1 per scene.
6b. Pacing: no scene > 90 words; any scene > 34 words needs 2-5 shots with
   valid cameras and non-empty focus (one image per shot downstream).
7. On failure: send the validator's error list back to Sonnet with
   "Fix ONLY these issues, return the full corrected JSON." One retry max,
   then mark story `failed_validation` and surface to UI.

## Files written

```
stories/{id}/premise.json
stories/{id}/bible.json
stories/{id}/beats.json
stories/{id}/script.json     ← input for image + voice pipelines
```
