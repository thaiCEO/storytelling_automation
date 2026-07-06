"""Per-story structured pipeline log.

One line per event: ts | stage | scene_id | event | detail | cost_usd
(see skills/project-structure.md — Conventions).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("story")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


class PipelineLog:
    def __init__(self, story_dir: Path):
        self.path = Path(story_dir) / "pipeline.log"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def event(
        self,
        stage: str,
        event: str,
        detail: str = "",
        scene_id: int | str = "",
        cost_usd: float | str = "",
    ) -> None:
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        detail = str(detail).replace("\n", " ").replace("|", "/")[:500]
        line = f"{ts} | {stage} | {scene_id} | {event} | {detail} | {cost_usd}"
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        logger.info(line)
