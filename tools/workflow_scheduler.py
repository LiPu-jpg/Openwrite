"""写作流程调度器（OpenCode Skill 版）

管理完整的写作流程状态，通过文件驱动协调各阶段：
  调度器(上下文) → 写作 → 审查 → 用户确认 → 风格润色 → 压缩归档

在 OpenCode Skill 架构下，Agent 类不复存在。
本调度器只负责：
  1. 管理流程状态（当前阶段、中间结果）
  2. 持久化到 YAML 文件（支持跨会话恢复）
  3. 提供阶段推进接口

实际的 LLM 调用由 OpenCode Agent 根据 SKILL.md 指令执行。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


# ── 数据结构 ────────────────────────────────────────────────────

STAGE_NAMES = [
    "context_assembly",  # 1. 组装上下文
    "writing",           # 2. 生成草稿
    "review",            # 3. 审查
    "user_confirm",      # 4. 用户确认
    "styling",           # 5. 风格润色
    "compression",       # 6. 压缩归档
]


@dataclass
class StageRecord:
    """阶段执行记录"""
    name: str
    status: str = "pending"      # pending / running / completed / failed / skipped
    started_at: str = ""
    completed_at: str = ""
    message: str = ""
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "message": self.message,
            "data": self.data,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "StageRecord":
        return cls(
            name=d.get("name", ""),
            status=d.get("status", "pending"),
            started_at=d.get("started_at", ""),
            completed_at=d.get("completed_at", ""),
            message=d.get("message", ""),
            data=d.get("data", {}),
        )


@dataclass
class WorkflowState:
    """工作流完整状态（可持久化）"""
    novel_id: str
    chapter_id: str
    current_stage: str = "context_assembly"
    draft_path: str = ""
    polished_path: str = ""
    review_passed: bool = True
    review_errors: List[str] = field(default_factory=list)
    review_warnings: List[str] = field(default_factory=list)
    user_approved: Optional[bool] = None
    stages: List[StageRecord] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "novel_id": self.novel_id,
            "chapter_id": self.chapter_id,
            "current_stage": self.current_stage,
            "draft_path": self.draft_path,
            "polished_path": self.polished_path,
            "review_passed": self.review_passed,
            "review_errors": self.review_errors,
            "review_warnings": self.review_warnings,
            "user_approved": self.user_approved,
            "stages": [s.to_dict() for s in self.stages],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "WorkflowState":
        return cls(
            novel_id=d.get("novel_id", ""),
            chapter_id=d.get("chapter_id", ""),
            current_stage=d.get("current_stage", "context_assembly"),
            draft_path=d.get("draft_path", ""),
            polished_path=d.get("polished_path", ""),
            review_passed=d.get("review_passed", True),
            review_errors=d.get("review_errors", []),
            review_warnings=d.get("review_warnings", []),
            user_approved=d.get("user_approved"),
            stages=[StageRecord.from_dict(s) for s in d.get("stages", [])],
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
            error=d.get("error", ""),
        )


# ── 调度器 ──────────────────────────────────────────────────────

class WorkflowScheduler:
    """写作流程调度器（状态管理器版）

    不再直接调用 Agent，而是：
    - 管理流程状态并持久化到 YAML
    - 提供阶段推进接口
    - 由 OpenCode Agent 按 SKILL.md 指令逐阶段驱动

    Usage:
        scheduler = WorkflowScheduler(
            project_root=Path("/path/to/project"),
            novel_id="my_novel",
        )

        # 创建新工作流
        state = scheduler.create_workflow("ch_001")

        # 阶段 1: 上下文组装（由 Agent 调用 context_builder 完成后回报）
        scheduler.complete_stage(state, "context_assembly", message="上下文已组装")

        # 阶段 2: 写作完成后
        scheduler.complete_stage(state, "writing", data={"draft_path": "..."})

        # 恢复已有工作流
        state = scheduler.load_workflow("ch_001")
    """

    def __init__(self, project_root: Path, novel_id: str):
        self.project_root = Path(project_root).resolve()
        self.novel_id = novel_id
        self.workflow_dir = (
            self.project_root / "data" / "novels" / novel_id / "data" / "workflows"
        )
        self.workflow_dir.mkdir(parents=True, exist_ok=True)

    # ── 工作流生命周期 ────────────────────────────────────────

    def create_workflow(self, chapter_id: str) -> WorkflowState:
        """创建新的章节写作工作流"""
        now = datetime.now().isoformat()
        state = WorkflowState(
            novel_id=self.novel_id,
            chapter_id=chapter_id,
            current_stage="context_assembly",
            stages=[StageRecord(name=n) for n in STAGE_NAMES],
            created_at=now,
            updated_at=now,
        )
        self._save_state(state)
        return state

    def load_workflow(self, chapter_id: str) -> Optional[WorkflowState]:
        """加载已有工作流（跨会话恢复）"""
        path = self._state_path(chapter_id)
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            return WorkflowState.from_dict(data)
        except Exception:
            return None

    def load_or_create(self, chapter_id: str) -> WorkflowState:
        """加载或创建工作流"""
        state = self.load_workflow(chapter_id)
        if state is None:
            state = self.create_workflow(chapter_id)
        return state

    # ── 阶段推进 ──────────────────────────────────────────────

    def start_stage(self, state: WorkflowState, stage_name: str) -> WorkflowState:
        """标记阶段开始"""
        stage = self._find_stage(state, stage_name)
        if stage:
            stage.status = "running"
            stage.started_at = datetime.now().isoformat()
            stage.completed_at = ""
            stage.message = ""
            state.current_stage = stage_name
            state.error = ""
            state.updated_at = datetime.now().isoformat()
            self._save_state(state)
        return state

    def complete_stage(
        self,
        state: WorkflowState,
        stage_name: str,
        message: str = "",
        data: Optional[Dict[str, Any]] = None,
    ) -> WorkflowState:
        """标记阶段完成并推进"""
        stage = self._find_stage(state, stage_name)
        if stage:
            stage.status = "completed"
            stage.completed_at = datetime.now().isoformat()
            stage.message = message
            if data:
                stage.data = data

            # 同步关键数据到顶层
            if stage_name == "writing" and data:
                state.draft_path = data.get("draft_path", state.draft_path)
            elif stage_name == "review" and data:
                state.review_passed = data.get("passed", True)
                state.review_errors = data.get("errors", [])
                state.review_warnings = data.get("warnings", [])
            elif stage_name == "user_confirm" and data:
                state.user_approved = data.get("approved", False)
            elif stage_name == "styling" and data:
                state.polished_path = data.get("polished_path", state.polished_path)

            # 推进到下一阶段
            next_stage = self._next_stage_name(stage_name)
            if next_stage:
                state.current_stage = next_stage

            state.updated_at = datetime.now().isoformat()
            self._save_state(state)
        return state

    def fail_stage(
        self, state: WorkflowState, stage_name: str, error: str
    ) -> WorkflowState:
        """标记阶段失败"""
        stage = self._find_stage(state, stage_name)
        if stage:
            stage.status = "failed"
            stage.completed_at = datetime.now().isoformat()
            stage.message = error
            state.error = f"{stage_name}: {error}"
            state.updated_at = datetime.now().isoformat()
            self._save_state(state)
        return state

    def skip_stage(
        self, state: WorkflowState, stage_name: str, reason: str = ""
    ) -> WorkflowState:
        """跳过阶段"""
        stage = self._find_stage(state, stage_name)
        if stage:
            stage.status = "skipped"
            stage.message = reason or "跳过"
            next_name = self._next_stage_name(stage_name)
            if next_name:
                state.current_stage = next_name
            state.updated_at = datetime.now().isoformat()
            self._save_state(state)
        return state

    # ── 查询 ──────────────────────────────────────────────────

    def get_status_summary(self, state: WorkflowState) -> str:
        """生成可读的状态摘要"""
        lines = [
            f"# 工作流: {state.novel_id} / {state.chapter_id}",
            f"当前阶段: {state.current_stage}",
            f"创建时间: {state.created_at}",
            "",
            "## 阶段进度",
        ]
        for s in state.stages:
            icon = {
                "pending": "⬜",
                "running": "🔄",
                "completed": "✅",
                "failed": "❌",
                "skipped": "⏭️",
            }.get(s.status, "?")
            line = f"  {icon} {s.name}"
            if s.message:
                line += f" — {s.message}"
            lines.append(line)

        if state.error:
            lines.append(f"\n⚠️ 错误: {state.error}")

        return "\n".join(lines)

    def is_complete(self, state: WorkflowState) -> bool:
        """检查工作流是否完成"""
        return all(
            s.status in ("completed", "skipped") for s in state.stages
        )

    def is_waiting_for_user(self, state: WorkflowState) -> bool:
        """检查是否在等待用户确认"""
        return state.current_stage == "user_confirm"

    def list_active_workflows(self) -> List[WorkflowState]:
        """列出所有未完成的工作流"""
        results = []
        if not self.workflow_dir.exists():
            return results
        for path in sorted(self.workflow_dir.glob("wf_*.yaml")):
            state = self._load_from_path(path)
            if state and not self.is_complete(state):
                results.append(state)
        return results

    # ── 内部方法 ──────────────────────────────────────────────

    def _find_stage(
        self, state: WorkflowState, stage_name: str
    ) -> Optional[StageRecord]:
        for s in state.stages:
            if s.name == stage_name:
                return s
        return None

    def _next_stage_name(self, current: str) -> Optional[str]:
        try:
            idx = STAGE_NAMES.index(current)
            if idx + 1 < len(STAGE_NAMES):
                return STAGE_NAMES[idx + 1]
        except ValueError:
            pass
        return None

    def _state_path(self, chapter_id: str) -> Path:
        return self.workflow_dir / f"wf_{chapter_id}.yaml"

    def _save_state(self, state: WorkflowState) -> None:
        path = self._state_path(state.chapter_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            yaml.dump(
                state.to_dict(),
                f,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )

    def _load_from_path(self, path: Path) -> Optional[WorkflowState]:
        try:
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            return WorkflowState.from_dict(data)
        except Exception:
            return None
