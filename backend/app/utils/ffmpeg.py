"""Thin async wrappers around ffmpeg/ffprobe subprocesses.

Subprocesses run in a worker thread via subprocess.run instead of
asyncio.create_subprocess_exec: uvicorn --reload on Windows uses the
SelectorEventLoop, where asyncio subprocesses raise NotImplementedError.
"""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from ..config import settings


class FFmpegError(RuntimeError):
    pass


def _run_blocking(args: list[str], timeout: float,
                  cwd: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, timeout=timeout, cwd=cwd)


async def run(args: list[str], timeout: float = 600, cwd: Path | str | None = None) -> str:
    """Run ffmpeg with args (no leading binary), raise FFmpegError on failure."""
    full = [settings.ffmpeg_bin, "-hide_banner", "-y", *args]
    try:
        proc = await asyncio.to_thread(_run_blocking, full, timeout,
                                       str(cwd) if cwd else None)
    except subprocess.TimeoutExpired:
        raise FFmpegError(f"ffmpeg timed out after {timeout}s: {' '.join(args[:8])}...")
    if proc.returncode != 0:
        tail = proc.stderr.decode(errors="replace")[-2000:]
        raise FFmpegError(f"ffmpeg exit {proc.returncode}: {tail}")
    return proc.stderr.decode(errors="replace")  # ffmpeg logs to stderr


async def probe_duration(path: Path | str) -> float:
    """Real media duration in seconds — the timing source of truth."""
    args = [settings.ffprobe_bin, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(path)]
    try:
        proc = await asyncio.to_thread(_run_blocking, args, 60)
    except subprocess.TimeoutExpired:
        raise FFmpegError(f"ffprobe timed out on {path}")
    if proc.returncode != 0:
        raise FFmpegError(
            f"ffprobe failed on {path}: {proc.stderr.decode(errors='replace')[-500:]}")
    try:
        return float(proc.stdout.decode().strip())
    except ValueError:
        raise FFmpegError(f"ffprobe returned no duration for {path}")


async def probe_streams(path: Path | str) -> str:
    """codec_type lines for stream presence checks (video/audio)."""
    args = [settings.ffprobe_bin, "-v", "error",
            "-show_entries", "stream=codec_type,width,height,avg_frame_rate",
            "-of", "default=noprint_wrappers=1", str(path)]
    try:
        proc = await asyncio.to_thread(_run_blocking, args, 60)
    except subprocess.TimeoutExpired:
        raise FFmpegError(f"ffprobe timed out on {path}")
    return proc.stdout.decode(errors="replace")
