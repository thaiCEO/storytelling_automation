"""Central settings, loaded from .env at the repo root (see CLAUDE.md)."""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env",),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    atlas_api_key: str = ""
    atlas_base_url: str = "https://api.atlascloud.ai"
    llm_model: str = "claude-sonnet"
    image_model_gpt: str = "openai/gpt-image-2/text-to-image"
    image_edit_model_gpt: str = "openai/gpt-image-2/edit"
    image_model_nb2: str = "google/nano-banana-2/text-to-image"
    image_model_flux: str = "black-forest-labs/flux-schnell"
    image_edit_model_flux: str = "black-forest-labs/flux-2-pro/edit"
    image_model_grok: str = "xai/grok-imagine-image/text-to-image"
    image_edit_model_grok: str = "xai/grok-imagine-image/edit"
    image_model_default: str = "auto"
    hook_enabled: bool = True
    hook_video_model: str = "bytedance/seedance-2.0-mini/reference-to-video"
    hook_duration_sec: int = 12
    hook_resolution: str = "720p"
    hook_bitrate_mode: str = "standard"
    hook_seed: int = -1
    tts_model: str = "xai/tts-v1"
    tts_voice_id: str = ""          # legacy single-voice fallback
    tts_voice_id_male: str = ""     # locked male brand voice
    tts_voice_id_female: str = ""   # locked female brand voice
    stories_dir: Path = REPO_ROOT / "stories"
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"

    def model_post_init(self, __context) -> None:
        # relative STORIES_DIR in .env is resolved against the repo root,
        # not the process CWD, so uvicorn can start from anywhere
        if not self.stories_dir.is_absolute():
            self.stories_dir = (REPO_ROOT / self.stories_dir).resolve()

    def story_dir(self, story_id: str) -> Path:
        return Path(self.stories_dir) / story_id


settings = Settings()
