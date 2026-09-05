"""Durable manuscript acceptance and derived-fact reconciliation.

Canonical prose can be written by Studio, agents, revision restore, imports, or
an external editor.  This module gives every such write one causal protocol:
freeze the accepted bytes, invalidate dependent artifacts immediately, analyze
the frozen revision, rebuild replayable chapter facts, and only then declare
the project safe for continued generation.

The read side always compares the manuscript on disk with the recorded accepted
SHA.  A crash between the prose rename and journal creation therefore fails
closed as an external change instead of allowing old summaries or runtime facts
to enter the next prompt.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from models.runtime_state import RuntimeState, RuntimeStateDelta
from tools.chapter_memory import ChapterMemoryStore
from tools.runtime_state import RuntimeStateManager, legacy_updates_to_delta

SCHEMA_VERSION = "openwrite.manuscript-acceptance.v1"
STAGE_NAMES = ("capture", "invalidate", "analyze", "rebuild", "propagate")
REVIEW_DOMAINS = {"outline", "foreshadowing"}

Analyzer = Callable[[str, str, str, str], dict[str, Any]]


class ManuscriptAcceptanceError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "MANUSCRIPT_ACCEPTANCE_ERROR",
        recoverable: bool = True,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.recoverable = recoverable
        self.details = details or {}


class ManuscriptAcceptanceService:
    def __init__(self, project_root: Path, novel_id: str) -> None:
        self.project_root = Path(project_root).resolve()
        self.novel_id = str(novel_id)
        self.novel_root = self.project_root / "data" / "novels" / self.novel_id
        self.root = self.novel_root / "data" / "manuscript_acceptance"
        self.state_path = self.root / "state.json"
        self.operations_dir = self.root / "operations"
        self.snapshots_dir = self.root / "snapshots"
        self.facts_dir = self.root / "facts"

    @staticmethod
    def fingerprint(content: str) -> str:
        return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()

    def fact_path(self, chapter_id: str) -> Path:
        return self.facts_dir / f"{self._chapter_id(chapter_id)}.json"

    def operation_path(self, operation_id: str) -> Path:
        clean = str(operation_id or "")
        if not re.fullmatch(r"accept_[A-Za-z0-9_-]{12,80}", clean):
            raise ManuscriptAcceptanceError("接纳操作 ID 无效", code="INVALID_OPERATION_ID")
        return self.operations_dir / f"{clean}.json"

    def operation(self, operation_id: str) -> dict[str, Any]:
        path = self.operation_path(operation_id)
        payload = self._read_json(path)
        if payload is None or payload.get("schema_version") != SCHEMA_VERSION:
            raise ManuscriptAcceptanceError("接纳操作不存在或损坏", code="OPERATION_NOT_FOUND")
        return payload

    def inspect(self) -> dict[str, Any]:
        """Return current disk-vs-acceptance state without writing a baseline."""
        state = self._state()
        heads = state.get("chapters") if isinstance(state.get("chapters"), dict) else {}
        chapters: list[dict[str, Any]] = []
        seen: set[str] = set()
        for chapter_id, path in self._chapters():
            seen.add(chapter_id)
            content = path.read_text(encoding="utf-8")
            current = self.fingerprint(content)
            head = heads.get(chapter_id) if isinstance(heads.get(chapter_id), dict) else {}
            accepted = str(head.get("accepted_revision") or "")
            pending = str(head.get("pending_revision") or "")
            status = str(head.get("status") or "baseline_required")
            if status in {"pending", "processing", "failed", "stale"}:
                expected_current = pending or accepted
                if not expected_current or expected_current != current:
                    status = "external_change"
            elif not accepted:
                status = "baseline_required"
            elif accepted != current:
                status = "external_change"
            chapters.append(
                {
                    "chapter_id": chapter_id,
                    "path": path.relative_to(self.novel_root).as_posix(),
                    "status": status,
                    "current_revision": current,
                    "accepted_revision": accepted,
                    "pending_revision": pending,
                    "facts_revision": str(head.get("facts_revision") or ""),
                    "operation_id": str(head.get("operation_id") or ""),
                    "source": str(head.get("source") or ""),
                    "updated_at": str(head.get("updated_at") or ""),
                }
            )
        for chapter_id, head in heads.items():
            if chapter_id in seen or not isinstance(head, dict):
                continue
            chapters.append(
                {
                    "chapter_id": chapter_id,
                    "path": str(head.get("path") or ""),
                    "status": "external_change",
                    "current_revision": "",
                    "accepted_revision": str(head.get("accepted_revision") or ""),
                    "facts_revision": str(head.get("facts_revision") or ""),
                    "operation_id": str(head.get("operation_id") or ""),
                    "source": str(head.get("source") or ""),
                    "updated_at": str(head.get("updated_at") or ""),
                }
            )
        chapters.sort(key=lambda item: self._chapter_number(item["chapter_id"]))
        statuses = {item["status"] for item in chapters}
        latest_id = str(state.get("latest_operation_id") or "")
        impacts: list[dict[str, Any]] = []
        if latest_id:
            try:
                impacts = list(self.operation(latest_id).get("impacts") or [])
            except ManuscriptAcceptanceError:
                pass
        needs_review = [item for item in impacts if str(item.get("status") or "") == "needs_review"]
        if "external_change" in statuses:
            status = "external_change"
        elif "baseline_required" in statuses:
            status = "baseline_required"
        elif statuses & {"pending", "processing", "failed", "stale"}:
            status = "pending"
        elif needs_review:
            status = "needs_review"
        else:
            status = "current"
        return {
            "schema_version": SCHEMA_VERSION,
            "novel_id": self.novel_id,
            "status": status,
            "blocking": status != "current",
            "chapters": chapters,
            "latest_operation_id": latest_id,
            "impacts": impacts,
            "needs_review": needs_review,
        }

    def require_current(self, target_chapter_id: str) -> dict[str, Any]:
        surface = self.inspect()
        target = self._chapter_number(target_chapter_id)
        relevant = [
            item
            for item in surface["chapters"]
            if not target or self._chapter_number(item["chapter_id"]) < target
        ]
        statuses = {item["status"] for item in relevant}
        if "external_change" in statuses:
            raise ManuscriptAcceptanceError(
                "检测到正文被外部修改，请先确认并重建关联事实",
                code="EXTERNAL_MANUSCRIPT_CHANGE",
                details={"chapters": relevant},
            )
        if "baseline_required" in statuses:
            raise ManuscriptAcceptanceError(
                "现有正文尚未建立接纳基线，请先显式建立并重建事实",
                code="ACCEPTANCE_BASELINE_REQUIRED",
                details={"chapters": relevant},
            )
        if statuses & {"pending", "processing", "failed", "stale"}:
            raise ManuscriptAcceptanceError(
                "正文已保存，关联事实仍待更新",
                code="MANUSCRIPT_FACTS_PENDING",
                details={"chapters": relevant},
            )
        if surface["needs_review"]:
            raise ManuscriptAcceptanceError(
                "事实已重建，但后续大纲或伏笔仍需作者复核",
                code="MANUSCRIPT_DEPENDENCIES_NEED_REVIEW",
                details={"impacts": surface["needs_review"]},
            )
        return surface

    def establish_baseline(self, *, confirm: bool = False) -> dict[str, Any]:
        if not confirm:
            raise ManuscriptAcceptanceError(
                "建立接纳基线需要显式确认", code="CONFIRMATION_REQUIRED"
            )
        chapters = self._chapters()
        if not chapters:
            raise ManuscriptAcceptanceError("当前没有正文", code="DOCUMENT_NOT_FOUND")
        state = self._state()
        tracked = state.get("chapters") if isinstance(state.get("chapters"), dict) else {}
        untracked = [
            item
            for item in chapters
            if not tracked.get(item[0], {}).get("accepted_revision")
            and not tracked.get(item[0], {}).get("pending_revision")
        ]
        if not untracked:
            raise ManuscriptAcceptanceError("正文基线已经存在", code="BASELINE_ALREADY_EXISTS")
        return self._start(
            chapter_ids=[chapter_id for chapter_id, _path in chapters],
            source="baseline",
            expected_previous_revision="",
            baseline=True,
        )

    def accept_external(self, chapter_id: str, *, confirm: bool = False) -> dict[str, Any]:
        if not confirm:
            raise ManuscriptAcceptanceError(
                "接纳外部修改需要显式确认", code="CONFIRMATION_REQUIRED"
            )
        clean = self._chapter_id(chapter_id)
        state = self._state()
        head = dict((state.get("chapters") or {}).get(clean) or {})
        expected = str(head.get("pending_revision") or head.get("accepted_revision") or "")
        return self.start_acceptance(
            clean,
            source="external_editor",
            expected_previous_revision=expected,
        )

    def start_acceptance(
        self,
        chapter_id: str,
        *,
        source: str,
        expected_previous_revision: str = "",
        source_run_id: str = "",
    ) -> dict[str, Any]:
        clean = self._chapter_id(chapter_id)
        chapters = self._chapters()
        affected = [
            item[0]
            for item in chapters
            if self._chapter_number(item[0]) >= self._chapter_number(clean)
        ]
        if clean not in affected:
            raise ManuscriptAcceptanceError("正文不存在", code="DOCUMENT_NOT_FOUND")
        return self._start(
            chapter_ids=affected,
            source=self._source(source),
            expected_previous_revision=expected_previous_revision,
            baseline=False,
            source_run_id=source_run_id,
        )

    def resume(
        self,
        operation_id: str,
        *,
        analyzer: Analyzer | None = None,
        fault_injector: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        operation = self.operation(operation_id)
        if operation["status"] == "completed":
            return operation
        if operation["status"] == "stale":
            raise ManuscriptAcceptanceError(
                "接纳操作的正文已变化，请从当前正文创建新操作",
                code="ACCEPTED_SOURCE_CHANGED",
            )
        analyze = analyzer or self._default_analyzer
        operation["status"] = "running"
        self._write_operation(operation)
        try:
            self._analyze(operation, analyze, fault_injector)
            self._rebuild(operation, fault_injector)
            self._finish_propagation(operation, fault_injector)
        except ManuscriptAcceptanceError:
            raise
        except Exception as exc:
            active = self._active_stage(operation)
            if active:
                stage = operation["stages"][active]
                stage["status"] = "failed"
                stage["error_code"] = type(exc).__name__
                stage["error_message"] = str(exc)[:1000]
                stage["completed_at"] = self._now()
            operation["status"] = "failed"
            operation["updated_at"] = self._now()
            self._write_operation(operation)
            self._set_heads_status(operation, "failed")
            raise
        operation["status"] = "completed"
        operation["accepted_revision"] = str(operation.get("target_revision") or "")
        operation["updated_at"] = self._now()
        operation["completed_at"] = self._now()
        self._write_operation(operation)
        self._set_heads_status(operation, "current", facts_current=True)
        return operation

    def acknowledge(
        self,
        operation_id: str,
        *,
        domains: Iterable[str],
        confirm: bool = False,
    ) -> dict[str, Any]:
        if not confirm:
            raise ManuscriptAcceptanceError("复核确认不能为空", code="CONFIRMATION_REQUIRED")
        operation = self.operation(operation_id)
        requested = {str(item or "").strip() for item in domains}
        invalid = requested - REVIEW_DOMAINS
        if invalid:
            raise ManuscriptAcceptanceError(
                f"不可确认的影响域: {', '.join(sorted(invalid))}", code="INVALID_DOMAIN"
            )
        for impact in operation.get("impacts") or []:
            if impact.get("domain") in requested and impact.get("status") == "needs_review":
                impact["status"] = "acknowledged"
                impact["acknowledged_at"] = self._now()
        operation["updated_at"] = self._now()
        self._write_operation(operation)
        return operation

    def record_precomputed(
        self,
        chapter_id: str,
        *,
        source: str,
        fact: dict[str, Any],
        expected_previous_revision: str = "",
        source_run_id: str = "",
    ) -> dict[str, Any]:
        """Register a write pipeline result without making another model call."""
        operation = self.start_acceptance(
            chapter_id,
            source=source,
            expected_previous_revision=expected_previous_revision,
            source_run_id=source_run_id,
        )
        clean = self._chapter_id(chapter_id)
        frozen = next(item for item in operation["frozen_chapters"] if item["chapter_id"] == clean)
        full_content = (self.root / frozen["snapshot"]).read_text(encoding="utf-8")
        title, _body = self._split_chapter(clean, full_content)
        operation["analysis_results"] = {
            clean: self._normalize_fact(
                clean,
                title,
                full_content,
                frozen["revision"],
                dict(fact),
            )
        }
        self._write_operation(operation)
        return self.resume(
            operation["operation_id"],
            analyzer=lambda cid, title, content, prior: self._default_analyzer(
                cid, title, content, prior
            ),
        )

    def _start(
        self,
        *,
        chapter_ids: list[str],
        source: str,
        expected_previous_revision: str,
        baseline: bool,
        source_run_id: str = "",
    ) -> dict[str, Any]:
        state = self._state()
        heads = state.setdefault("chapters", {})
        first = chapter_ids[0]
        existing = dict(heads.get(first) or {})
        recorded_previous = str(existing.get("accepted_revision") or "")
        recorded_base = str(existing.get("pending_revision") or recorded_previous)
        expected = str(expected_previous_revision or "")
        if not baseline and recorded_base and expected != recorded_base:
            raise ManuscriptAcceptanceError(
                "接纳基线已变化，请重新读取",
                code="STALE_ACCEPTED_REVISION",
                details={"expected": expected, "current": recorded_base},
            )
        now = self._now()
        operation_id = (
            f"accept_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:12]}"
        )
        frozen: list[dict[str, Any]] = []
        for chapter_id in chapter_ids:
            path = self._chapter_path(chapter_id)
            content = path.read_text(encoding="utf-8")
            revision = self.fingerprint(content)
            snapshot = self.snapshots_dir / operation_id / f"{chapter_id}.md"
            self._atomic_text(snapshot, content)
            frozen.append(
                {
                    "chapter_id": chapter_id,
                    "path": path.relative_to(self.novel_root).as_posix(),
                    "revision": revision,
                    "snapshot": snapshot.relative_to(self.root).as_posix(),
                }
            )
        stages = {
            name: {
                "status": "pending",
                "attempts": 0,
                "started_at": "",
                "completed_at": "",
                "error_code": "",
                "error_message": "",
            }
            for name in STAGE_NAMES
        }
        stages["capture"].update(
            {"status": "completed", "attempts": 1, "started_at": now, "completed_at": now}
        )
        impacts = self._impacts(first, baseline=baseline)
        operation = {
            "schema_version": SCHEMA_VERSION,
            "operation_id": operation_id,
            "novel_id": self.novel_id,
            "chapter_id": first,
            "affected_chapters": chapter_ids,
            "source": source,
            "baseline": baseline,
            "revises_existing": bool(expected),
            "source_run_id": str(source_run_id or ""),
            "expected_previous_revision": expected,
            "previous_accepted_revision": recorded_previous,
            "target_revision": frozen[0]["revision"],
            "accepted_revision": recorded_previous,
            "status": "pending",
            "created_at": now,
            "updated_at": now,
            "completed_at": "",
            "frozen_chapters": frozen,
            "analysis_results": {},
            "impacts": impacts,
            "stages": stages,
        }
        self._write_operation(operation)
        for item in frozen:
            previous = dict(heads.get(item["chapter_id"]) or {})
            heads[item["chapter_id"]] = {
                **previous,
                "chapter_id": item["chapter_id"],
                "path": item["path"],
                "pending_revision": item["revision"],
                "status": "pending",
                "operation_id": operation_id,
                "source": source,
                "updated_at": now,
            }
        state["latest_operation_id"] = operation_id
        state["updated_at"] = now
        state["revision"] = int(state.get("revision") or 0) + 1
        self._write_state(state)
        self._invalidate(operation)
        return self.operation(operation_id)

    def _invalidate(self, operation: dict[str, Any]) -> None:
        stage = operation["stages"]["invalidate"]
        if stage["status"] == "completed":
            return
        stage.update(
            {"status": "running", "attempts": int(stage["attempts"]) + 1, "started_at": self._now()}
        )
        self._write_operation(operation)
        first_number = self._chapter_number(operation["chapter_id"])
        accepted = str(operation.get("accepted_revision") or "")

        from tools.review_store import ReviewStore

        review_store = ReviewStore(self.project_root, self.novel_id)
        for chapter_id in operation["affected_chapters"]:
            review_store.mark_stale(
                chapter_id,
                reason="manuscript_acceptance_pending",
                current_source_revision=(accepted if chapter_id == operation["chapter_id"] else ""),
            )

        from tools.rolling_planning import RollingPlanningService

        plans = RollingPlanningService(self.project_root, self.novel_id)
        for candidate in plans.list(limit=100):
            if candidate.state != "stale":
                candidate.state = "stale"
                plans.save(candidate)

        from tools.chapter_run_v2 import ChapterRunV2Store

        runs = ChapterRunV2Store(self.project_root, self.novel_id)
        for manifest in runs.list(limit=200):
            if manifest.run_id == str(operation.get("source_run_id") or ""):
                continue
            if self._chapter_number(manifest.chapter_id) >= first_number:
                runs.invalidate_from(
                    manifest,
                    "context",
                    reason=f"manuscript_acceptance:{operation['operation_id']}",
                )
        stage.update({"status": "completed", "completed_at": self._now()})
        operation["updated_at"] = self._now()
        self._write_operation(operation)

    def _analyze(
        self,
        operation: dict[str, Any],
        analyzer: Analyzer,
        fault_injector: Callable[[str], None] | None,
    ) -> None:
        stage = operation["stages"]["analyze"]
        if stage["status"] == "completed":
            return
        stage.update(
            {
                "status": "running",
                "attempts": int(stage.get("attempts") or 0) + 1,
                "started_at": self._now(),
                "error_code": "",
                "error_message": "",
            }
        )
        self._write_operation(operation)
        results = operation.setdefault("analysis_results", {})
        prior_context = ""
        for frozen in operation["frozen_chapters"]:
            chapter_id = frozen["chapter_id"]
            self._assert_frozen_current(operation, frozen)
            if chapter_id not in results:
                if fault_injector:
                    fault_injector("analyze")
                snapshot = (self.root / frozen["snapshot"]).read_text(encoding="utf-8")
                title, body = self._split_chapter(chapter_id, snapshot)
                result = analyzer(chapter_id, title, body, prior_context)
                if not isinstance(result, dict):
                    raise ManuscriptAcceptanceError(
                        "事实分析结果必须是对象", code="INVALID_ANALYSIS_RESULT"
                    )
                self._assert_frozen_current(operation, frozen)
                results[chapter_id] = self._normalize_fact(
                    chapter_id, title, snapshot, frozen["revision"], result
                )
                operation["updated_at"] = self._now()
                self._write_operation(operation)
            prior_context = self._fact_context(results[chapter_id])
        stage.update({"status": "completed", "completed_at": self._now()})
        operation["updated_at"] = self._now()
        self._write_operation(operation)

    def _rebuild(
        self,
        operation: dict[str, Any],
        fault_injector: Callable[[str], None] | None,
    ) -> None:
        stage = operation["stages"]["rebuild"]
        if stage["status"] == "completed":
            return
        stage.update(
            {
                "status": "running",
                "attempts": int(stage.get("attempts") or 0) + 1,
                "started_at": self._now(),
                "error_code": "",
                "error_message": "",
            }
        )
        self._write_operation(operation)
        if fault_injector:
            fault_injector("rebuild")
        for frozen in operation["frozen_chapters"]:
            self._assert_frozen_current(operation, frozen)

        facts: dict[str, dict[str, Any]] = {}
        affected = set(operation["affected_chapters"])
        for chapter_id, _path in self._chapters():
            if chapter_id in affected:
                fact = operation["analysis_results"].get(chapter_id)
            else:
                fact = self._read_json(self.fact_path(chapter_id))
            if not isinstance(fact, dict):
                raise ManuscriptAcceptanceError(
                    f"{chapter_id} 缺少可重放事实，请先建立完整基线",
                    code="FACT_BASELINE_REQUIRED",
                    details={"chapter_id": chapter_id},
                )
            current = self.fingerprint(self._chapter_path(chapter_id).read_text(encoding="utf-8"))
            if str(fact.get("source_revision") or "") != current:
                raise ManuscriptAcceptanceError(
                    f"{chapter_id} 事实来源已变化",
                    code="ACCEPTED_SOURCE_CHANGED",
                    details={"chapter_id": chapter_id},
                )
            facts[chapter_id] = fact

        runtime = RuntimeStateManager(self.project_root, self.novel_id)
        previous = runtime.load()
        state = RuntimeState(
            novel_id=self.novel_id,
            legacy_documents=dict(previous.legacy_documents),
        )
        memory = ChapterMemoryStore(self.project_root, self.novel_id)
        for chapter_id in sorted(facts, key=self._chapter_number):
            fact = facts[chapter_id]
            delta_payload = fact.get("state_delta")
            delta: RuntimeStateDelta
            if isinstance(delta_payload, dict) and delta_payload.get("operations"):
                normalized = {
                    **delta_payload,
                    "chapter_id": chapter_id,
                    "source_revision": state.revision,
                }
                delta = RuntimeStateDelta.model_validate(normalized)
            else:
                delta = legacy_updates_to_delta(
                    dict(fact.get("legacy_updates") or {}),
                    chapter_id=chapter_id,
                    source_revision=state.revision,
                )
            state = runtime.apply(state, delta)
            self._atomic_json(self.fact_path(chapter_id), fact)
            memory.save(
                chapter_id=chapter_id,
                title=str(fact.get("title") or chapter_id),
                summary=str(fact.get("chapter_summary") or ""),
                word_count=int(fact.get("word_count") or 0),
                observations=str(fact.get("observations") or ""),
                token_usage=dict(fact.get("token_usage") or {}),
                source_revision=str(fact.get("source_revision") or ""),
                acceptance_operation_id=str(operation["operation_id"]),
            )
        runtime.save_with_projections(state)
        try:
            from tools.character_state_index import CharacterStateIndex

            CharacterStateIndex(self.project_root, self.novel_id).refresh()
        except Exception as exc:
            raise ManuscriptAcceptanceError(
                f"人物状态索引重建失败: {exc}", code="CHARACTER_INDEX_REBUILD_FAILED"
            ) from exc
        stage.update({"status": "completed", "completed_at": self._now()})
        operation["updated_at"] = self._now()
        self._write_operation(operation)

    def _finish_propagation(
        self,
        operation: dict[str, Any],
        fault_injector: Callable[[str], None] | None,
    ) -> None:
        stage = operation["stages"]["propagate"]
        if stage["status"] == "completed":
            return
        stage.update(
            {
                "status": "running",
                "attempts": int(stage.get("attempts") or 0) + 1,
                "started_at": self._now(),
                "error_code": "",
                "error_message": "",
            }
        )
        self._write_operation(operation)
        if fault_injector:
            fault_injector("propagate")
        for impact in operation.get("impacts") or []:
            if (
                impact.get("domain") in REVIEW_DOMAINS
                and not operation.get("baseline")
                and operation.get("revises_existing")
            ):
                impact["status"] = "needs_review"
            else:
                impact["status"] = "current"
        stage.update({"status": "completed", "completed_at": self._now()})
        operation["updated_at"] = self._now()
        self._write_operation(operation)

    def _assert_frozen_current(self, operation: dict[str, Any], frozen: dict[str, Any]) -> None:
        path = self.novel_root / frozen["path"]
        current = self.fingerprint(path.read_text(encoding="utf-8")) if path.is_file() else ""
        if current == frozen["revision"]:
            return
        operation["status"] = "stale"
        operation["updated_at"] = self._now()
        stage = operation["stages"]["analyze"]
        stage["status"] = "failed"
        stage["error_code"] = "ACCEPTED_SOURCE_CHANGED"
        stage["error_message"] = f"{frozen['chapter_id']} changed after capture"
        stage["completed_at"] = self._now()
        self._write_operation(operation)
        self._set_heads_status(operation, "stale")
        raise ManuscriptAcceptanceError(
            "事实分析期间正文再次变化，旧结果已拒绝",
            code="ACCEPTED_SOURCE_CHANGED",
            details={
                "chapter_id": frozen["chapter_id"],
                "expected": frozen["revision"],
                "current": current,
            },
        )

    def _set_heads_status(
        self,
        operation: dict[str, Any],
        status: str,
        *,
        facts_current: bool = False,
    ) -> None:
        state = self._state()
        heads = state.setdefault("chapters", {})
        frozen_by_id = {item["chapter_id"]: item for item in operation["frozen_chapters"]}
        for chapter_id in operation["affected_chapters"]:
            head = dict(heads.get(chapter_id) or {})
            if head.get("operation_id") != operation["operation_id"]:
                continue
            head["status"] = status
            head["updated_at"] = self._now()
            if facts_current:
                head["accepted_revision"] = frozen_by_id[chapter_id]["revision"]
                head["facts_revision"] = frozen_by_id[chapter_id]["revision"]
                head.pop("pending_revision", None)
            heads[chapter_id] = head
        state["updated_at"] = self._now()
        state["revision"] = int(state.get("revision") or 0) + 1
        self._write_state(state)

    def _state(self) -> dict[str, Any]:
        payload = self._read_json(self.state_path)
        if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
            return {
                "schema_version": SCHEMA_VERSION,
                "novel_id": self.novel_id,
                "revision": 0,
                "updated_at": "",
                "latest_operation_id": "",
                "chapters": {},
            }
        return payload

    def _write_state(self, payload: dict[str, Any]) -> None:
        self._atomic_json(self.state_path, payload)

    def _write_operation(self, payload: dict[str, Any]) -> None:
        self._atomic_json(self.operation_path(str(payload["operation_id"])), payload)

    def _chapters(self) -> list[tuple[str, Path]]:
        manuscript = self.novel_root / "data" / "manuscript"
        records = (
            [
                (path.stem, path)
                for path in manuscript.rglob("ch_*.md")
                if path.is_file() and re.fullmatch(r"ch_\d+", path.stem)
            ]
            if manuscript.is_dir()
            else []
        )
        return sorted(records, key=lambda item: self._chapter_number(item[0]))

    def _chapter_path(self, chapter_id: str) -> Path:
        clean = self._chapter_id(chapter_id)
        matches = [path for cid, path in self._chapters() if cid == clean]
        if len(matches) != 1:
            raise ManuscriptAcceptanceError("正文章节不存在或路径不唯一", code="DOCUMENT_NOT_FOUND")
        return matches[0]

    @staticmethod
    def _chapter_id(value: str) -> str:
        clean = str(value or "")
        if not re.fullmatch(r"ch_\d+", clean):
            raise ManuscriptAcceptanceError("章节 ID 必须形如 ch_001", code="INVALID_CHAPTER_ID")
        return clean

    @staticmethod
    def _chapter_number(value: str) -> int:
        match = re.search(r"(\d+)", str(value or ""))
        return int(match.group(1)) if match else 0

    @staticmethod
    def _source(value: str) -> str:
        clean = str(value or "").strip()
        allowed = {
            "manual",
            "autosave",
            "agent",
            "revision",
            "history_restore",
            "import",
            "batch_revision",
            "chapter_write",
            "multi_agent_write",
            "external_editor",
            "baseline",
        }
        if clean not in allowed:
            raise ManuscriptAcceptanceError("正文接纳来源无效", code="INVALID_SOURCE")
        return clean

    def _impacts(self, chapter_id: str, *, baseline: bool) -> list[dict[str, Any]]:
        reason = "baseline_rebuild" if baseline else f"{chapter_id}_content_changed"
        domains = (
            "chapter_memory",
            "runtime_facts",
            "character_state",
            "canon",
            "review",
            "plan",
            "search",
            "downstream_chapters",
            "outline",
            "foreshadowing",
        )
        return [
            {
                "domain": domain,
                "status": "stale",
                "reason": reason,
                "source_chapter": chapter_id,
            }
            for domain in domains
        ]

    def _normalize_fact(
        self,
        chapter_id: str,
        title: str,
        full_content: str,
        source_revision: str,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "chapter_id": chapter_id,
            "title": title,
            "source_revision": source_revision,
            "chapter_summary": str(result.get("chapter_summary") or "").strip(),
            "observations": str(result.get("observations") or "").strip(),
            "word_count": max(0, len(self._split_chapter(chapter_id, full_content)[1])),
            "state_delta": dict(result.get("state_delta") or {}),
            "legacy_updates": dict(
                result.get("legacy_updates") or result.get("state_updates") or {}
            ),
            "token_usage": dict(result.get("token_usage") or {}),
            "analyzed_at": self._now(),
        }

    @staticmethod
    def _fact_context(fact: dict[str, Any]) -> str:
        return "\n".join(
            item
            for item in (
                str(fact.get("chapter_summary") or ""),
                str(fact.get("observations") or ""),
                "\n".join(str(value) for value in (fact.get("legacy_updates") or {}).values()),
            )
            if item.strip()
        )[-2400:]

    @staticmethod
    def _split_chapter(chapter_id: str, content: str) -> tuple[str, str]:
        clean = str(content or "").strip()
        if clean.startswith("#"):
            first, _, body = clean.partition("\n")
            return first.lstrip("#").strip() or chapter_id, body.strip()
        return chapter_id, clean

    def _default_analyzer(
        self, chapter_id: str, title: str, content: str, prior_context: str
    ) -> dict[str, Any]:
        from tools.settle_backfill import analyze_existing_chapter

        return analyze_existing_chapter(
            self.project_root,
            self.novel_id,
            chapter_id=chapter_id,
            title=title,
            content=content,
            truth_context=prior_context,
        )

    @staticmethod
    def _active_stage(operation: dict[str, Any]) -> str:
        for name in STAGE_NAMES:
            if (operation.get("stages") or {}).get(name, {}).get("status") == "running":
                return name
        return ""

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
        ManuscriptAcceptanceService._atomic_text(
            path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        )

    @staticmethod
    def _atomic_text(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
                temporary = Path(handle.name)
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
