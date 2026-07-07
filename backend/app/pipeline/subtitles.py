"""Stage 4.5 — Subtitles: SRT (plain) + ASS (styled burn-in), $0, 100% code.

Timing is proportional-by-characters within each scene's real audio window.
See skills/subtitles.md.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from ..models import Script
from ..utils.log import PipelineLog
from .timeline import SceneTiming, compute_timeline

MIN_CUE = 0.8
MAX_CUE = 7.0
CUE_GAP = 0.05

# max chars per line: 42 = Netflix-style for landscape; vertical screens are
# much narrower, so shorter lines for tiktok
CHARS_PER_LINE = {"youtube": 42, "tiktok": 26}

ASS_HEADER_TEMPLATE = """[Script Info]
ScriptType: v4.00+
PlayResX: {play_x}
PlayResY: {play_y}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Inter,{font_size},&H00FFFFFF,&H000000FF,&H00101010,&H96000000,-1,0,0,0,100,100,0,0,1,3,1,2,{margin_lr},{margin_lr},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

# youtube: bottom-center inside YouTube safe area, above the progress bar.
# tiktok: MarginV 340 keeps text above TikTok/Reels caption + button overlays.
ASS_STYLE = {
    "youtube": {"play_x": 1920, "play_y": 1080, "font_size": 58,
                "margin_lr": 80, "margin_v": 72},
    "tiktok": {"play_x": 1080, "play_y": 1920, "font_size": 64,
               "margin_lr": 60, "margin_v": 340},
}


@dataclass
class Cue:
    start: float
    end: float
    text: str


def strip_tags(text: str) -> str:
    """Audio tags must never appear on screen."""
    return re.sub(r"\s*\[[^\]]*\]\s*", " ", text).strip()


def strip_trailing_punct(text: str) -> str:
    """On-screen style: cues never END with '.' or ',' (incl. '...');
    mid-cue punctuation and meaningful '?' / '!' endings stay."""
    return re.sub(r"[.,]+$", "", text.strip()).strip()


def chunk(narration: str, max_chars: int = 42) -> list[str]:
    """Split on punctuation first, then length (<= max_chars chars)."""
    pieces = re.split(r"(?<=[.!?;,—])\s+", narration.strip())
    chunks: list[str] = []
    for piece in pieces:
        piece = piece.strip()
        if not piece:
            continue
        if len(piece) <= max_chars:
            chunks.append(piece)
            continue
        # too long — split on word boundaries
        words, cur = piece.split(), ""
        for w in words:
            if cur and len(cur) + 1 + len(w) > max_chars:
                chunks.append(cur)
                cur = w
            else:
                cur = f"{cur} {w}".strip()
        if cur:
            chunks.append(cur)
    return chunks


def scene_cues(timing: SceneTiming, narration: str,
               max_chars: int = 42) -> list[Cue]:
    """Distribute the scene's audio window proportionally by character count."""
    text = strip_tags(narration)
    chunks = chunk(text, max_chars)
    if not chunks:
        return []

    # pre-merge chunks whose proportional duration would be < MIN_CUE
    total_chars = sum(len(c) for c in chunks)
    dur_of = lambda c: timing.audio_duration * len(c) / total_chars
    merged = list(chunks)
    i = 0
    while len(merged) > 1 and i < len(merged):
        if dur_of(merged[i]) < MIN_CUE:
            if i + 1 < len(merged):
                merged[i:i + 2] = [merged[i] + " " + merged[i + 1]]
            else:
                merged[i - 1:i + 1] = [merged[i - 1] + " " + merged[i]]
            i = 0  # re-scan after merge
        else:
            i += 1

    cues: list[Cue] = []
    t0 = timing.audio_start
    total_chars = sum(len(c) for c in merged)
    for c in merged:
        dur = timing.audio_duration * len(c) / total_chars
        end = min(t0 + dur - CUE_GAP, t0 + MAX_CUE)
        text = strip_trailing_punct(c)
        if text:  # a punctuation-only chunk vanishes entirely
            cues.append(Cue(start=round(t0, 3), end=round(end, 3), text=text))
        t0 += dur
    return cues


def _srt_ts(t: float) -> str:
    ms = round(t * 1000)
    h, rem = divmod(ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def _ass_ts(t: float) -> str:
    cs = round(t * 100)
    h, rem = divmod(cs, 360_000)
    m, rem = divmod(rem, 6_000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02}:{s:02}.{cs:02}"


def write_srt(cues: list[Cue], path: Path) -> None:
    lines = []
    for i, c in enumerate(cues, 1):
        lines += [str(i), f"{_srt_ts(c.start)} --> {_srt_ts(c.end)}", c.text, ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_ass(cues: list[Cue], path: Path,
              video_format: str = "youtube") -> None:
    lines = [ASS_HEADER_TEMPLATE.format(**ASS_STYLE[video_format])]
    for c in cues:
        text = c.text.replace("\n", "\\N")
        lines.append(f"Dialogue: 0,{_ass_ts(c.start)},{_ass_ts(c.end)},Cap,,0,0,0,,{text}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def validate_cues(cues: list[Cue], video_duration: float | None = None) -> list[str]:
    errors: list[str] = []
    if not cues:
        errors.append("no cues generated")
        return errors
    for a, b in zip(cues, cues[1:]):
        if b.start < a.end:
            errors.append(f"overlapping cues at {a.end:.2f}s")
    for c in cues:
        if c.end - c.start < MIN_CUE - 0.01:
            errors.append(f"cue < {MIN_CUE}s at {c.start:.2f}s: '{c.text[:30]}'")
        if c.end - c.start > MAX_CUE:
            errors.append(f"cue > {MAX_CUE}s at {c.start:.2f}s")
        if "[" in c.text or "]" in c.text:
            errors.append(f"audio tag leaked into cue at {c.start:.2f}s")
    if video_duration and cues[-1].end > video_duration:
        errors.append(f"last cue ends {cues[-1].end:.2f}s after video end")
    return errors


def run_subtitles(story_dir: Path, script: Script,
                  video_format: str = "youtube") -> Path:
    """Always writes subs.srt + subs.ass (burn-in decision happens in render)."""
    log = PipelineLog(story_dir)
    subs_dir = story_dir / "subtitles"
    subs_dir.mkdir(parents=True, exist_ok=True)

    audio_manifest = json.loads(
        (story_dir / "audio" / "manifest.json").read_text(encoding="utf-8"))
    timings = compute_timeline(audio_manifest)
    narration_by_id = {s.id: s.narration for s in script.scenes}

    max_chars = CHARS_PER_LINE[video_format]
    cues: list[Cue] = []
    for t in timings:
        cues.extend(scene_cues(t, narration_by_id.get(t.scene_id, ""), max_chars))

    errors = validate_cues(cues)
    hard = [e for e in errors if "leaked" in e or e == "no cues generated"]
    if hard:
        raise RuntimeError("subtitle validation failed: " + "; ".join(hard))
    for e in errors:
        log.event("subtitles", "warning", detail=e)

    write_srt(cues, subs_dir / "subs.srt")
    write_ass(cues, subs_dir / "subs.ass", video_format)
    log.event("subtitles", "written", detail=f"{len(cues)} cues")
    return subs_dir / "subs.ass"
