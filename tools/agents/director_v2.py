"""Skill-Based Director — 基于功能模块的主控 Agent

重构后的 Director 使用 SkillRegistry 进行动态意图匹配，
使用 ToolExecutor 进行统一的工具调用。

核心改进：
1. 意图识别：使用 SkillRegistry.match_trigger() 替代硬编码关键词
2. 工具调用：使用 ToolExecutor 替代占位符 _execute_tool()
3. 提示词加载：从 config/main_prompt.md 加载主 AI 提示词
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
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


class SkillBasedDirector:
    """基于 Skill 模块的主控 Agent。

    使用 SkillRegistry 进行动态意图匹配，使用 ToolExecutor 进行统一的工具调用。

    Features:
    - 动态功能发现（通过 SkillRegistry）
    - 统一工具执行（通过 ToolExecutor）
    - 主 AI 提示词外部化（config/main_prompt.md）
    - 向后兼容 Pipeline V2

    Usage:
        director = SkillBasedDirector(project_root=Path.cwd(), novel_id="my_novel")
        response = director.process_request("写第1章")
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
        project_root: Optional[Path] = None,
        novel_id: Optional[str] = None,
        llm_client: Optional["LLMClient"] = None,
        router: Optional["ModelRouter"] = None,
    ):
        """初始化 Director。

        Args:
            project_root: 项目根目录
            novel_id: 当前小说 ID
            llm_client: 可选 LLM 客户端
            router: 可选模型路由器
        """
        self.project_root = project_root or Path.cwd()
        self.novel_id = novel_id
        self._llm_client = llm_client
        self._router = router

        # 延迟加载组件
        self._skill_registry = None
        self._tool_executor = None
        self._main_prompt = None
        self._sessions: Dict[str, Any] = {}

    # ============================================================
    # 延迟加载属性
    # ============================================================

    @property
    def skill_registry(self):
        """获取功能注册表（延迟加载）。"""
        if self._skill_registry is None:
            from skills.skill_loader import SkillLoader

            loader = SkillLoader(project_root=self.project_root)
            self._skill_registry = loader.load_all()
        return self._skill_registry

    @property
    def tool_executor(self):
        """获取工具执行器（延迟加载）。"""
        if self._tool_executor is None:
            from skills.tools.executor import ToolExecutor

            self._tool_executor = ToolExecutor(
                project_root=self.project_root,
                novel_id=self.novel_id,
            )
        return self._tool_executor

    @property
    def main_prompt(self) -> str:
        """获取主 AI 提示词（延迟加载）。"""
        if self._main_prompt is None:
            prompt_path = self.project_root / "config" / "main_prompt.md"
            if prompt_path.exists():
                self._main_prompt = prompt_path.read_text(encoding="utf-8")
            else:
                self._main_prompt = self._get_default_prompt()
        return self._main_prompt

    def _get_default_prompt(self) -> str:
        """获取默认提示词。"""
        return """# OpenWrite 创作助手

你是 OpenWrite 写作系统的核心主控。你的任务是：
1. 理解用户的创作意图
2. 根据意图选择合适的功能模块
3. 协调各个子功能完成用户请求

## 工作原则

1. **意图优先**：先理解用户想做什么，再选择功能
2. **渐进交互**：复杂任务分步完成，每步确认用户意图
3. **上下文感知**：根据当前小说项目的状态调整行为
4. **工具查询**：不确定数据时，主动使用工具查询
"""

    # ============================================================
    # 意图识别（基于 SkillRegistry）
    # ============================================================

    def classify_intent(
        self,
        user_message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> "IntentDecision":
        """识别用户意图。

        使用 SkillRegistry.match_trigger() 进行动态匹配。

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

        # 1. 使用 SkillRegistry 匹配
        matched_skill = self.skill_registry.match_trigger(user_message)

        if matched_skill:
            # 将 Skill 映射到 TaskIntent
            intent = self._map_skill_to_intent(matched_skill.name)

            # 计算置信度
            score = sum(
                1 for t in matched_skill.triggers if t.lower() in user_message.lower()
            )
            if matched_skill.trigger and user_message.strip().startswith(
                matched_skill.trigger
            ):
                score += 10

            confidence = (
                IntentConfidence.HIGH if score >= 2 else IntentConfidence.MEDIUM
            )
            confidence_score = min(0.95, 0.5 + score * 0.1)

            return IntentDecision(
                intent=intent,
                confidence=confidence,
                confidence_score=confidence_score,
                matched_keywords=matched_skill.triggers[:5],
                reasoning=f"匹配到功能模块: {matched_skill.name}",
                tool_parameters={"skill": matched_skill.name},
                entity_references=self._extract_entities(user_message),
            )

        # 2. 无匹配时的 fallback
        return IntentDecision(
            intent=TaskIntent.GENERAL_CHAT,
            confidence=IntentConfidence.LOW,
            confidence_score=0.2,
            matched_keywords=[],
            reasoning="未匹配到特定功能，使用通用对话",
            entity_references=self._extract_entities(user_message),
        )

    def _map_skill_to_intent(self, skill_name: str) -> "TaskIntent":
        """将 Skill 名称映射到 TaskIntent。

        Args:
            skill_name: 功能模块名称

        Returns:
            对应的 TaskIntent
        """
        from tools.models.intent import TaskIntent

        # Skill 名称到 TaskIntent 的映射
        mapping = {
            "outline": TaskIntent.OUTLINE_ASSIST,
            "writing": TaskIntent.WRITE_CHAPTER,
            "style": TaskIntent.STYLE_COMPOSE,
            "character": TaskIntent.CHARACTER_CREATE,
            "world": TaskIntent.LORE_QUERY,
            "foreshadowing": TaskIntent.FORESHADOW_PLANT,
            "project": TaskIntent.PROJECT_INIT,
        }

        return mapping.get(skill_name, TaskIntent.UNKNOWN)

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
            r"第(\d+)章",
            r"ch_(\w+)",
            r"chapter\s*(\d+)",
        ]
        for pattern in chapter_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            entities.extend([f"chapter:{m}" for m in matches])

        # 提取可能的角色名（简单规则：中文人名）
        name_pattern = r"[\u4e00-\u9fa5]{2,4}(?=的|说|想|看|走|来|去|在)"
        names = re.findall(name_pattern, text)
        entities.extend([f"character:{name}" for name in names[:3]])  # 最多3个

        return list(set(entities))

    # ============================================================
    # 工具执行（基于 ToolExecutor）
    # ============================================================

    def execute_tool(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
    ) -> Dict[str, Any]:
        """执行工具。

        使用 ToolExecutor 进行统一的工具调用。

        Args:
            tool_name: 工具名称
            parameters: 工具参数

        Returns:
            工具执行结果
        """
        result = self.tool_executor.execute(tool_name, parameters)

        if not result.get("success"):
            logger.warning(
                "Tool execution failed: %s - %s",
                tool_name,
                result.get("error"),
            )

        return result

    def load_context(self, key: str) -> Optional[str]:
        """加载上下文数据。

        使用 ToolExecutor 查询数据。

        Args:
            key: 上下文键

        Returns:
            加载的数据
        """
        if not self.novel_id:
            return None

        tool_mapping = {
            "outline": ("query_outline", {}),
            "characters": ("query_characters", {}),
            "foreshadowing": ("query_foreshadowing", {}),
            "world": ("query_world", {}),
            "manuscript": ("query_manuscript", {}),
            "style": ("query_style", {}),
        }

        if key not in tool_mapping:
            return None

        tool_name, params = tool_mapping[key]
        result = self.execute_tool(tool_name, params)

        if result.get("success"):
            data = result.get("result", {})
            # 将 dict 转换为字符串摘要
            return self._summarize_context(key, data)

        return None

    def _summarize_context(self, key: str, data: Dict[str, Any]) -> str:
        """将上下文数据转换为摘要字符串。

        Args:
            key: 上下文键
            data: 数据字典

        Returns:
            摘要字符串
        """
        if key == "outline":
            chapters = data.get("chapters", {})
            if chapters:
                return f"共 {len(chapters)} 章"
            return "暂无大纲"

        elif key == "characters":
            chars = data.get("characters", {})
            if chars:
                return f"共 {len(chars)} 个角色"
            return "暂无角色"

        elif key == "foreshadowing":
            nodes = data.get("nodes", {})
            pending = sum(1 for n in nodes.values() if n.get("status") == "pending")
            return f"{pending} 条待回收伏笔"

        elif key == "world":
            entities = data.get("entities", {})
            return f"共 {len(entities)} 个世界观数据"

        elif key == "style":
            return "已加载风格配置"

        return str(data)[:200]

    # ============================================================
    # 工作流处理
    # ============================================================

    def process_request(
        self,
        user_message: str,
        session_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> "DirectorResponse":
        """处理用户请求。

        这是 Director 的主入口。

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
            SuggestedAction,
        )

        context = context or {}

        # 1. 获取/创建会话
        session = self._get_or_create_session(session_id, context)
        session.add_message("user", user_message)

        # 2. 意图识别
        intent = self.classify_intent(user_message, context)

        # 3. 检测工作流
        workflow = self._detect_workflow(intent, user_message, context)

        if not workflow:
            # 无匹配工作流，使用默认处理
            return self._process_without_workflow(
                user_message, session, intent, context
            )

        # 4. 执行工作流
        return self._execute_workflow(workflow, user_message, session, intent, context)

    def _get_or_create_session(
        self,
        session_id: Optional[str],
        context: Dict[str, Any],
    ) -> "ConversationSession":
        """获取或创建会话。"""
        from datetime import datetime
        from uuid import uuid4

        from tools.models.intent import ConversationSession

        if session_id and session_id in self._sessions:
            return self._sessions[session_id]

        new_session = ConversationSession(
            session_id=session_id or str(uuid4())[:8],
            novel_id=context.get("novel_id", self.novel_id),
            context_data=context,
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        )

        self._sessions[new_session.session_id] = new_session
        return new_session

    def _detect_workflow(
        self,
        intent: "IntentDecision",
        user_message: str,
        context: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """检测工作流。

        Args:
            intent: 意图识别结果
            user_message: 用户消息
            context: 上下文数据

        Returns:
            工作流定义，无匹配返回 None
        """
        # 根据意图选择工作流
        skill_name = intent.tool_parameters.get("skill")
        if skill_name:
            skill = self.skill_registry.get(skill_name)
            if skill:
                # 尝试获取工作流
                workflow = skill.get_workflow("main")
                if workflow:
                    return {
                        "skill": skill,
                        "workflow": workflow,
                        "workflow_id": f"{skill_name}_main",
                    }

                # 使用默认工作流
                return {
                    "skill": skill,
                    "workflow": None,
                    "workflow_id": f"{skill_name}_default",
                }

        return None

    def _execute_workflow(
        self,
        workflow_info: Dict[str, Any],
        user_message: str,
        session: "ConversationSession",
        intent: "IntentDecision",
        context: Dict[str, Any],
    ) -> "DirectorResponse":
        """执行工作流。

        Args:
            workflow_info: 工作流信息
            user_message: 用户消息
            session: 会话
            intent: 意图
            context: 上下文

        Returns:
            Director 响应
        """
        from tools.models.intent import (
            DirectorResponse,
            SuggestedAction,
        )

        skill = workflow_info["skill"]
        workflow_id = workflow_info["workflow_id"]

        # 获取技能指令
        skill_instruction = skill.content

        # 根据技能类型执行不同逻辑
        if skill.name == "writing":
            return self._execute_writing_workflow(
                user_message, session, intent, context, skill
            )
        elif skill.name == "outline":
            return self._execute_outline_workflow(
                user_message, session, intent, context, skill
            )
        elif skill.name == "style":
            return self._execute_style_workflow(
                user_message, session, intent, context, skill
            )
        else:
            # 通用技能响应
            return DirectorResponse(
                success=True,
                message=f"已识别功能：{skill.name}\n\n{skill.description}",
                detected_intent=intent.intent,
                detected_workflow=workflow_id,
                confidence=intent.confidence_score,
                session_id=session.session_id,
                suggested_actions=[
                    SuggestedAction(
                        action="execute_skill",
                        label=f"执行 {skill.name}",
                        description=skill.description[:100],
                    )
                ],
            )

    def _execute_writing_workflow(
        self,
        user_message: str,
        session: "ConversationSession",
        intent: "IntentDecision",
        context: Dict[str, Any],
        skill: "Skill",
    ) -> "DirectorResponse":
        """执行写作工作流。"""
        from tools.models.intent import DirectorResponse, SuggestedAction

        # 提取章节 ID
        chapter_id = self._extract_chapter_id(user_message)

        # 加载上下文
        outline = self.load_context("outline")
        characters = self.load_context("characters")
        style = self.load_context("style")

        # 构建响应
        message = f"准备生成章节 {chapter_id or '（未指定）'}\n\n"
        message += f"- 大纲：{outline or '未加载'}\n"
        message += f"- 角色：{characters or '未加载'}\n"
        message += f"- 风格：{style or '未加载'}\n"

        return DirectorResponse(
            success=True,
            message=message,
            detected_intent=intent.intent,
            detected_workflow="writing_chapter",
            confidence=intent.confidence_score,
            session_id=session.session_id,
            reasoning="已加载写作上下文，准备生成章节",
            suggested_actions=[
                SuggestedAction(
                    action="generate_chapter",
                    label="生成章节",
                    description="根据大纲生成章节内容",
                    parameters={"chapter_id": chapter_id},
                ),
                SuggestedAction(
                    action="modify_settings",
                    label="调整设置",
                    description="修改生成参数",
                ),
            ],
        )

    def _execute_outline_workflow(
        self,
        user_message: str,
        session: "ConversationSession",
        intent: "IntentDecision",
        context: Dict[str, Any],
        skill: "Skill",
    ) -> "DirectorResponse":
        """执行大纲工作流。"""
        from tools.models.intent import DirectorResponse, SuggestedAction

        # 加载大纲
        outline = self.load_context("outline")

        message = "大纲管理\n\n"
        message += f"当前状态：{outline or '暂无大纲'}\n\n"
        message += "请选择操作：\n"
        message += "1. 创建大纲\n"
        message += "2. 修改大纲\n"
        message += "3. 查看大纲结构\n"

        return DirectorResponse(
            success=True,
            message=message,
            detected_intent=intent.intent,
            detected_workflow="outline_manage",
            confidence=intent.confidence_score,
            session_id=session.session_id,
            reasoning="大纲工作流已启动",
            suggested_actions=[
                SuggestedAction(
                    action="create_outline",
                    label="创建大纲",
                    description="从零创建四级大纲",
                ),
                SuggestedAction(
                    action="modify_outline",
                    label="修改大纲",
                    description="修改现有大纲",
                ),
                SuggestedAction(
                    action="view_outline",
                    label="查看大纲",
                    description="查看大纲结构",
                ),
            ],
        )

    def _execute_style_workflow(
        self,
        user_message: str,
        session: "ConversationSession",
        intent: "IntentDecision",
        context: Dict[str, Any],
        skill: "Skill",
    ) -> "DirectorResponse":
        """执行风格工作流。"""
        from tools.models.intent import DirectorResponse, SuggestedAction

        # 加载风格
        style = self.load_context("style")

        message = "风格管理\n\n"
        message += f"当前状态：{style or '暂无风格配置'}\n\n"
        message += "请选择操作：\n"
        message += "1. 风格初始化（推荐新项目使用）\n"
        message += "2. 风格合成\n"
        message += "3. 风格分析\n"

        return DirectorResponse(
            success=True,
            message=message,
            detected_intent=intent.intent,
            detected_workflow="style_manage",
            confidence=intent.confidence_score,
            session_id=session.session_id,
            reasoning="风格工作流已启动",
            suggested_actions=[
                SuggestedAction(
                    action="initialize_style",
                    label="风格初始化",
                    description="通过问询生成专属风格",
                ),
                SuggestedAction(
                    action="compose_style",
                    label="风格合成",
                    description="合成三层风格文档",
                ),
                SuggestedAction(
                    action="analyze_style",
                    label="风格分析",
                    description="分析文本风格特征",
                ),
            ],
        )

    def _process_without_workflow(
        self,
        user_message: str,
        session: "ConversationSession",
        intent: "IntentDecision",
        context: Dict[str, Any],
    ) -> "DirectorResponse":
        """无工作流时的默认处理。"""
        from tools.models.intent import DirectorResponse, SuggestedAction

        if intent.intent.value == "general_chat":
            # 生成可用功能列表
            skills_prompt = self.skill_registry.get_skills_prompt()

            return DirectorResponse(
                success=True,
                message=f"您好！我是 OpenWrite 的创作助手。\n\n{skills_prompt}\n\n请告诉我您想做什么？",
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
                        action="style_init",
                        label="风格初始化",
                        description="设置作品风格",
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

        # 其他意图
        return DirectorResponse(
            success=True,
            message=f"我理解您想要{intent.intent.value}。请问您具体想做什么？",
            detected_intent=intent.intent,
            confidence=intent.confidence_score,
            session_id=session.session_id,
            follow_up_questions=intent.matched_keywords
            if intent.matched_keywords
            else ["请提供更多细节"],
        )

    def _extract_chapter_id(self, text: str) -> Optional[str]:
        """从文本中提取章节 ID。

        Args:
            text: 输入文本

        Returns:
            章节 ID，未找到返回 None
        """
        # 第X章
        match = re.search(r"第(\d+)章", text)
        if match:
            return f"ch_{int(match.group(1)):03d}"

        # ch_XXX
        match = re.search(r"ch_(\w+)", text, re.IGNORECASE)
        if match:
            return f"ch_{match.group(1)}"

        # chapter X
        match = re.search(r"chapter\s*(\d+)", text, re.IGNORECASE)
        if match:
            return f"ch_{int(match.group(1)):03d}"

        return None

    def _get_help_message(self) -> str:
        """获取帮助消息。"""
        skills_list = "\n".join(
            [
                f"- **{s.name}**: {s.description[:50]}..."
                for s in self.skill_registry.list_all()[:10]
            ]
        )

        return f"""**OpenWrite 创作助手使用指南**

## 可用功能

{skills_list}

## 快捷命令

- `写第X章` - 生成指定章节
- `/outline` - 大纲管理
- `/write` - 写作功能
- `/style` - 风格管理
- `帮助` - 显示此帮助

## 更多信息

每个功能都有详细的 SKILL.md 文件，包含使用说明和工作流定义。
"""

    # ============================================================
    # Pipeline V2 兼容方法
    # ============================================================

    def plan(
        self,
        objective: str,
        context: Dict[str, str],
        chapter_id: str = "",
        use_stylist: bool = False,
        style_summary: Optional[str] = None,
    ) -> DirectorDecision:
        """分析上下文并产生路由决策（Pipeline V2 兼容）。

        Args:
            objective: 章节写作目标
            context: 上下文数据
            chapter_id: 章节标识符
            use_stylist: 是否启用风格润色
            style_summary: 风格摘要

        Returns:
            路由决策
        """
        # 压缩上下文
        compressed = self._compress_context(context)

        # LLM 模式
        if self._llm_client and self._router:
            return self._plan_with_llm(
                objective,
                context,
                chapter_id,
                use_stylist,
                style_summary,
                compressed,
            )

        # 规则引擎模式
        return self._plan_rule_based(
            objective,
            context,
            chapter_id,
            use_stylist,
            style_summary,
            compressed,
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
        """规则引擎路由决策。"""
        required_agents = ["librarian", "lore_checker"]
        notes: List[str] = []
        priority_elements: List[str] = []

        # 检测严格模式
        suggested_strict = self._should_strict_lore(objective, context)
        if suggested_strict:
            notes.append("检测到高风险章节内容，建议启用严格逻辑检查")

        # 检测重点要素
        priority_elements = self._extract_priority_elements(objective, context)
        if priority_elements:
            notes.append(f"本章重点要素: {', '.join(priority_elements)}")

        # 风格指令
        style_instructions = ""
        if use_stylist:
            required_agents.append("stylist")
            style_instructions = self._build_style_instructions(style_summary)
            notes.append("文风处理已启用，Stylist 将在逻辑检查通过后执行")

        # 伏笔提醒
        foreshadowing_text = context.get("foreshadowing", "")
        if foreshadowing_text and "暂无" not in foreshadowing_text:
            pending_count = foreshadowing_text.count(";") + 1
            notes.append(f"有{pending_count}条待回收伏笔，Librarian 应考虑自然融入")

        # 标准规则
        notes.append("总纲/卷纲默认只读，本轮仅生成草稿")
        notes.append("逻辑检查未通过时禁止进入文风润色")

        # 构建摘要
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
        """压缩上下文。"""
        try:
            from tools.utils.context_compressor import ContextCompressor
        except ImportError:
            from utils.context_compressor import ContextCompressor

        total_budget = (
            self.BUDGET_OUTLINE
            + self.BUDGET_CHARACTERS
            + self.BUDGET_FORESHADOWING
            + self.BUDGET_WORLD
            + self.BUDGET_SCENES
            + self.BUDGET_STYLE
        )
        compressor = ContextCompressor(budget=total_budget)

        compressible = {
            k: v
            for k, v in context.items()
            if k
            in (
                "outline",
                "characters",
                "foreshadowing",
                "world",
                "scenes",
                "cross_chapter",
                "seed",
                "summary",
            )
            and v
        }

        if not compressible:
            return {}

        result = compressor.compress(compressible)
        return result.sections

    def _should_strict_lore(self, objective: str, context: Dict[str, str]) -> bool:
        """判断是否需要严格逻辑检查。"""
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
        """提取重点要素。"""
        elements: List[str] = []

        # 伏笔
        foreshadowing = context.get("foreshadowing", "")
        if foreshadowing and "暂无" not in foreshadowing:
            ids = re.findall(r"(\w+)\(权重=(\d+)", foreshadowing)
            high_weight = [nid for nid, w in ids if int(w) >= 7]
            if high_weight:
                elements.append(f"高权重伏笔: {', '.join(high_weight[:3])}")

        # 角色
        characters = context.get("characters", "")
        if characters and "暂无" not in characters:
            names = re.findall(r"(\S+?)\(境界=", characters)
            if names:
                elements.append(f"涉及角色: {', '.join(names[:4])}")

        # 场景
        scenes = context.get("scenes", "")
        if scenes and "未标注" not in scenes:
            elements.append(f"场景要求: {scenes}")

        return elements

    def _build_style_instructions(self, style_summary: Optional[str]) -> str:
        """构建风格指令。"""
        if not style_summary:
            return "使用默认风格规则进行润色（无特定风格文档加载）"

        instructions: List[str] = [
            "风格润色指令：",
            "1. 检查并移除AI痕迹（禁用表达清单）",
            "2. 验证叙述者-角色声音融合度",
            "3. 检查段落节奏（短段60%/中段30%/长段10%）",
            "4. 确保吐槽密度符合风格要求",
            "5. 验证现代感用语自然融入",
        ]

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
        """LLM 路由决策。"""
        import json

        from tools.llm.prompts import PromptBuilder
        from tools.llm.router import TaskType

        assert self._llm_client is not None
        assert self._router is not None

        # 构建摘要
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
                messages=messages,
                routes=routes,
            )
            return self._parse_llm_decision(
                response.content,
                objective,
                chapter_id,
                use_stylist,
                compressed,
                full_summary,
            )
        except Exception as e:
            logger.warning("Director LLM 调用失败，回退到规则引擎: %s", e)
            return self._plan_rule_based(
                objective,
                context,
                chapter_id,
                use_stylist,
                style_summary,
                compressed,
            )

    def _parse_llm_decision(
        self,
        llm_output: str,
        objective: str,
        chapter_id: str,
        use_stylist: bool,
        compressed: Dict[str, str],
        full_summary: str,
    ) -> DirectorDecision:
        """解析 LLM 输出。"""
        import json

        # 提取 JSON
        json_match = re.search(r"```json\s*(.+?)\s*```", llm_output, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = llm_output.strip()

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("Director LLM 输出 JSON 解析失败，使用默认值")
            data = {}

        required_agents = ["librarian", "lore_checker"]
        if use_stylist:
            required_agents.append("stylist")

        return DirectorDecision(
            objective=objective,
            chapter_id=chapter_id,
            required_agents=required_agents,
            context_summary=full_summary[:800],
            notes=data.get("notes", []),
            compressed_context=compressed,
            style_instructions=data.get("style_instructions", ""),
            suggested_strict_lore=data.get("strict_lore", False),
            priority_elements=data.get("priority_elements", []),
            generation_instructions=data.get("generation_instructions", ""),
        )


# ============================================================
# 向后兼容：DirectorAgent 别名
# ============================================================

# 为了向后兼容，保留 DirectorAgent 作为 SkillBasedDirector 的别名
# 但实际上应该使用 SkillBasedDirector
DirectorAgent = SkillBasedDirector
