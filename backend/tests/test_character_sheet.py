import pytest
from pathlib import Path
from io import BytesIO

from PIL import Image

from app.main import (_crop_ref_front_from_character_sheet,
                      _looks_like_character_sheet_upload)
from app.models import Asset, CharacterAsset, ReferenceImage, Scene, StoryInput, Bible
from app.pipeline.images import (build_prompt, is_character_sheet,
                                 extra_view_urls, _build_view_sheets)
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

def test_find_uploaded_character_sheet_url_by_5_views():
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
    url = find_uploaded_character_sheet_url("Lyra", inp)
    assert url == "https://example.com/1.png"

def test_is_character_sheet_by_dna():
    asset = CharacterAsset(id="char_lyra", name="Lyra", visual_dna="character sheet of a pilot, turnaround views", role="protagonist")
    inp = StoryInput(
        topic="A very interesting topic that has at least ten words in it and a conflict",
        genre="sci-fi",
        ending="open",
        image_style="cinematic_realistic"
    )
    assert is_character_sheet(asset, inp) is True

def test_is_character_sheet_by_separate_views():
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
    assert is_character_sheet(asset, inp) is True

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


def test_character_sheet_ref_front_crop_outputs_left_panel_png():
    img = Image.new("RGB", (2000, 1000), "white")
    # Put a solid block inside the expected ref_front area.
    for x in range(100, 500):
        for y in range(100, 850):
            img.putpixel((x, y), (120, 80, 40))
    buf = BytesIO()
    img.save(buf, format="JPEG")

    cropped = _crop_ref_front_from_character_sheet(buf.getvalue())

    assert cropped is not None
    out = Image.open(BytesIO(cropped))
    assert out.format == "PNG"
    assert out.size == (540, 875)


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
async def test_build_view_sheets_skips_character_sheet(tmp_path):
    asset = CharacterAsset(id="char_lyra", name="Lyra", visual_dna="a pilot", reference_image_url="https://example.com/char_sheet.png", role="protagonist")
    inp = StoryInput(
        topic="A very interesting topic that has at least ten words in it and a conflict",
        genre="sci-fi",
        ending="open",
        image_style="cinematic_realistic",
        reference_images=[
            ReferenceImage(kind="character", name="Lyra", view="front", url="https://example.com/char_sheet.png")
        ]
    )
    # Give the reference image a turnaround keyword in its name
    inp.reference_images[0].name = "Lyra (character sheet)"
    
    bible = Bible(style="cinematic", world="world", characters=[asset], locations=[], objects=[])
    log = PipelineLog(tmp_path)
    
    sheets = await _build_view_sheets(bible, inp, tmp_path, log)
    # The build should be skipped because of character sheet keyword, returning empty sheets dict
    assert "char_lyra" not in sheets
