"""Pydantic models: Level-2 story input, Premise, Asset Bible, Beats, Script, state."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

Genre = Literal["sci-fi", "fantasy", "horror", "drama", "thriller", "mystery"]
Ending = Literal["happy", "tragic", "bittersweet", "twist", "open"]
ImageStyle = Literal["cartoon_3d", "anime", "storybook_2d", "cinematic_realistic"]
ImageModel = Literal["gpt-image-2", "nano-banana-2", "flux-schnell", "grok-imagine", "auto"]
# youtube = 16:9 landscape 1920x1080; tiktok = 9:16 vertical 1080x1920
# (TikTok / Reels / Shorts) — geometry in pipeline/formats.py
VideoFormat = Literal["youtube", "tiktok"]
# two LOCKED brand voices (one per gender) — ids live in .env, never per-video
NarratorVoice = Literal["male", "female"]
Camera = Literal["wide", "medium", "close-up", "over-shoulder", "aerial", "detail"]

ALLOWED_AUDIO_TAGS = {"[whispers]", "[excited]", "[sad]", "[pause]", "[intense]"}


RefKind = Literal["character", "location", "object"]
# "front" is the MASTER IDENTITY image — the one shown in the UI box and
# stored as the asset's reference_image_url. Other views (side/back/pose/
# expression) are extra consistency references for the image pipeline.
RefView = Literal["front", "side", "back", "pose", "expression"]


# location reference behaviour: "world" (default) = the photo defines the
# WORLD aesthetic — every scene there is generated fresh (different spot/angle)
# but inside the same universe; "exact" = lock the photo, same spot every scene
# (e.g. the user's own shop). Characters/objects are always identity-locked.
RefMode = Literal["world", "exact"]


class ReferenceImage(BaseModel):
    kind: RefKind = "character"
    name: str = ""
    view: RefView = "front"
    mode: RefMode = "world"
    # True when the upload is already a full turnaround/model sheet. The image
    # pipeline uses it directly instead of generating replacement side/back refs.
    is_character_sheet: bool = False
    # Original full upload when `url` has been replaced with an extracted
    # front-view crop for stronger identity matching.
    source_image_url: str = ""
    # optional user-assigned role for a character reference box (protagonist,
    # villain, minion…); soft-validated later, wired to the generated character
    # of the same name in apply_user_hints()
    role: str = ""
    # empty url = hint-only box: the user named/role-tagged an asset on /create
    # without uploading a picture — it feeds the prompt hints, never vision
    url: str = ""

    @property
    def asset_hint(self) -> str:
        return f'{self.kind} "{self.name}"' if self.name else self.kind


class RelationshipHint(BaseModel):
    """User-drawn edge from the /create form, keyed by asset NAME (ids don't
    exist yet). Resolved to bible ids in apply_user_hints() after Pass 2."""
    source: str = ""     # a reference-box name (or free-typed name)
    target: str = ""
    type: str = "ally_of"
    label: str = ""


class StoryInput(BaseModel):
    """Level-2 structured topic input (see skills/story-engine.md)."""

    topic: str
    genre: Genre
    tone: str = "emotional, cinematic"
    target_audience: str = "18-35 general"
    duration_minutes: int = Field(default=7, ge=1, le=15)
    visual_style: str = "cinematic, moody lighting, film grain"
    narrator_style: str = "deep, measured, documentary-like"
    narrator_voice: NarratorVoice = "male"
    ending: Ending
    language: Literal["en"] = "en"
    image_style: ImageStyle
    image_model: ImageModel = "auto"
    video_format: VideoFormat = "youtube"
    subtitles: Literal["burned", "off"] = "burned"
    # Optional 10-15s Seedance 2.0 Mini opening clip prepended before render.
    hook_enabled: bool = False
    reference_images: list[ReferenceImage] = []
    # optional relationships the user drew on /create — honored by Pass 2 and
    # force-wired into the bible afterwards (see apply_user_hints)
    relationship_hints: list[RelationshipHint] = []

    @field_validator("topic")
    @classmethod
    def topic_word_count(cls, v: str) -> str:
        words = len(v.split())
        if not 10 <= words <= 50:
            raise ValueError(f"topic must be 10-50 words (got {words})")
        return v

    # word/scene math — drives every pass (skills/story-engine.md)
    @property
    def word_target(self) -> int:
        return self.duration_minutes * 150

    @property
    def scene_count(self) -> int:
        return self.duration_minutes * 10

    @property
    def beat_count(self) -> int:
        return min(30, max(5, round(self.duration_minutes * 2.5)))


class Premise(BaseModel):
    title: str
    logline: str
    hook: str
    act_1_setup: str
    act_2_conflict: str
    act_3_resolution: str
    emotional_arc: str
    themes: list[str]


class Asset(BaseModel):
    id: str
    name: str
    visual_dna: str
    reference_image_url: Optional[str] = None


# soft-validated (normalize + warn, never crash) because the bible is LLM
# output mid-pipeline — a Literal mismatch would fail the paid story stage
CHARACTER_ROLES = ("protagonist", "deuteragonist", "villain", "villain_lieutenant",
                   "minion", "mentor", "ally", "love_interest", "supporting")
# one edge per pair, fixed directions: parent_of = parent->child,
# commands = leader->subordinate, mentors = mentor->student,
# loves = who->whom (label "mutual" if returned),
# owns/uses = character->object only. Symmetric types (sibling_of,
# ally_of, enemy_of) are emitted once, never reciprocated.
RELATIONSHIP_TYPES = ("parent_of", "sibling_of", "commands", "ally_of",
                      "enemy_of", "loves", "mentors", "owns", "uses")


class Relationship(BaseModel):
    source: str          # asset id
    target: str          # asset id (character or object; never a location)
    type: str
    label: str = ""      # optional nuance, e.g. "adoptive father"


class CharacterAsset(Asset):
    role: str = "supporting"


class Bible(BaseModel):
    style: str
    # shared world/era aesthetic every location belongs to (e.g. "year-3000
    # solarpunk megacity: chrome-and-vine towers, holographic signage") —
    # appended to every image prompt so different places feel like one universe
    world: str = ""
    characters: list[CharacterAsset]
    locations: list[Asset]
    objects: list[Asset]
    relationships: list[Relationship] = []

    def asset_ids(self) -> set[str]:
        return {a.id for a in self.characters + self.locations + self.objects}

    def get(self, asset_id: str) -> Optional[Asset]:
        for a in self.characters + self.locations + self.objects:
            if a.id == asset_id:
                return a
        return None


class Beat(BaseModel):
    id: int
    act: int
    summary: str
    emotion: str
    cast: list[str] = []
    location: str
    props: list[str] = []
    is_cliffhanger: bool = False


class BeatSheet(BaseModel):
    beats: list[Beat]


class Scene(BaseModel):
    id: int
    beat_id: int
    narration: str
    cast: list[str] = []
    location: str
    # which specific spot/area of the location this scene shows — varies scene
    # to scene so the same location never repeats the same framing
    location_detail: str = ""
    props: list[str] = []
    camera: Camera
    time_of_day: str
    weather: str
    character_state: str = ""
    duration_estimate_sec: float = 6


class Script(BaseModel):
    scenes: list[Scene]


class ImageManifestEntry(BaseModel):
    scene_id: int
    path: str
    prompt: str
    model: str
    aspect: Literal["16:9", "3:2", "9:16", "2:3"]
    attempts: int = 1


class AudioManifestEntry(BaseModel):
    scene_id: int
    path: str
    duration_sec: float
    chars: int


class UserPrefs(BaseModel):
    """App-level preferences persisted server-side (stories/_settings.json)."""

    default_voice: NarratorVoice = "male"


class StoryState(BaseModel):
    """stories/{id}/state.json — the pipeline state machine."""

    state: str = "created"
    progress_done: int = 0
    progress_total: int = 0
    error: Optional[str] = None
    retryable: bool = True
    warnings: list[str] = []
    updated_at: str = ""
