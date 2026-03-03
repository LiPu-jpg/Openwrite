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
        
        # Session 持久化目录
        self._sessions_dir = self.project_root / "data" / "sessions"
        self._sessions_dir.mkdir(parents=True, exist_ok=True)
        
        # 启动时加载持久化的 sessions
        self._load_sessions()
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
    # Agentic 能力：LLM 自主生成回复
    # ============================================================

    def _build_agent_system_prompt(self, context: Optional[Dict[str, Any]] = None) -> str:
        """构建 Director Agent 的系统提示词。
        
        Args:
            context: 上下文数据
            
        Returns:
            系统提示词字符串
        """
        context = context or {}
        
        # 获取可用功能
        skills = self.skill_registry.list_all()
        skills_desc = "\n".join([
            f"- **{s.name}**: {s.description[:80]}{'...' if len(s.description) > 80 else ''}"
            for s in skills
        ])
        
        # 获取项目信息
        project_info = f"小说ID: {self.novel_id or '未设置'}"
        if self.novel_id:
            # 尝试获取一些基本信息
            outline = self.load_context("outline")
            characters = self.load_context("characters")
            if outline:
                project_info += f"\n大纲状态: 已配置"
            if characters:
                project_info += f"\n角色数: {characters.count(',') + 1 if ',' in characters else 1}"
        
        return f"""# OpenWrite 创作助手

你是 OpenWrite 的核心 AI 助手，帮助用户进行小说创作。

## 当前项目
{project_info}

## 可用功能
{skills_desc}

## 你的能力

1. **回答问题**：关于项目、角色、大纲、世界观等
2. **引导创作**：帮助用户开始写作、创建大纲等
3. **查询数据**：可以读取项目文件和查询数据

## 回复原则

1. 简洁友好，直接回答用户问题
2. 如果用户想执行创作任务，引导他们使用相应功能
3. 如果被问到具体数据（角色、大纲等），说明你可以查询
4. 不要编造数据，如果不确定就说需要查询
"""

    def _generate_llm_response(
        self,
        user_message: str,
        session: "ConversationSession",
        context: Optional[Dict[str, Any]] = None,
    ) -> "DirectorResponse":
        """让 LLM 生成回复（支持 Function Calling）。
        
        Agentic Loop:
        1. LLM 决定是否调用工具
        2. 如果调用工具，执行后继续
        3. 直到 LLM 生成最终回复
        
        Args:
            user_message: 用户消息
            session: 会话对象
            context: 上下文数据
            
        Returns:
            Director 响应
        """
        from tools.models.intent import DirectorResponse, TaskIntent
        from tools.llm.router import TaskType
        from skills.tools.schemas import DIRECTOR_TOOLS
        import json
        
        if not self._llm_client or not self._router:
            return self._fallback_welcome_response(session)
        
        MAX_ITERATIONS = 10
        MAX_TOOL_CALLS = 5  # 最多调用 5 次工具
        tool_call_count = 0
        
        try:
            # 构建系统提示词
            system_prompt = self._build_agent_system_prompt(context)
            # 添加工具调用指导
            system_prompt += """

## 🔴 工具调用规则 [CRITICAL - 必须遵守]

### 什么时候必须调用工具

| 用户请求 | 必须调用的工具 | 示例 |
|---------|--------------|------|
| "创建大纲" / "新建大纲" / "写个大纲" | write_file | write_file(path="data/novels/my_novel/outline/hierarchy.yaml", content="...") |
| "写第X章" / "生成章节" / "开始写作" | call_writer | call_writer(chapter_id="ch_001", objective="推进主线") |
| "有什么角色" / "角色列表" | query_characters | query_characters() |
| "大纲是什么" / "查看大纲" | query_outline | query_outline() |
| "创建角色" / "添加人物" | write_file | write_file(path="data/novels/my_novel/characters/char_xxx.yaml", content="...") |
| "添加世界观数据" / "创建地点" | write_file | write_file(path="data/novels/my_novel/world/entities.yaml", content="...") |

### 🚫 禁止行为

1. **禁止**只说"我已经创建了X"或"正在为你生成Y"而不实际调用工具
2. **禁止**在没调用工具的情况下告诉用户"完成了"
3. **禁止**只返回对话回复而不执行实际操作

### ✅ 正确做法

1. 用户说"创建大纲" → 先调用 write_file → 等待结果 → 根据结果回复
2. 用户说"写第1章" → 先调用 call_writer → 等待结果 → 根据结果回复
3. 用户说"有什么角色" → 先调用 query_characters → 根据查询结果回复

### 💡 关键原则

用户期望的是**实际执行**，而不是**描述执行**。
如果你只是在聊天中说"创建了"，用户看不到任何文件，这是完全错误的！
"""
            # 构建消息历史
            messages: List[Dict[str, Any]] = [{"role": "system", "content": system_prompt}]
            
            # 添加对话历史
            history = session.message_history[-20:]
            messages.extend(history)
            
            # 添加当前用户消息
            messages.append({"role": "user", "content": user_message})
            
            # Agentic Loop
            routes = self._router.get_routes(TaskType.REASONING)
            
            for iteration in range(MAX_ITERATIONS):
                # 如果已经调用过工具，后续不再传 tools，强制生成回复
                use_tools = DIRECTOR_TOOLS if tool_call_count < MAX_TOOL_CALLS else None
                
                # 调用 LLM
                response = self._llm_client.complete_with_fallback(
                    messages=messages,
                    routes=routes,
                    tools=use_tools,
                )
                
                # 检查是否有工具调用
                if response.tool_calls and tool_call_count < MAX_TOOL_CALLS:
                    tool_call_count += 1
                    # 处理每个工具调用
                    for tool_call in response.tool_calls:
                        tool_name = tool_call["name"]
                        tool_args_str = tool_call["arguments"]
                        tool_id = tool_call["id"]
                        
                        try:
                            tool_args = json.loads(tool_args_str) if isinstance(tool_args_str, str) else tool_args_str
                        except json.JSONDecodeError:
                            tool_args = {}
                        
                        # 执行工具
                        tool_result = self._execute_tool_for_llm(tool_name, tool_args)
                        
                        # 添加 assistant 消息（带 tool_calls）
                        messages.append({
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [{
                                "id": tool_id,
                                "type": "function",
                                "function": {
                                    "name": tool_name,
                                    "arguments": tool_args_str
                                }
                            }]
                        })
                        
                        # 添加 tool 结果消息
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_id,
                            "content": json.dumps(tool_result, ensure_ascii=False)
                        })
                    
                    # 继续循环，让 LLM 处理工具结果
                    continue
                
                # 没有工具调用，或已达到工具调用上限，生成最终回复
                if response.content:
                    return DirectorResponse(
                        success=True,
                        message=response.content,
                        detected_intent=TaskIntent.GENERAL_CHAT,
                        confidence=0.9,
                        session_id=session.session_id,
                    )
                else:
                    # 无内容，继续循环
                    continue
            
            # 达到最大迭代次数，尝试不带 tools 生成最终回复
            logger.warning("Agentic loop 达到最大迭代次数")
            
            try:
                final_response = self._llm_client.complete_with_fallback(
                    messages=messages,
                    routes=routes,
                    # 不传 tools，强制生成最终回复
                )
                if final_response and final_response.content:
                    return DirectorResponse(
                        success=True,
                        message=final_response.content,
                        detected_intent=TaskIntent.GENERAL_CHAT,
                        confidence=0.8,
                        session_id=session.session_id,
                    )
            except Exception as e:
                logger.warning(f"Final response generation failed: {e}")
            
            return DirectorResponse(
                success=True,
                message="抱歉，处理您的请求时遇到了一些复杂情况。请尝试简化您的问题，或者直接告诉我您想做什么。\n\n您可以尝试：\n• \"写第1章\" - 生成章节\n• \"创建大纲\" - 创建故事大纲\n• \"创建角色\" - 添加角色",
                detected_intent=TaskIntent.GENERAL_CHAT,
                confidence=0.5,
                session_id=session.session_id,
            )
            
        except Exception as e:
            logger.warning(f"LLM 生成回复失败: {e}")
            return self._fallback_welcome_response(session)

    def _execute_tool_for_llm(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """执行 LLM 请求的工具调用。
        
        支持两种类型：
        1. ToolExecutor 工具（文件、查询等）
        2. 子 Agent 调用（Writer, Reviewer, Stylist）
        
        Args:
            tool_name: 工具名称
            arguments: 工具参数
            
        Returns:
            工具执行结果
        """
        from skills.tools.schemas import SUB_AGENT_TOOLS, SKILL_TOOLS
        
        # 检查是否是子 Agent 调用
        if tool_name in SUB_AGENT_TOOLS:
            return self._execute_sub_agent(tool_name, arguments)
        
        # 检查是否是 Skill 调用
        if tool_name in SKILL_TOOLS:
            return self._execute_skill_tool(tool_name, arguments)
        
        # 普通 ToolExecutor 工具
        result = self.execute_tool(tool_name, arguments)
        return result
    def _execute_sub_agent(self, agent_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """执行子 Agent 调用。
        
        Args:
            agent_name: Agent 名称（call_writer, call_reviewer, call_stylist）
            arguments: 调用参数
            
        Returns:
            执行结果
        """
        try:
            if agent_name == "call_writer":
                return self._call_writer(
                    chapter_id=arguments.get("chapter_id", ""),
                    objective=arguments.get("objective", ""),
                    context_keys=arguments.get("context_keys", ["outline", "characters"]),
                )
            elif agent_name == "call_reviewer":
                return self._call_reviewer(
                    content=arguments.get("content", ""),
                    check_types=arguments.get("check_types", ["all"]),
                )
            elif agent_name == "call_stylist":
                return self._call_stylist(
                    content=arguments.get("content", ""),
                    style_id=arguments.get("style_id"),
                )
            else:
                return {"success": False, "error": f"Unknown sub-agent: {agent_name}"}
        except Exception as e:
            logger.warning(f"Sub-agent {agent_name} failed: {e}")
            return {"success": False, "error": str(e)}

    def _execute_skill_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """执行 Skill 工具调用。
        
        Args:
            tool_name: 工具名称（目前只有 use_skill）
            arguments: 调用参数
            
        Returns:
            执行结果
        """
        if tool_name != "use_skill":
            return {"success": False, "error": f"Unknown skill tool: {tool_name}"}
        
        skill_name = arguments.get("skill_name")
        action = arguments.get("action")
        params = arguments.get("parameters", {})
        
        if not skill_name:
            return {"success": False, "error": "skill_name is required"}
        
        if not action:
            return {"success": False, "error": "action is required"}
        
        # 获取 Skill
        skill = self.skill_registry.get(skill_name)
        if not skill:
            return {"success": False, "error": f"Skill not found: {skill_name}"}
        
        # 获取 Skill 的指令内容
        skill_content = skill.content[:2000] if skill.content else "No content available"
        
        # 根据 action 执行相应操作
        try:
            if action == "query":
                # 查询 Skill 相关数据
                return self._query_skill_data(skill_name, params)
            elif action == "describe":
                # 返回 Skill 描述
                return {
                    "success": True,
                    "skill_name": skill_name,
                    "description": skill.description,
                    "content_preview": skill_content[:500] + "..." if len(skill_content) > 500 else skill_content,
                    "prompts": skill.list_prompts(),
                    "workflows": skill.list_workflows(),
                }
            else:
                # 默认返回 Skill 信息
                return {
                    "success": True,
                    "skill_name": skill_name,
                    "action": action,
                    "description": skill.description,
                    "content": skill_content,
                    "available_prompts": skill.list_prompts(),
                }
        except Exception as e:
            logger.warning(f"Skill tool {skill_name} failed: {e}")
            return {"success": False, "error": str(e)}

    def _query_skill_data(self, skill_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """查询 Skill 相关数据。
        
        Args:
            skill_name: Skill 名称
            params: 查询参数
            
        Returns:
            查询结果
        """
        # 根据 Skill 类型查询相应数据
        if skill_name == "writing":
            return {
                "success": True,
                "data": {
                    "manuscript": self.load_context("manuscript"),
                    "style": self.load_context("style"),
                }
            }
        elif skill_name == "outline":
            return {
                "success": True,
                "data": {
                    "outline": self.load_context("outline"),
                }
            }
        elif skill_name == "character":
            return {
                "success": True,
                "data": {
                    "characters": self.load_context("characters"),
                }
            }
        elif skill_name == "world":
            return {
                "success": True,
                "data": {
                    "world": self.load_context("world"),
                }
            }
        elif skill_name == "foreshadowing":
            return {
                "success": True,
                "data": {
                    "foreshadowing": self.load_context("foreshadowing"),
                }
            }
        elif skill_name == "style":
            return {
                "success": True,
                "data": {
                    "style": self.load_context("style"),
                }
            }
        else:
            return {"success": False, "error": f"Unknown skill: {skill_name}"}

    def _call_writer(
        self,
        chapter_id: str,
        objective: str,
        context_keys: List[str],
    ) -> Dict[str, Any]:
        """调用 Writer Agent 生成草稿。
        
        Args:
            chapter_id: 章节ID
            objective: 写作目标
            context_keys: 要加载的上下文键
            
        Returns:
            生成结果
        """
        from tools.agents.librarian import LibrarianAgent
        
        if not chapter_id:
            return {"success": False, "error": "chapter_id is required"}
        
        # 加载上下文
        context = {}
        for key in context_keys:
            value = self.load_context(key)
            if value:
                context[key] = value
        
        # 创建 Writer
        writer = LibrarianAgent(
            llm_client=self._llm_client,
            router=self._router,
        )
        
        # 生成草稿
        result = writer.generate_chapter(
            chapter_id=chapter_id,
            objective=objective,
            context=context,
        )
        
        # 提取草稿文本
        draft_text = result.draft if hasattr(result, 'draft') else str(result)
        
        return {
            "success": True,
            "chapter_id": chapter_id,
            "draft": draft_text[:2000] + "..." if len(draft_text) > 2000 else draft_text,
            "draft_length": len(draft_text),
        }

    def _call_reviewer(
        self,
        content: str,
        check_types: List[str],
    ) -> Dict[str, Any]:
        """调用 Reviewer Agent 进行逻辑检查。
        
        Args:
            content: 要检查的内容
            check_types: 检查类型
            
        Returns:
            检查结果
        """
        from tools.agents.lore_checker import LoreCheckerAgent
        
        if not content:
            return {"success": False, "error": "content is required"}
        
        # 创建 Reviewer
        reviewer = LoreCheckerAgent(
            llm_client=self._llm_client,
            router=self._router,
        )
        
        # 执行检查
        result = reviewer.check_draft(
            draft=content,
            forbidden=[],
            required=[],
        )
        
        return {
            "success": True,
            "passed": result.passed,
            "issues": result.errors + result.warnings,
            "suggestions": [],
        }

    def _call_stylist(
        self,
        content: str,
        style_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """调用 Stylist Agent 进行风格润色。
        
        Args:
            content: 要润色的内容
            style_id: 风格ID
            
        Returns:
            润色结果
        """
        from tools.agents.stylist import StylistAgent
        
        if not content:
            return {"success": False, "error": "content is required"}
        
        # 创建 Stylist
        stylist = StylistAgent(
            llm_client=self._llm_client,
            router=self._router,
            project_root=self.project_root,
            novel_id=self.novel_id or "",
        )
        
        # 执行润色 (polish 接受 text 参数，不是 content)
        result = stylist.polish(
            text=content,
            novel_id=style_id or self.novel_id,
        )
        
        # 提取润色后的文本
        polished_text = result.polished if hasattr(result, 'polished') else str(result)
        
        return {
            "success": True,
            "polished": polished_text[:2000] + "..." if len(polished_text) > 2000 else polished_text,
            "polished_length": len(polished_text),
        }
    def _fallback_welcome_response(self, session: "ConversationSession") -> "DirectorResponse":
        """无 LLM 时的欢迎回复。
        
        Args:
            session: 会话对象
            
        Returns:
            固定的欢迎消息响应
        """
        from tools.models.intent import DirectorResponse, SuggestedAction, TaskIntent
        
        return DirectorResponse(
            success=True,
            message="您好！我是 OpenWrite 创作助手。\n\n我可以：写章节、创建大纲、管理角色、埋设伏笔。\n\n请告诉我您想做什么？",
            detected_intent=TaskIntent.GENERAL_CHAT,
            confidence=0.5,
            session_id=session.session_id,
            suggested_actions=[
                SuggestedAction(
                    action="write_chapter",
                    label="写章节",
                    description="根据大纲生成章节内容",
                ),
                SuggestedAction(
                    action="outline_assist",
                    label="创建大纲",
                    description="创建或修改大纲",
                ),
                SuggestedAction(
                    action="project_init",
                    label="初始化项目",
                    description="初始化新小说项目",
                ),
            ],
        )


    def _fallback_help_response(self, session: "ConversationSession") -> "DirectorResponse":
        """无 LLM 且无 Skill 匹配时的帮助回复。
        
        Args:
            session: 会话对象
            
        Returns:
            帮助消息响应
        """
        from tools.models.intent import DirectorResponse, SuggestedAction, TaskIntent
        
        return DirectorResponse(
            success=True,
            message=("无法识别您的请求。\n\n"
                     "可用指令：\n"
                     "- 写章节：\"写第1章\" 或 \"/write\"\n"
                     "- 大纲：\"创建大纲\" 或 \"/outline\"\n"
                     "- 角色：\"创建角色\" 或 \"/character\"\n"
                     "- 世界观：\"查看世界观\" 或 \"/world\"\n"
                     "- 伏笔：\"伏笔管理\" 或 \"/foreshadowing\"\n"
                     "- 风格：\"风格分析\" 或 \"/style\"\n"
                     "- 项目：\"初始化项目\" 或 \"/project\"\n\n"
                     "请告诉我您想做什么？"),
            detected_intent=TaskIntent.UNKNOWN,
            confidence=0.0,
            session_id=session.session_id,
        )
    
    def _execute_skill_fallback(
        self,
        skill: "Skill",
        user_message: str,
        session: "ConversationSession",
        context: Dict[str, Any],
    ) -> "DirectorResponse":
        """执行 Skill 的基础响应（无工作流定义时）。
        
        Args:
            skill: 匹配的 Skill
            user_message: 用户消息
            session: 会话对象
            context: 上下文数据
            
        Returns:
            Skill 响应
        """
        from tools.models.intent import DirectorResponse, SuggestedAction, TaskIntent
        from skills.skill import Skill
        
        # 获取 Skill 描述和内容
        skill_desc = skill.description
        skill_content = skill.content[:500] if skill.content else ""
        
        # 构建响应消息
        message = f"**{skill.name}**\n\n{skill_desc}\n\n"
        
        # 添加可用操作提示
        if skill.list_workflows():
            message += f"可用工作流: {', '.join(skill.list_workflows())}\n"
        if skill.list_prompts():
            message += f"可用提示词: {', '.join(skill.list_prompts())}\n"
        
        # 根据 Skill 类型添加特定提示
        if skill.name == "character":
            message += "\n您可以：创建角色、查询角色、更新角色状态"
            suggested_actions = [
                SuggestedAction(action="create_character", label="创建角色", description="创建新角色"),
                SuggestedAction(action="query_character", label="查询角色", description="查询现有角色"),
            ]
        elif skill.name == "world":
            message += "\n您可以：添加实体、创建关系、冲突检查"
            suggested_actions = [
                SuggestedAction(action="add_entity", label="添加实体", description="添加世界观实体"),
                SuggestedAction(action="check_conflict", label="冲突检查", description="检查世界观一致性"),
            ]
        elif skill.name == "foreshadowing":
            message += "\n您可以：埋设伏笔、回收伏笔、查看待回收伏笔"
            suggested_actions = [
                SuggestedAction(action="plant_foreshadow", label="埋设伏笔", description="埋设新伏笔"),
                SuggestedAction(action="list_pending", label="待回收伏笔", description="查看待回收伏笔"),
            ]
        elif skill.name == "style":
            message += "\n您可以：初始化风格、合成风格、分析文本"
            suggested_actions = [
                SuggestedAction(action="init_style", label="初始化风格", description="初始化作品风格"),
                SuggestedAction(action="compose_style", label="合成风格", description="合成三层风格"),
            ]
        else:
            suggested_actions = []
        
        return DirectorResponse(
            success=True,
            message=message,
            detected_intent=self._map_skill_to_intent(skill.name),
            detected_workflow=f"{skill.name}_default",
            confidence=0.8,
            session_id=session.session_id,
            suggested_actions=suggested_actions,
        )
    
    def _map_skill_to_intent(self, skill_name: str) -> "TaskIntent":
        """将 Skill 名称映射到 TaskIntent。
        
        Args:
            skill_name: Skill 名称
            
        Returns:
            对应的 TaskIntent
        """
        from tools.models.intent import TaskIntent
        
        skill_to_intent = {
            "writing": TaskIntent.WRITE_CHAPTER,
            "outline": TaskIntent.OUTLINE_ASSIST,
            "character": TaskIntent.CHARACTER_CREATE,
            "world": TaskIntent.LORE_QUERY,
            "foreshadowing": TaskIntent.FORESHADOW_PLANT,
            "style": TaskIntent.STYLE_COMPOSE,
            "project": TaskIntent.PROJECT_INIT,
        }
        
        return skill_to_intent.get(skill_name, TaskIntent.UNKNOWN)

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
    # 意图识别（基于 LLM，移除硬匹配）
    # ============================================================

    def classify_intent(
        self,
        user_message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> "IntentDecision":
        """识别用户意图。

        **优先使用 LLM 理解意图，完全移除硬编码关键词匹配。**
        - 如果有 LLM，使用 LLM 进行意图识别
        - 如果无 LLM，只保留命令触发器 (/xxx) 作为快捷方式

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
        skills = list(self.skill_registry._skills.values())

        # 只使用 LLM 进行意图识别，不做任何关键词/命令匹配
        if self._llm_client and self._router:
            try:
                from tools.agents.intent_classifier import LLMIntentClassifier

                classifier = LLMIntentClassifier(
                    llm_client=self._llm_client,
                    router=self._router,
                )

                # 获取对话历史
                history = []
                if hasattr(self, '_sessions') and context.get("session_id"):
                    session = self._sessions.get(context["session_id"])
                    if session:
                        history = session.message_history

                result = classifier.classify(
                    user_message=user_message,
                    skills=skills,
                    history=history,
                    context=context,
                )

                return IntentDecision(
                    intent=result["intent"],
                    confidence=result["confidence"],
                    confidence_score=result["confidence_score"],
                    matched_keywords=result.get("entity_references", []),
                    reasoning=result.get("reasoning", ""),
                    tool_parameters={"skill": result.get("skill")} if result.get("skill") else {},
                    entity_references=result.get("entity_references", []),
                )

            except Exception as e:
                logger.warning(f"LLM 意图识别失败: {e}")
        
        # 无 LLM 或识别失败：返回 GENERAL_CHAT，让 LLM 直接处理对话
        logger.info("无 LLM 或意图识别失败，使用 GENERAL_CHAT")
        return IntentDecision(
            intent=TaskIntent.GENERAL_CHAT,
            confidence=IntentConfidence.LOW,
            confidence_score=0.0,
            matched_keywords=[],
            reasoning="",
            entity_references=self._extract_entities(user_message),
        )
        skills = list(self.skill_registry._skills.values())

        # 1. 检查命令触发器（快速路径，不调用 LLM）
        for skill in skills:
            if skill.trigger and user_message.strip().startswith(skill.trigger):
                logger.info(f"命令触发器匹配: {skill.trigger}")
                return IntentDecision(
                    intent=self._map_skill_to_intent(skill.name),
                    confidence=IntentConfidence.HIGH,
                    confidence_score=0.95,
                    matched_keywords=[skill.trigger],
                    reasoning=f"用户使用了命令触发器 {skill.trigger}",
                    tool_parameters={"skill": skill.name},
                    entity_references=self._extract_entities(user_message),
                )

        # 2. 使用 LLM 意图识别（如果有 LLM）
        if self._llm_client and self._router:
            try:
                from tools.agents.intent_classifier import LLMIntentClassifier

                classifier = LLMIntentClassifier(
                    llm_client=self._llm_client,
                    router=self._router,
                )

                # 获取对话历史
                history = []
                if hasattr(self, '_sessions') and context.get("session_id"):
                    session = self._sessions.get(context["session_id"])
                    if session:
                        history = session.message_history

                result = classifier.classify(
                    user_message=user_message,
                    skills=skills,
                    history=history,
                    context=context,
                )

                return IntentDecision(
                    intent=result["intent"],
                    confidence=result["confidence"],
                    confidence_score=result["confidence_score"],
                    matched_keywords=result.get("entity_references", []),
                    reasoning=result.get("reasoning", ""),
                    tool_parameters={"skill": result.get("skill")} if result.get("skill") else {},
                    entity_references=result.get("entity_references", []),
                )

            except Exception as e:
                logger.warning(f"LLM 意图识别失败: {e}")
                # 继续使用 fallback
        # 3. 无 LLM 可用：返回错误，提示用户配置 LLM 或使用命令触发器
        logger.warning("LLM 未配置，无法进行意图识别")
        return IntentDecision(
            intent=TaskIntent.GENERAL_CHAT,
            confidence=IntentConfidence.LOW,
            confidence_score=0.0,
            matched_keywords=[],
            reasoning="LLM 未配置。请配置 LLM 模型（访问 /settings）或使用命令触发器（如 /write, /outline）。",
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
            TaskIntent,
            IntentConfidence,
            IntentDecision,
        )

        context = context or {}

        # 1. 获取/创建会话


        # 1. 获取/创建会话
        session = self._get_or_create_session(session_id, context)
        session.add_message("user", user_message)

        # 2. 如果有 LLM，完全由 LLM 决定调用哪个工具（关闭硬匹配）
        if self._llm_client and self._router:
            # LLM Agentic 模式：让 LLM 自主决定调用哪个 Skill/工具
            response = self._generate_llm_response(user_message, session, context)
        else:
            # 无 LLM 时，使用规则引擎 fallback（硬匹配）
            matched_skill = self.skill_registry.match_trigger(user_message)
            
            if matched_skill:
                intent = IntentDecision(
                    intent=self._map_skill_to_intent(matched_skill.name),
                    confidence=IntentConfidence.HIGH,
                    confidence_score=0.9,
                    tool_parameters={"skill": matched_skill.name},
                    matched_keywords=[matched_skill.name],
                    reasoning=f"Skill 触发器匹配: {matched_skill.name}",
                )
                workflow_info = self._detect_workflow(intent, user_message, context)
                if workflow_info:
                    response = self._execute_workflow(workflow_info, user_message, session, intent, context)
                else:
                    response = self._execute_skill_fallback(matched_skill, user_message, session, context)
            else:
                response = self._fallback_help_response(session)

        # 3. 保存 agent 回复到会话
        if response.message:
            session.add_message("assistant", response.message)
            if len(session.message_history) >= 2:
                self._save_session(session.session_id)

        return response

    # 向后兼容别名
    process_request_with_workflow = process_request

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
        # 保存到磁盘
        self._save_session(new_session.session_id)
        return new_session

    def _detect_workflow(
        self,
        intent: "IntentDecision",
        user_message: str,
        context: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """检测工作流。
        
        只使用 LLM 识别的意图，不使用关键词匹配。
        如果没有 LLM，返回 None，让 process_request 走 LLM 对话路径。

        Args:
            intent: 意图识别结果
            user_message: 用户消息
            context: 上下文数据

        Returns:
            工作流定义，无匹配返回 None
        """
        # 只使用 LLM 识别的意图
        skill_name = intent.tool_parameters.get("skill")
        if skill_name:
            skill = self.skill_registry.get(skill_name)
            if skill:
                workflow = skill.get_workflow("main")
                if workflow:
                    return {
                        "skill": skill,
                        "workflow": workflow,
                        "workflow_id": f"{skill_name}_main",
                    }
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
        elif skill.name == "project":
            return self._execute_project_workflow(
                user_message, session, intent, context, skill
            )
        elif skill.name == "character":
            return self._execute_character_workflow(
                user_message, session, intent, context, skill
            )
        elif skill.name == "world":
            return self._execute_world_workflow(
                user_message, session, intent, context, skill
            )
        elif skill.name == "foreshadowing":
            return self._execute_foreshadowing_workflow(
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
        """执行大纲工作流。
        
        支持的操作：
        - 创建大纲：从零创建四级大纲
        - 修改大纲：修改现有大纲
        - 查看大纲：查看大纲结构
        """
        from tools.models.intent import DirectorResponse, SuggestedAction
        
        # 加载现有大纲
        outline = self.load_context("outline")
        
        # 获取工作流状态
        workflow_state = session.workflow_context.get("outline_workflow", {})
        current_phase = workflow_state.get("phase", "menu")
        
        # 根据当前阶段和用户输入决定下一步
        user_lower = user_message.lower().strip()
        
        # 如果是新会话或用户想看菜单
        if current_phase == "menu" or user_lower in ["大纲", "大纲管理", "outline"]:
            # 检查是否已有大纲
            if outline:
                message = f"大纲管理\n\n当前已有大纲，请选择操作：\n\n"
                message += f"当前大纲：{outline[:200]}...\n\n" if len(outline) > 200 else f"当前大纲：{outline}\n\n"
            else:
                message = "大纲管理\n\n当前暂无大纲，请选择操作：\n\n"
            
            message += "1. 创建大纲 — 从零创建四级大纲（总纲→篇纲→节纲→章纲）\n"
            if outline:
                message += "2. 修改大纲 — 修改现有大纲\n"
                message += "3. 查看大纲 — 查看完整大纲结构\n"
            
            return DirectorResponse(
                success=True,
                message=message,
                detected_intent=intent.intent,
                detected_workflow="outline_manage",
                confidence=intent.confidence_score,
                session_id=session.session_id,
                reasoning="大纲管理菜单",
                suggested_actions=[
                    SuggestedAction(
                        action="start_create_outline",
                        label="创建新大纲",
                        description="从零开始创建四级大纲",
                    ),
                ] + ([
                    SuggestedAction(
                        action="view_outline",
                        label="查看现有大纲",
                        description="查看当前大纲结构",
                    ),
                ] if outline else []),
            )
        
        # 用户想创建大纲
        if "创建" in user_message or "新建" in user_message or user_lower == "1":
            # 进入创建流程
            session.workflow_context["outline_workflow"] = {"phase": "collect_master"}
            
            message = "## 创建大纲\n\n"
            message += "我来帮您创建四级大纲：\n\n"
            message += "**第一步：确定总纲**\n\n"
            message += "请告诉我以下信息：\n"
            message += "- **书名**：小说的名称\n"
            message += "- **核心主题**：一句话概括全书主题\n"
            message += "- **结局走向**：大团圆/悲剧/开放式\n"
            message += "- **预计字数**：如 100 万字\n"
            
            return DirectorResponse(
                success=True,
                message=message,
                detected_intent=intent.intent,
                detected_workflow="outline_create",
                confidence=intent.confidence_score,
                session_id=session.session_id,
                reasoning="开始创建大纲，收集总纲信息",
            )
        
        # 用户想查看大纲
        if "查看" in user_message or "结构" in user_message or user_lower == "3":
            if outline:
                message = f"## 大纲结构\n\n{outline}"
            else:
                message = "暂无大纲，请先创建大纲。"
            
            return DirectorResponse(
                success=True,
                message=message,
                detected_intent=intent.intent,
                detected_workflow="outline_view",
                confidence=intent.confidence_score,
                session_id=session.session_id,
                reasoning="查看大纲结构",
            )
        
        # 用户想修改大纲
        if "修改" in user_message or "调整" in user_message or user_lower == "2":
            if not outline:
                message = "暂无大纲，请先创建大纲。"
            else:
                message = "## 修改大纲\n\n"
                message += "请告诉我您想修改哪部分？\n"
                message += "- 总纲（书名、主题、结局）\n"
                message += "- 篇纲（大剧情弧）\n"
                message += "- 节纲（情节单元）\n"
                message += "- 章纲（具体章节）\n"
            
            return DirectorResponse(
                success=True,
                message=message,
                detected_intent=intent.intent,
                detected_workflow="outline_modify",
                confidence=intent.confidence_score,
                session_id=session.session_id,
                reasoning="修改大纲",
            )
        
        # 如果正在创建大纲流程中，处理用户输入
        if current_phase == "collect_master":
            # 保存用户输入的总纲信息
            session.workflow_context["outline_workflow"]["master_input"] = user_message
            session.workflow_context["outline_workflow"]["phase"] = "confirm_master"
            
            message = f"## 确认总纲信息\n\n"
            message += f"您提供的信息：\n\n{user_message}\n\n"
            message += "---\n"
            message += "请确认是否正确？如需修改请直接告诉我。"
            
            return DirectorResponse(
                success=True,
                message=message,
                detected_intent=intent.intent,
                detected_workflow="outline_create",
                confidence=intent.confidence_score,
                session_id=session.session_id,
                reasoning="确认总纲信息",
                suggested_actions=[
                    SuggestedAction(
                        action="confirm_master",
                        label="确认，继续规划篇纲",
                        description="确认总纲，进入篇纲规划",
                    ),
                ],
            )
        
        # 默认返回菜单
        message = "请选择大纲操作：创建大纲 / 修改大纲 / 查看大纲"
        return DirectorResponse(
            success=True,
            message=message,
            detected_intent=intent.intent,
            detected_workflow="outline_manage",
            confidence=intent.confidence_score,
            session_id=session.session_id,
            reasoning="大纲管理",
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

    def _execute_project_workflow(
        self,
        user_message: str,
        session: "ConversationSession",
        intent: "IntentDecision",
        context: Dict[str, Any],
        skill: "Skill",
    ) -> "DirectorResponse":
        """执行项目管理工作流。"""
        from tools.models.intent import DirectorResponse, SuggestedAction
        
        # 检查项目状态
        project_status = "未初始化"
        if self.novel_id:
            outline = self.load_context("outline")
            characters = self.load_context("characters")
            if outline:
                project_status = "已配置（有大纲）"
            elif characters:
                project_status = "已配置（有角色）"
            else:
                project_status = "已初始化（空）"
        
        message = f"项目管理\n\n"
        message += f"当前项目：{self.novel_id or '未设置'}\n"
        message += f"状态：{project_status}\n\n"
        message += "请选择操作：\n"
        message += "1. 初始化新项目\n"
        message += "2. 查看项目状态\n"
        message += "3. 配置 LLM\n"
        
        return DirectorResponse(
            success=True,
            message=message,
            detected_intent=intent.intent,
            detected_workflow="project_manage",
            confidence=intent.confidence_score,
            session_id=session.session_id,
            reasoning="项目管理工作流已启动",
            suggested_actions=[
                SuggestedAction(
                    action="init_project",
                    label="初始化项目",
                    description="创建新的小说项目",
                ),
                SuggestedAction(
                    action="view_status",
                    label="查看状态",
                    description="查看当前项目状态",
                ),
            ],
        )

    def _execute_character_workflow(
        self,
        user_message: str,
        session: "ConversationSession",
        intent: "IntentDecision",
        context: Dict[str, Any],
        skill: "Skill",
    ) -> "DirectorResponse":
        """执行角色管理工作流。"""
        from tools.models.intent import DirectorResponse, SuggestedAction
        
        characters = self.load_context("characters")
        
        message = "角色管理\n\n"
        message += f"当前状态：{characters or '暂无角色'}\n\n"
        message += "请选择操作：\n"
        message += "1. 创建角色\n"
        message += "2. 查看角色\n"
        message += "3. 修改角色\n"
        
        return DirectorResponse(
            success=True,
            message=message,
            detected_intent=intent.intent,
            detected_workflow="character_manage",
            confidence=intent.confidence_score,
            session_id=session.session_id,
            reasoning="角色管理工作流已启动",
            suggested_actions=[
                SuggestedAction(
                    action="create_character",
                    label="创建角色",
                    description="添加新角色",
                ),
                SuggestedAction(
                    action="list_characters",
                    label="查看角色",
                    description="查看所有角色",
                ),
            ],
        )

    def _execute_world_workflow(
        self,
        user_message: str,
        session: "ConversationSession",
        intent: "IntentDecision",
        context: Dict[str, Any],
        skill: "Skill",
    ) -> "DirectorResponse":
        """执行世界观管理工作流。"""
        from tools.models.intent import DirectorResponse, SuggestedAction
        
        world = self.load_context("world")
        
        message = "世界观管理\n\n"
        message += f"当前状态：{world or '暂无世界观设定'}\n\n"
        message += "请选择操作：\n"
        message += "1. 添加实体\n"
        message += "2. 查看世界观\n"
        message += "3. 检查冲突\n"
        
        return DirectorResponse(
            success=True,
            message=message,
            detected_intent=intent.intent,
            detected_workflow="world_manage",
            confidence=intent.confidence_score,
            session_id=session.session_id,
            reasoning="世界观管理工作流已启动",
            suggested_actions=[
                SuggestedAction(
                    action="add_entity",
                    label="添加实体",
                    description="添加地点、势力、物品等",
                ),
                SuggestedAction(
                    action="view_world",
                    label="查看世界观",
                    description="查看所有世界观设定",
                ),
            ],
        )

    def _execute_foreshadowing_workflow(
        self,
        user_message: str,
        session: "ConversationSession",
        intent: "IntentDecision",
        context: Dict[str, Any],
        skill: "Skill",
    ) -> "DirectorResponse":
        """执行伏笔管理工作流。"""
        from tools.models.intent import DirectorResponse, SuggestedAction
        
        foreshadowing = self.load_context("foreshadowing")
        
        message = "伏笔管理\n\n"
        message += f"当前状态：{foreshadowing or '暂无伏笔'}\n\n"
        message += "请选择操作：\n"
        message += "1. 添加伏笔\n"
        message += "2. 查看伏笔\n"
        message += "3. 检查伏笔状态\n"
        
        return DirectorResponse(
            success=True,
            message=message,
            detected_intent=intent.intent,
            detected_workflow="foreshadowing_manage",
            confidence=intent.confidence_score,
            session_id=session.session_id,
            reasoning="伏笔管理工作流已启动",
            suggested_actions=[
                SuggestedAction(
                    action="add_foreshadowing",
                    label="添加伏笔",
                    description="埋设新伏笔",
                ),
                SuggestedAction(
                    action="list_foreshadowing",
                    label="查看伏笔",
                    description="查看所有伏笔",
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
        """无工作流时的默认处理 - 所有请求都走 LLM。"""
        from tools.models.intent import DirectorResponse, SuggestedAction

        # 有 LLM 时，直接让 LLM 处理所有请求
        if self._llm_client and self._router:
            return self._generate_llm_response(user_message, session, context)
        
        # 无 LLM 时返回提示
        return DirectorResponse(
            success=True,
            message="LLM 未配置。请在 /settings 页面配置 API Key 后重试。",
            detected_intent=intent.intent,
            confidence=intent.confidence_score,
            session_id=session.session_id,
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

        # 检测严格模式 - 不再硬编码判断严格模式，由子 agent 自行决定
        suggested_strict = False

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
        if foreshadowing_text and len(foreshadowing_text) > 10:
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



    def _extract_priority_elements(
        self, objective: str, context: Dict[str, str]
    ) -> List[str]:
        """提取重点要素。"""
        elements: List[str] = []

        # 伏笔 - 直接检查是否有内容
        foreshadowing = context.get("foreshadowing", "")
        if foreshadowing and len(foreshadowing) > 10:  # 有实际内容
            ids = re.findall(r"(\w+)\(权重=(\d+)", foreshadowing)
            high_weight = [nid for nid, w in ids if int(w) >= 7]
            if high_weight:
                elements.append(f"高权重伏笔: {', '.join(high_weight[:3])}")

        # 角色
        characters = context.get("characters", "")
        if characters and len(characters) > 10:
            names = re.findall(r"(\S+?)\(境界=", characters)
            if names:
                elements.append(f"涉及角色: {', '.join(names[:4])}")

        # 场景
        scenes = context.get("scenes", "")
        if scenes and len(scenes) > 5 and "未标注" not in scenes:
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
    # Session Management (向后兼容)
    # ============================================================

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
            # 同时删除持久化文件
            self._delete_session_file(session_id)
            return True
        return False

    def _load_sessions(self) -> None:
        """启动时加载持久化的 sessions。"""
        import json
        
        if not self._sessions_dir.exists():
            return
        
        for session_file in self._sessions_dir.glob("*.json"):
            try:
                with open(session_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                from tools.models.intent import ConversationSession
                session = ConversationSession(**data)
                self._sessions[session.session_id] = session
                
            except Exception as e:
                logger.warning(f"Failed to load session {session_file}: {e}")
        
        logger.info(f"Loaded {len(self._sessions)} sessions from disk")

    def _save_session(self, session_id: str) -> None:
        """保存 session 到磁盘。"""
        import json
        
        session = self._sessions.get(session_id)
        if not session:
            return
        
        session_file = self._sessions_dir / f"{session_id}.json"
        try:
            with open(session_file, "w", encoding="utf-8") as f:
                json.dump(session.model_dump(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save session {session_id}: {e}")

    def _delete_session_file(self, session_id: str) -> None:
        """删除 session 文件。"""
        session_file = self._sessions_dir / f"{session_id}.json"
        if session_file.exists():
            session_file.unlink()

# ============================================================
# 向后兼容：DirectorAgent 别名
# ============================================================

# ============================================================
# 向后兼容：DirectorAgent 别名
# ============================================================

# 为了向后兼容，保留 DirectorAgent 作为 SkillBasedDirector 的别名
# 但实际上应该使用 SkillBasedDirector
DirectorAgent = SkillBasedDirector
