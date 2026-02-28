"""Intent classification models for Director.

定义用户意图分类和 Director 响应格式。
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

try:
    from tools.models.workflow import WorkflowState
except ImportError:  # pragma: no cover
    from models.workflow import WorkflowState


class TaskIntent(str, Enum):
    """用户任务意图分类。

    每个意图对应一类工作流或操作。
    """

    UNKNOWN = "unknown"
    """未识别的意图"""

    # 写作相关
    WRITE_CHAPTER = "write_chapter"
    """写章节：根据大纲生成章节内容"""

    CONTINUE_WRITING = "continue_writing"
    """续写：继续当前章节"""

    # 大纲相关
    OUTLINE_ASSIST = "outline_assist"
    """大纲辅助：创建或修改大纲"""

    OUTLINE_QUERY = "outline_query"
    """大纲查询：查看大纲结构"""

    # 风格相关
    STYLE_COMPOSE = "style_compose"
    """风格合成：合成风格文档"""

    STYLE_ANALYZE = "style_analyze"
    """风格分析：分析文本风格"""

    # 角色相关
    CHARACTER_CREATE = "character_create"
    """创建角色"""

    CHARACTER_MODIFY = "character_modify"
    """修改角色"""

    CHARACTER_QUERY = "character_query"
    """查询角色信息"""

    # 伏笔相关
    FORESHADOW_PLANT = "foreshadow_plant"
    """埋设伏笔"""

    FORESHADOW_RECOVER = "foreshadow_recover"
    """回收伏笔"""

    FORESHADOW_QUERY = "foreshadow_query"
    """查询伏笔状态"""

    # 世界观相关
    LORE_QUERY = "lore_query"
    """世界观查询"""

    WORLD_BUILD = "world_build"
    """世界观构建"""

    # 项目相关
    PROJECT_INIT = "project_init"
    """项目初始化"""

    PROJECT_STATUS = "project_status"
    """项目状态查询"""

    # 通用
    GENERAL_CHAT = "general_chat"
    """普通对话"""

    HELP = "help"
    """帮助请求"""


class IntentConfidence(str, Enum):
    """意图识别置信度级别。"""

    HIGH = "high"
    """高置信度：明确的意图"""

    MEDIUM = "medium"
    """中置信度：需要确认"""

    LOW = "low"
    """低置信度：猜测性匹配"""


class IntentDecision(BaseModel):
    """意图识别结果。

    包含识别出的意图、置信度和相关参数。
    """

    intent: TaskIntent = Field(default=TaskIntent.UNKNOWN, description="识别的意图")
    confidence: IntentConfidence = Field(
        default=IntentConfidence.LOW, description="置信度"
    )
    confidence_score: float = Field(
        default=0.0, ge=0.0, le=1.0, description="置信度分数"
    )

    # 提取的参数
    tool_parameters: Dict[str, Any] = Field(
        default_factory=dict, description="工具参数"
    )
    entity_references: List[str] = Field(
        default_factory=list, description="提及的实体（角色、章节等）"
    )

    # 推理过程
    matched_keywords: List[str] = Field(
        default_factory=list, description="匹配的关键词"
    )
    reasoning: str = Field(default="", description="推理说明")


class SuggestedAction(BaseModel):
    """建议的下一步操作。"""

    action: str = Field(..., description="操作类型")
    label: str = Field(..., description="显示标签")
    description: str = Field(default="", description="操作描述")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="操作参数")


class PhaseOption(BaseModel):
    """阶段可选操作。"""

    option_id: str = Field(..., description="选项ID")
    label: str = Field(..., description="显示标签")
    description: str = Field(default="", description="选项描述")
    next_phase: Optional[str] = Field(default=None, description="选择后进入的阶段")


class DirectorResponse(BaseModel):
    """Director 统一响应格式。

    工作流驱动的 Director 返回的标准化响应。
    """

    # 基础信息
    success: bool = Field(default=True, description="是否成功")
    message: str = Field(default="", description="主要响应消息")
    error: str = Field(default="", description="错误信息（如果有）")

    # 意图与工作流
    detected_intent: TaskIntent = Field(
        default=TaskIntent.UNKNOWN, description="识别的意图"
    )
    detected_workflow: str = Field(default="", description="匹配的工作流ID")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="置信度分数")

    # 工作流状态
    workflow_state: Optional[WorkflowState] = Field(
        default=None, description="工作流状态"
    )
    current_phase: str = Field(default="", description="当前阶段名称")
    current_phase_id: str = Field(default="", description="当前阶段ID")
    phase_progress: float = Field(
        default=0.0, ge=0.0, le=1.0, description="阶段进度 0-1"
    )
    total_phases: int = Field(default=0, description="总阶段数")
    completed_phases: int = Field(default=0, description="已完成阶段数")

    # 执行结果
    tool_used: str = Field(default="", description="使用的工具")
    tool_result: Optional[Dict[str, Any]] = Field(
        default=None, description="工具执行结果"
    )

    # 交互支持
    user_prompt: str = Field(default="", description="向用户展示的提示")
    follow_up_questions: List[str] = Field(default_factory=list, description="后续问题")
    suggested_actions: List[SuggestedAction] = Field(
        default_factory=list, description="建议的下一步操作"
    )

    # 阶段特定选项
    phase_options: List[PhaseOption] = Field(
        default_factory=list, description="当前阶段可选操作"
    )

    # 会话
    session_id: str = Field(default="", description="会话ID")
    session_state: str = Field(default="active", description="会话状态")

    # 元数据
    reasoning: str = Field(default="", description="决策推理过程")
    context_loaded: List[str] = Field(
        default_factory=list, description="已加载的上下文键"
    )

    # 向后兼容：原始决策（用于 Pipeline V2）
    legacy_decision: Optional[Dict[str, Any]] = Field(
        default=None, description="原始 DirectorDecision 格式（向后兼容）"
    )

    def is_workflow_active(self) -> bool:
        """检查是否有活跃的工作流。"""
        return self.workflow_state is not None and self.workflow_state.is_active()

    def is_complete(self) -> bool:
        """检查工作流是否完成。"""
        return self.workflow_state is not None and self.workflow_state.is_complete()

    def get_progress_percentage(self) -> float:
        """获取进度百分比。"""
        return self.phase_progress * 100

    def to_legacy_format(self) -> Dict[str, Any]:
        """转换为旧的 DirectorDecision 格式。

        用于向后兼容 Pipeline V2。
        """
        if self.legacy_decision:
            return self.legacy_decision

        return {
            "objective": self.message,
            "chapter_id": self.tool_parameters.get("chapter_id", ""),
            "required_agents": self.tool_parameters.get("required_agents", []),
            "context_summary": self.reasoning,
            "notes": self.follow_up_questions,
            "compressed_context": {},
            "style_instructions": "",
            "suggested_strict_lore": False,
            "priority_elements": [],
            "generation_instructions": self.message,
        }

    @property
    def tool_parameters(self) -> Dict[str, Any]:
        """获取工具参数（便捷访问）。"""
        return self.tool_result or {}


class ConversationSession(BaseModel):
    """对话会话。

    存储用户的对话上下文和工作流状态。
    """

    session_id: str = Field(..., description="会话ID")
    novel_id: Optional[str] = Field(default=None, description="当前小说项目ID")

    # 上下文数据
    context_data: Dict[str, Any] = Field(
        default_factory=dict, description="会话上下文数据"
    )

    # 工作流状态
    workflow_context: Dict[str, Any] = Field(
        default_factory=dict, description="工作流上下文"
    )

    # 消息历史（最近N条）
    message_history: List[Dict[str, str]] = Field(
        default_factory=list, description="消息历史"
    )
    max_history: int = Field(default=20, description="最大历史消息数")

    # 元数据
    created_at: str = Field(default="", description="创建时间")
    updated_at: str = Field(default="", description="更新时间")

    def add_message(self, role: str, content: str) -> None:
        """添加消息到历史。"""
        from datetime import datetime

        self.message_history.append(
            {"role": role, "content": content, "timestamp": datetime.now().isoformat()}
        )
        # 限制历史长度
        if len(self.message_history) > self.max_history:
            self.message_history = self.message_history[-self.max_history :]
        self.updated_at = datetime.now().isoformat()

    def get_workflow_state(self) -> Optional[Dict[str, Any]]:
        """获取工作流状态。"""
        return self.workflow_context.get("active_workflow")

    def set_workflow_state(self, state: Dict[str, Any]) -> None:
        """设置工作流状态。"""
        from datetime import datetime

        self.workflow_context["active_workflow"] = state
        self.updated_at = datetime.now().isoformat()

    def clear_workflow_state(self) -> None:
        """清除工作流状态。"""
        if "active_workflow" in self.workflow_context:
            del self.workflow_context["active_workflow"]

    def get_recent_messages(self, count: int = 5) -> List[Dict[str, str]]:
        """获取最近的消息。"""
        return self.message_history[-count:] if self.message_history else []
