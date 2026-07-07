import pytest

from app.models import Asset, Bible, CharacterAsset, Scene, Script, Shot, StoryInput
from app.pipeline.images import build_prompt, scene_shot_list, _generate_one
from app.pipeline.render import CF_FRAMES, _shot_frames
from app.pipeline.story_engine import validate_script
from app.utils.log import PipelineLog


def _bible() -> Bible:
    return Bible(
        style="s", world="w",
        characters=[CharacterAsset(id="char_a", name="A", visual_dna="dna",
                                   role="protagonist")],
        locations=[Asset(id="loc_x", name="X", visual_dna="place")],
        objects=[])


def _inp(**kw) -> StoryInput:
    return StoryInput(
        topic="A very interesting topic that has at least ten words in it and conflict",
        genre="fantasy", ending="happy", image_style="storybook_2d",
        duration_minutes=1, **kw)


def _scene(id=1, words=20, camera="wide", shots=None) -> Scene:
    return Scene(id=id, beat_id=1, narration=" ".join(["word"] * words),
                 cast=["char_a"], location="loc_x", camera=camera,
                 time_of_day="dawn", weather="mist", shots=shots or [])


def test_deep_scene_without_shots_fails_validation():
    script = Script(scenes=[_scene(1, words=50)])
    errors = validate_script(script, _bible(), _inp())
    assert any("needs \"shots\"" in e for e in errors)


def test_deep_scene_with_shots_passes_shot_rule():
    shots = [Shot(camera="wide", focus="the crater rim"),
             Shot(camera="close-up", focus="trembling hands"),
             Shot(camera="detail", focus="the glowing stone")]
    script = Script(scenes=[_scene(1, words=50, shots=shots)])
    errors = validate_script(script, _bible(), _inp())
    assert not any("needs \"shots\"" in e for e in errors)
    assert not any("unknown camera" in e for e in errors)


def test_shot_validation_catches_bad_camera_and_empty_focus():
    shots = [Shot(camera="fisheye", focus="the crater"),
             Shot(camera="wide", focus="  ")]
    script = Script(scenes=[_scene(1, words=50, shots=shots)])
    errors = validate_script(script, _bible(), _inp())
    assert any("unknown camera 'fisheye'" in e for e in errors)
    assert any("empty focus" in e for e in errors)


def test_shot_frames_reproduce_scene_total_exactly():
    for total in (150, 301, 600, 907):
        for n in (1, 2, 3, 4, 5):
            frames = _shot_frames(total, n)
            assert len(frames) == n
            assert all(f > CF_FRAMES for f in frames)
            assert sum(frames) - CF_FRAMES * (n - 1) == total


def test_scene_shot_list_fallback_and_override():
    plain = _scene(1, words=20, camera="aerial")
    assert scene_shot_list(plain) == [("aerial", "")]
    deep = _scene(2, words=50, shots=[Shot(camera="detail", focus="the stone")])
    assert scene_shot_list(deep) == [("detail", "the stone")]


def test_build_prompt_shot_overrides():
    scene = _scene(1, words=20, camera="wide")
    prompt = build_prompt(scene, _bible(), "storybook_2d", "grok-imagine",
                          shot_camera="close-up", shot_focus="trembling hands")
    assert prompt.startswith("close-up shot of")
    assert "focusing on trembling hands" in prompt
    # without overrides the scene camera rules
    assert build_prompt(scene, _bible(), "storybook_2d",
                        "grok-imagine").startswith("wide shot of")


@pytest.mark.anyio
async def test_generate_one_writes_one_image_per_shot(tmp_path, monkeypatch):
    from app.pipeline import images

    async def fake_generate_image(payload, *, timeout):
        return b"png-bytes"

    monkeypatch.setattr(images.atlas, "generate_image", fake_generate_image)
    (tmp_path / "images").mkdir(parents=True)

    shots = [Shot(camera="wide", focus="crater rim"),
             Shot(camera="close-up", focus="trembling hands"),
             Shot(camera="detail", focus="glowing stone")]
    scene = _scene(1, words=50, shots=shots)
    entry = await _generate_one(scene, _bible(), _inp(image_model="grok-imagine"),
                                tmp_path, PipelineLog(tmp_path), {}, {}, {})

    assert entry.path == "images/scene_001.png"
    assert entry.extra_shots == ["images/scene_001_s2.png",
                                 "images/scene_001_s3.png"]
    for p in [entry.path] + entry.extra_shots:
        assert (tmp_path / p).exists()

    # second run: everything cached -> attempts 0, same paths
    entry2 = await _generate_one(scene, _bible(), _inp(image_model="grok-imagine"),
                                 tmp_path, PipelineLog(tmp_path), {}, {}, {})
    assert entry2.attempts == 0
    assert entry2.extra_shots == entry.extra_shots
