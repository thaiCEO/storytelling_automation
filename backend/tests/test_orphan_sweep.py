from app.models import StoryState
from app.pipeline import runner


def _make_story(stories_dir, story_id: str, state: str) -> None:
    story_dir = stories_dir / story_id
    story_dir.mkdir(parents=True)
    runner.save_state(story_dir, StoryState(state=state))


def test_sweep_parks_orphaned_running_stories(tmp_path, monkeypatch):
    monkeypatch.setattr(runner.settings, "stories_dir", tmp_path)
    _make_story(tmp_path, "aaa111", "images_running")
    _make_story(tmp_path, "bbb222", "render_running")
    _make_story(tmp_path, "ccc333", "done")
    _make_story(tmp_path, "ddd444", "failed_voice")

    runner.sweep_orphaned_runs()

    orphan = runner.load_state(tmp_path / "aaa111")
    assert orphan.state == "failed_images"
    assert orphan.retryable is True
    assert "server restarted" in orphan.error

    assert runner.load_state(tmp_path / "bbb222").state == "failed_render"
    # finished / already-failed stories are untouched
    assert runner.load_state(tmp_path / "ccc333").state == "done"
    assert runner.load_state(tmp_path / "ddd444").state == "failed_voice"
