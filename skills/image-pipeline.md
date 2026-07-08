---
name: image-pipeline
description: Generate all scene images in 16:9 for YouTube with a user-selectable image model (GPT Image 2 / Nano Banana 2 / Flux Schnell / auto-hybrid) and a user-selectable image style (cartoon 3D, anime, cinematic realistic). Use this skill whenever generating images, building image prompts from the Asset Bible, routing between image models, applying style presets, handling reference-image edits, 16:9 sizing/cropping, or debugging retries and image costs.
---

# Image Pipeline (Stage 3)

Loops over `script.json` scenes and produces one 16:9 image per scene via
Atlas Cloud. Both the **image model** and the **image style** are chosen by
the user in the Nuxt UI and flow through the backend as part of the story
input — never hard-code either.

## User selection 1 — `image_style` (UI: style cards with sample thumbnails)

| UI label (km) | value | style anchor appended to EVERY prompt |
|---|---|---|
| តុក្កតា 3D | `cartoon_3d` | "3D animated movie style, Pixar-like character design, soft rounded shapes, vibrant colors, expressive faces, cinematic lighting, high detail render" |
| អានីមេ | `anime` | "2D anime film style, clean line art, cel shading, detailed painted background, dramatic lighting, Makoto Shinkai-inspired atmosphere" |
| រឿងនិទាន 2D | `storybook_2d` | "2D hand-drawn children's storybook illustration, soft watercolor wash, warm pencil line art, rounded childlike proportions, simple expressive faces, muted earth colors, gentle paper texture, cinematic composition" |
| ដូចមនុស្សពិត | `cinematic_realistic` | "photorealistic cinematic film still, shot on 35mm, shallow depth of field, natural skin texture, moody film lighting, film grain" |

Backend: `STYLE_PRESETS` dict in `images.py`. The chosen anchor:
1. Is passed to the Asset Bible pass so `bible.style` matches (see
   `skills/asset-bible.md`) — visual_dna wording must fit the style
   (e.g. no "skin pores" in cartoon_3d).
2. Is appended as the FINAL clause of every image prompt. One style per
   story — never mix styles across scenes.

UI note (frontend `/create`): show the three options as image cards
(pre-generated samples in `frontend/public/styles/`), single-select,
required. Store as `image_style` in the story input.

## User selection 2 — `image_model` (UI: radio under Advanced, default `auto`)

| value | model(s) | price/img | best for |
|---|---|---|---|
| `gpt-image-2` | `openai/gpt-image-2/text-to-image` + `/edit` | $0.008 | cheapest, ~$0.56/video |
| `nano-banana-2` | `google/nano-banana-2/text-to-image` + edit | ~$0.056 | strongest character consistency (14 reference images), native 16:9, ~$3.92/video |
| `flux-schnell` | `black-forest-labs/flux-schnell` + `black-forest-labs/flux-2-pro/edit` | ~$0.038 | fast Flux generation, native 16:9/9:16 via size |
| `auto` (default) | hybrid routing | ~$2–2.5/video | best quality-per-dollar |

**Auto-hybrid routing rule (in `images.py`):**
- Scene has `cast` (characters visible) → **Nano Banana 2** with the
  character's reference image(s) attached (anchor or user upload).
- Scene has empty `cast` (landscape/establishing, ~30% of scenes) →
  **GPT Image 2**.

UI must show the live per-video cost estimate next to each option
(`scene_count × price`, split by routing for `auto`).

## Sizing per `video_format` (16:9 YouTube / 9:16 TikTok-Reels)

Story input `video_format`: `youtube` (default, 1920x1080 landscape) |
`tiktok` (1080x1920 vertical, also for Reels/Shorts). All geometry lives in
`pipeline/formats.py` (`FORMATS` dict) — never hard-code sizes.

**Nano Banana 2:** native both ways — pass `"aspect_ratio": "16:9"` or
`"9:16"` (plus `"resolution": "2k"`). No crop needed downstream; record
`aspect: "16:9"` / `"9:16"` in the manifest.

**GPT Image 2:** no native 16:9 or 9:16. Generate the nearest size —
`1536x1024` (3:2) for youtube, `1024x1536` (2:3) for tiktok — then
sync-render center-crops (landscape: 1536x864, loses 80 px top/bottom;
vertical: 864x1536, loses 80 px left/right) and scales up (Ken Burns hides
the upscale). Append the orientation-matched safe-area clause to GPT Image 2
prompts only (`SAFE_AREA_CLAUSE[video_format]` in images.py). Record
`aspect: "3:2"` / `"2:3"` in the manifest so sync-render knows which files
to crop.

## Prompt builder (code, not LLM)

```
[camera] shot of [char.visual_dna + ", " + character_state]
in [location.visual_dna], [time_of_day], [weather],
[action summary from beat], featuring [object.visual_dna],
[STYLE_PRESETS[image_style]]            ← style anchor LAST
(+ safe-area clause if model == gpt-image-2)
```

Rules:
- Subject first, style anchor last. 40–70 words; trim props before
  character DNA.
- No-cast scenes: start with location DNA.

## API calls

```python
# GPT Image 2 (text-to-image)
{"model": "openai/gpt-image-2/text-to-image", "prompt": p,
 "size": "1536x1024", "quality": IMAGE_QUALITY, "output_format": "png"}

# GPT Image 2 (edit — reference images present)
{"model": "openai/gpt-image-2/edit", "prompt": p,
 "images": [ref_urls], "input_fidelity": "high",
 "size": "1536x1024", "quality": "high"}

# Nano Banana 2 (text-to-image / edit)
{"model": "google/nano-banana-2/text-to-image", "prompt": p,
 "aspect_ratio": "16:9", "resolution": "2k",
 "output_format": "png"}
# edit variant: add "images": [ref_urls] (up to 14)

# Flux Schnell (text-to-image) — size 256-4096/dim, priced PER RUN
# ($0.003) so full HD costs the same as 720p; always request native
# 1920*1080 (youtube) / 1080*1920 (tiktok)
{"model": "black-forest-labs/flux-schnell", "prompt": p,
 "size": "1920*1080", "seed": -1, "num_images": 1}

# Grok Imagine (text-to-image) — NO output_format param; resolution 1k|2k
{"model": "xai/grok-imagine-image/text-to-image", "prompt": p,
 "aspect_ratio": "16:9", "resolution": "2k"}

# Grok Imagine (edit — reference images present)
# CRITICAL: references go in "image_urls", NOT "images".
# An "images" key is silently ignored by Atlas and the model degrades to
# pure text-to-image — generated characters won't match the upload at all.
# Docs claim up to 8 reference images; the LIVE API rejects >5 (HTTP 400
# "supports at most 5 input image(s)") — cap at 5.
{"model": "xai/grok-imagine-image/edit", "prompt": p,
 "image_urls": [ref_urls],  # max 5 (live limit)
 "aspect_ratio": "16:9", "resolution": "2k"}

# Flux 2 Pro Edit (reference/edit) — size 256-2048/dim ($0.03/pic),
# refs go in "images" (1-8)
{"model": "black-forest-labs/flux-2-pro/edit", "prompt": p,
 "images": [ref_urls], "size": "1920*1080",
 "output_format": "png", "safety_tolerance": 2, "seed": -1}
```

Reference-image triggers (both models): any asset with
`reference_image_url` (user upload — see `skills/asset-bible.md`), or
consistency-anchor mode (scene-1 render of the main character uploaded via
`uploadMedia` and reused for all later scenes with that character).

Reference ordering (`scene_reference_urls` in images.py): master identity
refs (upload/anchor) for EVERY cast member + location + props go first,
then extra turnaround views round-robin across assets. Never fill all of
one character's views before another character's master — per-model caps
(grok/flux slice to 8) would silently drop later characters' identity in
multi-cast scenes.

## Concurrency, retries, cost

- 4 concurrent requests (asyncio.Semaphore(4)); ~70 scenes ≈ 5–9 min.
- 2 retries on error/timeout (60 s), backoff 2s/8s → `image_failed` →
  UI "regenerate failed scenes".
- Log per-call cost into `cost.json` using the ACTUAL model used per scene:
  gpt-image-2 $0.008, nano-banana-2 ~$0.056 (verify current rate on the
  Atlas model page at setup — promo pricing changes).

## Output contract

```
stories/{id}/images/scene_001.png ...          ← shot 1 (legacy name; also
                                                  anchor/hook/thumbnail source)
stories/{id}/images/scene_001_s2.png ...       ← shots 2..N of deep scenes
stories/{id}/images/manifest.json
  ← [{scene_id, path, extra_shots: [..], prompt, model, aspect, attempts}]
```

Deep scenes (script `shots` array — see skills/story-engine.md) render one
image per shot: `build_prompt(..., shot_camera=, shot_focus=)` swaps the
camera and appends "focusing on {focus}"; same references for every shot of
the scene.

Never proceed to sync-render unless every scene has an image in the
manifest.
