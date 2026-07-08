import json

import pytest

from app.models import Asset, Bible, Scene, Script, StoryInput
from app.pipeline import images


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _input() -> StoryInput:
    return StoryInput(
        topic="A careful hero crosses a silent city to find a hidden signal",
        genre="sci-fi",
        ending="open",
        image_style="cinematic_realistic",
    )


def _scene(scene_id: int) -> Scene:
    return Scene(
        id=scene_id,
        beat_id=1,
        narration=f"Scene {scene_id}",
        location="loc_city",
        camera="wide",
        time_of_day="night",
        weather="clear",
    )


def _bible() -> Bible:
    return Bible(
        style="cinematic",
        world="a rain-dark future city",
        characters=[],
        locations=[
            Asset(
                id="loc_city",
                name="City",
                visual_dna="glass towers, wet streets, distant neon",
            )
        ],
        objects=[],
    )


def test_flux_text_payload_uses_atlas_size_format(monkeypatch):
    monkeypatch.setattr(images.settings, "image_model_flux", "black-forest-labs/flux-schnell")

    atlas_model, payload, aspect = images._payload(
        "flux-schnell", "prompt", [], images.FORMATS["youtube"]
    )

    assert atlas_model == "black-forest-labs/flux-schnell"
    assert aspect == "16:9"
    assert payload["size"] == "1920*1080"  # native full HD, priced per run
    assert "quality" not in payload
    assert "input_fidelity" not in payload


def test_flux_edit_payload_uses_flux_2_pro_schema(monkeypatch):
    monkeypatch.setattr(images.settings, "image_edit_model_flux", "black-forest-labs/flux-2-pro/edit")

    atlas_model, payload, aspect = images._payload(
        "flux-schnell",
        "prompt",
        [f"https://example.com/{i}.png" for i in range(9)],
        images.FORMATS["tiktok"],
    )

    assert atlas_model == "black-forest-labs/flux-2-pro/edit"
    assert aspect == "9:16"
    assert payload["size"] == "1080*1920"  # native full HD (max 2048/dim)
    assert payload["output_format"] == "png"
    assert len(payload["images"]) == 8
    assert "quality" not in payload
    assert "input_fidelity" not in payload


def test_every_model_matches_video_format_geometry():
    """youtube -> 16:9 (1920x1080-class), tiktok -> 9:16 (1080x1920-class)."""
    fy, ft = images.FORMATS["youtube"], images.FORMATS["tiktok"]
    assert (fy.width, fy.height) == (1920, 1080)
    assert (ft.width, ft.height) == (1080, 1920)
    assert images._flux_size(fy) == "1920*1080"
    assert images._flux_size(ft) == "1080*1920"

    for fmt, want_ar in ((fy, "16:9"), (ft, "9:16")):
        for model in ("grok-imagine", "nano-banana-2"):
            _, payload, aspect = images._payload(model, "p", [], fmt)
            assert payload["aspect_ratio"] == want_ar
            assert aspect == want_ar

    # gpt-image-2 has no native 16:9/9:16 — nearest size, cropped at render
    _, py, ay = images._payload("gpt-image-2", "p", [], fy)
    _, pt, at = images._payload("gpt-image-2", "p", [], ft)
    assert (py["size"], ay) == ("1536x1024", "3:2")
    assert (pt["size"], at) == ("1024x1536", "2:3")


def test_grok_text_payload(monkeypatch):
    monkeypatch.setattr(images.settings, "image_model_grok", "xai/grok-imagine-image/text-to-image")

    atlas_model, payload, aspect = images._payload(
        "grok-imagine", "prompt", [], images.FORMATS["youtube"]
    )

    assert atlas_model == "xai/grok-imagine-image/text-to-image"
    assert aspect == "16:9"
    assert payload["aspect_ratio"] == "16:9"
    assert payload["resolution"] == "2k"
    assert "output_format" not in payload  # not in the Atlas grok schema


def test_grok_edit_payload(monkeypatch):
    monkeypatch.setattr(images.settings, "image_edit_model_grok", "xai/grok-imagine-image/edit")

    atlas_model, payload, aspect = images._payload(
        "grok-imagine",
        "prompt",
        [f"https://example.com/{i}.png" for i in range(9)],
        images.FORMATS["tiktok"],
    )

    assert atlas_model == "xai/grok-imagine-image/edit"
    assert aspect == "9:16"
    assert payload["aspect_ratio"] == "9:16"
    assert payload["resolution"] == "2k"
    # Atlas grok edit takes references in "image_urls" — "images" is silently
    # ignored and the model falls back to pure text-to-image. Docs say max 8
    # but the live API 400s above 5.
    assert "images" not in payload
    assert len(payload["image_urls"]) == 5


def test_scene_reference_urls_keeps_every_cast_master_within_model_cap():
    from app.models import Asset, Bible, CharacterAsset, Scene

    chars = [
        CharacterAsset(id=f"char_{n}", name=n.title(), visual_dna="dna",
                       reference_image_url=f"https://example.com/{n}_sheet.png",
                       role=role)
        for n, role in (("orin", "protagonist"), ("moko", "deuteragonist"),
                        ("tora", "mentor"))
    ]
    bible = Bible(style="s", world="w", characters=chars,
                  locations=[Asset(id="loc_river", name="River",
                                   visual_dna="river bank")],
                  objects=[])
    scene = Scene(id=5, beat_id=3, narration="They meet.",
                  cast=["char_orin", "char_moko", "char_tora"],
                  location="loc_river", camera="medium",
                  time_of_day="dawn", weather="mist")
    extra = {f"char_{n}": [f"https://example.com/{n}_v{i}.png" for i in range(6)]
             for n in ("orin", "moko", "tora")}

    urls = images.scene_reference_urls(scene, bible, {}, extra)

    # every cast member's master ref must survive the grok/flux 8-image slice
    assert urls[:3] == [f"https://example.com/{n}_sheet.png"
                        for n in ("orin", "moko", "tora")]
    # remaining slots fill with extra views round-robin across the cast
    assert urls[3:9] == [
        "https://example.com/orin_v0.png", "https://example.com/moko_v0.png",
        "https://example.com/tora_v0.png", "https://example.com/orin_v1.png",
        "https://example.com/moko_v1.png", "https://example.com/tora_v1.png",
    ]
    assert len(urls) == 14  # NB2 cap


@pytest.mark.anyio
async def test_scene_generation_commits_each_image_before_next_request(
    tmp_path, monkeypatch
):
    calls = []

    async def fake_generate_image(payload, *, timeout):
        calls.append(payload)
        if len(calls) == 2:
            manifest = json.loads((tmp_path / "images" / "manifest.json").read_text())
            status = json.loads((tmp_path / "images" / "status.json").read_text())
            assert [entry["scene_id"] for entry in manifest] == [1]
            assert status["1"]["status"] == "completed"
        return f"image-{len(calls)}".encode()

    monkeypatch.setattr(images.atlas, "generate_image", fake_generate_image)

    entries = await images.run_image_pipeline(
        tmp_path,
        _input(),
        Script(scenes=[_scene(1), _scene(2)]),
        _bible(),
    )

    assert [entry.scene_id for entry in entries] == [1, 2]
    assert len(calls) == 2


@pytest.mark.anyio
async def test_scene_generation_stops_immediately_on_failure(tmp_path, monkeypatch):
    calls = []

    async def fake_generate_image(payload, *, timeout):
        calls.append(payload)
        if len(calls) == 2:
            raise RuntimeError("model failed")
        return f"image-{len(calls)}".encode()

    monkeypatch.setattr(images.atlas, "generate_image", fake_generate_image)

    with pytest.raises(RuntimeError, match="scene 2 image failed"):
        await images.run_image_pipeline(
            tmp_path,
            _input(),
            Script(scenes=[_scene(1), _scene(2), _scene(3)]),
            _bible(),
        )

    manifest = json.loads((tmp_path / "images" / "manifest.json").read_text())
    status = json.loads((tmp_path / "images" / "status.json").read_text())
    assert [entry["scene_id"] for entry in manifest] == [1]
    assert status["1"]["status"] == "completed"
    assert status["2"]["status"] == "failed"
    assert not (tmp_path / "images" / "scene_003.png").exists()
    assert len(calls) == 2
