"""Dante 长会话主 Agent。"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..goethe import build_prompt_session, is_exit_command
from ..llm import LLMClient, LLMConfig, Message
from ..outline_contract import OUTLINE_MARKDOWN_CONTRACT
from ..runtime_skills import (
    RuleCompiler,
    RuntimeSkillResolver,
    extract_explicit_skill_mentions,
    render_runtime_context,
)
from ..shared_documents import CHARACTER_MARKDOWN_CONTRACT
from .book_state import BookState, BookStateStore
from .confirmation import (
    guard_confirmable_executors,
    remember_document_edit_previews,
    remember_relation_previews,
)
from .manuscript_safety import manual_chapter_delete_guidance
from .react import OPENWRITE_TOOLS, ReActAgent, ToolDefinition
from .session_state import DanteSessionState, SessionStateStore, SessionTurn
from .tool_layers import build_dante_tool_layers
from .toolkits import DANTE_DIRECT_TOOLKIT

DEFAULT_DANTE_SYSTEM_PROMPT = (
    "你是 OpenWrite 的 Dante，长期会话正文创作 Agent。"
    "你的默认职责是基于已确认的人物、设定和大纲持续推进正文写作、预检、审查与状态结算。"
    "当写作推进需要修正人物、设定或大纲时，你可以提出并执行必要回修，"
    "但不要把自己当成建书向导或一次性 wizard。"
    "若作者意图、背景、人物或大纲明显未就绪，先明确告知用户应先回到 Goethe 补齐资产，不要硬写。"
    "优先保持对话连续性，并让一切回修都为正文推进服务。"
    "修改人物或世界关系时，先用 search_relation_targets/get_world_relations 定位，"
    "再用 edit_world_relation 或 edit_world_relations 且 confirm=false 预览 diff；"
    "relations 必须优先使用查询返回的正式实体 ID；单条关系确认时携带 base_revision；"
    "批量关系确认时只携带 preview_token/preview_tokens，不得重新生成 relations，"
    "并设置 confirm=true 写入。"
    "普通讨论、分析和未确认建议不得写入关系。"
    "修改已有角色、故事资料、世界设定或正文时，先 read_project_document 读取 revision，"
    "再 edit_project_document(confirm=false) 预览 diff；长范围使用唯一的 start_text/end_text，"
    "短句才使用 old_text；只有用户明确确认后才仅使用预览返回的"
    " preview_token 和 confirm=true 写入，不得重新生成 path/edits。"
    "写章前优先用 get_outline_structure 定位明确的章纲 ID、所属卷幕节与建议目标，"
    "不要仅按最大章节号盲目创建下一章。"
    "如果状态显示 pending_confirmation=outline_scope，或阶段仍是 rolling_outline 但用户明确要求"
    "“根据现在/当前大纲写下一章”、“就按这个大纲写”或等价表达，先调用 confirm_outline_scope，"
    "再执行章节预检与写作。"
    "用户要求修改大纲时，先用 get_outline_structure 获取 revision，"
    "再用 edit_outline_structure(confirm=false) 预览；"
    "只有用户明确确认后才用相同 revision 和 confirm=true 写入；"
    "不要整篇重写或覆盖已有大纲；局部修改按下面的 revision 预览流程处理。"
    "用户要求删除已写正文、现有章节或全部章节时，不得调用大纲编辑或文档编辑工具绕过，"
    "也不得声称重写 src/outline.md 可以删除正文；应说明为避免 AI 误删，"
    "必须由用户在 Studio 正文页打开最新章节并点击“删除正文”，按章节 ID 手动确认，"
    "如需清空则从最新章依次向前删除。"
) + "\n\n" + OUTLINE_MARKDOWN_CONTRACT + "\n\n" + CHARACTER_MARKDOWN_CONTRACT

_DANTE_ACTION_TOOL_DEFINITIONS = [
    ToolDefinition(
        name="summarize_ideation",
        description="汇总当前收集到的想法，生成会话共识摘要。",
        parameters={"type": "object", "properties": {}},
    ),
    ToolDefinition(
        name="confirm_ideation_summary",
        description="确认或修正当前的想法摘要。",
        parameters={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "确认文本"},
            },
        },
    ),
    ToolDefinition(
        name="generate_outline_draft",
        description="基于共识摘要并按系统提示中的大纲写入契约生成大纲草案。",
        parameters={
            "type": "object",
            "properties": {
                "request_text": {"type": "string", "description": "大纲生成请求"},
            },
            "required": ["request_text"],
        },
    ),
    ToolDefinition(
        name="confirm_outline_scope",
        description=(
            "确认当前可写大纲范围可作为章节写作依据，并解除 outline_scope 阻塞。"
            "仅在用户明确要求按当前/现有大纲继续写作或明确确认大纲时使用。"
        ),
        parameters={"type": "object", "properties": {}},
    ),
    ToolDefinition(
        name="run_chapter_preflight",
        description="为指定章节执行写作前预检。",
        parameters={
            "type": "object",
            "properties": {
                "chapter_id": {"type": "string", "description": "章节 ID"},
            },
            "required": ["chapter_id"],
        },
    ),
    ToolDefinition(
        name="delegate_chapter_write",
        description="基于已确认资产委派章节写作，并按需要触发审查。",
        parameters={
            "type": "object",
            "properties": {
                "chapter_id": {"type": "string", "description": "章节 ID"},
                "guidance": {"type": "string", "description": "额外写作要求"},
                "target_words": {"type": "integer", "description": "目标字数"},
                "temperature": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 2,
                    "default": 0.7,
                    "description": "生成温度，默认 0.7",
                },
            },
            "required": ["chapter_id"],
        },
    ),
    ToolDefinition(
        name="delegate_chapter_review",
        description="对指定章节执行独立审查，检查设定冲突、连续性和质量问题。",
        parameters={
            "type": "object",
            "properties": {
                "chapter_id": {"type": "string", "description": "章节 ID"},
                "guidance": {"type": "string", "description": "额外审查要求"},
                "strict": {"type": "boolean", "description": "warning 也视为不通过"},
                "dimensions": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 1, "maximum": 37},
                    "description": "只审查指定维度；省略时审查全部维度",
                },
            },
            "required": ["chapter_id"],
        },
    ),
]


def _build_dante_tool_definitions(
    allowed_tools: set[str] | None = None,
) -> list[ToolDefinition]:
    direct_tool_defs = [
        tool for tool in OPENWRITE_TOOLS if tool.name in DANTE_DIRECT_TOOLKIT
    ]
    combined = direct_tool_defs + _DANTE_ACTION_TOOL_DEFINITIONS
    if allowed_tools is None:
        return combined
    return [tool for tool in combined if tool.name in allowed_tools]


@dataclass
class DanteStartupSnapshot:
    session_state: DanteSessionState
    book_state: BookState
    recovery_prompt: str


@dataclass
class DanteRunResult:
    success: bool
    exit_reason: str = ""
    turns_processed: int = 0
    startup: DanteStartupSnapshot | None = None


class DanteChatAgent:
    def __init__(
        self,
        project_root: Path,
        novel_id: str,
        *,
        react_agent: Any | None = None,
        session_store: SessionStateStore | None = None,
        book_state_store: BookStateStore | None = None,
        prompt_session_factory: Callable[[], Any] | None = None,
        llm_client_factory: Callable[[], LLMClient] | None = None,
        tool_executors: dict[str, Callable[[dict[str, Any]], Any]] | None = None,
        action_executors: dict[str, Callable[[dict[str, Any]], Any]] | None = None,
        tool_layer_factory: Callable[[Path], dict[str, object]] | None = None,
        activity_callback: Callable[[dict[str, Any]], None] | None = None,
        prompt_text: str = "\n🕯️ Dante> ",
    ):
        self.project_root = Path(project_root).resolve()
        self.novel_id = novel_id
        self.session_store = session_store or SessionStateStore(self.project_root, novel_id)
        self.book_state_store = book_state_store or BookStateStore(
            self.project_root, novel_id
        )
        self.prompt_session_factory = (
            prompt_session_factory
            or (lambda: build_prompt_session(prompt_style={"prompt": "#ansibrightblue bold"}))
        )
        self.llm_client_factory = llm_client_factory or self._build_default_llm_client
        self.tool_layer_factory = tool_layer_factory or build_dante_tool_layers
        self._use_default_tool_layers = tool_executors is None and action_executors is None
        self._tool_layers: dict[str, object] | None = None
        self.tool_executors = tool_executors or {}
        self.action_executors = action_executors or {}
        self.activity_callback = activity_callback
        self.prompt_text = prompt_text
        self._react_agent = react_agent
        self._active_user_instruction = ""
        self._react_agent_factory = (
            self._build_default_react_agent if react_agent is None else None
        )

        if self._react_agent is not None:
            self._ensure_react_agent_surface(self._react_agent)

        self.session_state: DanteSessionState | None = None
        self.book_state: BookState | None = None
        self.recovery_prompt: str = ""
        self.startup_snapshot: DanteStartupSnapshot | None = None

    def startup(self) -> DanteStartupSnapshot:
        session_state = self.session_store.load_or_create()
        book_state = self.book_state_store.load_or_create()
        self.session_state = session_state
        self.book_state = book_state
        self.recovery_prompt = self.build_recovery_prompt()
        self.startup_snapshot = DanteStartupSnapshot(
            session_state=session_state,
            book_state=book_state,
            recovery_prompt=self.recovery_prompt,
        )
        return self.startup_snapshot

    def build_recovery_prompt(self) -> str:
        session_state = self._require_session_state()
        book_state = self._refresh_book_state()
        onboarding = self._load_onboarding_snapshot()
        is_first_run = not (
            session_state.conversation_summary
            or session_state.recent_turns
            or session_state.last_action
        )

        if is_first_run:
            lines = [
                "Dante 首次写作会话。",
                "默认职责：在已确认资产上推进正文写作、预检、审查与状态结算。",
            ]
        else:
            lines = [
                "Dante 已恢复，可以继续上次的长会话。",
                f"会话: {session_state.session_id} / active_agent={session_state.active_agent}",
            ]

        lines.extend(
            [
                f"当前阶段: {book_state.stage.value}",
                (
                    "当前篇/节/章: "
                    f"{book_state.current_arc or '未设置'} / "
                    f"{book_state.current_section or '未设置'} / "
                    f"{book_state.current_chapter or '未设置'}"
                ),
            ]
        )

        if onboarding.get("missing_labels"):
            lines.append("资产缺口: " + "、".join(onboarding["missing_labels"]))
            if not onboarding.get("ready_to_write"):
                lines.append(
                    "写作资产未就绪。请先切到 Goethe 补齐作者意图、背景、人物与可写大纲，"
                    "再回来从 get_outline_structure → preflight → write 推进。"
                )
            else:
                lines.append(
                    "建议顺序：get_outline_structure → confirm_outline_scope（如需）"
                    " → run_chapter_preflight → delegate_chapter_write → review。"
                )
        if book_state.pending_confirmation:
            lines.append(f"待确认: {book_state.pending_confirmation}")
        if book_state.blocking_reason:
            lines.append(f"阻塞: {book_state.blocking_reason}")
        if book_state.last_agent_action:
            lines.append(f"最近动作: {book_state.last_agent_action}")
        if session_state.conversation_summary:
            lines.append(f"会话摘要: {session_state.conversation_summary}")
        if session_state.working_memory:
            memory_bits = ", ".join(
                f"{key}={value}" for key, value in session_state.working_memory.items()
            )
            lines.append(f"工作记忆: {memory_bits}")
        if session_state.open_questions:
            lines.append("未决问题: " + "；".join(session_state.open_questions))
        if session_state.recent_files:
            lines.append("最近文件: " + "；".join(session_state.recent_files))
        return "\n".join(lines)

    def _load_onboarding_snapshot(self) -> dict[str, Any]:
        try:
            from tools.novel_workspace import build_onboarding_checklist

            return build_onboarding_checklist(self.project_root, self.novel_id)
        except Exception:
            return {}

    def run(self) -> DanteRunResult:
        startup = self.startup()
        session = self.prompt_session_factory()
        react_agent = self._get_react_agent()

        print("\n" + "=" * 50)
        print("   OpenWrite Dante 长会话主 Agent")
        print("   (输入 '退出'、'quit'、'exit' 或 'q' 可结束对话)")
        print("=" * 50)
        print(startup.recovery_prompt)

        turns_processed = 0
        while True:
            try:
                user_input = session.prompt(self.prompt_text).strip()
            except KeyboardInterrupt:
                state = self._require_session_state()
                state.last_action = "keyboard_interrupt"
                self.session_store.save(self._require_session_state())
                return DanteRunResult(
                    success=True,
                    exit_reason="keyboard_interrupt",
                    turns_processed=turns_processed,
                    startup=startup,
                )

            if not user_input:
                continue

            if is_exit_command(user_input):
                state = self._require_session_state()
                state.last_action = "exit"
                self.session_store.save(state)
                print("\n好的，随时欢迎回来！")
                return DanteRunResult(
                    success=True,
                    exit_reason=user_input,
                    turns_processed=turns_processed,
                    startup=startup,
                )

            self._append_user_turn(user_input)
            state = self._require_session_state()
            state.last_action = "chat"
            self.session_store.save(state)
            response_text = manual_chapter_delete_guidance(user_input)
            if response_text:
                state.last_action = "manual_chapter_delete_guidance"
            else:
                try:
                    response_text = self._run_react_agent(react_agent, user_input)
                except Exception:
                    state.last_action = "react_error"
                    self.session_store.save(state)
                    raise
            if response_text:
                self._append_assistant_turn(response_text)
                print(f"\n🤖 Dante: {response_text}")
            self.session_store.save(self._require_session_state())
            turns_processed += 1

    def respond(self, user_input: str) -> str:
        """Process one persisted Dante turn for non-terminal clients."""
        text = str(user_input or "").strip()
        if not text:
            raise ValueError("消息不能为空")
        if self.session_state is None or self.book_state is None:
            self.startup()
        self._active_user_instruction = text
        self._append_user_turn(text)
        state = self._require_session_state()
        state.last_action = "chat"
        self.session_store.save(state)
        response_text = manual_chapter_delete_guidance(text)
        if response_text:
            state.last_action = "manual_chapter_delete_guidance"
            self._active_user_instruction = ""
        else:
            try:
                response_text = self._run_react_agent(self._get_react_agent(), text)
            except Exception:
                state.last_action = "react_error"
                self.session_store.save(state)
                raise
        if response_text:
            self._append_assistant_turn(response_text)
        self.session_store.save(self._require_session_state())
        return response_text

    def _build_default_llm_client(self) -> LLMClient:
        return LLMClient(LLMConfig.from_env())

    def _build_default_react_agent(self) -> ReActAgent:
        client = self.llm_client_factory()
        allowed_tools, runtime_prompt = self._runtime_surface()
        react_agent = ReActAgent(
            client=client,
            model=client.config.model,
            tools=_build_dante_tool_definitions(allowed_tools),
            system_prompt=f"{DEFAULT_DANTE_SYSTEM_PROMPT}\n\n{runtime_prompt}",
            max_turns=20,
            activity_callback=self.activity_callback,
        )
        if self._combined_tool_executors():
            react_agent._register_tool_executors(self._combined_tool_executors())
        return react_agent

    def _get_react_agent(self) -> Any:
        if self._react_agent is None:
            self._react_agent = self._react_agent_factory()
        self._ensure_react_agent_surface(self._react_agent)
        return self._react_agent

    def _ensure_react_agent_surface(self, react_agent: Any) -> None:
        if react_agent is None:
            return
        allowed_tools, runtime_prompt = self._runtime_surface()
        combined_tools = _build_dante_tool_definitions(allowed_tools)
        canonical_tools = {tool.name: tool for tool in combined_tools}
        if hasattr(react_agent, "tools"):
            if self._react_agent_factory is not None:
                react_agent.tools = combined_tools
            else:
                existing_tools = list(getattr(react_agent, "tools", []) or [])
                merged_tools = []
                seen: set[str] = set()
                for tool in existing_tools:
                    tool_name = getattr(tool, "name", "")
                    if not tool_name:
                        merged_tools.append(tool)
                        continue
                    canonical_tool = canonical_tools.get(tool_name)
                    if canonical_tool is not None:
                        merged_tools.append(canonical_tool)
                        seen.add(tool_name)
                    else:
                        merged_tools.append(tool)
                for tool_name, canonical_tool in canonical_tools.items():
                    if tool_name not in seen and all(
                        getattr(tool, "name", "") != tool_name for tool in merged_tools
                    ):
                        merged_tools.append(canonical_tool)
                react_agent.tools = merged_tools
        if self._react_agent_factory is not None and hasattr(react_agent, "system_prompt"):
            react_agent.system_prompt = f"{DEFAULT_DANTE_SYSTEM_PROMPT}\n\n{runtime_prompt}"
        if self._combined_tool_executors() and hasattr(react_agent, "_register_tool_executors"):
            react_agent._register_tool_executors(self._combined_tool_executors())
        if hasattr(react_agent, "activity_callback"):
            react_agent.activity_callback = self.activity_callback

    def _run_react_agent(self, react_agent: Any, instruction: str) -> str:
        self._active_user_instruction = instruction
        try:
            self._ensure_react_agent_surface(react_agent)
            result = react_agent.run(
                instruction,
                context_messages=self._build_context_messages(include_recent_turns=False),
            )
            if inspect.isawaitable(result):
                result = asyncio.run(result)
            if result is None:
                return ""
            if isinstance(result, str):
                return result.strip()
            if hasattr(result, "content"):
                content = getattr(result, "content", "")
                return str(content).strip()
            if isinstance(result, dict):
                content = result.get("content", "")
                return str(content).strip()
            return str(result).strip()
        finally:
            self._active_user_instruction = ""

    def _build_context_messages(self, *, include_recent_turns: bool = True) -> list[Message]:
        session_state = self._require_session_state()
        # Reload: the snapshot taken in startup() goes stale as soon as any tool
        # action advances the book, and the LLM was then told a stage and chapter
        # the book had already left.
        book_state = self._refresh_book_state()
        context_messages: list[Message] = []

        if session_state.conversation_summary:
            context_messages.append(
                Message("assistant", f"会话摘要: {session_state.conversation_summary}")
            )

        if session_state.working_memory:
            memory_bits = ", ".join(
                f"{key}={value}" for key, value in session_state.working_memory.items()
            )
            context_messages.append(Message("assistant", f"工作记忆: {memory_bits}"))

        recent_turns = session_state.recent_turns
        if not include_recent_turns and recent_turns:
            recent_turns = recent_turns[:-1]

        if recent_turns:
            recent_lines = [
                f"{turn.role}: {turn.content}" for turn in recent_turns
            ]
            context_messages.append(
                Message("assistant", "最近轮次:\n" + "\n".join(recent_lines))
            )

        if session_state.open_questions:
            context_messages.append(
                Message("assistant", "未决问题: " + "；".join(session_state.open_questions))
            )

        if session_state.recent_files:
            context_messages.append(
                Message("assistant", "最近文件: " + "；".join(session_state.recent_files))
            )

        context_messages.append(
            Message(
                "assistant",
                (
                    "书状态: "
                    f"stage={book_state.stage.value}, "
                    f"arc={book_state.current_arc or '未设置'}, "
                    f"section={book_state.current_section or '未设置'}, "
                    f"chapter={book_state.current_chapter or '未设置'}, "
                    f"pending={book_state.pending_confirmation or '无'}, "
                    f"blocking={book_state.blocking_reason or '无'}, "
                    f"last_action={book_state.last_agent_action or '无'}"
                ),
            )
        )
        return context_messages

    def _combined_tool_executors(self) -> dict[str, Callable[[dict[str, Any]], Any]]:
        combined: dict[str, Callable[[dict[str, Any]], Any]] = {}
        if self._use_default_tool_layers:
            layers = self._load_tool_layers()
            direct = layers.get("direct_tool_executors", {})
            actions = layers.get("action_tool_executors", {})
            if isinstance(direct, dict):
                combined.update(direct)
            if isinstance(actions, dict):
                combined.update(actions)
        combined.update(self.tool_executors)
        combined.update(self.action_executors)
        combined = remember_document_edit_previews(
            combined,
            working_memory=lambda: (
                self.session_state.working_memory if self.session_state is not None else {}
            ),
            persist=lambda: (
                self.session_store.save(self.session_state)
                if self.session_state is not None
                else None
            ),
            instruction=lambda: self._active_user_instruction,
        )
        combined = remember_relation_previews(
            combined,
            working_memory=lambda: (
                self.session_state.working_memory if self.session_state is not None else {}
            ),
            persist=lambda: (
                self.session_store.save(self.session_state)
                if self.session_state is not None
                else None
            ),
            instruction=lambda: self._active_user_instruction,
        )
        return guard_confirmable_executors(
            combined,
            instruction=lambda: self._active_user_instruction,
        )

    def _load_tool_layers(self) -> dict[str, object]:
        if self._tool_layers is None:
            self._tool_layers = dict(self.tool_layer_factory(self.project_root))
        return self._tool_layers

    def _runtime_surface(self) -> tuple[set[str], str]:
        layers = self._load_tool_layers()
        resolution = layers.get("runtime_resolution")
        resolver = RuntimeSkillResolver(self.project_root)
        available = set(resolver.discover()[0])
        explicit = tuple(
            skill_id
            for skill_id in extract_explicit_skill_mentions(
                self._active_user_instruction
            )
            if skill_id in available
        )
        if explicit:
            baseline = set(DANTE_DIRECT_TOOLKIT) | {
                item.name for item in _DANTE_ACTION_TOOL_DEFINITIONS
            }
            resolution = resolver.resolve(
                agent="dante",
                task="chapter.write",
                base_tools=baseline,
                explicit_skills=explicit,
            )
        if resolution is None:
            return (
                set(DANTE_DIRECT_TOOLKIT)
                | {item.name for item in _DANTE_ACTION_TOOL_DEFINITIONS},
                "",
            )
        allowed_tools = set(getattr(resolution, "allowed_tools", ()) or ())
        rules = RuleCompiler(self.project_root).active()
        return allowed_tools, render_runtime_context(resolution, rules)

    def _append_user_turn(self, content: str) -> None:
        state = self._require_session_state()
        state.recent_turns.append(SessionTurn(role="user", content=content))
        self.session_store.append_turn("user", content)

    def _append_assistant_turn(self, content: str) -> None:
        state = self._require_session_state()
        state.recent_turns.append(SessionTurn(role="assistant", content=content))
        self.session_store.append_turn("assistant", content)

    def _require_session_state(self) -> DanteSessionState:
        if self.session_state is None:
            raise RuntimeError("Dante session has not been started")
        return self.session_state

    def _refresh_book_state(self) -> BookState:
        """Re-read the book state, keeping the in-memory copy as a fallback.

        `startup()` loads the state once; every tool action can advance it after
        that, and a stale snapshot makes the prompt describe a stage and chapter
        the book has already left.
        """
        try:
            self.book_state = self.book_state_store.load_or_create()
        except Exception:
            # A transient read failure must not break the turn; the last known
            # state is better than none.
            pass
        return self._require_book_state()

    def _require_book_state(self) -> BookState:
        if self.book_state is None:
            raise RuntimeError("Dante book state has not been started")
        return self.book_state


def run_dante() -> int:
    project_root = Path.cwd()
    config_path = project_root / "novel_config.yaml"
    if not config_path.exists():
        print("未找到 novel_config.yaml，请先运行 openwrite init")
        return 1

    import yaml

    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    novel_id = config.get("novel_id")
    if not novel_id:
        print("novel_config.yaml 缺少 novel_id")
        return 1

    layers = build_dante_tool_layers(project_root)
    agent = DanteChatAgent(
        project_root=project_root,
        novel_id=novel_id,
        tool_executors=layers.get("direct_tool_executors", {}),
        action_executors=layers.get("action_tool_executors", {}),
    )
    result = agent.run()
    return 0 if result.success else 1
