"""Video format geometry — single source of truth for output size per platform.

youtube: 16:9 landscape 1920x1080 (YouTube)
tiktok : 9:16 vertical  1080x1920 (TikTok / Reels / Shorts)

GPT Image 2 has no native 16:9 or 9:16, so it generates the nearest size
(3:2 or 2:3) and sync-render center-crops with `crop`; Nano Banana 2 is
native for both aspects and skips the crop.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FormatSpec:
    label: str
    width: int        # final export
    height: int
    nb2_aspect: str   # nano-banana-2 aspect_ratio param (native, no crop)
    gpt_size: str     # gpt-image-2 size param
    gpt_aspect: str   # manifest aspect recorded for gpt files
    crop: str         # center-crop gpt output to the final aspect
    scale: str        # 4x supersampled intermediate against zoompan jitter


# zoompan crops on INTEGER source pixels, so slow Ken Burns moves step less
# than 1px/frame and visibly judder unless the source is heavily oversampled:
# 4x intermediate + 2x zoompan output + lanczos downscale = sub-pixel motion.
FORMATS: dict[str, FormatSpec] = {
    "youtube": FormatSpec(
        label="YouTube 16:9", width=1920, height=1080,
        nb2_aspect="16:9", gpt_size="1536x1024", gpt_aspect="3:2",
        crop="crop=1536:864:(iw-1536)/2:(ih-864)/2",   # cut 80px top+bottom
        scale="scale=7680:4320"),
    "tiktok": FormatSpec(
        label="TikTok / Reels 9:16", width=1080, height=1920,
        nb2_aspect="9:16", gpt_size="1024x1536", gpt_aspect="2:3",
        crop="crop=864:1536:(iw-864)/2:0",             # cut 80px left+right
        scale="scale=4320:7680"),
}
