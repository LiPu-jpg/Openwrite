"""Workflow definition models.

工作流是完成特定任务的**结构化步骤序列**。每个工作流定义：
- 触发条件：什么情况下启动此工作流
- 阶段序列：需要经过哪些步骤
- 工具配置：每个阶段使用哪些工具
- 上下文需求：需要加载什么数据
- 退出条件：何时工作流完成
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class WorkflowStatus(str, Enum):
    """工作流状态。"""

    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowPhase(BaseModel):
    """工作流阶段。

    每个阶段定义：
    - 可用/必需的工具
    - 需要加载的上下文
    - 向用户展示的提示和问题
    - 阶段转换规则
    """

    phase_id: str = Field(..., description="阶段ID")
    name: str = Field(..., description="阶段名称")
    description: str = Field(default="", description="阶段描述")

    # 工具配置
    available_tools: List[str] = Field(
        default_factory=list,
        description="可用工具列表（可选调用）",
    )
    required_tools: List[str] = Field(
        default_factory=list,
        description="必需工具列表（必须调用）",
    )

    # 上下文需求
    context_keys: List[str] = Field(
        default_factory=list,
        description="需要加载的上下文键",
    )

    # 用户交互
    user_prompt: str = Field(
        default="",
        description="向用户展示的提示",
    )
    questions: List[str] = Field(
        default_factory=list,
        description="需要用户回答的问题",
    )

    # 阶段转换
    auto_advance: bool = Field(
        default=False,
        description="是否自动进入下一阶段",
    )
    next_phase: Optional[str] = Field(
        default=None,
        description="下一阶段ID（默认顺序）",
    )
    conditions: Dict[str, str] = Field(
        default_factory=dict,
        description="条件转换规则 {condition: target_phase}",
    )

    # 选项配置
    options: List[Dict[str, str]] = Field(
        default_factory=list,
        description="阶段可选操作",
    )


class WorkflowDefinition(BaseModel):
    """工作流定义。

    工作流是完成特定任务的预定义步骤序列。
    支持从 YAML 文件加载，可扩展。
    """

    workflow_id: str = Field(..., description="工作流ID")
    name: str = Field(..., description="工作流名称")
    description: str = Field(default="", description="工作流描述")
    category: str = Field(default="general", description="工作流类别")

    # 触发配置
    trigger_intents: List[str] = Field(
        default_factory=list,
        description="触发意图列表",
    )
    trigger_keywords: List[str] = Field(
        default_factory=list,
        description="触发关键词",
    )
    priority: int = Field(
        default=0,
        description="优先级（数值越高优先级越高）",
    )

    # 阶段定义
    phases: List[WorkflowPhase] = Field(
        default_factory=list,
        description="阶段列表",
    )
    entry_phase: str = Field(
        default="",
        description="入口阶段ID",
    )

    # 前置条件
    requires_novel_id: bool = Field(
        default=True,
        description="是否需要小说ID",
    )
    requires_outline: bool = Field(
        default=False,
        description="是否需要大纲存在",
    )
    requires_characters: bool = Field(
        default=False,
        description="是否需要角色数据",
    )

    # 元数据
    version: str = Field(default="1.0", description="版本号")
    author: str = Field(default="system", description="作者")

    def get_phase(self, phase_id: str) -> Optional[WorkflowPhase]:
        """获取指定阶段。"""
        for phase in self.phases:
            if phase.phase_id == phase_id:
                return phase
        return None

    def get_entry_phase(self) -> Optional[WorkflowPhase]:
        """获取入口阶段。"""
        entry_id = self.entry_phase or (self.phases[0].phase_id if self.phases else "")
        return self.get_phase(entry_id) if entry_id else None

    def get_phase_index(self, phase_id: str) -> int:
        """获取阶段索引。"""
        for i, phase in enumerate(self.phases):
            if phase.phase_id == phase_id:
                return i
        return -1


class WorkflowState(BaseModel):
    """工作流运行时状态。

    追踪用户在某个工作流中的当前位置和历史。
    """

    workflow_id: str = Field(..., description="当前工作流ID")
    current_phase: str = Field(..., description="当前阶段ID")
    phase_history: List[str] = Field(
        default_factory=list,
        description="已完成的阶段列表",
    )

    # 阶段数据
    phase_data: Dict[str, Any] = Field(
        default_factory=dict,
        description="各阶段积累的数据",
    )

    # 状态
    status: WorkflowStatus = Field(
        default=WorkflowStatus.ACTIVE,
        description="工作流状态",
    )
    error_message: str = Field(
        default="",
        description="错误信息（如果失败）",
    )

    # 时间戳
    started_at: str = Field(
        default_factory=lambda: datetime.now().isoformat(),
        description="启动时间",
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now().isoformat(),
        description="更新时间",
    )

    def advance_to(self, phase_id: str) -> None:
        """进入下一阶段。"""
        if self.current_phase:
            self.phase_history.append(self.current_phase)
        self.current_phase = phase_id
        self.updated_at = datetime.now().isoformat()

    def complete(self) -> None:
        """标记工作流完成。"""
        if self.current_phase:
            self.phase_history.append(self.current_phase)
        self.status = WorkflowStatus.COMPLETED
        self.updated_at = datetime.now().isoformat()

    def fail(self, error: str) -> None:
        """标记工作流失败。"""
        self.status = WorkflowStatus.FAILED
        self.error_message = error
        self.updated_at = datetime.now().isoformat()

    def pause(self) -> None:
        """暂停工作流。"""
        self.status = WorkflowStatus.PAUSED
        self.updated_at = datetime.now().isoformat()

    def resume(self) -> None:
        """恢复工作流。"""
        self.status = WorkflowStatus.ACTIVE
        self.updated_at = datetime.now().isoformat()

    def cancel(self) -> None:
        """取消工作流。"""
        self.status = WorkflowStatus.CANCELLED
        self.updated_at = datetime.now().isoformat()

    def is_complete(self) -> bool:
        """检查是否完成。"""
        return self.status == WorkflowStatus.COMPLETED

    def is_active(self) -> bool:
        """检查是否活跃。"""
        return self.status == WorkflowStatus.ACTIVE

    def set_phase_data(self, key: str, value: Any) -> None:
        """设置当前阶段数据。"""
        if self.current_phase not in self.phase_data:
            self.phase_data[self.current_phase] = {}
        self.phase_data[self.current_phase][key] = value
        self.updated_at = datetime.now().isoformat()

    def get_phase_data(self, key: str, default: Any = None) -> Any:
        """获取当前阶段数据。"""
        phase_data = self.phase_data.get(self.current_phase, {})
        return phase_data.get(key, default)

    def get_all_phase_data(self, phase_id: Optional[str] = None) -> Dict[str, Any]:
        """获取指定阶段或所有阶段数据。"""
        if phase_id:
            return self.phase_data.get(phase_id, {})
        return self.phase_data


class WorkflowSessionContext(BaseModel):
    """工作流会话上下文。

    存储在会话中的工作流相关上下文。
    """

    active_workflow: Optional[WorkflowState] = Field(
        default=None,
        description="当前活跃的工作流状态",
    )
    workflow_history: List[WorkflowState] = Field(
        default_factory=list,
        description="已完成的工作流历史",
    )

    def start_workflow(self, workflow_id: str, entry_phase: str) -> WorkflowState:
        """启动新工作流。"""
        # 如果有活跃工作流，移入历史
        if self.active_workflow and self.active_workflow.is_active():
            self.active_workflow.pause()
            self.workflow_history.append(self.active_workflow)

        state = WorkflowState(
            workflow_id=workflow_id,
            current_phase=entry_phase,
        )
        self.active_workflow = state
        return state

    def get_active_workflow(self) -> Optional[WorkflowState]:
        """获取当前活跃的工作流。"""
        if self.active_workflow and self.active_workflow.is_active():
            return self.active_workflow
        return None

    def complete_active_workflow(self) -> Optional[WorkflowState]:
        """完成当前活跃工作流。"""
        if self.active_workflow:
            self.active_workflow.complete()
            completed = self.active_workflow
            self.workflow_history.append(completed)
            self.active_workflow = None
            return completed
        return None
