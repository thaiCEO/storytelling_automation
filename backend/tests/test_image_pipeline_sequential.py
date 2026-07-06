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
    assert payload["size"] == "1280*720"
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
    assert payload["size"] == "720*1280"
    assert payload["output_format"] == "png"
    assert len(payload["images"]) == 8
    assert "quality" not in payload
    assert "input_fidelity" not in payload


def test_grok_text_payload(monkeypatch):
    monkeypatch.setattr(images.settings, "image_model_grok", "xai/grok-imagine-image/text-to-image")

    atlas_model, payload, aspect = images._payload(
        "grok-imagine", "prompt", [], images.FORMATS["youtube"]
    )

    assert atlas_model == "xai/grok-imagine-image/text-to-image"
    assert aspect == "16:9"
    assert payload["aspect_ratio"] == "16:9"
    assert payload["output_format"] == "png"


def test_grok_edit_payload(monkeypatch):
    monkeypatch.setattr(images.settings, "image_edit_model_grok", "xai/grok-imagine-image/edit")

    atlas_model, payload, aspect = images._payload(
        "grok-imagine",
        "prompt",
        [f"https://example.com/{i}.png" for i in range(5)],
        images.FORMATS["tiktok"],
    )

    assert atlas_model == "xai/grok-imagine-image/edit"
    assert aspect == "9:16"
    assert payload["aspect_ratio"] == "9:16"
    assert payload["output_format"] == "png"
    assert len(payload["images"]) == 3  # Grok edit supports max 3 references


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
