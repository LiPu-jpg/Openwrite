"""Filesystem-backed Chapter Run V2 with deterministic recovery semantics."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from models.chapter_run_v2 import (
    ChapterRunV2Manifest,
    ChapterRunV2Stage,
    InterventionV1,
)

V2_STAGE_NAMES = (
    "context",
    "plan",
    "draft",
    "fact_extract",
    "settle",
    "validate",
    "commit",
    "review",
)

V2_STAGE_DEPENDENCIES = {
    "context": (),
    "plan": ("context",),
    "draft": ("plan",),
    "fact_extract": ("draft",),
    "settle": ("fact_extract",),
    "validate": ("settle",),
    "commit": ("validate",),
    "review": ("commit",),
}


class ChapterRunV2Error(RuntimeError):
    def __init__(self, message: str, *, code: str = "RUN_V2_ERROR") -> None:
        super().__init__(message)
        self.code = code


class ChapterRunV2Store:
    def __init__(self, project_root: Path, novel_id: str) -> None:
        self.project_root = Path(project_root).resolve()
        self.novel_id = str(novel_id)
        self.root = (
            self.project_root / "data" / "novels" / self.novel_id / "data" / "chapter_runs_v2"
        )

    def create(
        self,
        chapter_id: str,
        *,
        requested_target_words: int = 0,
        effective_target_words: int = 0,
        provider: str = "",
        model: str = "",
        model_profile: str = "",
        input_revisions: dict[str, str] | None = None,
    ) -> ChapterRunV2Manifest:
        now = self._now()
        manifest = ChapterRunV2Manifest(
            run_id=f"runv2_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:10]}",
            novel_id=self.novel_id,
            chapter_id=str(chapter_id),
            created_at=now,
            updated_at=now,
            requested_target_words=max(0, int(requested_target_words)),
            effective_target_words=max(0, int(effective_target_words)),
            provider=str(provider or ""),
            model=str(model or ""),
            model_profile=str(model_profile or model or ""),
            input_revisions=dict(input_revisions or {}),
            stages={name: ChapterRunV2Stage() for name in V2_STAGE_NAMES},
        )
        self.save(manifest)
        return manifest

    def load(self, run_id: str) -> ChapterRunV2Manifest | None:
        path = self.path_for(run_id)
        if not path.is_file():
            return None
        try:
            return ChapterRunV2Manifest.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def list(
        self,
        *,
        chapter_id: str = "",
        statuses: set[str] | None = None,
        limit: int = 50,
        since: str = "",
    ) -> list[ChapterRunV2Manifest]:
        if not self.root.is_dir():
            return []
        result: list[ChapterRunV2Manifest] = []
        for path in self.root.glob("runv2_*.json"):
            manifest = self.load(path.stem)
            if manifest is None:
                continue
            if manifest.archived or since and manifest.created_at < since:
                continue
            if chapter_id and manifest.chapter_id != chapter_id:
                continue
            if statuses is not None and manifest.status not in statuses:
                continue
            result.append(manifest)
        result.sort(key=lambda item: item.created_at, reverse=True)
        return result[: max(1, min(200, int(limit)))]

    def latest_for_chapter(self, chapter_id: str) -> ChapterRunV2Manifest | None:
        result = self.list(chapter_id=chapter_id, limit=1)
        return result[0] if result else None

    def latest_reviewable_for_chapter(self, chapter_id: str) -> ChapterRunV2Manifest | None:
        result = self.list(
            chapter_id=chapter_id,
            statuses={"committed", "reviewed"},
            limit=1,
        )
        return result[0] if result else None

    def revision(self, manifest: ChapterRunV2Manifest) -> str:
        return self.content_revision(manifest.model_dump(mode="json"))

    def payload(self, manifest: ChapterRunV2Manifest) -> dict[str, Any]:
        payload = manifest.model_dump(mode="json")
        payload["revision"] = self.revision(manifest)
        payload["next_stage"] = self.next_stage(manifest)
        return payload

    def require_revision(self, manifest: ChapterRunV2Manifest, expected_revision: str) -> None:
        expected = str(expected_revision or "").strip()
        if not expected:
            raise ChapterRunV2Error(
                "修改 Chapter Run V2 前必须提供 revision",
                code="REVISION_REQUIRED",
            )
        if expected != self.revision(manifest):
            raise ChapterRunV2Error(
                "Chapter Run V2 已变化，请重新读取后再操作",
                code="STALE_REVISION",
            )

    def start_stage(
        self,
        manifest: ChapterRunV2Manifest,
        stage: str,
        *,
        input_revisions: dict[str, str] | None = None,
        prompt_version: str = "",
        model_profile: str = "",
    ) -> ChapterRunV2Manifest:
        self._require_stage(stage)
        self._require_dependencies(manifest, stage)
        previous = manifest.stages[stage]
        stage_inputs = dict(input_revisions or manifest.input_revisions)
        if input_revisions:
            manifest.input_revisions.update(input_revisions)
        if previous.status == "completed" and self._inputs_match(
            previous.input_revisions, stage_inputs
        ):
            self.save(manifest)
            return manifest
        now = self._now()
        manifest.status = "running"
        manifest.updated_at = now
        manifest.stages[stage] = ChapterRunV2Stage(
            status="running",
            input_revisions=stage_inputs,
            prompt_version=str(prompt_version or previous.prompt_version),
            model_profile=str(model_profile or manifest.model_profile),
            attempts=previous.attempts + 1,
            started_at=now,
        )
        self.save(manifest)
        return manifest

    def complete_stage(
        self,
        manifest: ChapterRunV2Manifest,
        stage: str,
        *,
        output: Any = None,
        artifact: str = "",
        usage: dict[str, Any] | None = None,
        expected_input_revisions: dict[str, str] | None = None,
    ) -> ChapterRunV2Manifest:
        self._require_stage(stage)
        previous = manifest.stages[stage]
        if previous.status not in {"running", "completed"}:
            raise ChapterRunV2Error(f"阶段尚未运行: {stage}", code="INVALID_STAGE_TRANSITION")
        expected = expected_input_revisions or previous.input_revisions
        if not self._inputs_match(expected, manifest.input_revisions):
            self.mark_stale(manifest, manifest.input_revisions)
            raise ChapterRunV2Error(f"阶段输入 revision 已变化: {stage}", code="STALE_STAGE")
        now = self._now()
        manifest.updated_at = now
        manifest.stages[stage] = ChapterRunV2Stage(
            status="completed",
            input_revisions=dict(previous.input_revisions),
            output_revision=self.content_revision(output),
            artifact=self._safe_artifact(artifact),
            prompt_version=previous.prompt_version,
            model_profile=previous.model_profile,
            usage=dict(usage or {}),
            attempts=max(1, previous.attempts),
            started_at=previous.started_at,
            completed_at=now,
        )
        if stage == "draft":
            manifest.status = "drafted"
        elif stage == "commit":
            manifest.status = "committed"
        elif stage == "review":
            manifest.status = "reviewed"
        self.save(manifest)
        return manifest

    def fail_stage(
        self,
        manifest: ChapterRunV2Manifest,
        stage: str,
        *,
        code: str,
        message: str = "",
    ) -> ChapterRunV2Manifest:
        self._require_stage(stage)
        now = self._now()
        previous = manifest.stages[stage]
        if stage == "review" and manifest.stages["commit"].status == "completed":
            manifest.status = "committed"
        elif stage in {"fact_extract", "settle", "validate", "commit"} and (
            manifest.stages["draft"].status == "completed"
        ):
            manifest.status = "drafted"
        else:
            manifest.status = "failed"
        manifest.updated_at = now
        manifest.stages[stage] = ChapterRunV2Stage(
            status="failed",
            input_revisions=dict(previous.input_revisions),
            prompt_version=previous.prompt_version,
            model_profile=previous.model_profile,
            attempts=max(1, previous.attempts),
            started_at=previous.started_at,
            completed_at=now,
            error_code=str(code or "RUN_FAILED"),
            error_message=str(message or "")[:2000],
        )
        self.save(manifest)
        return manifest

    def request_cancel(
        self, manifest: ChapterRunV2Manifest, *, reason: str = "user_cancelled"
    ) -> ChapterRunV2Manifest:
        manifest.cancel_requested = True
        manifest.stop_reason = str(reason or "user_cancelled")
        manifest.updated_at = self._now()
        self.save(manifest)
        return manifest

    def finalize_cancel(self, manifest: ChapterRunV2Manifest) -> ChapterRunV2Manifest:
        manifest.cancel_requested = True
        manifest.status = "cancelled"
        manifest.updated_at = self._now()
        self.save(manifest)
        return manifest

    def assert_accepts_result(self, manifest: ChapterRunV2Manifest) -> None:
        current = self.load(manifest.run_id)
        if current and current.cancel_requested:
            manifest.cancel_requested = True
        if manifest.cancel_requested or manifest.status == "cancelled":
            raise ChapterRunV2Error("运行已取消，拒绝晚到模型结果", code="LATE_RESULT_REJECTED")

    def mark_stale(
        self,
        manifest: ChapterRunV2Manifest,
        current_input_revisions: dict[str, str],
    ) -> tuple[str, ...]:
        changed = {
            key
            for key, value in current_input_revisions.items()
            if manifest.input_revisions.get(key) != value
        }
        changed.update(set(manifest.input_revisions) - set(current_input_revisions))
        manifest.input_revisions = dict(current_input_revisions)
        stale: set[str] = set()
        for stage in V2_STAGE_NAMES:
            record = manifest.stages[stage]
            dependency_stale = any(dep in stale for dep in V2_STAGE_DEPENDENCIES[stage])
            input_stale = any(
                key in changed
                and record.input_revisions.get(key) != current_input_revisions.get(key)
                for key in record.input_revisions
            )
            if record.status == "completed" and (dependency_stale or input_stale):
                manifest.stages[stage] = record.model_copy(update={"status": "stale"})
                stale.add(stage)
        if stale:
            manifest.status = "running"
            manifest.updated_at = self._now()
            self.save(manifest)
        return tuple(stage for stage in V2_STAGE_NAMES if stage in stale)

    def next_stage(self, manifest: ChapterRunV2Manifest) -> str:
        for stage in V2_STAGE_NAMES:
            status = manifest.stages[stage].status
            if status in {"pending", "failed", "stale", "running"}:
                return stage
        return ""

    def add_intervention(
        self,
        manifest: ChapterRunV2Manifest,
        *,
        scope: str,
        risk: str,
        request: str,
        affected_items: Iterable[str] = (),
        rewrite_required: bool = False,
    ) -> InterventionV1:
        now = self._now()
        intervention = InterventionV1(
            intervention_id=f"int_{uuid4().hex[:16]}",
            scope=scope,  # type: ignore[arg-type]
            risk=risk,  # type: ignore[arg-type]
            affected_items=tuple(str(item) for item in affected_items),
            rewrite_required=bool(rewrite_required),
            request=str(request).strip(),
            created_at=now,
            updated_at=now,
        )
        manifest.interventions = (*manifest.interventions, intervention)
        manifest.updated_at = now
        self.save(manifest)
        return intervention

    def update_intervention(
        self,
        manifest: ChapterRunV2Manifest,
        intervention_id: str,
        *,
        state: str,
        facts_revision: str | None = None,
        impact: Iterable[str] | None = None,
        proposal: str | None = None,
        confirm: bool = False,
    ) -> InterventionV1:
        index, current = self._intervention(manifest, intervention_id)
        if state in {"confirmed", "applied"} and not confirm:
            raise ChapterRunV2Error("干预确认或应用需要显式确认", code="CONFIRMATION_REQUIRED")
        allowed = {
            "recorded": {"facts_read", "rejected", "stale"},
            "facts_read": {"classified", "rejected", "stale"},
            "classified": {"proposed", "rejected", "stale"},
            "proposed": {"awaiting_confirmation", "rejected", "stale"},
            "awaiting_confirmation": {"confirmed", "rejected", "stale"},
            "confirmed": {"applied", "stale"},
            "applied": {"stale"},
            "rejected": set(),
            "stale": set(),
        }
        if state not in allowed[current.state]:
            raise ChapterRunV2Error(
                f"无效干预状态转换: {current.state} -> {state}",
                code="INVALID_INTERVENTION_TRANSITION",
            )
        now = self._now()
        updated = current.model_copy(
            update={
                "state": state,
                "facts_revision": (
                    current.facts_revision if facts_revision is None else str(facts_revision)
                ),
                "impact": (
                    current.impact if impact is None else tuple(str(item) for item in impact)
                ),
                "proposal": current.proposal if proposal is None else str(proposal)[:20000],
                "updated_at": now,
            }
        )
        interventions = list(manifest.interventions)
        interventions[index] = updated
        manifest.interventions = tuple(interventions)
        manifest.updated_at = now
        if state == "applied":
            self.invalidate_from(manifest, "plan", reason="intervention_applied")
        self.save(manifest)
        return updated

    def invalidate_from(
        self,
        manifest: ChapterRunV2Manifest,
        stage: str,
        *,
        reason: str = "input_changed",
    ) -> tuple[str, ...]:
        self._require_stage(stage)
        start = V2_STAGE_NAMES.index(stage)
        stale: list[str] = []
        for name in V2_STAGE_NAMES[start:]:
            record = manifest.stages[name]
            if record.status in {"completed", "running", "failed"}:
                manifest.stages[name] = record.model_copy(
                    update={
                        "status": "stale",
                        "error_code": "STALE_STAGE",
                        "error_message": reason,
                    }
                )
                stale.append(name)
        if stale:
            manifest.status = "running"
            manifest.updated_at = self._now()
            self.save(manifest)
        return tuple(stale)

    def stale_interventions(
        self,
        manifest: ChapterRunV2Manifest,
        *,
        facts_revision: str,
        reason: str = "facts_revision_changed",
    ) -> tuple[str, ...]:
        changed: list[str] = []
        updated: list[InterventionV1] = []
        for item in manifest.interventions:
            if (
                item.state not in {"applied", "rejected", "stale"}
                and item.facts_revision
                and item.facts_revision != facts_revision
            ):
                item = item.model_copy(
                    update={
                        "state": "stale",
                        "stale_reason": reason,
                        "updated_at": self._now(),
                    }
                )
                changed.append(item.intervention_id)
            updated.append(item)
        if changed:
            manifest.interventions = tuple(updated)
            manifest.updated_at = self._now()
            self.save(manifest)
        return tuple(changed)

    def save(self, manifest: ChapterRunV2Manifest) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        existing = self.load(manifest.run_id)
        if existing and existing.cancel_requested:
            manifest.cancel_requested = True
        target = self.path_for(manifest.run_id)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.root,
            prefix=f".{manifest.run_id}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(manifest.model_dump_json(indent=2))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        temporary.replace(target)
        return target

    def write_artifact(
        self,
        manifest: ChapterRunV2Manifest,
        stage: str,
        payload: Any,
    ) -> str:
        self._require_stage(stage)
        root = self.root / "artifacts" / manifest.run_id
        target = root / f"{stage}.json"
        root.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        temporary.replace(target)
        return str(target.relative_to(self.project_root))

    def read_artifact(self, artifact: str) -> Any:
        safe = self._safe_artifact(artifact)
        if not safe:
            raise ChapterRunV2Error("artifact 为空", code="ARTIFACT_NOT_FOUND")
        path = (self.project_root / safe).resolve()
        if not path.is_file():
            raise ChapterRunV2Error("artifact 不存在", code="ARTIFACT_NOT_FOUND")
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ChapterRunV2Error("artifact 无法读取", code="INVALID_ARTIFACT") from exc

    def path_for(self, run_id: str) -> Path:
        clean = str(run_id or "")
        if not clean.startswith("runv2_") or any(part in clean for part in ("/", "\\", "..")):
            raise ValueError("无效 Chapter Run V2 ID")
        return self.root / f"{clean}.json"

    @staticmethod
    def content_revision(payload: Any) -> str:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _require_stage(stage: str) -> None:
        if stage not in V2_STAGE_DEPENDENCIES:
            raise ChapterRunV2Error(f"未知阶段: {stage}", code="INVALID_STAGE")

    @staticmethod
    def _require_dependencies(manifest: ChapterRunV2Manifest, stage: str) -> None:
        incomplete = [
            dependency
            for dependency in V2_STAGE_DEPENDENCIES[stage]
            if manifest.stages[dependency].status not in {"completed", "skipped"}
        ]
        if incomplete:
            raise ChapterRunV2Error(
                f"前置阶段未完成: {', '.join(incomplete)}",
                code="STAGE_DEPENDENCY_INCOMPLETE",
            )

    @staticmethod
    def _inputs_match(expected: dict[str, str], current: dict[str, str]) -> bool:
        return all(current.get(key) == value for key, value in expected.items())

    def _safe_artifact(self, artifact: str) -> str:
        value = str(artifact or "").strip()
        if not value:
            return ""
        path = Path(value)
        if path.is_absolute():
            try:
                return str(path.resolve().relative_to(self.project_root))
            except ValueError as exc:
                raise ChapterRunV2Error(
                    "artifact 必须位于项目目录内", code="PATH_OUT_OF_BOUNDS"
                ) from exc
        if ".." in path.parts:
            raise ChapterRunV2Error("artifact 路径越界", code="PATH_OUT_OF_BOUNDS")
        return str(path)

    @staticmethod
    def _intervention(
        manifest: ChapterRunV2Manifest, intervention_id: str
    ) -> tuple[int, InterventionV1]:
        for index, item in enumerate(manifest.interventions):
            if item.intervention_id == intervention_id:
                return index, item
        raise ChapterRunV2Error("干预不存在", code="INTERVENTION_NOT_FOUND")


def chapter_run_v2_action(
    project_root: Path,
    novel_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Shared Chapter Run V2 action surface for Agent, CLI and Studio."""

    store = ChapterRunV2Store(project_root, novel_id)
    action = str(payload.get("action") or "list").strip().lower()
    if action == "list":
        statuses_value = payload.get("statuses")
        statuses = (
            {str(item) for item in statuses_value}
            if isinstance(statuses_value, (list, tuple, set))
            else None
        )
        runs = store.list(
            chapter_id=str(payload.get("chapter_id") or ""),
            statuses=statuses,
            limit=int(payload.get("limit") or 20),
            since=str(payload.get("since") or ""),
        )
        return {
            "runs": [store.payload(run) for run in runs],
            "count": len(runs),
        }

    run_id = str(payload.get("run_id") or "").strip()
    if not run_id:
        raise ChapterRunV2Error("缺少 run_id", code="RUN_ID_REQUIRED")
    manifest = store.load(run_id)
    if manifest is None:
        raise ChapterRunV2Error("Chapter Run V2 不存在", code="RUN_NOT_FOUND")
    if action in {"get", "show", "status"}:
        return store.payload(manifest)

    store.require_revision(manifest, str(payload.get("revision") or ""))
    if action == "archive":
        if any(stage.status == "running" for stage in manifest.stages.values()):
            raise ChapterRunV2Error(
                "Cannot archive a running stage; cancel and wait first", code="RUN_ACTIVE"
            )
        manifest.archived = True
        store.save(manifest)
        return {"run": store.payload(manifest), "archived": True}
    if action in {"record_intervention", "intervene"}:
        intervention = store.add_intervention(
            manifest,
            scope=str(payload.get("scope") or "chapter"),
            risk=str(payload.get("risk") or "medium"),
            request=str(payload.get("request") or ""),
            affected_items=(
                payload.get("affected_items")
                if isinstance(payload.get("affected_items"), list)
                else ()
            ),
            rewrite_required=bool(payload.get("rewrite_required")),
        )
        return {
            "run": store.payload(manifest),
            "intervention": intervention.model_dump(mode="json"),
        }
    if action in {"update_intervention", "transition"}:
        intervention = store.update_intervention(
            manifest,
            str(payload.get("intervention_id") or ""),
            state=str(payload.get("state") or ""),
            facts_revision=(
                str(payload["facts_revision"]) if "facts_revision" in payload else None
            ),
            impact=(payload.get("impact") if isinstance(payload.get("impact"), list) else None),
            proposal=(str(payload["proposal"]) if "proposal" in payload else None),
            confirm=bool(payload.get("confirm")),
        )
        return {
            "run": store.payload(manifest),
            "intervention": intervention.model_dump(mode="json"),
        }
    if action == "cancel":
        if manifest.status in {"reviewed", "cancelled"}:
            return {
                "run": store.payload(manifest),
                "cancelled": manifest.status == "cancelled",
                "already_terminal": True,
                "code": "RUN_ALREADY_TERMINAL",
                "message": (
                    "运行已经完成审稿，不能再取消。"
                    if manifest.status == "reviewed"
                    else "运行已经取消。"
                ),
            }
        store.request_cancel(manifest, reason=str(payload.get("reason") or "user_cancelled"))
        active = any(stage.status == "running" for stage in manifest.stages.values())
        if not active:
            store.finalize_cancel(manifest)
        return {
            "run": store.payload(manifest),
            "cancelled": not active,
            "cancel_requested": True,
            "cancellation_status": "requested" if active else "cancelled",
        }
    raise ChapterRunV2Error(f"未知 Chapter Run V2 操作: {action}", code="INVALID_RUN_ACTION")
