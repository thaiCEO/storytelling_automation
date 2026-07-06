"""Stage 5 — Sync & Render: images + audio -> output/final.mp4 @30fps
(1920x1080 youtube / 1080x1920 tiktok — see formats.py).

Timing source of truth = audio/manifest.json (ffprobe durations) via the
shared timeline module. Ken Burns per scene, xfade crossfades, narration
assembly, optional music ducking, loudnorm, ASS burn-in, YouTube export.
See skills/sync-render.md.
"""
from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path

from PIL import Image, ImageStat

from ..config import REPO_ROOT
from ..models import Script, StoryInput
from ..utils import ffmpeg
from ..utils.log import PipelineLog
from .formats import FORMATS, FormatSpec
from .timeline import (CROSSFADE, FPS, SceneTiming, compute_timeline,
                       total_video_duration)

CLIP_CONCURRENCY = 4  # max parallel ffmpeg processes — watch VPS CPU
XFADE_BATCH = 12      # two-level merge keeps input counts manageable
FONTS_DIR = REPO_ROOT / "assets" / "fonts"

EXPORT_ARGS = [
    "-c:v", "libx264", "-preset", "slow", "-crf", "18",
    "-pix_fmt", "yuv420p", "-r", str(FPS),
    "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart",
]


def _fpath(p: Path | str) -> str:
    """Escape a path for use inside an ffmpeg filter string."""
    return str(p).replace("\\", "/").replace(":", "\\:")


# ------------------------------------------------------------ Ken Burns clips
def kenburns_filter(scene_idx: int, camera: str, aspect: str, dur: float,
                    fmt: FormatSpec) -> str:
    """Crop (gpt aspects only) + oversized scale + zoompan. Motion alternates to
    avoid monotony; camera hints override (detail -> stronger zoom, wide/aerial
    -> pan)."""
    frames = max(2, round(dur * FPS))
    center = "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
    pan_lr = f"x='(iw-iw/zoom)*on/{frames}':y='ih/2-(ih/zoom/2)'"
    pan_rl = f"x='(iw-iw/zoom)*(1-on/{frames})':y='ih/2-(ih/zoom/2)'"

    if camera in ("aerial", "wide"):
        motion = f"z='1.05':{pan_lr if scene_idx % 2 == 0 else pan_rl}"
    elif camera == "detail":
        motion = f"z='1.0+0.15*on/{frames}':{center}"
    elif scene_idx % 4 == 3:
        motion = f"z='1.10':{pan_lr if scene_idx % 8 == 3 else pan_rl}"
    elif scene_idx % 2 == 0:
        motion = f"z='1.0+0.10*on/{frames}':{center}"     # zoom in
    else:
        motion = f"z='1.10-0.10*on/{frames}':{center}"    # zoom out

    filters = []
    if aspect in ("3:2", "2:3"):  # GPT Image 2 -> center-crop to final aspect
        filters.append(fmt.crop)
    filters.append(fmt.scale)  # oversized intermediate prevents jitter
    filters.append(
        f"zoompan={motion}:d={frames}:s={fmt.width}x{fmt.height}:fps={FPS}")
    return ",".join(filters)


async def build_clip(story_dir: Path, image_entry: dict, timing: SceneTiming,
                     camera: str, scene_idx: int, fmt: FormatSpec) -> Path:
    out = story_dir / "clips" / f"clip_{timing.scene_id:03}.mp4"
    if out.exists():  # idempotent
        return out
    vf = kenburns_filter(scene_idx, camera, image_entry["aspect"],
                         timing.video_duration, fmt)
    await ffmpeg.run([
        "-loop", "1", "-i", str(story_dir / image_entry["path"]),
        "-t", f"{timing.video_duration:.3f}",
        "-filter_complex", vf,
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p", "-an", str(out),
    ], timeout=300, cwd=story_dir)
    return out


# ------------------------------------------------------------------ xfade
async def _xfade_merge(inputs: list[Path], durations: list[float], out: Path,
                       story_dir: Path) -> float:
    """Chain xfade over inputs; returns merged duration."""
    if len(inputs) == 1:
        if not out.exists():
            await ffmpeg.run(["-i", str(inputs[0]), "-c", "copy", str(out)],
                             timeout=300, cwd=story_dir)
        return durations[0]

    lines = []
    for i in range(len(inputs)):
        lines.append(f"[{i}:v]settb=AVTB,fps={FPS}[p{i}];")
    prev = "p0"
    elapsed = durations[0]
    for i in range(1, len(inputs)):
        offset = elapsed - CROSSFADE
        label = f"m{i}" if i < len(inputs) - 1 else "vout"
        lines.append(
            f"[{prev}][p{i}]xfade=transition=fade:duration={CROSSFADE}:offset={offset:.3f}[{label}];")
        prev = label
        elapsed = elapsed + durations[i] - CROSSFADE

    if not out.exists():
        script_path = out.with_suffix(".filter")
        script_path.write_text("\n".join(lines).rstrip(";"), encoding="utf-8")
        args: list[str] = []
        for p in inputs:
            args += ["-i", str(p)]
        args += ["-filter_complex_script", str(script_path),
                 "-map", "[vout]", "-c:v", "libx264", "-preset", "medium",
                 "-crf", "18", "-pix_fmt", "yuv420p", "-an", str(out)]
        await ffmpeg.run(args, timeout=1800, cwd=story_dir)
    return elapsed


async def merge_clips(story_dir: Path, clips: list[Path],
                      durations: list[float]) -> Path:
    """Two-level batched xfade merge -> merged.mp4 (silent video)."""
    merged = story_dir / "clips" / "merged.mp4"
    if merged.exists():
        return merged

    parts: list[Path] = []
    part_durs: list[float] = []
    for b in range(math.ceil(len(clips) / XFADE_BATCH)):
        batch = clips[b * XFADE_BATCH:(b + 1) * XFADE_BATCH]
        bdurs = durations[b * XFADE_BATCH:(b + 1) * XFADE_BATCH]
        part = story_dir / "clips" / f"part_{b:03}.mp4"
        part_durs.append(await _xfade_merge(batch, bdurs, part, story_dir))
        parts.append(part)

    await _xfade_merge(parts, part_durs, merged, story_dir)
    return merged


# --------------------------------------------------------------- narration
async def build_narration(story_dir: Path, audio_manifest: list[dict],
                          timings: list[SceneTiming]) -> Path:
    """One narration track matching the video timeline exactly: lead-in
    silence + scene audios separated by gaps derived from the timeline
    (≈0.1s = padding 0.5 - crossfade 0.4, exact after frame quantization)."""
    out = story_dir / "clips" / "narration.m4a"
    if out.exists():
        return out

    fmt = "aformat=sample_rates=44100:channel_layouts=stereo"
    lines = [f"aevalsrc=0:d={timings[0].audio_start:.4f}:s=44100,{fmt}[g0];"]
    seq = ["[g0]"]
    for i, (entry, t) in enumerate(zip(audio_manifest, timings)):
        if i > 0:
            prev_end = timings[i - 1].audio_start + audio_manifest[i - 1]["duration_sec"]
            gap = max(0.001, t.audio_start - prev_end)
            lines.append(f"aevalsrc=0:d={gap:.4f}:s=44100,{fmt}[g{i}];")
            seq.append(f"[g{i}]")
        lines.append(f"[{i}:a]{fmt}[a{i}];")
        seq.append(f"[a{i}]")
    lines.append(f"{''.join(seq)}concat=n={len(seq)}:v=0:a=1[aout]")

    script_path = out.with_suffix(".filter")
    script_path.write_text("\n".join(lines), encoding="utf-8")
    args: list[str] = []
    for entry in audio_manifest:
        args += ["-i", str(story_dir / entry["path"])]
    args += ["-filter_complex_script", str(script_path),
             "-map", "[aout]", "-c:a", "aac", "-b:a", "192k", str(out)]
    await ffmpeg.run(args, timeout=600, cwd=story_dir)
    return out


# ------------------------------------------------------------------- final
async def export_story_body(story_dir: Path, inp: StoryInput, merged: Path,
                            narration: Path) -> Path:
    out_dir = story_dir / "output"
    out_dir.mkdir(exist_ok=True)
    body = out_dir / "story_body.mp4"
    if body.exists():
        return body

    music = REPO_ROOT / "assets" / "music" / f"{inp.genre}.mp3"
    burn = inp.subtitles == "burned"

    args = ["-i", str(merged), "-i", str(narration)]
    filters = []

    if burn:
        ass = _fpath(story_dir / "subtitles" / "subs.ass")
        fonts = _fpath(FONTS_DIR)
        filters.append(f"[0:v]ass='{ass}':fontsdir='{fonts}'[v]")
        vmap = "[v]"
    else:
        vmap = "0:v"

    if music.exists():
        args += ["-stream_loop", "-1", "-i", str(music)]
        filters.append("[1:a]asplit=2[nv1][nv2]")
        # music dips under speech (sidechain), then final YouTube loudness
        filters.append(
            "[2:a][nv1]sidechaincompress=threshold=0.05:ratio=8:attack=5:release=300[duck]")
        filters.append(
            "[nv2][duck]amix=inputs=2:duration=first:normalize=0,"
            "loudnorm=I=-14:TP=-1.5:LRA=11[aout]")
    else:
        filters.append("[1:a]loudnorm=I=-14:TP=-1.5:LRA=11[aout]")

    script_path = out_dir / "story_body.filter"
    script_path.write_text(";\n".join(filters), encoding="utf-8")
    args += ["-filter_complex_script", str(script_path),
             "-map", vmap, "-map", "[aout]", *EXPORT_ARGS, str(body)]
    await ffmpeg.run(args, timeout=3600, cwd=story_dir)

    # subs.srt always ships in output/ for YouTube CC upload
    srt = story_dir / "subtitles" / "subs.srt"
    if srt.exists():
        (out_dir / "subs.srt").write_bytes(srt.read_bytes())
    return body


async def prepend_hook(story_dir: Path, hook: Path | None, body: Path,
                       fmt: FormatSpec) -> Path:
    out_dir = story_dir / "output"
    final = out_dir / "final.mp4"
    manifest = out_dir / "final_manifest.json"
    if final.exists() and manifest.exists():
        return final

    if hook is None or not hook.exists():
        await ffmpeg.run(["-i", str(body), "-c", "copy", str(final)],
                         timeout=600, cwd=story_dir)
        manifest.write_text(json.dumps({"hook": None, "body": str(body)}, indent=2),
                            encoding="utf-8")
        return final

    scale = (
        f"fps={FPS},scale={fmt.width}:{fmt.height}:force_original_aspect_ratio=increase,"
        f"crop={fmt.width}:{fmt.height},setsar=1"
    )
    filters = [
        f"[0:v]{scale}[v0]",
        "[0:a]aformat=sample_rates=44100:channel_layouts=stereo[a0]",
        f"[1:v]{scale}[v1]",
        "[1:a]aformat=sample_rates=44100:channel_layouts=stereo[a1]",
        "[v0][a0][v1][a1]concat=n=2:v=1:a=1[vout][aout]",
    ]
    script_path = out_dir / "prepend_hook.filter"
    script_path.write_text(";\n".join(filters), encoding="utf-8")
    await ffmpeg.run([
        "-i", str(hook), "-i", str(body),
        "-filter_complex_script", str(script_path),
        "-map", "[vout]", "-map", "[aout]",
        *EXPORT_ARGS, str(final),
    ], timeout=3600, cwd=story_dir)
    manifest.write_text(json.dumps({"hook": str(hook), "body": str(body)}, indent=2),
                        encoding="utf-8")
    return final


async def make_thumbnail(final: Path, out_dir: Path) -> Path:
    thumb = out_dir / "thumbnail.png"
    if not thumb.exists():  # frame from the hook scene at 2s
        await ffmpeg.run(["-ss", "2", "-i", str(final), "-vframes", "1", str(thumb)],
                         timeout=120)
    return thumb


# -------------------------------------------------------------- verification
async def verify(final: Path, timings: list[SceneTiming], story_dir: Path,
                 fmt: FormatSpec, hook_duration: float = 0.0) -> list[str]:
    problems: list[str] = []
    expected = total_video_duration(timings) + hook_duration
    actual = await ffmpeg.probe_duration(final)
    if abs(actual - expected) > 2:
        problems.append(f"final duration {actual:.1f}s vs expected {expected:.1f}s (>2s off)")

    streams = await ffmpeg.probe_streams(final)
    if "codec_type=video" not in streams or "codec_type=audio" not in streams:
        problems.append("missing video or audio stream")
    if f"width={fmt.width}" not in streams or f"height={fmt.height}" not in streams:
        problems.append(f"unexpected resolution: {streams[:200]}")

    # spot-check frames at 25/50/75% are not black/corrupt
    for pct in (0.25, 0.5, 0.75):
        frame = story_dir / "output" / f"_check_{int(pct * 100)}.png"
        await ffmpeg.run(["-ss", f"{actual * pct:.2f}", "-i", str(final),
                          "-vframes", "1", str(frame)], timeout=120)
        mean = sum(ImageStat.Stat(Image.open(frame).convert("L")).mean)
        if mean < 8:
            problems.append(f"frame at {int(pct * 100)}% looks black (mean luma {mean:.1f})")
        frame.unlink(missing_ok=True)
    return problems


# -------------------------------------------------------------------- stage
async def run_render(story_dir: Path, inp: StoryInput, script: Script,
                     on_progress=None) -> Path:
    log = PipelineLog(story_dir)
    (story_dir / "clips").mkdir(exist_ok=True)
    fmt = FORMATS[inp.video_format]

    image_manifest = {e["scene_id"]: e for e in json.loads(
        (story_dir / "images" / "manifest.json").read_text(encoding="utf-8"))}
    audio_manifest = json.loads(
        (story_dir / "audio" / "manifest.json").read_text(encoding="utf-8"))
    timings = compute_timeline(audio_manifest)
    camera_by_id = {s.id: s.camera for s in script.scenes}

    # 1. per-scene Ken Burns clips (parallel, capped)
    sem = asyncio.Semaphore(CLIP_CONCURRENCY)
    done = 0

    async def clip_worker(idx: int, t: SceneTiming) -> Path:
        nonlocal done
        async with sem:
            p = await build_clip(story_dir, image_manifest[t.scene_id], t,
                                 camera_by_id.get(t.scene_id, "medium"), idx, fmt)
        done += 1
        if on_progress:
            await on_progress(done, len(timings))
        log.event("render", "clip_done", scene_id=t.scene_id)
        return p

    clips = await asyncio.gather(*(clip_worker(i, t) for i, t in enumerate(timings)))

    # 2. crossfade merge -> silent merged.mp4
    log.event("render", "merge_start", detail=f"{len(clips)} clips")
    merged = await merge_clips(story_dir, list(clips),
                               [t.video_duration for t in timings])

    # 3. narration track matching the timeline
    narration = await build_narration(story_dir, audio_manifest, timings)

    # 4. burn-in + mix + export the story body
    log.event("render", "export_start")
    body = await export_story_body(story_dir, inp, merged, narration)

    # 5. prepend the Seedance hook if this story requested one
    hook = story_dir / "hook" / "hook.mp4"
    hook_path = hook if inp.hook_enabled and hook.exists() else None
    hook_duration = await ffmpeg.probe_duration(hook_path) if hook_path else 0.0
    final = await prepend_hook(story_dir, hook_path, body, fmt)
    await make_thumbnail(final, story_dir / "output")

    # 6. verification before marking done
    problems = await verify(final, timings, story_dir, fmt, hook_duration)
    if problems:
        raise RuntimeError("render verification failed: " + "; ".join(problems))

    log.event("render", "done", detail=str(final))
    return final
