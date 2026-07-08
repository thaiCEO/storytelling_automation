"""Stage 3 — Image Pipeline: one image per scene via Atlas Cloud, sized for
the chosen video_format (16:9 YouTube / 9:16 TikTok-Reels — see formats.py).

Model + style are user-chosen (never hard-coded). Prompts are built by CODE
from the Asset Bible (visual_dna injection) — never LLM free-hand.
See skills/image-pipeline.md.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from itertools import zip_longest
from pathlib import Path

from ..clients.atlas import atlas
from ..config import settings
from ..models import (Bible, ImageManifestEntry, Scene, Script, StoryInput,
                      canonical_view)
from ..utils.cost import PRICES, add_cost
from ..utils.log import PipelineLog
from .formats import FORMATS, FormatSpec

STYLE_PRESETS = {
    "cartoon_3d": (
        "3D animated movie style, Pixar-like character design, soft rounded "
        "shapes, vibrant colors, expressive faces, cinematic lighting, high "
        "detail render"
    ),
    "anime": (
        "2D anime film style, clean line art, cel shading, detailed painted "
        "background, dramatic lighting, Makoto Shinkai-inspired atmosphere"
    ),
    "storybook_2d": (
        "2D hand-drawn children's storybook illustration, soft watercolor "
        "wash, warm pencil line art, rounded childlike proportions, simple "
        "expressive faces, muted earth colors, gentle paper texture, cinematic "
        "composition"
    ),
    "cinematic_realistic": (
        "photorealistic cinematic film still, shot on 35mm, shallow depth of "
        "field, natural skin texture, moody film lighting, film grain"
    ),
}

# GPT Image 2 output gets center-cropped to the final aspect (formats.py):
# landscape loses top/bottom, vertical loses left/right — warn the model.
SAFE_AREA_CLAUSE = {
    "youtube": ("key subject centered, comfortable headroom, nothing important "
                "at top or bottom edges"),
    "tiktok": ("key subject centered, vertical composition, nothing important "
               "at left or right edges"),
}

IMAGE_QUALITY = "high"

# hard wall-clock cap per generate+upload step: hangs that slip past the
# per-request httpx timeouts become clean, retryable failures instead of a
# silent images_running-forever stall
STEP_WATCHDOG_SEC = 600


def _flux_size(fmt: FormatSpec) -> str:
    """Native full-HD output — 1920*1080 (youtube) / 1080*1920 (tiktok).
    Atlas ranges verified 2026-07-07: flux-schnell size 256-4096,
    flux-2-pro/edit 256-2048; schnell is priced per run, not per pixel."""
    return f"{fmt.width}*{fmt.height}"


def route_model(scene: Scene, image_model: str) -> str:
    """auto-hybrid: cast scenes -> nano-banana-2, landscape -> gpt-image-2."""
    if image_model != "auto":
        return image_model
    return "nano-banana-2" if scene.cast else "gpt-image-2"


def build_prompt(scene: Scene, bible: Bible, image_style: str, model: str,
                 beat_summary: str = "", video_format: str = "youtube",
                 shot_camera: str = "", shot_focus: str = "") -> str:
    """[camera] shot of [char dna + state] in [location dna], [tod], [weather],
    [action], featuring [object dna], [style anchor last].

    shot_camera/shot_focus override per shot in multi-shot (deep) scenes."""
    camera = shot_camera or scene.camera
    parts: list[str] = []
    char_bits = []
    for cid in scene.cast:
        asset = bible.get(cid)
        if asset:
            if getattr(asset, "role", None) and asset.reference_image_url:
                dna = (
                    f"{asset.name}, exact same character from the uploaded "
                    "reference image, preserve the original face, hair, outfit, "
                    "age, body proportions, colors, and drawing style; no added "
                    "scars, age changes, realistic redesign, or costume changes"
                )
            else:
                dna = asset.visual_dna
            if scene.character_state:
                dna += ", " + scene.character_state
            char_bits.append(dna)

    loc = bible.get(scene.location)
    loc_dna = loc.visual_dna if loc else scene.location
    # per-scene spot inside the location — varies scene to scene so the same
    # location never repeats the same framing
    if scene.location_detail:
        loc_dna = f"{scene.location_detail}, {loc_dna}"

    if char_bits:
        parts.append(f"{camera} shot of " + " and ".join(char_bits))
        parts.append(f"in {loc_dna}")
    else:
        # no-cast scenes start with location DNA
        parts.append(f"{camera} shot of {loc_dna}")

    if shot_focus:
        parts.append(f"focusing on {shot_focus}")

    parts.append(scene.time_of_day)
    parts.append(scene.weather)
    if beat_summary:
        parts.append(beat_summary)

    # trim props before character DNA if the prompt runs long (40-70 words)
    prompt_so_far = ", ".join(p for p in parts if p)
    if len(prompt_so_far.split()) < 55:
        obj_bits = []
        for oid in scene.props:
            asset = bible.get(oid)
            if asset:
                obj_bits.append(asset.visual_dna)
        if obj_bits:
            parts.append("featuring " + ", ".join(obj_bits))

    # world DNA keeps different locations feeling like one universe
    if bible.world:
        parts.append(f"set in {bible.world}")

    parts.append(STYLE_PRESETS[image_style])  # style anchor LAST — every prompt
    # narration/beat text otherwise gets rendered INTO the frame as captions
    parts.append("no text, no captions, no lettering, no labels, no watermark")
    if model == "gpt-image-2":
        parts.append(SAFE_AREA_CLAUSE[video_format])
    return ", ".join(p for p in parts if p)


SHEET_KEYWORDS = [
    "character sheet",
    "turnaround",
    "refsheet",
    "model sheet",
    "reference sheet",
    "multi-view",
    "multiview",
]


def _ref_is_sheet(r) -> bool:
    """A single upload that is itself a multi-view sheet/collage."""
    if r.is_character_sheet:
        return True
    name, url = r.name.lower(), r.url.lower()
    return (any(kw in name for kw in SHEET_KEYWORDS)
            or any(kw in url for kw in ("sheet", "turnaround")))


def is_character_sheet(asset, inp: StoryInput) -> bool:
    """Check if the asset has a complete character sheet uploaded."""
    if not hasattr(asset, "role"):  # locations and objects don't have roles
        return False

    dna = (asset.visual_dna or "").lower()
    dna_keywords = SHEET_KEYWORDS
    if any(kw in dna for kw in dna_keywords):
        return True
    if "front" in dna and "side" in dna and "back" in dna:
        return True

    # Check user-uploaded reference images for matching asset
    matching_refs = []
    for r in inp.reference_images:
        if r.kind == "character" and r.url:
            if r.name and (r.name.lower() in asset.name.lower() or asset.name.lower() in r.name.lower()):
                matching_refs.append(r)

    if any(r.is_character_sheet for r in matching_refs):
        return True

    for r in matching_refs:
        name_lower = r.name.lower()
        url_lower = r.url.lower()
        if any(kw in name_lower for kw in dna_keywords) or any(kw in url_lower for kw in ["sheet", "turnaround"]):
            return True

    # NOTE: separately uploaded views are NOT a sheet — the master is a
    # plain front image, so the other views must keep riding as extra scene
    # refs (extra_view_urls) instead of being dropped as sheet-covered.
    return False


def extra_view_urls(inp: StoryInput, bible: Bible) -> dict[str, list[str]]:
    """asset_id -> user reference urls beyond the master front view
    (side/back/pose/expressions), matched to bible assets by name."""
    out: dict[str, list[str]] = {}
    for asset in bible.characters + bible.locations + bible.objects:
        if is_character_sheet(asset, inp):
            continue
        urls = [r.url for r in inp.reference_images
                if r.url and canonical_view(r.view) != "ref_front" and r.name
                and (r.name.lower() in asset.name.lower()
                     or asset.name.lower() in r.name.lower())]
        if urls:
            out[asset.id] = urls
    return out


# ---------------------------------------------------------------- view sheets
# One user upload -> a full turnaround set, so the model understands the full
# body (characters) / whole shape (objects) from every angle, not just the one
# photo. Views the user already uploaded themselves are skipped.
VIEW_PROMPTS = {
    "character": {
        "ref_front": "front-facing full-body standing pose, relaxed natural "
                     "posture, arms hanging naturally at the sides, feet "
                     "shoulder-width apart, looking directly at the camera, "
                     "gentle neutral expression, perfect symmetrical body "
                     "alignment",
        "ref_side": "full-body side profile view for side-scroll spine "
                    "reference, standing straight, whole body visible from "
                    "head to feet",
        "ref_back": "full-body back view, standing straight, whole body "
                    "visible from head to feet",
        "pose_run": "full-body dynamic running pose for the main chase action, "
                    "mid-motion, whole body visible",
        "expr_fear": "close-up portrait, fearful reaction expression, face "
                     "filling the frame",
        "expr_determined": "close-up portrait, determined hero expression, "
                           "face filling the frame",
    },
    "object": {
        "side": "side view of the object, whole object visible, centered",
        "back": "back view of the object, whole object visible, centered",
    },
}


MASTER_CHARACTER_REF_VIEW = "ref_front"


def _character_refsheet_identity(master_view: str, target_view: str) -> str:
    if target_view == master_view:
        view_rule = (
            f"Use ONLY the front-facing full-body character ({master_view}) as "
            "the source of truth. Ignore all other views. Recreate the "
            f"character exactly as shown in the {master_view} reference. "
        )
    else:
        view_rule = (
            f"Use the front-facing full-body character ({master_view}) as the "
            "source of truth for identity. Use the matching labeled view or "
            "expression in the uploaded sheet only as pose/view guidance while "
            f"preserving the {master_view} identity. "
        )

    return (
        "REFERENCE\n"
        "Use the uploaded character sheet as the ONLY master identity "
        f"reference. {view_rule}"
        "Maintain identical face shape, head size, facial proportions, "
        "hairstyle, hair color, eye shape, nose, mouth, skin tone, body "
        "proportions, arm thickness, leg thickness, hand size, foot size, "
        "barefoot or shoe state, clothing silhouette, clothing construction, "
        "primitive outfit details, belts, rope belt if present, fabric folds, "
        "clothing colors, ink line quality, watercolor rendering, paper "
        "texture, and overall illustration style. Do not redesign the "
        "character. Do not change proportions. Do not change hairstyle. Do not "
        "change clothing. Do not change colors. Do not add accessories, "
        "jewelry, shoes, logos, scars, modern outfit details, or extra costume "
        "pieces. Treat this as the permanent production model."
    )


CHARACTER_REFSHEET_BACKGROUND = (
    "BACKGROUND\n"
    "Solid neutral light gray background (#E5E5E5). Flat matte studio "
    "backdrop. No gradients. No environment. No scenery. No props. No "
    "decorative elements. No shadows on the background."
)


CHARACTER_REFSHEET_TEXT = (
    "TEXT\n"
    "Do NOT display any text. Do NOT display any labels. Do NOT display any "
    "captions. Do NOT display any titles. Do NOT display any symbols. Do NOT "
    "display any measurements. Do NOT display any watermark. Do NOT display "
    "any logo."
)


def _character_refsheet_prompt(
    view: str,
    desc: str,
    style: str,
    master_view: str = MASTER_CHARACTER_REF_VIEW,
) -> str:
    if view == master_view:
        pose = (
            "POSE\n"
            "Front-facing full-body standing pose. Relaxed natural posture. "
            "Arms hanging naturally at the sides. Feet shoulder-width apart. "
            "Looking directly at the camera. Gentle neutral expression. Perfect "
            "symmetrical body alignment."
        )
        composition = (
            "COMPOSITION\n"
            "Character centered. Entire body visible from head to toes. "
            "Comfortable margins around the character. No cropping. Portrait "
            "composition. No additional views."
        )
        output = (
            "OUTPUT\n"
            "A single front-facing full-body master character reference. No "
            "text. No labels. No additional views. Only the character on a "
            "clean light gray studio background."
        )
    elif view.startswith("expr_"):
        pose = f"POSE\n{desc}. Preserve the exact same identity from {master_view}."
        composition = (
            "COMPOSITION\n"
            "Single close-up portrait reference. Face centered and fully "
            "visible with comfortable margins. No labels. No additional views."
        )
        output = (
            f"OUTPUT\n"
            f"A single {view} close-up expression character reference. No text. "
            f"No labels. No additional views. Only the character on a clean "
            f"light gray studio background."
        )
    else:
        pose = f"POSE\n{desc}. Preserve the exact same identity from {master_view}."
        composition = (
            "COMPOSITION\n"
            "Character centered. Entire body visible from head to toes. "
            "Comfortable margins around the character. No cropping. Single "
            "reference pose. No additional views."
        )
        output = (
            f"OUTPUT\n"
            f"A single {view} full-body character reference matching the "
            f"requested view. No text. No labels. No additional views. Only "
            f"the character on a clean light gray studio background."
        )

    return (
        f"{_character_refsheet_identity(master_view, view)}\n\n"
        f"{pose}\n\n"
        f"{composition}\n\n"
        f"{CHARACTER_REFSHEET_BACKGROUND}\n\n"
        f"{CHARACTER_REFSHEET_TEXT}\n\n"
        "STYLE\n"
        "Original storybook illustration. Classic children's book illustration. "
        "Traditional watercolor painting. Hand-drawn ink line art. Soft pencil "
        "texture. Organic brush strokes. Visible paper texture. Warm earth tone "
        "palette. Natural handmade look. Minimalist character design. Family "
        "friendly. Production ready. Highly consistent character design. Ultra "
        f"detailed. 8K. {style}"
        f"\n\n{output}"
    )


def _sheet_model(image_model: str) -> str:
    """Use the locked story model for models with edit support; otherwise NB2
    has the strongest identity consistency for turnaround views."""
    if image_model in ("gpt-image-2", "flux-schnell", "grok-imagine"):
        return image_model
    return "nano-banana-2"


def _user_views(inp: StoryInput, asset) -> set[str]:
    """Canonical sheet-view keys the user already uploaded for this asset —
    each one suppresses the paid generation of that view (cost saver).

    A sheet/collage upload never counts as a view: clean standalone views
    still get generated FROM the sheet."""
    return {canonical_view(r.view) for r in inp.reference_images
            if r.url and r.name and not _ref_is_sheet(r)
            and (r.name.lower() in asset.name.lower()
                 or asset.name.lower() in r.name.lower())}


async def _build_view_sheets(bible: Bible, inp: StoryInput, story_dir: Path,
                             log: PipelineLog) -> dict[str, dict[str, str]]:
    """For every character/object with a user-uploaded master image, generate
    the missing turnaround views via the edit endpoint (identity locked to the
    upload), upload each to Atlas, and return asset_id -> {view: url}.

    refsheet.json accumulates per completed view, so a retry resumes exactly
    where the previous run stopped instead of skipping the missing views.
    Any failure stops the image stage immediately."""
    sheet_file = story_dir / "images" / "refsheet.json"
    sheets: dict[str, dict[str, str]] = {}
    if sheet_file.exists():
        raw = json.loads(sheet_file.read_text(encoding="utf-8"))
        # pre-view-keyed files (asset_id -> [urls]) lack view names — rebuild;
        # cached view PNGs make that free apart from the re-upload
        if raw and all(isinstance(v, dict) for v in raw.values()):
            sheets = raw

    todo = []
    for kind, assets in (("character", bible.characters), ("object", bible.objects)):
        for asset in assets:
            if not asset.reference_image_url:
                continue
            todo.append((kind, asset))
    if not todo:
        return sheets

    model = _sheet_model(inp.image_model)
    fmt = FORMATS[inp.video_format]
    style = STYLE_PRESETS[inp.image_style]
    refs_dir = story_dir / "images" / "refs"
    refs_dir.mkdir(parents=True, exist_ok=True)
    async def one_view(asset, kind: str, view: str, desc: str) -> str:
        if kind == "character":
            prompt = _character_refsheet_prompt(view, desc, style)
        else:
            prompt = (
                f"object turnaround reference image: the exact same {kind} as "
                f"in the reference image, identical shape, materials, colors, "
                f"surface details and scale, {desc}, {asset.visual_dna}, plain "
                f"neutral gray studio background, no text, no labels, no "
                f"watermark, {style}"
            )
        out = refs_dir / f"{asset.id}_{view}.png"
        if not out.exists():
            atlas_model, payload, _ = _payload(model, prompt,
                                               [asset.reference_image_url], fmt)
            out.write_bytes(await atlas.generate_image(payload, timeout=60))
            # price by the ACTUAL endpoint (edit vs text differ, e.g. flux)
            usd = PRICES.get(atlas_model, PRICES[model])
            add_cost(story_dir, "images", f"refsheet:{asset.id}:{view}", usd)
            log.event("images", "refsheet_generated",
                      detail=f"{asset.id} {view} {model}", cost_usd=usd)
        return await atlas.upload_media(out.read_bytes(), out.name, "image/png")

    for kind, asset in todo:
        have = _user_views(inp, asset)
        for view, desc in VIEW_PROMPTS[kind].items():
            # canonical on both sides: object keys "side"/"back" normalize
            # like the legacy upload views do
            if canonical_view(view) in have or view in sheets.get(asset.id, {}):
                continue
            try:
                url = await asyncio.wait_for(
                    one_view(asset, kind, view, desc),
                    timeout=STEP_WATCHDOG_SEC)
            except Exception as exc:
                detail = f"{asset.id} {view}: {exc}"
                log.event("images", "refsheet_failed", detail=detail)
                raise RuntimeError(f"refsheet failed for {asset.id} {view}: {exc}") from exc
            sheets.setdefault(asset.id, {})[view] = url
            sheet_file.write_text(json.dumps(sheets, indent=2), encoding="utf-8")

    sheet_file.write_text(json.dumps(sheets, indent=2), encoding="utf-8")
    log.event("images", "refsheet_done",
              detail=f"{sum(len(v) for v in sheets.values())} views "
                     f"for {len(sheets)} assets")
    return sheets


def scene_reference_urls(scene: Scene, bible: Bible, anchors: dict[str, str],
                         extra: dict[str, list[str]] | None = None) -> list[str]:
    """User uploads (bible) + consistency anchors + extra views, max 14 (NB2 limit).

    Master identity refs (upload or anchor) for every cast member, the
    location and props go FIRST, then extra views round-robin across assets —
    so per-model reference caps (grok/flux slice to 8) trim views, never a
    character's only identity reference."""
    masters: list[str] = []
    view_lists: list[list[str]] = []
    for aid in scene.cast + [scene.location] + scene.props:
        asset = bible.get(aid)
        if asset and asset.reference_image_url:
            masters.append(asset.reference_image_url)
        elif aid in anchors:
            masters.append(anchors[aid])
        if extra and aid in extra:
            view_lists.append(extra[aid])
    views = [u for group in zip_longest(*view_lists) for u in group if u]
    return list(dict.fromkeys(masters + views))[:14]


def _manifest_path(story_dir: Path) -> Path:
    return story_dir / "images" / "manifest.json"


def _status_path(story_dir: Path) -> Path:
    return story_dir / "images" / "status.json"


def _load_manifest(story_dir: Path) -> list[ImageManifestEntry]:
    path = _manifest_path(story_dir)
    if not path.exists():
        return []
    return [ImageManifestEntry.model_validate(e)
            for e in json.loads(path.read_text(encoding="utf-8"))]


def _commit_manifest_entry(story_dir: Path, entry: ImageManifestEntry,
                           log: PipelineLog) -> list[ImageManifestEntry]:
    entries = {e.scene_id: e for e in _load_manifest(story_dir)}
    existing = entries.get(entry.scene_id)
    if existing and entry.attempts == 0:
        entry = existing.model_copy(update={
            "path": entry.path,
            "extra_shots": entry.extra_shots,
            "prompt": entry.prompt,
            "model": entry.model,
            "aspect": entry.aspect,
        })
    entries[entry.scene_id] = entry
    ordered = sorted(entries.values(), key=lambda e: e.scene_id)
    _manifest_path(story_dir).write_text(
        json.dumps([e.model_dump() for e in ordered], indent=2),
        encoding="utf-8")
    log.event("images", "manifest_committed",
              detail=f"{len(ordered)} image entries", scene_id=entry.scene_id)
    return ordered


def _mark_scene_status(story_dir: Path, scene_id: int, status: str,
                       detail: str = "") -> None:
    path = _status_path(story_dir)
    statuses = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    statuses[str(scene_id)] = {
        "status": status,
        "detail": detail,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    path.write_text(json.dumps(statuses, indent=2), encoding="utf-8")


def _payload(model: str, prompt: str, ref_urls: list[str],
             fmt: FormatSpec) -> tuple[str, dict, str]:
    """-> (atlas_model_id, request_payload, aspect)."""
    if model == "grok-imagine":
        # Atlas schema: references go in "image_urls", NOT "images"; no
        # output_format param; resolution is "1k" | "2k". Docs claim 8 ref
        # images but the live API rejects >5 with HTTP 400.
        if ref_urls:
            return settings.image_edit_model_grok, {
                "model": settings.image_edit_model_grok, "prompt": prompt,
                "image_urls": ref_urls[:5], "aspect_ratio": fmt.nb2_aspect,
                "resolution": "2k",
            }, fmt.nb2_aspect
        return settings.image_model_grok, {
            "model": settings.image_model_grok, "prompt": prompt,
            "aspect_ratio": fmt.nb2_aspect, "resolution": "2k",
        }, fmt.nb2_aspect
    if model == "flux-schnell":
        if ref_urls:
            return settings.image_edit_model_flux, {
                "model": settings.image_edit_model_flux, "prompt": prompt,
                "images": ref_urls[:8], "size": _flux_size(fmt),
                "output_format": "png", "safety_tolerance": 2, "seed": -1,
            }, fmt.nb2_aspect
        return settings.image_model_flux, {
            "model": settings.image_model_flux, "prompt": prompt,
            "size": _flux_size(fmt), "seed": -1, "num_images": 1,
        }, fmt.nb2_aspect
    if model == "gpt-image-2":
        if ref_urls:
            return settings.image_edit_model_gpt, {
                "model": settings.image_edit_model_gpt, "prompt": prompt,
                "images": ref_urls, "input_fidelity": "high",
                "size": fmt.gpt_size, "quality": "high",
            }, fmt.gpt_aspect
        return settings.image_model_gpt, {
            "model": settings.image_model_gpt, "prompt": prompt,
            "size": fmt.gpt_size, "quality": IMAGE_QUALITY, "output_format": "png",
        }, fmt.gpt_aspect
    # nano-banana-2 — native 16:9 and 9:16
    payload = {
        "model": settings.image_model_nb2, "prompt": prompt,
        "aspect_ratio": fmt.nb2_aspect, "resolution": "2k", "output_format": "png",
    }
    if ref_urls:
        payload["images"] = ref_urls
    return settings.image_model_nb2, payload, fmt.nb2_aspect


def scene_shot_list(scene: Scene) -> list[tuple[str, str]]:
    """(camera, focus) per shot; scenes without shots render exactly one
    image from the scene's own camera (pre-pacing scripts unchanged)."""
    if scene.shots:
        return [(sh.camera, sh.focus) for sh in scene.shots]
    return [(scene.camera, "")]


async def _generate_one(scene: Scene, bible: Bible, inp: StoryInput,
                        story_dir: Path, log: PipelineLog,
                        anchors: dict[str, str], extra: dict[str, list[str]],
                        beat_summaries: dict[int, str]) -> ImageManifestEntry:
    fmt = FORMATS[inp.video_format]
    model = route_model(scene, inp.image_model)
    ref_urls = scene_reference_urls(scene, bible, anchors, extra)
    shots = scene_shot_list(scene)

    paths: list[str] = []
    first_prompt = ""
    aspect = fmt.nb2_aspect
    generated_any = False
    for k, (cam, focus) in enumerate(shots, 1):
        suffix = "" if k == 1 else f"_s{k}"  # shot 1 keeps the legacy name
        out = story_dir / "images" / f"scene_{scene.id:03}{suffix}.png"
        prompt = build_prompt(scene, bible, inp.image_style, model,
                              beat_summaries.get(scene.beat_id, ""),
                              inp.video_format, shot_camera=cam, shot_focus=focus)
        if k == 1:
            first_prompt = prompt
        atlas_model, payload, aspect = _payload(model, prompt, ref_urls, fmt)
        if not out.exists():  # idempotent per shot file
            content = await asyncio.wait_for(
                atlas.generate_image(payload, timeout=60), timeout=STEP_WATCHDOG_SEC)
            out.write_bytes(content)
            # price by the ACTUAL endpoint (edit vs text differ, e.g. flux)
            usd = PRICES.get(atlas_model, PRICES[model])
            add_cost(story_dir, "images",
                     f"scene:{scene.id} shot:{k} model:{model}", usd)
            log.event("images", "generated",
                      detail=f"{model} shot:{k}/{len(shots)} refs:{len(ref_urls)}",
                      scene_id=scene.id, cost_usd=usd)
            generated_any = True
        paths.append(f"images/{out.name}")

    return ImageManifestEntry(scene_id=scene.id, path=paths[0],
                              extra_shots=paths[1:], prompt=first_prompt,
                              model=model, aspect=aspect,
                              attempts=1 if generated_any else 0)


def _anchor_path(story_dir: Path) -> Path:
    return story_dir / "images" / "anchors.json"


def _load_anchors(story_dir: Path) -> dict[str, str]:
    path = _anchor_path(story_dir)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


async def _record_scene_anchors(scene: Scene, bible: Bible, story_dir: Path,
                                anchors: dict[str, str],
                                log: PipelineLog) -> None:
    """After a scene is complete, reuse it as the future consistency anchor
    for newly-seen characters that do not already have a user upload."""
    png = story_dir / "images" / f"scene_{scene.id:03}.png"
    for cid in scene.cast:
        asset = bible.get(cid)
        if not asset or asset.reference_image_url or cid in anchors:
            continue
        url = await atlas.upload_media(png.read_bytes(), png.name, "image/png")
        anchors[cid] = url
        _anchor_path(story_dir).write_text(json.dumps(anchors, indent=2),
                                           encoding="utf-8")
        log.event("images", "anchor_uploaded", detail=cid, scene_id=scene.id)


async def run_image_pipeline(story_dir: Path, inp: StoryInput, script: Script,
                             bible: Bible, on_progress=None) -> list[ImageManifestEntry]:
    """Generate every scene image; write images/manifest.json.

    Never hands off to sync-render unless every scene has an image.
    """
    log = PipelineLog(story_dir)
    (story_dir / "images").mkdir(parents=True, exist_ok=True)

    beats_path = story_dir / "beats.json"
    beat_summaries: dict[int, str] = {}
    if beats_path.exists():
        for b in json.loads(beats_path.read_text(encoding="utf-8")).get("beats", []):
            beat_summaries[b["id"]] = b.get("summary", "")

    # reference view sheets first: one user upload -> full turnaround set
    # (side/back/pose/expression) so every scene sees the full body
    extra = extra_view_urls(inp, bible)
    sheets = await _build_view_sheets(bible, inp, story_dir, log)
    for aid, view_urls in sheets.items():
        extra.setdefault(aid, []).extend(view_urls.values())

    # Anchors are recorded inside the scene loop so scene generation remains
    # strictly in script order: scene 1 completes before scene 2 starts.
    anchors = _load_anchors(story_dir)

    done = 0
    entries: list[ImageManifestEntry] = []

    for scene in script.scenes:
        try:
            entry = await _generate_one(scene, bible, inp, story_dir, log,
                                        anchors, extra, beat_summaries)
            entries = _commit_manifest_entry(story_dir, entry, log)
            await _record_scene_anchors(scene, bible, story_dir, anchors, log)
            _mark_scene_status(story_dir, scene.id, "completed")
        except Exception as exc:
            detail = str(exc)
            _mark_scene_status(story_dir, scene.id, "failed", detail)
            log.event("images", "image_failed", detail=detail, scene_id=scene.id)
            raise RuntimeError(f"scene {scene.id} image failed: {exc}") from exc

        done += 1
        if on_progress:
            await on_progress(done, len(script.scenes))

    entries_by_id = {e.scene_id: e for e in _load_manifest(story_dir)}
    missing = [
        str(scene.id) for scene in script.scenes
        if scene.id not in entries_by_id
        or not all((story_dir / p).exists()
                   for p in [entries_by_id[scene.id].path]
                   + entries_by_id[scene.id].extra_shots)
    ]
    if missing:
        raise RuntimeError("image manifest missing scene(s): " + ", ".join(missing))

    entries = [entries_by_id[scene.id] for scene in script.scenes]
    log.event("images", "manifest_written", detail=f"{len(entries)} images")
    return entries
