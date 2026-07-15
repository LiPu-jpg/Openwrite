"""Persistent chapter memory used by long-form context assembly."""

from __future__ import annotations

import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


class ChapterMemoryStore:
    def __init__(self, project_root: Path, novel_id: str):
        self.project_root = Path(project_root).resolve()
        self.novel_id = novel_id
        self.memory_dir = (
            self.project_root
            / "data"
            / "novels"
            / novel_id
            / "data"
            / "memory"
            / "chapters"
        )

    def save(
        self,
        *,
        chapter_id: str,
        title: str,
        summary: str,
        word_count: int,
        observations: str = "",
        token_usage: dict[str, Any] | None = None,
    ) -> Path:
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        path = self.path_for(chapter_id)
        payload = {
            "chapter_id": chapter_id,
            "title": title.strip(),
            "summary": summary.strip(),
            "word_count": max(0, int(word_count)),
            "observations": observations.strip(),
            "token_usage": dict(token_usage or {}),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        content = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
        self._atomic_write(path, content)
        return path

    def load(self, chapter_id: str) -> dict[str, Any] | None:
        path = self.path_for(chapter_id)
        if not path.is_file():
            return None
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            return None
        return data if isinstance(data, dict) else None

    def list_before(self, chapter_id: str) -> list[dict[str, Any]]:
        target = self._chapter_number(chapter_id)
        records: list[dict[str, Any]] = []
        if not self.memory_dir.exists():
            return records
        for path in self.memory_dir.glob("ch_*.yaml"):
            number = self._chapter_number(path.stem)
            if target and number >= target:
                continue
            record = self.load(path.stem)
            if record:
                records.append(record)
        return sorted(
            records,
            key=lambda item: self._chapter_number(str(item.get("chapter_id", ""))),
        )

    def render_context(self, chapter_id: str, *, max_chars: int = 4000) -> str:
        records = self.list_before(chapter_id)
        selected: list[str] = []
        used = 0
        for record in reversed(records):
            summary = str(record.get("summary") or "").strip()
            if not summary:
                observations = str(record.get("observations") or "").strip()
                summary = observations[:500]
            if not summary:
                continue
            chapter = str(record.get("chapter_id") or "")
            title = str(record.get("title") or chapter)
            entry = f"- {chapter}《{title}》：{summary}"
            if selected and used + len(entry) > max_chars:
                break
            selected.append(entry[:max_chars])
            used += len(entry)
        selected.reverse()
        return "\n".join(selected)

    def usage_totals(self) -> dict[str, int]:
        totals = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        if not self.memory_dir.exists():
            return totals
        for path in self.memory_dir.glob("ch_*.yaml"):
            record = self.load(path.stem) or {}
            usage = record.get("token_usage", {})
            if not isinstance(usage, dict):
                continue
            for key in totals:
                value = usage.get(key, 0)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    totals[key] += int(value)
        return totals

    def path_for(self, chapter_id: str) -> Path:
        safe = chapter_id if re.fullmatch(r"ch_\d+", chapter_id) else ""
        if not safe:
            raise ValueError(f"无效章节 ID: {chapter_id}")
        return self.memory_dir / f"{safe}.yaml"

    def delete(self, chapter_id: str) -> None:
        self.path_for(chapter_id).unlink(missing_ok=True)

    @staticmethod
    def _chapter_number(chapter_id: str) -> int:
        match = re.search(r"(\d+)", chapter_id)
        return int(match.group(1)) if match else 0

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(content)
            temp_path = Path(handle.name)
        temp_path.replace(path)
