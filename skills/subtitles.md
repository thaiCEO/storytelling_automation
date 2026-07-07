---
name: subtitles
description: Generate word-synced subtitles from the narration and burn them into the final video with FFmpeg. Use this skill whenever working on subtitles, captions, SRT/ASS files, subtitle styling, timing text to speech, or the burn-in step of the render.
---

# Subtitles (Stage 4.5 — between voice-pipeline and sync-render)

Creates subtitles that appear on the video **while the narration is
speaking**, generated 100% by code from data the pipeline already has
(narration text + real audio timings). **Zero API cost.**

## UI option

Story input field `subtitles`: `"burned" | "off"` (default `"burned"`).
Nuxt `/create` — simple toggle "Subtitles on video". When `"off"`, this
stage still writes the `.srt` file (useful for YouTube upload) but
sync-render skips the burn-in filter.

## Input → Output

```
IN : script.json (narration per scene)
     audio/manifest.json (real duration_sec per scene, from ffprobe)
     sync timeline offsets (same math as sync-render)
OUT: subtitles/subs.srt   ← plain, for YouTube upload
     subtitles/subs.ass   ← styled, for FFmpeg burn-in
```

## Step 1 — Clean the text

Strip ALL audio tags (`[whispers]`, `[excited]`, `[pause]`, `[sad]`,
`[intense]`) from narration before subtitle use — they must never appear
on screen.

Cue text never ENDS with `.` or `,` (incl. `...`) — strip them from the
end of every cue (`strip_trailing_punct` in subtitles.py). Mid-cue
punctuation and meaningful `?` / `!` endings stay.

## Step 2 — Timing (per scene, then per chunk)

Scene audio start time = the scene's audio offset from the sync-render
timeline (scene visual start + 0.25 s). Within a scene, split narration
into chunks and distribute time **proportionally by character count**:

```python
CHARS_PER_LINE = 42          # max, Netflix-style readability
MAX_LINES = 1                # one line per cue (short scenes = short text)

def chunk(narration):        # split on punctuation first, then length
    ...

for scene in scenes:
    t0 = scene.audio_start
    total_chars = len(clean_text)
    for c in chunks:
        dur = scene.audio_duration * len(c) / total_chars
        yield Cue(start=t0, end=t0 + dur - 0.05, text=c)
        t0 += dur
```

Rules:
- Min cue duration 0.8 s — merge a too-short chunk into its neighbor.
- Cues never cross scene boundaries.
- Proportional timing is accurate enough at 10–20 words/scene. (Upgrade
  path if ever needed: per-character timestamps from the TTS response, or
  forced alignment — do NOT build this in v1.)

## Step 3 — Write files

**SRT** (plain):

```
1
00:00:00,250 --> 00:00:03,100
The city had been silent for 500 years.
```

**ASS** (styled for burn-in) — single style, defined once in the header:

```
[V4+ Styles]
Style: Cap,Inter,58,&H00FFFFFF,&H000000FF,&H00101010,&H96000000,-1,0,0,0,100,100,0,0,1,3,1,2,80,80,72,1
```

Meaning: white bold text, dark outline 3px + soft shadow (readable on any
image), alignment 2 (bottom-center), vertical margin 72 px — inside YouTube
safe area, above the progress bar. Font: bundle `assets/fonts/Inter.ttf`
and point FFmpeg at it with `fontsdir` so the VPS render is deterministic.

**Per `video_format`** (`ASS_STYLE` + `CHARS_PER_LINE` in subtitles.py):
youtube = PlayRes 1920x1080, font 58, MarginV 72, 42 chars/line;
tiktok = PlayRes 1080x1920, font 64, MarginV 340 (keeps text above the
TikTok/Reels caption + button overlays), 26 chars/line.

## Step 4 — Burn-in (hook in sync-render)

Applied ONCE on the final concatenated video (not per scene clip), as the
last video filter before export:

```bash
ffmpeg -i merged.mp4 -vf "ass=subtitles/subs.ass:fontsdir=assets/fonts" \
  <export settings from skills/sync-render.md> output/final.mp4
```

If `subtitles == "off"`: skip this filter; still keep `subs.srt` in
outputs so it can be uploaded to YouTube as closed captions (better for
SEO + viewer choice).

## Validation

1. Cue count > 0 and last cue end ≤ video duration.
2. No overlapping cues; no cue < 0.8 s or > 7 s.
3. No `[` or `]` characters in any cue (tag leak check).
4. Spot-check: extract 3 frames at random cue midpoints and confirm text
   is visible (same frame-extraction trick as sync-render verification).
