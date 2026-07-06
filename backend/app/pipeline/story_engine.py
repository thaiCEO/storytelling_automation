"""Stage 1 — Story Engine: 4 sequential LLM passes -> validated script.json.

Premise -> Asset Bible -> Beat Sheet -> Scene JSON. Prompts are verbatim from
skills/story-engine.md and skills/asset-bible.md, with the dynamic counts
(beat_count / scene_count / word_target) injected. Never one-shot the story.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..clients.atlas import atlas, parse_llm_json
from ..models import (ALLOWED_AUDIO_TAGS, CHARACTER_ROLES, RELATIONSHIP_TYPES,
                      Beat, BeatSheet, Bible, Premise, Relationship, Scene,
                      Script, StoryInput)
from ..utils.cost import add_cost
from ..utils.log import PipelineLog

PASS1_SYSTEM = """You are a professional story developer for cinematic YouTube storytelling
videos. Given the user's structured input, develop a story premise.
Respond ONLY with valid JSON, no markdown fences.

Rules:
- Honor every field the user provided. Fields marked "auto" are yours to
  decide — choose what makes the strongest story.
- Language: write all story text in English. If the topic includes Khmer or
  any other non-English text, translate/adapt it into natural English.
- The story must fit the target duration narrated at ~150 words/minute.
- Structure: 3 acts — Setup (20%), Conflict (60%), Resolution (20%).
- The opening must hook a viewer within the first 15 seconds.
- The ending must match the requested ending type.

Output:
{
  "title": "...",
  "logline": "one-sentence summary with clear conflict",
  "hook": "the opening moment, 2-3 sentences",
  "act_1_setup": "...",
  "act_2_conflict": "...",
  "act_3_resolution": "...",
  "emotional_arc": "how the viewer should feel act by act",
  "themes": ["..."]
}"""

PASS2_SYSTEM = """You are a production designer creating an Asset Bible for a cinematic video.
Respond ONLY with valid JSON matching the provided schema.

Rules:
- Write all output text in English.
- Derive every asset from the premise. Max 6 characters (use the FEWEST the
  story needs — 2-4 is typical; go higher only when the premise implies a
  hierarchy or ensemble), 4 locations, 3 objects.
- Every character gets a "role", exactly one of: protagonist | deuteragonist |
  villain | villain_lieutenant | minion | mentor | ally | love_interest |
  supporting. Exactly one protagonist. If the premise implies henchmen, build
  the chain: villain -commands-> villain_lieutenant -commands-> minion.
- "relationships": every character must appear in at least one relationship.
  type is exactly one of: parent_of | sibling_of | commands | ally_of |
  enemy_of | loves | mentors | owns | uses.
  Directions: parent_of = parent->child; commands = leader->subordinate;
  mentors = mentor->student; loves = who loves whom (label "mutual" if
  returned); owns and uses = character->object only.
  Emit symmetric types (sibling_of, ally_of, enemy_of) ONCE, not twice.
  source/target must be ids defined in this bible. Locations never appear
  in relationships. label: optional 2-6 words of nuance.
- visual_dna: 15-35 words, concrete and repeatable. No vague adjectives.
  No time-of-day or weather in location DNA.
- style: one line combining the user's visual_style with genre-appropriate
  cinematography language.
- world: one line (15-30 words) describing the shared world/era aesthetic
  every location belongs to — era, architecture family, technology level,
  color palette, atmosphere (e.g. "year-3000 megacity world: chrome towers
  overgrown with bioluminescent vines, holographic signage, teal-amber haze").
  Every location's visual_dna must clearly fit this world, so different
  places all feel like the same universe.
- If a USER REFERENCE IMAGE is listed for an asset hint, still write full
  visual_dna describing what is IN that image (you will be shown the image),
  and set reference_image_url to the given URL. If a LOCATION reference is
  marked "world style", derive the "world" line from that image's aesthetic.

Schema:
{
  "style": "one line of cinematography language",
  "world": "one line: shared world/era aesthetic of all locations",
  "characters": [{"id": "char_...", "name": "...", "role": "protagonist", "visual_dna": "...", "reference_image_url": null}],
  "locations":  [{"id": "loc_...",  "name": "...", "visual_dna": "...", "reference_image_url": null}],
  "objects":    [{"id": "obj_...",  "name": "...", "visual_dna": "...", "reference_image_url": null}],
  "relationships": [{"source": "char_...", "target": "char_... | obj_...", "type": "commands", "label": ""}]
}

Additional visual_dna rules:
- Concrete nouns + measurable attributes only. Ban vague words: "beautiful",
  "cool", "interesting", "unique".
- Characters: age, ethnicity/build, face detail, hair, outfit, one signature
  feature (the thing viewers recognize).
- Locations: architecture/terrain, scale, color palette, atmosphere.
- Objects: shape, material, color, one distinctive detail.
- The chosen image style for this story is: {image_style_anchor}
  bible "style" must start from this style anchor, and every visual_dna's
  wording must fit it (e.g. for cartoon 3D describe "rounded friendly face,
  big expressive eyes", not "skin pores, film grain"; for cinematic realistic
  use photographic language)."""

PASS3_SYSTEM = """You are a story editor breaking a premise into beats for a {duration_minutes}
-minute narrated video. Respond ONLY with valid JSON.

Rules:
- Write all output text in English.
- Produce {beat_count} beats. Each beat is ONE emotional moment.
- Beat 1 IS the hook: start in motion, no slow build-up.
- Place a mini-cliffhanger or open question every 60-90 seconds of runtime.
- Every beat must reference only asset IDs that exist in the provided Bible.
- Respect character roles and the relationships array: enemies drive the
  conflict, subordinates act on their leader's orders, owned objects appear
  with their owners.
- Distribute acts: ~20% setup beats, ~60% conflict, ~20% resolution.

Input: the premise JSON and the Asset Bible JSON (provided below).

Output:
{{
  "beats": [
    {{
      "id": 1,
      "act": 1,
      "summary": "...",
      "emotion": "dread | wonder | grief | hope | ...",
      "cast": ["char_..."],
      "location": "loc_...",
      "props": ["obj_..."],
      "is_cliffhanger": false
    }}
  ]
}}"""

PASS4_SYSTEM = """You are a screenwriter converting beats into narrated scenes for a
slideshow-style cinematic video. Respond ONLY with valid JSON.

Rules:
- Expand the beats into exactly {scene_count} scenes (±5).
- Total narration word count: {word_target} words (±10%).
- Voice language is English only. narration must be natural English prose for
  spoken delivery; never write Khmer or other non-English script in narration.
- narration: 10-20 words per scene, written for spoken delivery in the
  requested narrator style. Insert ElevenLabs v3 audio tags sparingly where
  they add emotion: [whispers] [excited] [sad] [pause] [intense]. At most one
  tag per scene, none on more than 40% of scenes.
- Each scene lists cast / location / props by Bible ID ONLY. Do not write
  visual descriptions — code builds image prompts from the Bible.
- camera: wide | medium | close-up | over-shoulder | aerial | detail.
  Never the same camera value on two consecutive scenes when either is
  close-up. Open on a wide or aerial.
- time_of_day and weather must stay continuous unless the story moves.
- location_detail: 3-8 words naming the SPECIFIC spot, area or angle of the
  scene's location (e.g. "collapsed monorail platform", "neon market alley",
  "rooftop garden above the canal"). Consecutive scenes at the same location
  MUST use different location_detail so the visuals vary from scene to scene
  while staying inside the same place and world.
- character_state: 2-4 words describing physical/emotional state
  (e.g. "exhausted, bleeding", "calm, resolute").

Output:
{{
  "scenes": [
    {{
      "id": 1,
      "beat_id": 1,
      "narration": "[intense] The city had been silent for 500 years.",
      "cast": ["char_rot"],
      "location": "loc_ruins",
      "location_detail": "collapsed monorail platform",
      "props": [],
      "camera": "aerial",
      "time_of_day": "dusk",
      "weather": "orange haze",
      "character_state": "alert, wary",
      "duration_estimate_sec": 6
    }}
  ]
}}"""

REPAIR_SYSTEM = (
    "You previously produced the JSON below, but it failed validation. "
    "Fix ONLY these issues, return the full corrected JSON. "
    "Respond ONLY with valid JSON, no markdown fences."
)


def _llm_cost_share(inp: StoryInput) -> float:
    # per-pass share of the linear LLM estimate (4 passes per story)
    return inp.duration_minutes * 0.07 / 4


async def _pass(story_dir: Path, log: PipelineLog, inp: StoryInput, name: str,
                system: str, user_content, temperature: float = 0.8,
                max_tokens: int = 8192) -> dict:
    log.event("story", f"{name}_start")
    text = await atlas.chat(system, user_content, temperature=temperature,
                            max_tokens=max_tokens)
    usd = _llm_cost_share(inp)
    add_cost(story_dir, "llm", f"pass:{name}", usd)
    data = await _parse_or_repair_json(
        story_dir, log, inp, name, text, user_content, max_tokens)
    log.event("story", f"{name}_done", cost_usd=usd)
    return data


def _write_debug_text(story_dir: Path, name: str, suffix: str, text: str) -> Path:
    debug_dir = story_dir / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)
    path = debug_dir / f"{name}_{suffix}.txt"
    path.write_text(text, encoding="utf-8")
    return path


def _json_error_detail(exc: json.JSONDecodeError) -> str:
    return f"{exc.msg}: line {exc.lineno} column {exc.colno} (char {exc.pos})"


def _content_to_text(user_content: Any) -> str:
    if isinstance(user_content, str):
        return user_content
    if not isinstance(user_content, list):
        return str(user_content)

    parts: list[str] = []
    for item in user_content:
        if not isinstance(item, dict):
            parts.append(str(item))
            continue
        if item.get("type") == "text":
            parts.append(str(item.get("text", "")))
        elif item.get("type") == "image_url":
            image_url = item.get("image_url", {})
            url = image_url.get("url", "") if isinstance(image_url, dict) else ""
            parts.append(f"[image_url: {url}]")
    return "\n".join(p for p in parts if p)


async def _parse_or_repair_json(
    story_dir: Path,
    log: PipelineLog,
    inp: StoryInput,
    name: str,
    text: str,
    user_content: Any,
    max_tokens: int,
) -> dict:
    try:
        return parse_llm_json(text)
    except json.JSONDecodeError as exc:
        detail = _json_error_detail(exc)
        raw_path = _write_debug_text(story_dir, name, "raw_invalid_json", text)
        log.event("story", f"{name}_json_parse_failed",
                  detail=f"{detail}; raw={raw_path.name}")

    repair_system = (
        "You are a JSON repair assistant. The previous response for this "
        "story-generation task was invalid JSON. Return the complete corrected "
        "JSON object only, no markdown fences or commentary. If the response "
        "was truncated, reconstruct missing required fields from the task "
        "context."
    )
    repair_user = (
        "Original task context:\n"
        + _content_to_text(user_content)
        + "\n\nInvalid JSON response:\n"
        + text
    )
    log.event("story", f"{name}_json_repair_start")
    repair_text = await atlas.chat(
        repair_system, repair_user, temperature=0.1, max_tokens=max_tokens)
    usd = _llm_cost_share(inp)
    add_cost(story_dir, "llm", f"pass:{name}:json_repair", usd)

    try:
        data = parse_llm_json(repair_text)
    except json.JSONDecodeError as exc:
        detail = _json_error_detail(exc)
        repair_path = _write_debug_text(
            story_dir, name, "repair_invalid_json", repair_text)
        log.event("story", f"{name}_json_repair_failed",
                  detail=f"{detail}; raw={repair_path.name}")
        raise RuntimeError(
            f"{name} returned invalid JSON after repair ({detail}); "
            f"raw outputs saved in {story_dir / 'debug'}"
        ) from exc

    log.event("story", f"{name}_json_repair_done", cost_usd=usd)
    return data


def _scene_pass_max_tokens(scene_count: int) -> int:
    # A full scene object is much larger than its narration. The prior
    # 60-token-per-scene estimate can truncate 7+ minute scripts near the end.
    return min(64000, max(8192, scene_count * 160 + 1000))


# -------------------------------------------------- user relationship hints
def _user_hint_block(inp: StoryInput) -> str:
    """Render the user's roles + drawn relationships as a prompt block so the
    LLM builds the cast around them. Empty when the user drew nothing."""
    lines: list[str] = []
    for r in inp.reference_images:
        if r.kind == "character" and r.role and r.name:
            lines.append(f'- character "{r.name}" MUST have role: {r.role}')
    for h in inp.relationship_hints:
        if not (h.source and h.target):
            continue
        lines.append(f'- "{h.source}" {h.type} "{h.target}"'
                     + (f' ({h.label})' if h.label else ''))
    if not lines:
        return ""
    return ("\n\nUSER-SPECIFIED ROLES & RELATIONSHIPS (honor these exactly — "
            "create characters/objects with these names and wire them as "
            "stated; you may add more characters to complete the story):\n"
            + "\n".join(lines))


def _match_asset_by_name(name: str, assets: list) -> object | None:
    """Fuzzy name match (user hint name ↔ generated asset name), reusing the
    same containment rule as the reference-url wiring below."""
    n = name.strip().lower()
    if not n:
        return None
    for a in assets:
        an = a.name.lower()
        if n == an or n in an or an in n:
            return a
    return None


def apply_user_hints(bible: Bible, inp: StoryInput) -> list[str]:
    """Force the user's drawn roles/relationships into the freshly generated
    bible. Runs BEFORE normalize_bible, which then canonicalizes and dedupes
    everything (so a hint the LLM already satisfied won't double up)."""
    warnings: list[str] = []

    for r in inp.reference_images:
        if r.kind != "character" or not r.role:
            continue
        match = _match_asset_by_name(r.name, bible.characters)
        if match:
            match.role = r.role   # canonicalized by normalize_bible
        else:
            warnings.append(f'role hint for "{r.name}" — no matching character, skipped')

    pool = bible.characters + bible.objects
    for h in inp.relationship_hints:
        if not (h.source and h.target):
            continue
        src = _match_asset_by_name(h.source, pool)
        tgt = _match_asset_by_name(h.target, pool)
        if not src or not tgt:
            missing = h.source if not src else h.target
            warnings.append(f'relationship "{h.source}->{h.target}" — "{missing}" not found, skipped')
            continue
        bible.relationships.append(
            Relationship(source=src.id, target=tgt.id, type=h.type, label=h.label))
    return warnings


# --------------------------------------------------------------- validation
ROLE_ALIASES = {
    "hero": "protagonist", "main": "protagonist", "lead": "protagonist",
    "antagonist": "villain", "child_villain": "villain_lieutenant",
    "lieutenant": "villain_lieutenant", "henchman": "minion",
    "henchmen": "minion", "sidekick": "ally", "friend": "ally",
    "lover": "love_interest", "romance": "love_interest",
    "side": "supporting", "npc": "supporting",
}

# aliases mapping to (canonical_type, flip_direction)
REL_ALIASES = {
    "child_of": ("parent_of", True), "father_of": ("parent_of", False),
    "mother_of": ("parent_of", False), "serves": ("commands", True),
    "works_for": ("commands", True), "leads": ("commands", False),
    "rules": ("commands", False), "wields": ("uses", False),
    "carries": ("uses", False), "possesses": ("owns", False),
    "has": ("owns", False), "rival_of": ("enemy_of", False),
    "hates": ("enemy_of", False), "friend_of": ("ally_of", False),
    "teaches": ("mentors", False), "mentor_of": ("mentors", False),
}

# symmetric types are deduped regardless of edge direction
SYMMETRIC_TYPES = {"sibling_of", "ally_of", "enemy_of"}


def normalize_bible(bible: Bible) -> list[str]:
    """Coerce LLM-emitted roles/relationships to canon in place.

    Returns human-readable warnings; never raises — a broken relationship is
    dropped, an unknown role becomes 'supporting' (the graph must render no
    matter what the LLM produced).
    """
    warnings: list[str] = []

    for c in bible.characters:
        raw = c.role.strip().lower().replace(" ", "_").replace("-", "_")
        role = ROLE_ALIASES.get(raw, raw)
        if role not in CHARACTER_ROLES:
            warnings.append(f"character {c.id}: unknown role '{c.role}' -> supporting")
            role = "supporting"
        c.role = role

    char_ids = {c.id for c in bible.characters}
    obj_ids = {o.id for o in bible.objects}
    valid_ids = char_ids | obj_ids
    kept, seen = [], set()
    for r in bible.relationships:
        raw = r.type.strip().lower().replace(" ", "_").replace("-", "_")
        canon, flip = REL_ALIASES.get(raw, (raw, False))
        if canon not in RELATIONSHIP_TYPES:
            warnings.append(f"relationship {r.source}->{r.target}: unknown type '{r.type}', dropped")
            continue
        r.type = canon
        if flip:
            r.source, r.target = r.target, r.source
        if r.source not in valid_ids or r.target not in valid_ids:
            warnings.append(f"relationship {r.source}-[{r.type}]->{r.target}: unknown or location id, dropped")
            continue
        if r.source == r.target:
            warnings.append(f"relationship {r.source}: self-edge dropped")
            continue
        if r.type in ("owns", "uses") and (r.source not in char_ids or r.target not in obj_ids):
            warnings.append(f"relationship {r.source}-[{r.type}]->{r.target}: must be character->object, dropped")
            continue
        if r.type not in ("owns", "uses") and r.target in obj_ids:
            warnings.append(f"relationship {r.source}-[{r.type}]->{r.target}: objects only allow owns/uses, dropped")
            continue
        key = (frozenset({r.source, r.target}) if r.type in SYMMETRIC_TYPES
               else (r.source, r.target), r.type)
        if key in seen:
            warnings.append(f"relationship {r.source}-[{r.type}]->{r.target}: duplicate dropped")
            continue
        seen.add(key)
        kept.append(r)
    bible.relationships = kept

    connected = {r.source for r in kept} | {r.target for r in kept}
    for c in bible.characters:
        if c.id not in connected:
            warnings.append(f"character {c.id} ({c.name}) has no relationships")
    return warnings


def validate_script(script: Script, bible: Bible, inp: StoryInput) -> list[str]:
    errors: list[str] = []
    ids = bible.asset_ids()

    total_words = sum(len(_strip_tags(s.narration).split()) for s in script.scenes)
    lo, hi = inp.word_target * 0.9, inp.word_target * 1.1
    if not lo <= total_words <= hi:
        errors.append(
            f"total narration words {total_words} outside ±10% of target {inp.word_target}")

    if abs(len(script.scenes) - inp.scene_count) > 5:
        errors.append(
            f"scene count {len(script.scenes)} outside ±5 of target {inp.scene_count}")

    for s in script.scenes:
        for ref in s.cast + [s.location] + s.props:
            if ref not in ids:
                errors.append(f"scene {s.id}: unknown Bible id '{ref}'")

    for prev, cur in zip(script.scenes, script.scenes[1:]):
        if prev.camera == "close-up" and cur.camera == "close-up":
            errors.append(f"scenes {prev.id}->{cur.id}: two consecutive close-ups")
    if script.scenes and script.scenes[0].camera not in ("wide", "aerial"):
        errors.append(f"scene 1 camera must be wide or aerial, got '{script.scenes[0].camera}'")

    import re
    for s in script.scenes:
        tags = re.findall(r"\[[^\]]+\]", s.narration)
        bad = [t for t in tags if t not in ALLOWED_AUDIO_TAGS]
        if bad:
            errors.append(f"scene {s.id}: disallowed audio tags {bad}")
        if len(tags) > 1:
            errors.append(f"scene {s.id}: more than one audio tag")
        if re.search(r"[\u1780-\u17FF]", s.narration):
            errors.append(f"scene {s.id}: narration must be English; found Khmer script")
    return errors


def _strip_tags(text: str) -> str:
    import re
    return re.sub(r"\[[^\]]+\]", "", text).strip()


class ValidationFailed(RuntimeError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors[:10]))
        self.errors = errors


def find_uploaded_character_sheet_url(asset_name: str, inp: StoryInput) -> str | None:
    keywords = ["character sheet", "turnaround", "refsheet", "model sheet", "reference sheet", "sheet"]
    # 1. Check if there is an image explicitly named or containing keywords in URL/name
    for r in inp.reference_images:
        if r.kind != "character" or not r.url:
            continue
        if r.is_character_sheet and r.name and (
            r.name.lower() in asset_name.lower()
            or asset_name.lower() in r.name.lower()
        ):
            return r.url
        if r.name and (r.name.lower() in asset_name.lower() or asset_name.lower() in r.name.lower()):
            name_lower = r.name.lower()
            url_lower = r.url.lower()
            if any(kw in name_lower for kw in keywords) or any(kw in url_lower for kw in ["sheet", "turnaround"]):
                return r.url
    # 2. Check if the user uploaded all 5 views separately. If so, use the front view as the master reference image.
    matching = [r for r in inp.reference_images
                if r.kind == "character" and r.url and r.name
                and (r.name.lower() in asset_name.lower() or asset_name.lower() in r.name.lower())]
    views = {r.view for r in matching}
    if {"front", "side", "back", "pose", "expression"}.issubset(views):
        front_ref = next((r for r in matching if r.view == "front"), None)
        if front_ref:
            return front_ref.url
    return None


# -------------------------------------------------------------------- stage
async def run_story_engine(story_dir: Path, inp: StoryInput) -> Script:
    """Runs passes 1-4, writes premise/bible/beats/script JSON files.

    Resumable: each pass is skipped if its output file already exists.
    """
    from .images import STYLE_PRESETS  # style anchor feeds the Bible pass

    log = PipelineLog(story_dir)
    story_dir.mkdir(parents=True, exist_ok=True)

    # ---- Pass 1: Premise
    premise_path = story_dir / "premise.json"
    if premise_path.exists():
        premise = Premise.model_validate_json(premise_path.read_text(encoding="utf-8"))
    else:
        user = "User input:\n" + inp.model_dump_json(indent=2, exclude={"reference_images"})
        data = await _pass(story_dir, log, inp, "premise", PASS1_SYSTEM, user)
        premise = Premise.model_validate(data)
        premise_path.write_text(premise.model_dump_json(indent=2), encoding="utf-8")

    # ---- Pass 2: Asset Bible (vision if user reference images present)
    bible_path = story_dir / "bible.json"
    if bible_path.exists():
        bible = Bible.model_validate_json(bible_path.read_text(encoding="utf-8"))
    else:
        system = PASS2_SYSTEM.replace("{image_style_anchor}", STYLE_PRESETS[inp.image_style])
        text_part = (
            "Premise:\n" + premise.model_dump_json(indent=2)
            + f"\n\nUser visual_style: {inp.visual_style}\nGenre: {inp.genre}"
        )
        text_part += _user_hint_block(inp)
        # hint-only boxes (no upload) have url="" — they feed the hint block
        # above but must never reach the vision payload
        vision_refs = [r for r in inp.reference_images if r.url]
        if vision_refs:
            refs = "\n".join(
                f'- {r.asset_hint} ({r.view} view'
                + (', full character sheet / turnaround - preserve exact design'
                   if r.is_character_sheet else '')
                + (', world style — defines the world aesthetic, not one fixed spot'
                   if r.kind == 'location' and r.mode == 'world' else '')
                + f'): {r.url}'
                for r in vision_refs)
            text_part += "\n\nUSER REFERENCE IMAGES (shown below in order):\n" + refs
            content: list[dict] = [{"type": "text", "text": text_part}]
            for r in vision_refs:
                content.append({"type": "image_url", "image_url": {"url": r.url}})
            data = await _pass(story_dir, log, inp, "bible", system, content, temperature=0.6)
        else:
            data = await _pass(story_dir, log, inp, "bible", system, text_part, temperature=0.6)
        bible = Bible.model_validate(data)
        for w in apply_user_hints(bible, inp):
            log.event("story", "bible_user_hint", detail=w)
        for w in normalize_bible(bible):
            log.event("story", "bible_normalized", detail=w)
        # enforce user-provided reference urls even if the LLM dropped them.
        # Only the "front" view becomes the master reference_image_url; other
        # views stay on the input and are added as extra refs per scene.
        kind_lists = {"character": bible.characters,
                      "location": bible.locations, "object": bible.objects}
        # world-mode location refs guide the Bible's "world" line only — they
        # must never lock scene generation to one fixed photo
        world_urls = {r.url for r in inp.reference_images
                      if r.url and r.kind == "location" and r.mode == "world"}
        for loc in bible.locations:
            if loc.reference_image_url in world_urls:
                loc.reference_image_url = None
        for r in inp.reference_images:
            if not r.url or r.view != "front":
                continue
            if r.kind == "location" and r.mode == "world":
                continue
            assets = kind_lists[r.kind]
            match = next(
                (a for a in assets if r.name
                 and (r.name.lower() in a.name.lower()
                      or a.name.lower() in r.name.lower())), None)
            if match is None:  # unnamed upload → first asset of that kind
                match = next((a for a in assets if not a.reference_image_url), None)
            if match and not match.reference_image_url:
                match.reference_image_url = r.url
        # Force set master reference image URL if a complete character sheet is uploaded
        for char in bible.characters:
            sheet_url = find_uploaded_character_sheet_url(char.name, inp)
            if sheet_url:
                char.reference_image_url = sheet_url
        bible_path.write_text(bible.model_dump_json(indent=2), encoding="utf-8")

    # ---- Pass 3: Beat Sheet
    beats_path = story_dir / "beats.json"
    if beats_path.exists():
        beats = BeatSheet.model_validate_json(beats_path.read_text(encoding="utf-8"))
    else:
        system = PASS3_SYSTEM.format(
            duration_minutes=inp.duration_minutes, beat_count=inp.beat_count)
        user = ("Premise:\n" + premise.model_dump_json(indent=2)
                + "\n\nAsset Bible:\n" + bible.model_dump_json(indent=2))
        data = await _pass(story_dir, log, inp, "beats", system, user)
        beats = BeatSheet.model_validate(data)
        beats_path.write_text(beats.model_dump_json(indent=2), encoding="utf-8")

    # ---- Pass 4: Scene JSON + validation with one repair retry
    script_path = story_dir / "script.json"
    if script_path.exists():
        return Script.model_validate_json(script_path.read_text(encoding="utf-8"))

    system = PASS4_SYSTEM.format(scene_count=inp.scene_count, word_target=inp.word_target)
    user = (
        "Narrator style: " + inp.narrator_style
        + "\nTone: " + inp.tone
        + "\n\nAsset Bible:\n" + bible.model_dump_json(indent=2)
        + "\n\nBeats:\n" + beats.model_dump_json(indent=2)
    )
    max_tokens = _scene_pass_max_tokens(inp.scene_count)
    data = await _pass(story_dir, log, inp, "scenes", system, user,
                       temperature=0.4, max_tokens=max_tokens)
    script = Script.model_validate(data)

    errors = validate_script(script, bible, inp)
    if errors:
        log.event("story", "validation_failed", detail="; ".join(errors[:5]))
        repair_user = (
            "Asset Bible:\n" + bible.model_dump_json(indent=2)
            + "\n\nBeats:\n" + beats.model_dump_json(indent=2)
            + "\n\nValidation errors:\n- " + "\n- ".join(errors)
            + "\n\nYour previous JSON:\n" + json.dumps(data)
        )
        data = await _pass(story_dir, log, inp, "scenes_repair",
                           REPAIR_SYSTEM + "\n\nOriginal task:\n" + system,
                           repair_user, temperature=0.3, max_tokens=max_tokens)
        script = Script.model_validate(data)
        errors = validate_script(script, bible, inp)
        if errors:
            raise ValidationFailed(errors)

    script_path.write_text(script.model_dump_json(indent=2), encoding="utf-8")
    log.event("story", "script_written", detail=f"{len(script.scenes)} scenes")
    return script
