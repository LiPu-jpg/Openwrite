"""Read-only unified diagnostics over OpenWrite's existing runtime stores."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from models.runtime_diagnostics import (
    DiagnosticActionV1,
    DiagnosticEvidenceV1,
    RuntimeDiagnosticFindingV1,
    RuntimeDiagnosticReportV1,
)


class RuntimeDiagnosticsService:
    SOURCES = (
        "tasks",
        "chapter_runs_v2",
        "workflows",
        "runtime_state",
        "reviews",
        "context",
        "foreshadowing",
        "outline",
        "runtime_skills",
        "transport",
    )

    def __init__(self, project_root: Path, novel_id: str) -> None:
        self.project_root = Path(project_root).resolve()
        self.novel_id = str(novel_id)
        self.novel_root = self.project_root / "data" / "novels" / self.novel_id

    def run(self, *, stuck_minutes: int = 30) -> RuntimeDiagnosticReportV1:
        findings: list[RuntimeDiagnosticFindingV1] = []
        findings.extend(self._task_findings(stuck_minutes))
        findings.extend(self._run_findings())
        findings.extend(self._review_findings())
        findings.extend(self._outline_findings())
        findings.extend(self._foreshadowing_findings())
        findings.extend(self._context_findings())
        findings.extend(self._timeline_findings())
        findings.extend(self._skill_findings())
        findings.extend(self._transport_findings())
        payload = [item.model_dump(mode="json") for item in findings]
        revision = self._hash(payload)
        return RuntimeDiagnosticReportV1(
            report_id=f"diag_{revision.split(':', 1)[-1][:16]}",
            novel_id=self.novel_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            revision=revision,
            sources=self.SOURCES,
            findings=tuple(findings),
        )

    def _transport_findings(self) -> list[RuntimeDiagnosticFindingV1]:
        from tools.chapter_run_v2 import ChapterRunV2Store

        findings = []
        root = self.project_root / ".openwrite" / "transport-errors"
        if root.is_dir():
            paths = sorted(
                root.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True
            )[:20]
            for path in paths:
                try:
                    record = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                findings.append(
                    self._finding(
                        "transport_error",
                        "warning",
                        "Tool transport failed",
                        "The backend may already have accepted this request. Inspect recent tasks/runs before submitting again.",
                        [str(record.get("tool_call_id") or path.stem)],
                        [
                            ("transport", "code", record.get("code")),
                            ("transport", "path", record.get("path")),
                            ("transport", "created_at", record.get("created_at")),
                        ],
                        "open_tasks",
                        {},
                    )
                )
        from tools.task_store import TaskStore

        tasks = TaskStore(self.project_root, self.novel_id).list(limit=500)
        for run in ChapterRunV2Store(self.project_root, self.novel_id).list(
            statuses={"running"}, limit=100
        ):
            if not any(stage.status == "running" for stage in run.stages.values()):
                continue
            if not any(
                task.get("status") == "running" and task.get("chapter_id") in {"", run.chapter_id}
                for task in tasks
            ):
                findings.append(
                    self._finding(
                        "orphan_chapter_run",
                        "warning",
                        "Chapter run has no active task",
                        "This may be a synchronous request that disconnected. Inspect the run and lock owner before retrying.",
                        [run.chapter_id, run.run_id],
                        [("transport", "run_id", run.run_id)],
                        "open_chapter_run",
                        {"run_id": run.run_id},
                    )
                )
        return findings

    def _task_findings(self, stuck_minutes: int) -> list[RuntimeDiagnosticFindingV1]:
        from tools.task_store import TaskStore

        tasks = TaskStore(self.project_root, self.novel_id).list(limit=500)
        findings: list[RuntimeDiagnosticFindingV1] = []
        threshold = datetime.now(timezone.utc) - timedelta(minutes=max(1, stuck_minutes))
        for task in tasks:
            if task.get("status") != "running":
                continue
            updated = self._date(task.get("updated_at"))
            if updated is not None and updated < threshold:
                findings.append(
                    self._finding(
                        "stuck_task",
                        "error",
                        "任务长时间没有进展",
                        "运行中的任务超过阈值未更新，可能需要取消后从持久化阶段恢复。",
                        [str(task.get("task_id") or "")],
                        [
                            ("tasks", "phase", task.get("phase")),
                            ("tasks", "updated_at", task.get("updated_at")),
                        ],
                        "open_task",
                        {"task_id": task.get("task_id")},
                    )
                )
        failed = [
            task
            for task in tasks
            if task.get("status") == "failed"
            and (task.get("error") or {}).get("code") != "PROJECT_BUSY"
        ]
        groups = Counter(
            (str(task.get("type") or ""), str(task.get("chapter_id") or "")) for task in failed
        )
        for (task_type, chapter_id), count in groups.items():
            if count < 2:
                continue
            findings.append(
                self._finding(
                    "repeated_task_failure",
                    "error",
                    "同一工作连续失败",
                    "相同任务与章节至少失败两次，应先查看最后错误和输入 revision。",
                    [item for item in (task_type, chapter_id) if item],
                    [("tasks", "failure_count", count)],
                    "open_diagnostics",
                    {"task_type": task_type, "chapter_id": chapter_id},
                )
            )
        return findings

    def _run_findings(self) -> list[RuntimeDiagnosticFindingV1]:
        from tools.chapter_run_v2 import ChapterRunV2Store

        store = ChapterRunV2Store(self.project_root, self.novel_id)
        findings: list[RuntimeDiagnosticFindingV1] = []
        for run in store.list(limit=100):
            failed = [name for name, stage in run.stages.items() if stage.status == "failed"]
            stale = [name for name, stage in run.stages.items() if stage.status == "stale"]
            if failed:
                stage = failed[0]
                findings.append(
                    self._finding(
                        "chapter_stage_failed",
                        "error",
                        f"章节运行停在 {stage}",
                        "该阶段失败，已完成且 revision 一致的前置 artifact 可以复用。",
                        [run.chapter_id, run.run_id],
                        [
                            ("chapter_runs_v2", "stage", stage),
                            (
                                "chapter_runs_v2",
                                "error_code",
                                run.stages[stage].error_code,
                            ),
                        ],
                        "open_chapter_run",
                        {"run_id": run.run_id},
                    )
                )
            if stale and run.status == "running":
                findings.append(
                    self._finding(
                        "chapter_stage_stale",
                        "warning",
                        "章节运行包含过时阶段",
                        "输入或前置产物 revision 已变化，过时阶段不会被静默复用。",
                        [run.chapter_id, run.run_id],
                        [("chapter_runs_v2", "stages", stale)],
                        "open_chapter_run",
                        {"run_id": run.run_id},
                    )
                )
            draft = run.stages.get("draft")
            if draft and draft.status == "completed" and draft.artifact:
                try:
                    artifact = store.read_artifact(draft.artifact)
                except Exception:
                    artifact = {}
                words = int(artifact.get("word_count") or 0) if isinstance(artifact, dict) else 0
                target = int(run.effective_target_words or 0)
                if target and words and (words < target * 0.5 or words > target * 1.8):
                    findings.append(
                        self._finding(
                            "abnormal_word_count",
                            "warning",
                            "章节字数明显偏离目标",
                            "草稿字数低于目标一半或超过目标 1.8 倍。",
                            [run.chapter_id],
                            [
                                ("chapter_runs_v2", "word_count", words),
                                ("chapter_runs_v2", "target_words", target),
                            ],
                            "open_chapter",
                            {"chapter_id": run.chapter_id},
                        )
                    )
        return findings

    def _review_findings(self) -> list[RuntimeDiagnosticFindingV1]:
        from tools.review_store import ReviewStore

        store = ReviewStore(self.project_root, self.novel_id)
        records: list[tuple[str, float]] = []
        if store.review_dir.is_dir():
            for path in store.review_dir.glob("ch_*.json"):
                record = store.load(path.stem) or {}
                try:
                    records.append((path.stem, float(record.get("score") or 0)))
                except (TypeError, ValueError):
                    continue
        low = [(chapter, score) for chapter, score in records if score < 75]
        if len(low) < 2:
            return []
        return [
            self._finding(
                "persistent_low_review_score",
                "warning",
                "多章审稿分持续偏低",
                "至少两章低于 75 分，建议先处理共同维度再继续批量写作。",
                [chapter for chapter, _ in low],
                [("reviews", "scores", dict(low))],
                "open_review",
                {"chapter_id": low[-1][0]},
            )
        ]

    def _outline_findings(self) -> list[RuntimeDiagnosticFindingV1]:
        from tools.outline_tree import build_outline_structure

        outline = build_outline_structure(self.novel_root)
        planned = int(outline.get("counts", {}).get("chapter", 0) or 0)
        drafted = int(outline.get("drafted_chapters") or 0)
        if planned > drafted and outline.get("recommendation"):
            return []
        return [
            self._finding(
                "outline_window_exhausted",
                "blocker",
                "近期大纲窗口已耗尽",
                "没有可写的下一章计划，应先由 Goethe 生成滚动规划候选。",
                ["src/outline.md"],
                [
                    ("outline", "planned_chapters", planned),
                    ("outline", "drafted_chapters", drafted),
                ],
                "create_rolling_plan",
                {},
            )
        ]

    def _foreshadowing_findings(self) -> list[RuntimeDiagnosticFindingV1]:
        from tools.foreshadowing_manager import ForeshadowingDAGManager

        nodes = ForeshadowingDAGManager(
            self.project_root, self.novel_id
        ).get_pending_nodes(min_weight=1)
        manuscript = list((self.novel_root / "data" / "manuscript").rglob("ch_*.md"))
        latest = max((self._chapter_number(path.stem) for path in manuscript), default=0)
        overdue = [
            node
            for node in nodes
            if self._chapter_number(node.created_at)
            and latest - self._chapter_number(node.created_at) >= 10
        ]
        if not overdue:
            return []
        return [
            self._finding(
                "foreshadowing_stalled",
                "warning",
                "伏笔长期没有推进",
                "伏笔已跨越至少十章仍处于埋伏或待收状态。",
                [node.id for node in overdue],
                [
                    ("foreshadowing", "latest_chapter", latest),
                    (
                        "foreshadowing",
                        "ages",
                        {
                            node.id: latest - self._chapter_number(node.created_at)
                            for node in overdue
                        },
                    ),
                ],
                "open_foreshadowing",
                {},
            )
        ]

    def _context_findings(self) -> list[RuntimeDiagnosticFindingV1]:
        from tools.context_builder import ContextBuilder
        from tools.outline_tree import build_outline_structure

        recommendation = build_outline_structure(self.novel_root).get("recommendation")
        if not isinstance(recommendation, dict):
            return []
        chapter_id = str(recommendation.get("chapter_id") or "")
        try:
            context = ContextBuilder(
                self.project_root, self.novel_id
            ).build_generation_context(chapter_id)
        except Exception as exc:
            return [
                self._finding(
                    "context_build_failed",
                    "blocker",
                    "下一章上下文无法组装",
                    "canonical context 构建失败，写作前必须修复。",
                    [chapter_id],
                    [("context", "error_type", type(exc).__name__)],
                    "inspect_context",
                    {"chapter_id": chapter_id},
                )
            ]
        missing = [
            name
            for name, value in {
                "chapter_goals": getattr(context, "chapter_goals", None),
                "dramatic_context": getattr(context, "dramatic_context", None),
            }.items()
            if not value
        ]
        findings: list[RuntimeDiagnosticFindingV1] = []
        if missing:
            findings.append(
                self._finding(
                    "critical_context_missing",
                    "blocker",
                    "下一章缺少关键上下文",
                    "章节目标或戏剧位置为空，不能靠模型自行猜测。",
                    [chapter_id],
                    [("context", "missing_fields", missing)],
                    "inspect_context",
                    {"chapter_id": chapter_id},
                )
            )
        compression = dict(getattr(context, "compression", {}) or {})
        if compression.get("within_budget") is False:
            findings.append(
                self._finding(
                    "context_overloaded",
                    "warning",
                    "下一章上下文超过预算",
                    "上下文压缩后仍超预算，应缩小窗口或补充摘要。",
                    [chapter_id],
                    [("context", "compression", compression)],
                    "inspect_context",
                    {"chapter_id": chapter_id},
                )
            )
        return findings

    def _timeline_findings(self) -> list[RuntimeDiagnosticFindingV1]:
        from tools.truth_manager import TruthFilesManager

        state = TruthFilesManager(self.project_root, self.novel_id).load_runtime_state()
        seen: set[str] = set()
        duplicates: set[str] = set()
        for event in state.timeline:
            if event.id in seen:
                duplicates.add(event.id)
            seen.add(event.id)
        if not duplicates:
            return []
        return [
            self._finding(
                "timeline_identity_conflict",
                "error",
                "时间线存在重复事件 ID",
                "重复 ID 会让后续 delta 无法稳定定位事件。",
                sorted(duplicates),
                [("runtime_state", "duplicate_event_ids", sorted(duplicates))],
                "open_continuity",
                {},
            )
        ]

    def _skill_findings(self) -> list[RuntimeDiagnosticFindingV1]:
        from tools.runtime_skills import RuntimeSkillResolver

        diagnostics = RuntimeSkillResolver(self.project_root).diagnose().get("diagnostics", [])
        if not diagnostics:
            return []
        return [
            self._finding(
                "runtime_skill_conflict",
                "error",
                "Runtime Skill 配置存在冲突",
                "Skill manifest、依赖或冲突诊断未通过。",
                [str(item.get("skill_id") or "runtime") for item in diagnostics],
                [
                    (
                        "runtime_skills",
                        "diagnostic_codes",
                        [item.get("code") for item in diagnostics],
                    )
                ],
                "open_runtime_skills",
                {},
            )
        ]

    def _finding(
        self,
        code: str,
        severity: str,
        summary: str,
        explanation: str,
        affected: list[str],
        evidence: list[tuple[str, str, Any]],
        action: str,
        params: dict[str, Any],
    ) -> RuntimeDiagnosticFindingV1:
        identity = self._hash([code, affected, evidence])
        return RuntimeDiagnosticFindingV1(
            finding_id=f"finding_{identity.split(':', 1)[-1][:16]}",
            code=code,
            severity=severity,  # type: ignore[arg-type]
            summary=summary,
            explanation=explanation,
            affected_items=tuple(affected),
            evidence=tuple(
                DiagnosticEvidenceV1(source=source, item=item, value=value)
                for source, item, value in evidence
            ),
            action=DiagnosticActionV1(label=summary, action=action, params=params),
        )

    @staticmethod
    def _hash(payload: Any) -> str:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @staticmethod
    def _date(value: Any) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    @staticmethod
    def _chapter_number(value: str) -> int:
        digits = "".join(character for character in str(value) if character.isdigit())
        return int(digits) if digits else 0
