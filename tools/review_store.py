"""Persistent structured chapter review results."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ReviewStore:
    def __init__(self, project_root: Path, novel_id: str):
        self.review_dir = (
            Path(project_root).resolve()
            / "data"
            / "novels"
            / novel_id
            / "data"
            / "reviews"
        )

    def save(self, chapter_id: str, result: dict[str, Any]) -> Path:
        self.review_dir.mkdir(parents=True, exist_ok=True)
        payload = dict(result)
        payload["reviewed_at"] = datetime.now(timezone.utc).isoformat()
        target = self.path_for(chapter_id)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.review_dir,
            prefix=f".{chapter_id}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            temp_path = Path(handle.name)
        temp_path.replace(target)
        return target

    def load(self, chapter_id: str) -> dict[str, Any] | None:
        path = self.path_for(chapter_id)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def path_for(self, chapter_id: str) -> Path:
        if not chapter_id.startswith("ch_") or not chapter_id[3:].isdigit():
            raise ValueError(f"无效章节 ID: {chapter_id}")
        return self.review_dir / f"{chapter_id}.json"

    def analytics(self) -> dict[str, int | float]:
        scores: list[float] = []
        passed = 0
        if self.review_dir.exists():
            for path in self.review_dir.glob("ch_*.json"):
                record = self.load(path.stem)
                if not record:
                    continue
                try:
                    scores.append(float(record.get("score") or 0))
                except (TypeError, ValueError):
                    continue
                passed += int(bool(record.get("passed")))
        return {
            "reviewed_chapters": len(scores),
            "passed_chapters": passed,
            "average_score": round(sum(scores) / len(scores), 1) if scores else 0.0,
        }
