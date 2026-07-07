---
name: sync-render
description: Sync images to real audio durations and render the final 1080p YouTube MP4 with FFmpeg (Ken Burns motion, crossfades, music ducking, loudness normalization). Use this skill whenever assembling video, writing FFmpeg filter graphs, fixing audio/video sync, timing scenes, adding background music, or exporting the final file.
---

# Sync & Render (Stage 5)

Assembles `images/` + `audio/` into `output/final.mp4` (H.264; 1920x1080
for `video_format: youtube`, 1080x1920 for `tiktok` — geometry from
`pipeline/formats.py`, never hard-coded). Timing source of truth =
`audio/manifest.json` durations.

Format consequences: the per-scene crop (gpt aspects 3:2 / 2:3 only), the
oversized zoompan intermediate, the zoompan output size, and the resolution
check in verification all come from `FORMATS[inp.video_format]`. The 16:9
examples below show the youtube numbers.

## Timing math

```
scene_video_duration = audio_duration + 0.5   # breathing room
crossfade = 0.4                                # overlaps neighbours
scene_start[n] = scene_start[n-1] + scene_video_duration[n-1] - crossfade
```

Audio for scene n starts exactly at the scene's visual start + 0.25 s
(half the padding) so narration never rides a transition.

## Per-scene clip: crop to 16:9 + Ken Burns

Check `images/manifest.json` per scene: files with `aspect: "3:2"`
(GPT Image 2) need the crop below; files with `aspect: "16:9"`
(Nano Banana 2) skip the `crop=` filter and go straight to scale + zoompan.
For 3:2 sources (1536x1024), crop to exact 16:9 then animate:

```bash
ffmpeg -framerate 30 -loop 1 -i scene_001.png -t {dur} \
  -filter_complex "
    crop=1536:864:(iw-1536)/2:(ih-864)/2,
    scale=7680:4320,
    zoompan=z='1.0+0.10*on/({dur}*30)':
      x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':
      d={dur}*30:s=3840x2160:fps=30,
    scale=1920:1080:flags=lanczos
  " -c:v libx264 -preset medium -crf 18 -pix_fmt yuv420p clip_001.mp4
```

- Alternate motion per scene to avoid monotony: even scenes zoom-in
  (1.0→1.10), odd scenes zoom-out (1.10→1.0); every 4th scene pan
  left↔right instead (animate `x` across the 3:2 overwidth).
- Anti-jitter supersampling is MANDATORY: zoompan crops on integer source
  pixels, so slow moves step <1px/frame and judder. 4x intermediate
  (`scale=7680:4320`) + zoompan at 2x target (`s=3840x2160`) + final
  `scale=1920:1080:flags=lanczos` keeps steps sub-pixel. A 1.2x
  intermediate with zoompan straight to 1080p visibly shakes.
- Camera hint from script.json may override: `detail` → stronger zoom 1.15;
  `aerial`/`wide` → slow pan only.

## Multi-shot (deep) scenes

A scene whose image-manifest entry carries `extra_shots` gets one Ken Burns
sub-clip per shot (`clip_XXX_s1.mp4`…), chained with the same 0.4s xfade
into `clip_XXX.mp4`. Sub-clip lengths come from `_shot_frames()` in
render.py — integer frame counts padded by CF_FRAMES per join so the merged
clip reproduces the scene's quantized duration EXACTLY (the outer xfade
offsets depend on it). Per-shot cameras come from the script's `shots`.

## Assembly

1. Build all scene clips in parallel (max 4 ffmpeg processes — watch VPS CPU).
2. Concat with crossfades — chain `xfade=transition=fade:duration=0.4`
   (generate the filter graph programmatically; 70 inputs by hand is
   unmaintainable).
3. Narration track: concat scene MP3s with the same offsets
   (`adelay` per scene → `amix`), or simpler: build one narration file first
   with 0.5 s silences (`ffmpeg -f lavfi -i anullsrc` segments) matching the
   video timeline exactly.

## Music + final mix

- Optional `assets/music/{genre}.mp3` loop under narration.
- Sidechain ducking so music dips under speech:

```
[music][voice]sidechaincompress=threshold=0.05:ratio=8:attack=5:release=300
```

- Final loudness for YouTube: `loudnorm=I=-14:TP=-1.5:LRA=11`.

## Subtitle burn-in (before export)

If story input `subtitles == "burned"`, apply the ASS filter from
`skills/subtitles.md` on the merged video as the LAST video filter:
`-vf "ass=subtitles/subs.ass:fontsdir=assets/fonts"`. If "off", skip the
filter but copy `subs.srt` into `output/` for manual YouTube CC upload.

## Export settings (YouTube)

```bash
-c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p -r 30 \
-c:a aac -b:a 192k -movflags +faststart
```

Output: `stories/{id}/output/final.mp4` (~7 min ≈ 300–500 MB at CRF 18).
Also write `output/thumbnail.png` — frame from the hook scene at 2 s
(`-ss 2 -vframes 1`), user can replace later.

## Verification before marking `done`

1. `ffprobe` final duration within ±2 s of narration total + paddings.
2. Audio stream present, video 1920x1080@30.
3. Spot-check: extract frames at 25%/50%/75% (`-vf fps=...`) and confirm they
   are not black/corrupt.
4. Write `cost.json` final totals (LLM + images + TTS) and `status: done`.
