"""Director agent — orchestrates sub-agents and compresses context.

The Director is the 'brain' of the simulation pipeline:
  1. Analyzes the chapter objective and available context
  2. Compresses context to fit within token budgets
  3. Routes sub-agents based on chapter needs
  4. Provides style-aware instructions when stylist is enabled

支持 LLM 模式（opt-in）：通过 llm_client + router 接入真实 LLM 进行路由决策。
不传入 llm_client 时保持原有规则模拟行为。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from tools.llm.client import LLMClient
    from tools.llm.router import ModelRouter

logger = logging.getLogger(__name__)


@dataclass
class DirectorDecision:
    """Decision output produced by Director."""

    objective: str
    chapter_id: str
    required_agents: List[str]
    context_summary: str
    notes: List[str]
    compressed_context: Dict[str, str] = field(default_factory=dict)
    style_instructions: str = ""
    suggested_strict_lore: bool = False
    priority_elements: List[str] = field(default_factory=list)
    generation_instructions: str = ""


class DirectorAgent:
    """Coordinates sub-agents and controls workflow routing.

    Args:
        llm_client: 可选 LLM 客户端，传入时启用 LLM 路由决策
        router: 可选模型路由器，与 llm_client 配合使用
    """

    # Context budget: max chars per section for compressed context
    BUDGET_OUTLINE: int = 300
    BUDGET_CHARACTERS: int = 400
    BUDGET_FORESHADOWING: int = 250
    BUDGET_WORLD: int = 200
    BUDGET_SCENES: int = 150
    BUDGET_STYLE: int = 300

    def __init__(
        self,
        llm_client: Optional["LLMClient"] = None,
        router: Optional["ModelRouter"] = None,
        persistence: Optional[Any] = None,
    ):
        self._llm_client = llm_client
        self._router = router
        self._sessions: Dict[str, Any] = {}  # 会话存储（内存缓存）
        self._persistence = persistence
        if self._persistence is None:
            from tools.session_persistence import SessionPersistence
            self._persistence = SessionPersistence()
        self._persistence = persistence  # 持久化管理器

    def plan(
        self,
        objective: str,
        context: Dict[str, str],
        chapter_id: str = "",
        use_stylist: bool = False,
        style_summary: Optional[str] = None,
    ) -> DirectorDecision:
        """Analyze context and produce a routing decision.

        当 llm_client 存在时，使用 LLM 进行路由决策；
        否则使用规则引擎（原有行为）。

        Args:
            objective: The chapter's writing goal.
            context: Raw context dict from simulator (outline, characters, etc.)
            chapter_id: Current chapter identifier.
            use_stylist: Whether the stylist agent should be included.
            style_summary: Optional composed style summary text.
        """
        # --- Context compression (always rule-based) ---
        compressed = self._compress_context(context)

        # --- LLM branch ---
        if self._llm_client and self._router:
            return self._plan_with_llm(
                objective, context, chapter_id, use_stylist,
                style_summary, compressed,
            )

        # --- Rule-based branch (original behavior) ---
        return self._plan_rule_based(
            objective, context, chapter_id, use_stylist,
            style_summary, compressed,
        )

    def _plan_rule_based(
        self,
        objective: str,
        context: Dict[str, str],
        chapter_id: str,
        use_stylist: bool,
        style_summary: Optional[str],
        compressed: Dict[str, str],
    ) -> DirectorDecision:
        """规则引擎路由决策（原有行为）。"""
        required_agents = ["librarian", "lore_checker"]
        notes: List[str] = []
        priority_elements: List[str] = []



        # --- Analyze objective for routing hints ---
        suggested_strict = self._should_strict_lore(objective, context)
        if suggested_strict:
            notes.append("检测到高风险章节内容，建议启用严格逻辑检查")

        # --- Detect priority elements from objective ---
        priority_elements = self._extract_priority_elements(objective, context)
        if priority_elements:
            notes.append(f"本章重点要素: {', '.join(priority_elements)}")

        # --- Stylist routing ---
        style_instructions = ""
        if use_stylist:
            required_agents.append("stylist")
            style_instructions = self._build_style_instructions(style_summary)
            notes.append("文风处理已启用，Stylist 将在逻辑检查通过后执行")
        else:
            notes.append("已按配置跳过 Stylist（文风单独处理）")

        # --- Foreshadowing awareness ---
        foreshadowing_text = context.get("foreshadowing", "")
        if foreshadowing_text and "暂无" not in foreshadowing_text:
            pending_count = foreshadowing_text.count(";") + 1
            notes.append(f"有{pending_count}条待回收伏笔，Librarian 应考虑自然融入")

        # --- Standard rules ---
        notes.append("总纲/卷纲默认只读，本轮仅生成草稿")
        notes.append("逻辑检查未通过时禁止进入文风润色")

        # Build full compressed summary
        summary_parts = [f"目标:{objective}", f"章节:{chapter_id}"]
        for key in ["outline", "characters", "foreshadowing", "scenes", "world"]:
            if key in compressed and compressed[key]:
                summary_parts.append(f"{key}:{compressed[key]}")
        full_summary = "; ".join(summary_parts)

        return DirectorDecision(
            objective=objective,
            chapter_id=chapter_id,
            required_agents=required_agents,
            context_summary=full_summary[:800],
            notes=notes,
            compressed_context=compressed,
            style_instructions=style_instructions,
            suggested_strict_lore=suggested_strict,
            priority_elements=priority_elements,
        )

    def _compress_context(self, context: Dict[str, str]) -> Dict[str, str]:
        """Compress each context section using the ContextCompressor."""
        try:
            from tools.utils.context_compressor import ContextCompressor
        except ImportError:
            from utils.context_compressor import ContextCompressor
        total_budget = (
            self.BUDGET_OUTLINE + self.BUDGET_CHARACTERS + self.BUDGET_FORESHADOWING
            + self.BUDGET_WORLD + self.BUDGET_SCENES + self.BUDGET_STYLE
        )
        compressor = ContextCompressor(budget=total_budget)
        # Only compress the main content sections
        compressible = {
            k: v for k, v in context.items()
            if k in ("outline", "characters", "foreshadowing", "world",
                     "scenes", "cross_chapter", "seed", "summary")
            and v
        }
        if not compressible:
            return {}
        result = compressor.compress(compressible)
        return result.sections

    def _truncate_smart(self, text: str, max_chars: int) -> str:
        """Truncate text intelligently — prefer cutting at sentence boundaries."""
        if len(text) <= max_chars:
            return text

        # Try to cut at a Chinese sentence boundary
        truncated = text[:max_chars]
        # Find last sentence-ending punctuation
        for marker in ["。", "；", "!", "？", "\n"]:
            last_pos = truncated.rfind(marker)
            if last_pos > max_chars * 0.6:
                return truncated[: last_pos + 1]

        # Fall back to hard truncation
        return truncated + "…"

    def _should_strict_lore(self, objective: str, context: Dict[str, str]) -> bool:
        """Heuristic: should this chapter use strict lore checking?"""
        high_risk_keywords = [
            "战斗",
            "死亡",
            "死斗",
            "决斗",
            "突破",
            "晋级",
            "关键",
            "转折",
            "高潮",
            "揭秘",
            "真相",
            "伏笔回收",
            "回收",
            "时间线",
        ]
        combined = objective + " " + context.get("outline", "")
        return any(kw in combined for kw in high_risk_keywords)

    def _extract_priority_elements(
        self, objective: str, context: Dict[str, str]
    ) -> List[str]:
        """Extract key elements that this chapter must address."""
        elements: List[str] = []

        # Check for foreshadowing targets
        foreshadowing = context.get("foreshadowing", "")
        if foreshadowing and "暂无" not in foreshadowing:
            # Extract node IDs from foreshadowing context
            ids = re.findall(r"(\w+)\(权重=(\d+)", foreshadowing)
            high_weight = [nid for nid, w in ids if int(w) >= 7]
            if high_weight:
                elements.append(f"高权重伏笔: {', '.join(high_weight[:3])}")

        # Check for character mentions in objective
        characters = context.get("characters", "")
        if characters and "暂无" not in characters:
            # Extract character names
            names = re.findall(r"(\S+?)\(境界=", characters)
            if names:
                elements.append(f"涉及角色: {', '.join(names[:4])}")

        # Check for scene requirements
        scenes = context.get("scenes", "")
        if scenes and "未标注" not in scenes:
            elements.append(f"场景要求: {scenes}")

        return elements

    def _build_style_instructions(self, style_summary: Optional[str]) -> str:
        """Build style instructions for the Stylist agent."""
        if not style_summary:
            return "使用默认风格规则进行润色（无特定风格文档加载）"

        # Extract key style points from the composed document
        instructions: List[str] = [
            "风格润色指令：",
            "1. 检查并移除AI痕迹（禁用表达清单）",
            "2. 验证叙述者-角色声音融合度",
            "3. 检查段落节奏（短段60%/中段30%/长段10%）",
            "4. 确保吐槽密度符合风格要求",
            "5. 验证现代感用语自然融入",
        ]

        # Add style-specific notes if available
        if "风格DNA" in style_summary or "风格指纹" in style_summary:
            instructions.append("6. 已加载作品风格指纹，按风格DNA维度评分")

        return "\n".join(instructions)

    def _plan_with_llm(
        self,
        objective: str,
        context: Dict[str, str],
        chapter_id: str,
        use_stylist: bool,
        style_summary: Optional[str],
        compressed: Dict[str, str],
    ) -> DirectorDecision:
        """LLM 路由决策 — 调用 LLM 分析章节目标并生成决策。"""
        assert self._llm_client is not None
        assert self._router is not None

        from tools.llm.prompts import PromptBuilder
        from tools.llm.router import TaskType

        # 构建压缩摘要
        summary_parts = [f"目标:{objective}", f"章节:{chapter_id}"]
        for key in ["outline", "characters", "foreshadowing", "scenes", "world"]:
            if key in compressed and compressed[key]:
                summary_parts.append(f"{key}:{compressed[key]}")
        full_summary = "; ".join(summary_parts)

        messages = PromptBuilder.director_plan(
            objective=objective,
            chapter_id=chapter_id,
            context_summary=full_summary[:2000],
            style_summary=style_summary,
        )

        try:
            routes = self._router.get_routes(TaskType.REASONING)
            response = self._llm_client.complete_with_fallback(
                messages=messages, routes=routes,
            )
            return self._parse_llm_decision(
                response.content, objective, chapter_id,
                use_stylist, compressed, full_summary,
                style_summary=style_summary,
            )
        except Exception as e:
            logger.warning("Director LLM 调用失败，回退到规则引擎: %s", e)
            return self._plan_rule_based(
                objective, context, chapter_id, use_stylist,
                style_summary, compressed,
            )

    def _parse_llm_decision(
        self,
        llm_output: str,
        objective: str,
        chapter_id: str,
        use_stylist: bool,
        compressed: Dict[str, str],
        full_summary: str,
        style_summary: Optional[str] = None,
    ) -> DirectorDecision:
        """解析 LLM JSON 输出为 DirectorDecision。"""
        # 提取 JSON 块
        json_match = re.search(r'```json\s*(.+?)\s*```', llm_output, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # 尝试直接解析
            json_str = llm_output.strip()

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("Director LLM 输出 JSON 解析失败，使用默认值")
            data = {}

        required_agents = ["librarian", "lore_checker"]
        if use_stylist:
            required_agents.append("stylist")

        notes = data.get("notes", [])
        gen_instr = data.get("generation_instructions", "")

        # 处理 style_instructions：LLM 输出优先，否则使用规则引擎
        style_instructions = data.get("style_instructions", "")
        if use_stylist and not style_instructions:
            style_instructions = self._build_style_instructions(style_summary)

        return DirectorDecision(
            objective=objective,
            chapter_id=chapter_id,
            required_agents=required_agents,
            context_summary=full_summary[:800],
            notes=notes,
            compressed_context=compressed,
            style_instructions=style_instructions,
            suggested_strict_lore=data.get("strict_lore", False),
            priority_elements=data.get("priority_elements", []),
            generation_instructions=gen_instr,
        )

    # =========================================================================
    # Workflow-Driven Processing (NEW)
    # =========================================================================

    def classify_intent(
        self,
        user_message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> "IntentDecision":
        """识别用户意图。

        Args:
            user_message: 用户消息
            context: 上下文数据

        Returns:
            意图识别结果
        """
        from tools.models.intent import (
            IntentConfidence,
            IntentDecision,
            TaskIntent,
        )

        context = context or {}
        message_lower = user_message.lower()

        # 意图关键词映射
        intent_keywords: Dict[TaskIntent, List[str]] = {
            TaskIntent.WRITE_CHAPTER: [
                "写章节", "生成章节", "写第", "生成第", "续写", "草稿",
                "write chapter", "generate chapter",
            ],
            TaskIntent.OUTLINE_ASSIST: [
                "创建大纲", "新建大纲", "写大纲", "构思大纲", "规划大纲",
                "修改大纲", "调整大纲", "大纲辅助", "大纲帮助",
                "create outline", "modify outline",
            ],
            TaskIntent.OUTLINE_QUERY: [
                "查看大纲", "大纲结构", "大纲内容", "大纲是什么",
                "view outline", "show outline",
            ],
            TaskIntent.STYLE_COMPOSE: [
                "合成风格", "选择风格", "文风设置", "风格合成",
                "compose style", "select style",
            ],
            TaskIntent.STYLE_ANALYZE: [
                "分析风格", "风格分析", "检测风格",
                "analyze style",
            ],
            TaskIntent.CHARACTER_CREATE: [
                "创建角色", "新建角色", "添加角色", "增加角色",
                "create character", "add character",
            ],
            TaskIntent.CHARACTER_MODIFY: [
                "修改角色", "编辑角色", "更新角色",
                "modify character", "edit character",
            ],
            TaskIntent.CHARACTER_QUERY: [
                "查看角色", "角色信息", "角色是什么",
                "view character", "show character",
            ],
            TaskIntent.FORESHADOW_PLANT: [
                "埋设伏笔", "埋伏笔", "设置伏笔",
                "plant foreshadowing",
            ],
            TaskIntent.FORESHADOW_RECOVER: [
                "回收伏笔", "伏笔回收", "揭示伏笔",
                "recover foreshadowing",
            ],
            TaskIntent.FORESHADOW_QUERY: [
                "查看伏笔", "伏笔状态", "伏笔列表",
                "view foreshadowing",
            ],
            TaskIntent.LORE_QUERY: [
                "世界观查询", "查询设定", "查看设定", "设定是什么",
                "query lore", "world info",
            ],
            TaskIntent.PROJECT_INIT: [
                "新建项目", "创建项目", "初始化项目", "开始新项目",
                "create project", "init project",
            ],
            TaskIntent.PROJECT_STATUS: [
                "项目状态", "进度", "统计",
                "project status", "progress",
            ],
            TaskIntent.HELP: [
                "帮助", "怎么用", "如何使用", "help", "how to",
            ],
        }

        # 匹配意图
        best_intent = TaskIntent.UNKNOWN
        best_score = 0
        matched_keywords: List[str] = []

        for intent, keywords in intent_keywords.items():
            score = 0
            intent_matched = []
            for kw in keywords:
                if kw in message_lower:
                    score += 1
                    intent_matched.append(kw)

            if score > best_score:
                best_score = score
                best_intent = intent
                matched_keywords = intent_matched

        # 确定置信度
        if best_score >= 2:
            confidence = IntentConfidence.HIGH
            confidence_score = 0.8 + min(0.2, best_score * 0.05)
        elif best_score == 1:
            confidence = IntentConfidence.MEDIUM
            confidence_score = 0.5
        else:
            confidence = IntentConfidence.LOW
            confidence_score = 0.2
            # 默认为普通对话
            best_intent = TaskIntent.GENERAL_CHAT

        # 提取实体引用
        entity_references = self._extract_entities(user_message)

        return IntentDecision(
            intent=best_intent,
            confidence=confidence,
            confidence_score=confidence_score,
            matched_keywords=matched_keywords,
            entity_references=entity_references,
            reasoning=f"基于关键词匹配识别为 {best_intent.value}",
        )

    def _extract_entities(self, text: str) -> List[str]:
        """从文本中提取实体引用。

        Args:
            text: 输入文本

        Returns:
            实体列表
        """
        entities = []

        # 提取章节引用 (第X章, ch_XXX)
        chapter_patterns = [
            r"第(\\d+)章",
            r"ch_(\\w+)",
            r"chapter\\s*(\\d+)",
        ]
        for pattern in chapter_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            entities.extend([f"chapter:{m}" for m in matches])

        # 提取可能的角色名（简单规则：中文人名）
        name_pattern = r"[\\u4e00-\\u9fa5]{2,4}(?=的|说|想|看|走|来|去|在)"
        names = re.findall(name_pattern, text)
        entities.extend([f"character:{name}" for name in names[:3]])  # 最多3个

        return list(set(entities))

    def detect_workflow(
        self,
        intent: "IntentDecision",
        user_message: str,
        context: Dict[str, Any],
    ) -> Optional["WorkflowDefinition"]:
        """检测最适合的工作流。

        Args:
            intent: 意图识别结果
            user_message: 用户消息
            context: 上下文数据

        Returns:
            匹配的工作流定义，无匹配则返回 None
        """
        from tools.workflow_registry import workflow_registry

        return workflow_registry.match_workflow(
            intent=intent.intent,
            user_message=user_message,
            context=context,
        )

    def get_or_create_workflow_state(
        self,
        session: "ConversationSession",
        workflow: "WorkflowDefinition",
    ) -> "WorkflowState":
        """获取或创建工作流状态。

        Args:
            session: 会话对象
            workflow: 工作流定义

        Returns:
            工作流状态
        """
        from tools.models.workflow import WorkflowState

        # 检查会话中是否已有工作流状态
        existing = session.get_workflow_state()
        if existing and existing.get("workflow_id") == workflow.workflow_id:
            return WorkflowState(**existing)

        # 创建新状态
        entry_phase = workflow.entry_phase or (
            workflow.phases[0].phase_id if workflow.phases else ""
        )
        state = WorkflowState(
            workflow_id=workflow.workflow_id,
            current_phase=entry_phase,
        )
        return state

    def get_current_phase_definition(
        self,
        workflow: "WorkflowDefinition",
        state: "WorkflowState",
    ) -> Optional["WorkflowPhase"]:
        """获取当前阶段定义。

        Args:
            workflow: 工作流定义
            state: 工作流状态

        Returns:
            当前阶段定义
        """
        return workflow.get_phase(state.current_phase)

    def advance_workflow(
        self,
        workflow: "WorkflowDefinition",
        state: "WorkflowState",
        phase_result: Dict[str, Any],
    ) -> Optional[str]:
        """推进工作流到下一阶段。

        Args:
            workflow: 工作流定义
            state: 工作流状态
            phase_result: 当前阶段执行结果

        Returns:
            下一阶段ID，如果工作流完成则返回 None
        """
        current_phase = self.get_current_phase_definition(workflow, state)
        if not current_phase:
            return None

        # 保存阶段数据
        state.set_phase_data("result", phase_result)

        # 检查转换条件
        next_phase_id = current_phase.next_phase

        # 条件转换
        for condition, target_phase in current_phase.conditions.items():
            if self._evaluate_phase_condition(condition, phase_result):
                next_phase_id = target_phase
                break

        if next_phase_id:
            state.advance_to(next_phase_id)
            return next_phase_id

        # 工作流完成
        state.complete()
        return None

    def _evaluate_phase_condition(
        self,
        condition: str,
        phase_result: Dict[str, Any],
    ) -> bool:
        """评估阶段转换条件。

        Args:
            condition: 条件表达式
            phase_result: 阶段执行结果

        Returns:
            是否满足条件
        """
        try:
            if "=" in condition:
                key, value = condition.split("=", 1)
                actual = phase_result.get(key, phase_result.get("data", {}).get(key))
                return str(actual).lower() == value.lower()
        except Exception:
            pass

        return False

    def process_request_with_workflow(
        self,
        user_message: str,
        session_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> "DirectorResponse":
        """使用工作流处理请求。

        这是 Director 的新主入口，支持工作流驱动的请求处理。

        Args:
            user_message: 用户消息
            session_id: 会话ID（可选）
            context: 上下文数据（可选）

        Returns:
            Director 响应
        """
        from datetime import datetime

        from tools.models.intent import (
            ConversationSession,
            DirectorResponse,
            PhaseOption,
            SuggestedAction,
        )
        from tools.models.workflow import WorkflowDefinition, WorkflowPhase, WorkflowState
        from tools.workflow_registry import init_workflows, workflow_registry

        context = context or {}

        # 确保工作流已初始化
        init_workflows()

        # 1. 获取/创建会话
        session = self._get_or_create_session(session_id, context)
        session.add_message("user", user_message)

        # 2. 意图识别
        intent = self.classify_intent(user_message, context)

        # 3. 检测工作流
        workflow = self.detect_workflow(intent, user_message, context)

        if not workflow:
            # 无匹配工作流，使用默认处理
            return self._process_without_workflow(
                user_message, session, intent, context
            )

        # 4. 获取工作流状态
        workflow_state = self.get_or_create_workflow_state(session, workflow)

        # 5. 获取当前阶段
        current_phase = self.get_current_phase_definition(workflow, workflow_state)

        if not current_phase:
            return DirectorResponse(
                success=False,
                message="工作流状态异常：无法找到当前阶段",
                detected_intent=intent.intent,
                detected_workflow=workflow.workflow_id,
                session_id=session.session_id,
            )

        # 6. 执行阶段
        phase_result = self._execute_phase(
            current_phase,
            user_message,
            context,
            intent.tool_parameters,
        )

        # 7. 推进工作流
        next_phase = self.advance_workflow(workflow, workflow_state, phase_result)

        # 8. 构建响应
        response = self._build_workflow_response(
            workflow=workflow,
            state=workflow_state,
            current_phase=current_phase,
            phase_result=phase_result,
            next_phase=next_phase,
            intent=intent,
            session=session,
        )

        # 9. 更新会话
        session.set_workflow_state(workflow_state.model_dump())
        session.add_message("assistant", response.message)

        # 10. 持久化保存会话
        if self._persistence:
            self._persistence.save_session(session.model_dump())

        return response

    def _get_or_create_session(
        self,
        session_id: Optional[str],
        context: Dict[str, Any],
    ) -> "ConversationSession":
        """获取或创建会话。

        Args:
            session_id: 会话ID
            context: 上下文数据

        Returns:
            会话对象
        """
        from datetime import datetime
        from uuid import uuid4

        from tools.models.intent import ConversationSession

        if session_id and session_id in self._sessions:
            return self._sessions[session_id]

        # 尝试从持久化存储加载
        if session_id and self._persistence:
            persisted_data = self._persistence.load_session(session_id)
            if persisted_data:
                # 从持久化存储恢复会话
                new_session = ConversationSession(**persisted_data)
                self._sessions[session_id] = new_session
                logger.info("从持久化存储恢复会话: %s", session_id)
                return new_session

        # 创建新会话
        new_session = ConversationSession(
            session_id=session_id or str(uuid4())[:8],
            novel_id=context.get("novel_id"),
            context_data=context,
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        )

        self._sessions[new_session.session_id] = new_session
        return new_session

    def _process_without_workflow(
        self,
        user_message: str,
        session: "ConversationSession",
        intent: "IntentDecision",
        context: Dict[str, Any],
    ) -> "DirectorResponse":
        """无工作流时的默认处理。

        Args:
            user_message: 用户消息
            session: 会话对象
            intent: 意图识别结果
            context: 上下文数据

        Returns:
            Director 响应
        """
        from tools.models.intent import DirectorResponse, SuggestedAction

        # 根据意图提供通用响应
        if intent.intent.value == "general_chat":
            return DirectorResponse(
                success=True,
                message="您好！我是 OpenWrite 的创作助手。我可以帮助您：\n"
                "- 写章节（根据大纲生成内容）\n"
                "- 创建/修改大纲\n"
                "- 管理角色、伏笔、世界观\n"
                "- 合成风格文档\n\n"
                "请告诉我您想做什么？",
                detected_intent=intent.intent,
                confidence=intent.confidence_score,
                session_id=session.session_id,
                suggested_actions=[
                    SuggestedAction(
                        action="write_chapter",
                        label="写章节",
                        description="根据大纲生成章节内容",
                    ),
                    SuggestedAction(
                        action="outline_assist",
                        label="大纲辅助",
                        description="创建或修改大纲",
                    ),
                    SuggestedAction(
                        action="help",
                        label="帮助",
                        description="查看使用说明",
                    ),
                ],
            )

        if intent.intent.value == "help":
            return DirectorResponse(
                success=True,
                message=self._get_help_message(),
                detected_intent=intent.intent,
                confidence=intent.confidence_score,
                session_id=session.session_id,
            )

        # 其他意图：返回需要更多信息的响应
        return DirectorResponse(
            success=True,
            message=f"我理解您想要{intent.intent.value}。请问您具体想做什么？",
            detected_intent=intent.intent,
            confidence=intent.confidence_score,
            session_id=session.session_id,
            follow_up_questions=intent.matched_keywords if intent.matched_keywords else ["请提供更多细节"],
        )

    def _get_help_message(self) -> str:
        """获取帮助消息。"""
        return """**OpenWrite 创作助手使用指南**

## 主要功能

### 1. 章节写作
- 输入「写第X章」或「生成章节」开始
- 系统会根据大纲和上下文生成章节内容
- 支持续写、草稿修改

### 2. 大纲管理
- **创建大纲**: 输入「创建大纲」开始四级大纲创作
- **修改大纲**: 输入「修改大纲」调整现有大纲
- **查看大纲**: 输入「查看大纲」浏览大纲结构

### 3. 角色管理
- 输入「创建角色」「修改角色」管理人物
- 支持主角、配角、龙套等不同层级

### 4. 伏笔管理
- 输入「埋设伏笔」创建新的伏笔节点
- 输入「回收伏笔」标记伏笔回收
- 系统会自动追踪伏笔状态

### 5. 风格系统
- 输入「合成风格」选择和合成风格文档
- 支持三层风格架构（通用技法→作者风格→作品设定）

## 快捷命令
- `写第X章` - 生成指定章节
- `大纲` - 查看大纲
- `角色` - 查看角色列表
- `伏笔` - 查看伏笔状态
- `帮助` - 显示此帮助
"""

    def _execute_phase(
        self,
        phase: "WorkflowPhase",
        user_message: str,
        context: Dict[str, Any],
        parameters: Dict[str, Any],
    ) -> Dict[str, Any]:
        """执行工作流阶段。

        Args:
            phase: 阶段定义
            user_message: 用户消息
            context: 上下文数据
            parameters: 工具参数

        Returns:
            阶段执行结果
        """
        result: Dict[str, Any] = {
            "user_message": user_message,
            "tools_called": [],
            "data": {},
            "context_loaded": [],
        }

        # 加载所需上下文
        for key in phase.context_keys:
            if key not in context:
                loaded = self._load_context(key, context.get("novel_id", ""))
                if loaded:
                    context[key] = loaded
                    result["context_loaded"].append(key)

        # 执行必需工具
        for tool_name in phase.required_tools:
            tool_result = self._execute_tool(tool_name, parameters, context)
            result["tools_called"].append(tool_name)
            result["data"][tool_name] = tool_result

        # 执行可选工具（根据用户消息判断）
        for tool_name in phase.available_tools:
            if tool_name not in phase.required_tools:
                if self._should_call_tool(tool_name, user_message):
                    tool_result = self._execute_tool(tool_name, parameters, context)
                    result["tools_called"].append(tool_name)
                    result["data"][tool_name] = tool_result

        return result

    def _load_context(self, key: str, novel_id: str) -> Optional[str]:
        """加载上下文数据。

        Args:
            key: 上下文键
            novel_id: 小说ID

        Returns:
            加载的数据
        """
        if not novel_id:
            return None

        try:
            if key == "outline" or key == "current_hierarchy":
                from tools.queries.outline_queries import get_outline_summary
                return get_outline_summary(novel_id)

            elif key == "characters":
                from tools.queries.character_queries import get_character_summary
                return get_character_summary(novel_id)

            elif key == "foreshadowing":
                from tools.queries.foreshadowing_queries import get_pending_foreshadowing
                return get_pending_foreshadowing(novel_id)

            elif key == "world":
                from tools.queries.world_queries import get_world_summary
                return get_world_summary(novel_id)

        except Exception as e:
            logger.warning("Failed to load context %s: %s", key, e)

        return None

    def _execute_tool(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """执行工具。

        Args:
            tool_name: 工具名称
            parameters: 工具参数
            context: 上下文数据

        Returns:
            工具执行结果
        """
        # 目前返回占位结果
        # 实际实现应该调用工具注册表
        return {
            "tool": tool_name,
            "status": "simulated",
            "message": f"工具 {tool_name} 已调用",
        }

    def _should_call_tool(self, tool_name: str, user_message: str) -> bool:
        """判断是否应该调用可选工具。

        Args:
            tool_name: 工具名称
            user_message: 用户消息

        Returns:
            是否应该调用
        """
        tool_keywords = {
            "outline_assist": ["大纲", "outline"],
            "lore_checker": ["检查", "逻辑", "check"],
            "stylist": ["风格", "润色", "style"],
        }

        keywords = tool_keywords.get(tool_name, [])
        return any(kw in user_message.lower() for kw in keywords)

    def _build_workflow_response(
        self,
        workflow: "WorkflowDefinition",
        state: "WorkflowState",
        current_phase: "WorkflowPhase",
        phase_result: Dict[str, Any],
        next_phase: Optional[str],
        intent: "IntentDecision",
        session: "ConversationSession",
    ) -> "DirectorResponse":
        """构建工作流响应。

        Args:
            workflow: 工作流定义
            state: 工作流状态
            current_phase: 当前阶段
            phase_result: 阶段执行结果
            next_phase: 下一阶段ID
            intent: 意图识别结果
            session: 会话对象

        Returns:
            Director 响应
        """
        from tools.models.intent import (
            DirectorResponse,
            PhaseOption,
            SuggestedAction,
        )

        # 计算进度
        total_phases = len(workflow.phases)
        current_index = workflow.get_phase_index(state.current_phase)
        progress = (current_index + 1) / total_phases if total_phases > 0 else 0

        # 获取下一个阶段信息
        next_phase_name = ""
        if next_phase:
            next_phase_def = workflow.get_phase(next_phase)
            next_phase_name = next_phase_def.name if next_phase_def else ""

        # 构建建议操作
        suggested_actions = []
        if next_phase:
            suggested_actions.append(
                SuggestedAction(
                    action="continue",
                    label=f"继续：{next_phase_name}",
                    description="进入下一阶段",
                    parameters={"phase": next_phase},
                )
            )
        else:
            suggested_actions.append(
                SuggestedAction(
                    action="complete",
                    label="完成工作流",
                    description="工作流已完成",
                )
            )

        # 构建阶段选项
        phase_options = [
            PhaseOption(
                option_id=opt.get("id", str(i)),
                label=opt.get("label", ""),
                description=opt.get("description", ""),
                next_phase=opt.get("next_phase"),
            )
            for i, opt in enumerate(current_phase.options)
        ]

        return DirectorResponse(
            success=True,
            message=current_phase.user_prompt or f"正在执行：{current_phase.name}",
            detected_intent=intent.intent,
            detected_workflow=workflow.workflow_id,
            confidence=intent.confidence_score,
            workflow_state=state,
            current_phase=current_phase.name,
            current_phase_id=current_phase.phase_id,
            phase_progress=progress,
            total_phases=total_phases,
            completed_phases=len(state.phase_history),
            user_prompt=current_phase.user_prompt,
            follow_up_questions=current_phase.questions,
            suggested_actions=suggested_actions,
            phase_options=phase_options,
            session_id=session.session_id,
            reasoning=f"工作流 {workflow.name}，阶段 {current_index + 1}/{total_phases}",
            context_loaded=phase_result.get("context_loaded", []),
        )


    def list_sessions(self) -> List[Dict[str, Any]]:
        """列出所有会话。
        
        Returns:
            会话列表，每个会话包含 session_id, novel_id, created_at, updated_at, message_count
        """
        return [
            {
                "session_id": session.session_id,
                "novel_id": session.novel_id,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
                "message_count": len(session.message_history),
            }
            for session in self._sessions.values()
        ]

    def delete_session(self, session_id: str) -> bool:
        """删除指定会话。
        
        Args:
            session_id: 会话ID
            
        Returns:
            是否删除成功
        """
        if session_id in self._sessions:
            del self._sessions[session_id]
            # 同步删除持久化文件
            if self._persistence:
                self._persistence.delete_session(session_id)
            return True
        return False

