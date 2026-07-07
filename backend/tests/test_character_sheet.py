import pytest
from pathlib import Path

from app.main import _looks_like_character_sheet_upload
from app.models import (Asset, Bible, CharacterAsset, ReferenceImage, Scene,
                        StoryInput, canonical_view)
from app.pipeline.images import (build_prompt, is_character_sheet,
                                 extra_view_urls, _build_view_sheets,
                                 _user_views)
from app.pipeline.story_engine import find_uploaded_character_sheet_url
from app.utils.log import PipelineLog

def test_find_uploaded_character_sheet_url_by_keywords():
    inp = StoryInput(
        topic="A very interesting topic that has at least ten words in it and a conflict",
        genre="sci-fi",
        ending="open",
        image_style="cinematic_realistic",
        reference_images=[
            ReferenceImage(
                kind="character",
                name="Lyra",
                view="front",
                url="https://example.com/lyra_turnaround_sheet.png"
            )
        ]
    )
    url = find_uploaded_character_sheet_url("Lyra", inp)
    assert url == "https://example.com/lyra_turnaround_sheet.png"

def test_find_uploaded_character_sheet_url_by_flag():
    inp = StoryInput(
        topic="A very interesting topic that has at least ten words in it and a conflict",
        genre="sci-fi",
        ending="open",
        image_style="cinematic_realistic",
        reference_images=[
            ReferenceImage(
                kind="character",
                name="Lyra",
                view="front",
                is_character_sheet=True,
                url="https://example.com/uploaded_uuid.png"
            )
        ]
    )
    url = find_uploaded_character_sheet_url("Lyra", inp)
    assert url == "https://example.com/uploaded_uuid.png"

def test_find_uploaded_character_sheet_url_ignores_separate_views():
    # separately uploaded views are NOT a sheet — the master is a plain
    # front image and the other views ride as extra scene refs
    inp = StoryInput(
        topic="A very interesting topic that has at least ten words in it and a conflict",
        genre="sci-fi",
        ending="open",
        image_style="cinematic_realistic",
        reference_images=[
            ReferenceImage(kind="character", name="Lyra", view="front", url="https://example.com/1.png"),
            ReferenceImage(kind="character", name="Lyra", view="side", url="https://example.com/2.png"),
            ReferenceImage(kind="character", name="Lyra", view="back", url="https://example.com/3.png"),
            ReferenceImage(kind="character", name="Lyra", view="pose", url="https://example.com/4.png"),
            ReferenceImage(kind="character", name="Lyra", view="expression", url="https://example.com/5.png"),
        ]
    )
    assert find_uploaded_character_sheet_url("Lyra", inp) is None

def test_is_character_sheet_by_dna():
    asset = CharacterAsset(id="char_lyra", name="Lyra", visual_dna="character sheet of a pilot, turnaround views", role="protagonist")
    inp = StoryInput(
        topic="A very interesting topic that has at least ten words in it and a conflict",
        genre="sci-fi",
        ending="open",
        image_style="cinematic_realistic"
    )
    assert is_character_sheet(asset, inp) is True

def test_is_character_sheet_not_triggered_by_separate_views():
    # separate views must NOT count as a sheet, or extra_view_urls would
    # stop attaching them to scene requests
    asset = CharacterAsset(id="char_lyra", name="Lyra", visual_dna="a pilot", role="protagonist")
    inp = StoryInput(
        topic="A very interesting topic that has at least ten words in it and a conflict",
        genre="sci-fi",
        ending="open",
        image_style="cinematic_realistic",
        reference_images=[
            ReferenceImage(kind="character", name="Lyra", view="front", url="https://example.com/1.png"),
            ReferenceImage(kind="character", name="Lyra", view="side", url="https://example.com/2.png"),
            ReferenceImage(kind="character", name="Lyra", view="back", url="https://example.com/3.png"),
            ReferenceImage(kind="character", name="Lyra", view="pose", url="https://example.com/4.png"),
            ReferenceImage(kind="character", name="Lyra", view="expression", url="https://example.com/5.png"),
        ]
    )
    assert is_character_sheet(asset, inp) is False

def test_is_character_sheet_by_upload_flag():
    asset = CharacterAsset(id="char_lyra", name="Lyra", visual_dna="a pilot", role="protagonist")
    inp = StoryInput(
        topic="A very interesting topic that has at least ten words in it and a conflict",
        genre="sci-fi",
        ending="open",
        image_style="cinematic_realistic",
        reference_images=[
            ReferenceImage(
                kind="character",
                name="Lyra",
                view="front",
                is_character_sheet=True,
                url="https://example.com/uuid.png"
            )
        ]
    )
    assert is_character_sheet(asset, inp) is True


def test_character_sheet_upload_detected_by_filename():
    assert _looks_like_character_sheet_upload(
        "character",
        "front",
        "Character_sheet_for_Orin_2K_202607061207.jpeg",
        b"not-image-needed",
    ) is True


def test_exact_reference_prompt_does_not_repeat_conflicting_dna():
    char = CharacterAsset(
        id="char_orin",
        name="Orin",
        visual_dna="scarred teenage warrior with realistic anatomy",
        reference_image_url="https://example.com/orin.png",
        role="protagonist",
    )
    bible = Bible(
        style="storybook",
        world="warm forest",
        characters=[char],
        locations=[Asset(id="loc_river", name="River", visual_dna="muddy river bank")],
        objects=[],
    )
    scene = Scene(
        id=1,
        beat_id=1,
        narration="Orin listens to the river.",
        cast=["char_orin"],
        location="loc_river",
        camera="wide",
        time_of_day="dawn",
        weather="mist",
    )
    prompt = build_prompt(scene, bible, "anime", "nano-banana-2")
    assert "exact same character from the uploaded reference image" in prompt
    assert "scarred teenage warrior" not in prompt
    assert "no added scars" in prompt
    assert "no text, no captions" in prompt

def test_extra_view_urls_skips_character_sheet():
    asset = CharacterAsset(id="char_lyra", name="Lyra", visual_dna="character sheet of a pilot", role="protagonist")
    inp = StoryInput(
        topic="A very interesting topic that has at least ten words in it and a conflict",
        genre="sci-fi",
        ending="open",
        image_style="cinematic_realistic",
        reference_images=[
            ReferenceImage(kind="character", name="Lyra", view="front", url="https://example.com/1.png"),
            ReferenceImage(kind="character", name="Lyra", view="side", url="https://example.com/2.png"),
        ]
    )
    bible = Bible(style="cinematic", world="world", characters=[asset], locations=[], objects=[])
    res = extra_view_urls(inp, bible)
    assert "char_lyra" not in res

@pytest.mark.anyio
async def test_build_view_sheets_generates_refs_for_character_sheet(tmp_path, monkeypatch):
    asset = CharacterAsset(id="char_lyra", name="Lyra", visual_dna="a pilot", reference_image_url="https://example.com/char_sheet.png", role="protagonist")
    inp = StoryInput(
        topic="A very interesting topic that has at least ten words in it and a conflict",
        genre="sci-fi",
        ending="open",
        image_style="cinematic_realistic",
        image_model="grok-imagine",
        reference_images=[
            ReferenceImage(kind="character", name="Lyra", view="front", url="https://example.com/char_sheet.png")
        ]
    )
    # Give the reference image a turnaround keyword in its name
    inp.reference_images[0].name = "Lyra (character sheet)"
    
    bible = Bible(style="cinematic", world="world", characters=[asset], locations=[], objects=[])
    log = PipelineLog(tmp_path)
    payloads = []

    async def fake_generate_image(payload, *, timeout):
        payloads.append(payload)
        return b"png-bytes"

    async def fake_upload_media(content, filename, mime):
        return f"https://example.com/{filename}"

    from app.pipeline import images
    monkeypatch.setattr(images.atlas, "generate_image", fake_generate_image)
    monkeypatch.setattr(images.atlas, "upload_media", fake_upload_media)
    
    sheets = await _build_view_sheets(bible, inp, tmp_path, log)
    assert len(payloads) == 6
    first_prompt = payloads[0]["prompt"]
    assert "Use the uploaded character sheet as the ONLY master identity reference" in first_prompt
    assert "Use ONLY the front-facing full-body character (ref_front)" in first_prompt
    assert "Ignore all other views" in first_prompt
    assert "Front-facing full-body standing pose" in first_prompt
    assert "A single front-facing full-body master character reference" in first_prompt
    assert "Do NOT display any text" in first_prompt
    assert "No additional views" in first_prompt
    assert payloads[0]["model"].endswith("/edit")
    assert payloads[0]["image_urls"] == ["https://example.com/char_sheet.png"]
    assert "a pilot" not in first_prompt
    assert "full-body dynamic running pose for the main chase action" in payloads[3]["prompt"]
    assert "fearful reaction expression" in payloads[4]["prompt"]
    assert "determined hero expression" in payloads[5]["prompt"]
    assert sheets["char_lyra"] == {
        "ref_front": "https://example.com/char_lyra_ref_front.png",
        "ref_side": "https://example.com/char_lyra_ref_side.png",
        "ref_back": "https://example.com/char_lyra_ref_back.png",
        "pose_run": "https://example.com/char_lyra_pose_run.png",
        "expr_fear": "https://example.com/char_lyra_expr_fear.png",
        "expr_determined": "https://example.com/char_lyra_expr_determined.png",
    }
    for view in ("ref_front", "ref_side", "ref_back", "pose_run", "expr_fear", "expr_determined"):
        assert (tmp_path / "images" / "refs" / f"char_lyra_{view}.png").exists()

    # a second run resumes from refsheet.json and regenerates nothing
    payloads.clear()
    resumed = await _build_view_sheets(bible, inp, tmp_path, log)
    assert payloads == []
    assert resumed == sheets


def test_user_views_normalizes_legacy_and_canonical():
    asset = CharacterAsset(id="char_lyra", name="Lyra", visual_dna="a pilot",
                           role="protagonist")
    inp = StoryInput(
        topic="A very interesting topic that has at least ten words in it and a conflict",
        genre="sci-fi", ending="open", image_style="cinematic_realistic",
        reference_images=[
            ReferenceImage(kind="character", name="Lyra", view="front", url="https://example.com/1.png"),
            ReferenceImage(kind="character", name="Lyra", view="ref_side", url="https://example.com/2.png"),
            ReferenceImage(kind="character", name="Lyra", view="pose", url="https://example.com/3.png"),
            ReferenceImage(kind="character", name="Lyra", view="expr_determined", url="https://example.com/4.png"),
            # hint-only box (no url) never counts
            ReferenceImage(kind="character", name="Lyra", view="back", url=""),
        ])
    assert _user_views(inp, asset) == {"ref_front", "ref_side", "pose_run",
                                       "expr_determined"}


def _six_view_input(**kw) -> StoryInput:
    views = ["ref_front", "ref_side", "ref_back", "pose_run",
             "expr_fear", "expr_determined"]
    return StoryInput(
        topic="A very interesting topic that has at least ten words in it and a conflict",
        genre="sci-fi", ending="open", image_style="cinematic_realistic",
        image_model="grok-imagine",
        reference_images=[
            ReferenceImage(kind="character", name="Lyra", view=v,
                           url=f"https://example.com/lyra_{v}.png")
            for v in views],
        **kw)


@pytest.mark.anyio
async def test_all_six_uploaded_views_skip_generation_entirely(tmp_path, monkeypatch):
    asset = CharacterAsset(id="char_lyra", name="Lyra", visual_dna="a pilot",
                           reference_image_url="https://example.com/lyra_ref_front.png",
                           role="protagonist")
    bible = Bible(style="c", world="w", characters=[asset], locations=[], objects=[])
    inp = _six_view_input()
    calls = []

    async def fake_generate_image(payload, *, timeout):
        calls.append(payload)
        return b"png"

    from app.pipeline import images
    monkeypatch.setattr(images.atlas, "generate_image", fake_generate_image)

    sheets = await _build_view_sheets(bible, inp, tmp_path, PipelineLog(tmp_path))
    assert calls == []          # zero paid requests
    assert sheets == {}

    # the five non-master views still ride as extra scene references
    extra = extra_view_urls(inp, bible)
    assert len(extra["char_lyra"]) == 5
    assert "https://example.com/lyra_ref_front.png" not in extra["char_lyra"]


@pytest.mark.anyio
async def test_partial_uploads_generate_only_missing_views(tmp_path, monkeypatch):
    asset = CharacterAsset(id="char_lyra", name="Lyra", visual_dna="a pilot",
                           reference_image_url="https://example.com/lyra_front.png",
                           role="protagonist")
    bible = Bible(style="c", world="w", characters=[asset], locations=[], objects=[])
    inp = StoryInput(
        topic="A very interesting topic that has at least ten words in it and a conflict",
        genre="sci-fi", ending="open", image_style="cinematic_realistic",
        image_model="grok-imagine",
        reference_images=[
            ReferenceImage(kind="character", name="Lyra", view="ref_front",
                           url="https://example.com/lyra_front.png"),
            ReferenceImage(kind="character", name="Lyra", view="ref_side",
                           url="https://example.com/lyra_side.png"),
            ReferenceImage(kind="character", name="Lyra", view="expr_fear",
                           url="https://example.com/lyra_fear.png"),
        ])
    generated = []

    async def fake_generate_image(payload, *, timeout):
        generated.append(payload)
        return b"png"

    async def fake_upload_media(content, filename, mime):
        return f"https://example.com/{filename}"

    from app.pipeline import images
    monkeypatch.setattr(images.atlas, "generate_image", fake_generate_image)
    monkeypatch.setattr(images.atlas, "upload_media", fake_upload_media)

    sheets = await _build_view_sheets(bible, inp, tmp_path, PipelineLog(tmp_path))
    # only the 3 missing views: ref_back, pose_run, expr_determined
    assert len(generated) == 3
    assert set(sheets["char_lyra"]) == {"ref_back", "pose_run", "expr_determined"}
