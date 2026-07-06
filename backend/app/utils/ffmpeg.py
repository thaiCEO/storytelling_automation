"""Thin async wrappers around ffmpeg/ffprobe subprocesses."""
from __future__ import annotations

import asyncio
from pathlib import Path

from ..config import settings


class FFmpegError(RuntimeError):
    pass


async def run(args: list[str], timeout: float = 600, cwd: Path | str | None = None) -> str:
    """Run ffmpeg with args (no leading binary), raise FFmpegError on failure."""
    proc = await asyncio.create_subprocess_exec(
        settings.ffmpeg_bin, "-hide_banner", "-y", *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        cwd=str(cwd) if cwd else None,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise FFmpegError(f"ffmpeg timed out after {timeout}s: {' '.join(args[:8])}...")
    if proc.returncode != 0:
        tail = err.decode(errors="replace")[-2000:]
        raise FFmpegError(f"ffmpeg exit {proc.returncode}: {tail}")
    return err.decode(errors="replace")  # ffmpeg logs to stderr


async def probe_duration(path: Path | str) -> float:
    """Real media duration in seconds — the timing source of truth."""
    proc = await asyncio.create_subprocess_exec(
        settings.ffprobe_bin, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise FFmpegError(f"ffprobe failed on {path}: {err.decode(errors='replace')[-500:]}")
    try:
        return float(out.decode().strip())
    except ValueError:
        raise FFmpegError(f"ffprobe returned no duration for {path}")


async def probe_streams(path: Path | str) -> str:
    """codec_type lines for stream presence checks (video/audio)."""
    proc = await asyncio.create_subprocess_exec(
        settings.ffprobe_bin, "-v", "error",
        "-show_entries", "stream=codec_type,width,height,avg_frame_rate",
        "-of", "default=noprint_wrappers=1", str(path),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    return out.decode(errors="replace")
