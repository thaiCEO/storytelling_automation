import pytest
from pydantic import ValidationError

from app.models import StoryInput


def _make(words: int) -> StoryInput:
    return StoryInput(topic=" ".join(["word"] * words), genre="fantasy",
                      ending="happy", image_style="storybook_2d")


def test_topic_accepts_full_synopsis_up_to_400_words():
    assert len(_make(400).topic.split()) == 400
    assert len(_make(50).topic.split()) == 50  # old cap still fine


def test_topic_rejects_over_400_words():
    with pytest.raises(ValidationError, match="10-400"):
        _make(401)


def test_topic_rejects_under_10_words():
    with pytest.raises(ValidationError, match="10-400"):
        _make(9)
