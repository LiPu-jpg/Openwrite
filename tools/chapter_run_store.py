"""Filesystem-backed chapter run manifests."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from tools.file_ops import atomic_write
from models.chapter_run import ChapterRunManifest, ChapterRunStage


class ChapterRunStore:
    def __init__(self, project_root: Path, novel_id: str):
        self.project_root = Path(project_root).resolve()
        self.novel_id = str(novel_id)
        self.root = self.project_root / "data" / "novels" / self.novel_id / "data" / "chapter_runs"

    def create(
        self,
        chapter_id: str,
        *,
        requested_target_words: int,
        outline_target_words: int,
        effective_target_words: int,
        provider: str,
        model: str,
        context_payload: dict[str, Any],
        baseline_state_revision: int,
    ) -> ChapterRunManifest:
        now = self._now()
        manifest = ChapterRunManifest(
            run_id=f"run_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:10]}",
            novel_id=self.novel_id,
            chapter_id=chapter_id,
            created_at=now,
            updated_at=now,
            requested_target_words=max(0, int(requested_target_words)),
            outline_target_words=max(0, int(outline_target_words)),
            effective_target_words=max(0, int(effective_target_words)),
            provider=str(provider or ""),
            model=str(model or ""),
            routes={"write": str(model or ""), "settle": str(model or "")},
            context_revision=self.content_revision(context_payload),
            baseline_state_revision=max(0, int(baseline_state_revision)),
            prompt_versions={
                "creative": "writer-creative-v1",
                "settlement": "runtime-delta-v1",
                "review": "reviewer-v1",
            },
            stages={
                "write": ChapterRunStage(status="running", started_at=now),
                "settle": ChapterRunStage(status="pending"),
                "review": ChapterRunStage(status="pending"),
            },
        )
        self.save(manifest)
        return manifest

    def load(self, run_id: str) -> ChapterRunManifest | None:
        path = self.path_for(run_id)
        if not path.is_file():
            return None
        try:
            return ChapterRunManifest.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def latest_for_chapter(
        self, chapter_id: str, *, statuses: set[str] | None = None
    ) -> ChapterRunManifest | None:
        records = self.list(chapter_id=chapter_id, statuses=statuses, limit=1)
        return records[0] if records else None

    def list(
        self,
        *,
        chapter_id: str = "",
        statuses: set[str] | None = None,
        limit: int = 20,
    ) -> list[ChapterRunManifest]:
        allowed_statuses = {"running", "written", "reviewed", "failed"}
        if statuses is not None and not statuses.issubset(allowed_statuses):
            raise ValueError("章节运行状态筛选无效")
        clean_limit = max(1, min(100, int(limit)))
        if not self.root.is_dir():
            return []
        records: list[ChapterRunManifest] = []
        for path in self.root.glob("run_*.json"):
            record = self.load(path.stem)
            if record is None:
                continue
            if chapter_id and record.chapter_id != chapter_id:
                continue
            if statuses is not None and record.status not in statuses:
                continue
            records.append(record)
        return sorted(records, key=lambda item: item.created_at, reverse=True)[:clean_limit]

    def complete_write(
        self,
        manifest: ChapterRunManifest,
        *,
        draft_content: str,
        usage: dict[str, Any],
    ) -> ChapterRunManifest:
        now = self._now()
        manifest.status = "written"
        manifest.updated_at = now
        manifest.draft_revision = self.text_revision(draft_content)
        manifest.stages["write"] = ChapterRunStage(
            status="completed",
            started_at=manifest.stages["write"].started_at,
            completed_at=now,
            usage=dict(usage or {}),
        )
        manifest.stages["settle"] = ChapterRunStage(
            status="completed", completed_at=now, usage=dict(usage or {})
        )
        self.save(manifest)
        return manifest

    def complete_review(
        self, manifest: ChapterRunManifest, *, review_payload: dict[str, Any]
    ) -> ChapterRunManifest:
        now = self._now()
        manifest.status = "reviewed"
        manifest.updated_at = now
        manifest.review_revision = self.content_revision(review_payload)
        manifest.stages["review"] = ChapterRunStage(
            status="completed", started_at=now, completed_at=now
        )
        self.save(manifest)
        return manifest

    def fail(self, manifest: ChapterRunManifest, *, stage: str, code: str = "") -> None:
        now = self._now()
        manifest.status = "failed"
        manifest.updated_at = now
        previous = manifest.stages.get(stage, ChapterRunStage())
        manifest.stages[stage] = ChapterRunStage(
            status="failed",
            started_at=previous.started_at,
            completed_at=now,
            error_code=str(code or "RUN_FAILED"),
        )
        self.save(manifest)

    def save(self, manifest: ChapterRunManifest) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.path_for(manifest.run_id)
        # atomic_write cleans up its temporary file in a finally block, so a
        # failed replace cannot leave a stray .tmp behind.
        atomic_write(target, manifest.model_dump_json(indent=2) + "\n")
        return target

    def path_for(self, run_id: str) -> Path:
        clean = str(run_id or "")
        if not clean.startswith("run_") or any(part in clean for part in ("/", "\\", "..")):
            raise ValueError("无效章节运行 ID")
        return self.root / f"{clean}.json"

    @staticmethod
    def content_revision(payload: dict[str, Any]) -> str:
        content = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        return ChapterRunStore.text_revision(content)

    @staticmethod
    def text_revision(content: str) -> str:
        return "sha256:" + hashlib.sha256(str(content).encode("utf-8")).hexdigest()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
