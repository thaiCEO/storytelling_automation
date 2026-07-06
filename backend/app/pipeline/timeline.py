"""Shared timeline math — single source of truth for sync-render AND subtitles.

scene_video_duration = audio_duration + 0.5   (breathing room)
crossfade            = 0.4                    (overlaps neighbours)
scene_start[n]       = scene_start[n-1] + scene_video_duration[n-1] - crossfade
audio_start[n]       = scene_start[n] + 0.25  (never rides a transition)

See skills/sync-render.md.
"""
from __future__ import annotations

from dataclasses import dataclass

PADDING = 0.5
CROSSFADE = 0.4
AUDIO_OFFSET = 0.25  # half the padding
FPS = 30


@dataclass
class SceneTiming:
    scene_id: int
    video_start: float
    video_duration: float
    audio_start: float
    audio_duration: float


def compute_timeline(audio_manifest: list[dict]) -> list[SceneTiming]:
    """audio_manifest entries: {scene_id, duration_sec, ...} in scene order."""
    timings: list[SceneTiming] = []
    start = 0.0
    for entry in audio_manifest:
        # quantize to the frame grid so xfade offsets, narration gaps and
        # subtitle cues all agree with the real rendered clip durations
        vdur = round((entry["duration_sec"] + PADDING) * FPS) / FPS
        timings.append(SceneTiming(
            scene_id=entry["scene_id"],
            video_start=round(start, 3),
            video_duration=round(vdur, 3),
            audio_start=round(start + AUDIO_OFFSET, 3),
            audio_duration=entry["duration_sec"],
        ))
        start += vdur - CROSSFADE
    return timings


def total_video_duration(timings: list[SceneTiming]) -> float:
    if not timings:
        return 0.0
    last = timings[-1]
    return round(last.video_start + last.video_duration, 3)
