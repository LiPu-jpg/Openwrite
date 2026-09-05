"""Revision-bound rolling planning candidates for Goethe."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from models.runtime_diagnostics import RollingPlanCandidateV1


class RollingPlanningError(RuntimeError):
    def __init__(self, message: str, *, code: str = "ROLLING_PLAN_ERROR") -> None:
        super().__init__(message)
        self.code = code


class RollingPlanningService:
    def __init__(self, project_root: Path, novel_id: str) -> None:
        self.project_root = Path(project_root).resolve()
        self.novel_id = str(novel_id)
        self.novel_root = self.project_root / "data" / "novels" / self.novel_id
        self.root = self.novel_root / "data" / "planning" / "rolling_candidates"

    def create(self, *, current_arc: str = "", window_size: int = 5) -> RollingPlanCandidateV1:
        from tools.chapter_memory import ChapterMemoryStore
        from tools.foreshadowing_manager import ForeshadowingDAGManager
        from tools.outline_tree import build_outline_structure
        from tools.review_store import ReviewStore
        from tools.truth_manager import TruthFilesManager

        self._require_current_facts()

        outline = build_outline_structure(self.novel_root)
        state = TruthFilesManager(self.project_root, self.novel_id).load_runtime_state()
        arc = str(current_arc or "arc_001")
        chapters = self._chapters(outline.get("roots", []))
        drafted = [item["id"] for item in chapters if item.get("status") == "drafted"]
        planned = [item["id"] for item in chapters if item.get("status") != "drafted"]
        size = max(1, min(20, int(window_size)))
        memory_store = ChapterMemoryStore(self.project_root, self.novel_id)
        summaries = []
        for chapter_id in drafted[-size:]:
            memory = memory_store.load(chapter_id) or {}
            summary = str(memory.get("summary") or memory.get("observations") or "").strip()
            if summary:
                summaries.append(f"{chapter_id}: {summary}")

        manager = ForeshadowingDAGManager(self.project_root, self.novel_id)
        dag = manager._load_dag()
        resolved = [
            node.id
            for node in dag.nodes.values()
            if dag.status.get(node.id, node.status) == "已收"
        ]
        unresolved = [
            node.id
            for node in dag.nodes.values()
            if dag.status.get(node.id, node.status) in {"埋伏", "待收"}
        ]
        style_drift: list[str] = []
        review_store = ReviewStore(self.project_root, self.novel_id)
        for chapter_id in drafted[-size:]:
            review = review_store.load(chapter_id) or {}
            for issue in review.get("issue_details") or []:
                if str(issue.get("dimension") or "").startswith("style"):
                    style_drift.append(str(issue.get("summary") or issue.get("description") or ""))

        goals = [f"推进未决伏笔 {item}" for item in unresolved[:3]]
        if planned:
            goals.append(f"细化近期章节 {', '.join(planned[:size])}")
        if not goals:
            goals.append("由 Goethe 基于全书方向提出下一弧目标")
        candidate = RollingPlanCandidateV1(
            candidate_id=f"roll_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:8]}",
            novel_id=self.novel_id,
            current_arc=arc,
            created_at=datetime.now(timezone.utc).isoformat(),
            outline_revision=str(outline.get("revision") or ""),
            facts_revision=str(state.revision),
            current_window=tuple(drafted[-size:]),
            next_window=tuple(planned[:size]),
            direction=self._direction(outline),
            arc_summary="\n".join(summaries) or "当前弧尚无可用章节摘要。",
            character_state=tuple(
                f"{name}: {item.state or item.location}"
                for name, item in state.characters.items()
            ),
            relationship_state=tuple(
                f"{item.source} -> {item.target}: {item.status}"
                for item in state.relationships.values()
            ),
            resolved_foreshadowing=tuple(resolved),
            unresolved_foreshadowing=tuple(unresolved),
            style_drift=tuple(item for item in style_drift if item),
            next_arc_goals=tuple(goals),
        )
        self.save(candidate)
        return candidate

    def list(self, *, limit: int = 20) -> list[RollingPlanCandidateV1]:
        if not self.root.is_dir():
            return []
        result = [item for path in self.root.glob("roll_*.json") if (item := self.load(path.stem))]
        result.sort(key=lambda item: item.created_at, reverse=True)
        return result[: max(1, min(100, int(limit)))]

    def load(self, candidate_id: str) -> RollingPlanCandidateV1 | None:
        path = self.path_for(candidate_id)
        if not path.is_file():
            return None
        try:
            return RollingPlanCandidateV1.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def stage_proposal(
        self,
        candidate_id: str,
        proposal: str,
        *,
        candidate_revision: str,
    ) -> RollingPlanCandidateV1:
        from tools.outline_tree import build_outline_structure
        from tools.story_planning import StoryPlanningStore
        from tools.truth_manager import TruthFilesManager

        self._require_current_facts()

        candidate = self.load(candidate_id)
        if candidate is None:
            raise RollingPlanningError("滚动规划候选不存在", code="CANDIDATE_NOT_FOUND")
        if candidate_revision != self.revision(candidate):
            raise RollingPlanningError("滚动规划候选已变化", code="STALE_CANDIDATE")
        current_outline = str(build_outline_structure(self.novel_root).get("revision") or "")
        current_facts = str(
            TruthFilesManager(self.project_root, self.novel_id).load_runtime_state().revision
        )
        if (
            current_outline != candidate.outline_revision
            or current_facts != candidate.facts_revision
        ):
            candidate.state = "stale"
            self.save(candidate)
            raise RollingPlanningError(
                "大纲或事实 revision 已变化，请重新生成候选",
                code="STALE_CANDIDATE_INPUT",
            )
        text = str(proposal or "").strip()
        if not text:
            raise RollingPlanningError("Goethe 提案为空", code="EMPTY_PROPOSAL")
        StoryPlanningStore(self.project_root, self.novel_id).save_outline_draft(
            text,
            mode="rolling_candidate",
        )
        candidate.state = "proposed"
        candidate.proposal_revision = self._hash(text)
        self.save(candidate)
        return candidate

    def _require_current_facts(self) -> None:
        from tools.manuscript_acceptance import (
            ManuscriptAcceptanceError,
            ManuscriptAcceptanceService,
        )

        try:
            ManuscriptAcceptanceService(
                self.project_root, self.novel_id
            ).require_current("ch_999999")
        except ManuscriptAcceptanceError as exc:
            raise RollingPlanningError(str(exc), code=exc.code) from exc

    def _proposal_text(self, candidate: RollingPlanCandidateV1) -> str:
        if not candidate.proposal_revision:
            return ""
        from tools.story_planning import StoryPlanningStore

        draft_path = StoryPlanningStore(
            self.project_root, self.novel_id
        ).outline_draft_path
        if not draft_path.is_file():
            return ""
        text = draft_path.read_text(encoding="utf-8")
        return text if self._hash(text) == candidate.proposal_revision else ""

    def delete(self, candidate_id: str, *, revision: str) -> bool:
        """删除滚动规划候选（revision 门控）。"""
        candidate = self.load(candidate_id)
        if candidate is None:
            raise RollingPlanningError("滚动规划候选不存在", code="CANDIDATE_NOT_FOUND")
        if revision and revision != self.revision(candidate):
            raise RollingPlanningError("滚动规划候选已变化", code="STALE_CANDIDATE")
        path = self.path_for(candidate_id)
        if path.exists():
            path.unlink()
        return True

    def apply_proposal(self, candidate_id: str, *, revision: str) -> dict[str, Any]:
        """把已暂存草案“接”进正式大纲（只追加不覆盖）。

        解析草案里的第 N 章（N 大于当前大纲最大章号且不与现有章冲突），
        以规范 markdown 块追加到大纲末尾；返回 added / skipped 清单。
        """
        from tools.outline_tree import build_outline_structure

        candidate = self.load(candidate_id)
        if candidate is None:
            raise RollingPlanningError("滚动规划候选不存在", code="CANDIDATE_NOT_FOUND")
        if revision and revision != self.revision(candidate):
            raise RollingPlanningError("滚动规划候选已变化", code="STALE_CANDIDATE")
        proposal = self._proposal_text(candidate)
        if not proposal:
            raise RollingPlanningError("该候选还没有已暂存草案（先 stage）", code="EMPTY_PROPOSAL")

        structure = build_outline_structure(self.novel_root)
        existing: set[str] = set()
        pending: list[dict[str, Any]] = list(structure.get("roots") or [])
        while pending:
            node = pending.pop()
            if node.get("kind") == "chapter":
                existing.add(str(node.get("id") or ""))
            pending.extend(reversed(node.get("children") or []))

        added: list[dict[str, Any]] = []
        skipped: list[str] = []
        current: dict[str, Any] | None = None
        for raw in proposal.splitlines():
            match = re.match(r"^#{1,6}\s*第\s*(\d+)\s*章[：:]\s*(.*)$", raw.strip())
            if match is not None:
                if current is not None and current["number"] is not None and current["number"] not in existing:
                    added.append(current)
                elif current is not None:
                    skipped.append(f"ch_{int(current['number']):03d}（已存在/冲突）")
                chapter_number = int(match.group(1))
                chapter_id = f"ch_{chapter_number:03d}"
                if chapter_id in existing:
                    current = None
                    skipped.append(f"{chapter_id}（已存在/冲突）")
                    continue
                current = {
                    "id": chapter_id,
                    "number": chapter_number,
                    "title": f"第{match.group(1)}章：{match.group(2).strip()}",
                    "summary": "",
                }
                continue
            if current is not None:
                line = raw.strip()
                if line != "" and not line.startswith(">") and not line.startswith("---"):
                    if len(current["summary"]) < 240:
                        current["summary"] += ("" if current["summary"] == "" else " ") + line
        if current is not None:
            if current["id"] not in existing:
                added.append(current)
            else:
                skipped.append(current["id"])

        if not added:
            return {
                "applied": False,
                "added": [],
                "skipped": skipped,
                "message": "没有可追加的不冲突章节（草案章节均已存在或小于等于当前进度）",
            }

        blocks = [f"#### {item['title']}\n\n{item['summary'] or ''}".rstrip() for item in added]
        outline_path = self.novel_root / "src" / "outline.md"
        content = outline_path.read_text(encoding="utf-8")
        if not content.endswith("\n"):
            content += "\n"
        content = content + "\n" + "\n\n".join(blocks) + "\n"
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=outline_path.parent,
            prefix=".outline-apply.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        temporary.replace(outline_path)

        return {
            "applied": True,
            "added": [
                {"id": item["id"], "title": item["title"]} for item in added
            ],
            "skipped": skipped,
            "message": f"已追加 {len(added)} 章到正式大纲（{', '.join(item['title'] for item in added[:6])}）",
        }

    def payload(self, candidate: RollingPlanCandidateV1) -> dict[str, Any]:
        result = candidate.model_dump(mode="json")
        result["revision"] = self.revision(candidate)
        result["goethe_brief"] = self.goethe_brief(candidate)
        # Attach the staged proposal body so viewers can render the draft
        # without re-reading files. The draft lives in the shared outline draft
        # slot; only attach when its hash still matches the candidate revision.
        if candidate.proposal_revision:
            try:
                from tools.story_planning import StoryPlanningStore

                draft_path = StoryPlanningStore(
                    self.project_root, self.novel_id
                ).outline_draft_path
                text = (
                    draft_path.read_text(encoding="utf-8")
                    if draft_path.is_file()
                    else ""
                )
                if text and self._hash(text) == candidate.proposal_revision:
                    result["proposal"] = text
            except Exception:
                pass
        return result

    def goethe_brief(self, candidate: RollingPlanCandidateV1) -> str:
        return (
            f"当前弧: {candidate.current_arc}\n"
            f"全书方向: {candidate.direction}\n"
            f"已写窗口: {', '.join(candidate.current_window) or '无'}\n"
            f"待规划窗口: {', '.join(candidate.next_window) or '已耗尽'}\n"
            f"当前弧摘要:\n{candidate.arc_summary}\n"
            f"未决伏笔: {', '.join(candidate.unresolved_foreshadowing) or '无'}\n"
            f"下一弧候选目标: {'; '.join(candidate.next_arc_goals)}\n"
            "请输出完整 Markdown 大纲草案。该草案只进入待确认区，不直接覆盖 canonical 大纲。"
        )

    def save(self, candidate: RollingPlanCandidateV1) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.path_for(candidate.candidate_id)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.root,
            prefix=f".{candidate.candidate_id}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(candidate.model_dump_json(indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
            temporary = Path(handle.name)
        temporary.replace(target)
        return target

    def revision(self, candidate: RollingPlanCandidateV1) -> str:
        return self._hash(candidate.model_dump(mode="json"))

    def path_for(self, candidate_id: str) -> Path:
        clean = str(candidate_id or "")
        if not clean.startswith("roll_") or any(part in clean for part in ("/", "\\", "..")):
            raise RollingPlanningError("无效滚动规划候选 ID", code="INVALID_CANDIDATE_ID")
        return self.root / f"{clean}.json"

    @staticmethod
    def _chapters(roots: Any) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []

        def visit(nodes: Any) -> None:
            if not isinstance(nodes, list):
                return
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                if node.get("kind") == "chapter":
                    result.append(node)
                visit(node.get("children"))

        visit(roots)
        return result

    @staticmethod
    def _direction(outline: dict[str, Any]) -> str:
        roots = outline.get("roots") if isinstance(outline, dict) else []
        titles = [str(item.get("title") or "") for item in roots if isinstance(item, dict)]
        return " / ".join(item for item in titles if item) or "尚未建立全书方向"

    @staticmethod
    def _hash(payload: Any) -> str:
        encoded = (
            payload
            if isinstance(payload, str)
            else json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        )
        return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def rolling_plan_action(
    project_root: Path,
    novel_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    service = RollingPlanningService(project_root, novel_id)
    action = str(payload.get("action") or "list")
    if action == "list":
        candidates = service.list(limit=int(payload.get("limit") or 20))
        return {"candidates": [service.payload(item) for item in candidates]}
    if action == "create":
        return service.payload(
            service.create(
                current_arc=str(payload.get("current_arc") or ""),
                window_size=int(payload.get("window_size") or 5),
            )
        )
    candidate_id = str(payload.get("candidate_id") or "")
    if action == "get":
        candidate = service.load(candidate_id)
        if candidate is None:
            raise RollingPlanningError("滚动规划候选不存在", code="CANDIDATE_NOT_FOUND")
        return service.payload(candidate)
    if action == "stage":
        return service.payload(
            service.stage_proposal(
                candidate_id,
                str(payload.get("proposal") or ""),
                candidate_revision=str(payload.get("revision") or ""),
            )
        )
    if action == "delete":
        service.delete(candidate_id, revision=str(payload.get("revision") or ""))
        return {"ok": True, "deleted": candidate_id}
    if action == "apply":
        return service.apply_proposal(
            candidate_id, revision=str(payload.get("revision") or "")
        )
    raise RollingPlanningError("未知滚动规划操作", code="INVALID_ROLLING_ACTION")
