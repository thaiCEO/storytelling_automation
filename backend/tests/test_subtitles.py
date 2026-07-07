from app.pipeline.subtitles import scene_cues, strip_trailing_punct
from app.pipeline.timeline import SceneTiming


def test_strip_trailing_punct():
    assert strip_trailing_punct("The city slept.") == "The city slept"
    assert strip_trailing_punct("he ran,") == "he ran"
    assert strip_trailing_punct("waiting...") == "waiting"
    # meaningful endings stay
    assert strip_trailing_punct("Who goes there?") == "Who goes there?"
    assert strip_trailing_punct("Run!") == "Run!"
    # mid-cue punctuation stays
    assert strip_trailing_punct("First, he waited.") == "First, he waited"


def test_scene_cues_never_end_with_period_or_comma():
    timing = SceneTiming(scene_id=1, video_start=0.0, video_duration=6.5,
                         audio_start=0.25, audio_duration=6.0)
    narration = ("After the storm, Orin stood alone at the riverbank, "
                 "breath misting in the cold golden dawn.")
    cues = scene_cues(timing, narration, max_chars=42)
    assert cues
    for c in cues:
        assert not c.text.endswith(".")
        assert not c.text.endswith(",")
        assert c.text  # never empty
