"""Dante 长会话主 Agent。"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .book_state import BookStage, BookState, BookStateStore
from .react import OPENWRITE_TOOLS, ReActAgent, ToolDefinition
from .toolkits import DANTE_DIRECT_TOOLKIT
from .session_state import DanteSessionState, SessionStateStore, SessionTurn
from .tool_layers import build_dante_tool_layers
from ..goethe import build_prompt_session, is_exit_command
from ..llm import LLMClient, LLMConfig, Message

DEFAULT_DANTE_SYSTEM_PROMPT = (
    "你是 OpenWrite 的 Dante，长期会话正文创作 Agent。"
    "你的默认职责是基于已确认的人物、设定和大纲持续推进正文写作、预检、审查与状态结算。"
    "当写作推进需要修正人物、设定或大纲时，你可以提出并执行必要回修，但不要把自己当成建书向导或一次性 wizard。"
    "优先保持对话连续性，并让一切回修都为正文推进服务。"
)

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
        description="基于共识摘要生成大纲草案。",
        parameters={
            "type": "object",
            "properties": {
                "request_text": {"type": "string", "description": "大纲生成请求"},
            },
            "required": ["request_text"],
        },
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
            },
            "required": ["chapter_id"],
        },
    ),
]


def _build_dante_tool_definitions() -> list[ToolDefinition]:
    direct_tool_defs = [
        tool for tool in OPENWRITE_TOOLS if tool.name in DANTE_DIRECT_TOOLKIT
    ]
    return direct_tool_defs + _DANTE_ACTION_TOOL_DEFINITIONS


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
        self.tool_executors = tool_executors or {}
        self.action_executors = action_executors or {}
        self.prompt_text = prompt_text
        self._react_agent = react_agent
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
        book_state = self._require_book_state()

        lines = [
            "Dante 已恢复，可以继续上次的长会话。",
            f"会话: {session_state.session_id} / active_agent={session_state.active_agent}",
            f"当前阶段: {book_state.stage.value}",
            (
                "当前篇/节/章: "
                f"{book_state.current_arc or '未设置'} / "
                f"{book_state.current_section or '未设置'} / "
                f"{book_state.current_chapter or '未设置'}"
            ),
            f"当前章: {book_state.current_chapter or '未设置'}",
        ]

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
        self._append_user_turn(text)
        state = self._require_session_state()
        state.last_action = "chat"
        self.session_store.save(state)
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
        react_agent = ReActAgent(
            client=client,
            model=client.config.model,
            tools=_build_dante_tool_definitions(),
            system_prompt=DEFAULT_DANTE_SYSTEM_PROMPT,
            max_turns=20,
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
        combined_tools = _build_dante_tool_definitions()
        canonical_tools = {tool.name: tool for tool in combined_tools}
        if hasattr(react_agent, "tools"):
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
        if self._combined_tool_executors() and hasattr(react_agent, "_register_tool_executors"):
            react_agent._register_tool_executors(self._combined_tool_executors())

    def _run_react_agent(self, react_agent: Any, instruction: str) -> str:
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

    def _build_context_messages(self, *, include_recent_turns: bool = True) -> list[Message]:
        session_state = self._require_session_state()
        book_state = self._require_book_state()
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
        combined.update(self.tool_executors)
        combined.update(self.action_executors)
        return combined

    def _append_user_turn(self, content: str) -> None:
        state = self._require_session_state()
        state.recent_turns.append(SessionTurn(role="user", content=content))

    def _append_assistant_turn(self, content: str) -> None:
        state = self._require_session_state()
        state.recent_turns.append(SessionTurn(role="assistant", content=content))

    def _require_session_state(self) -> DanteSessionState:
        if self.session_state is None:
            raise RuntimeError("Dante session has not been started")
        return self.session_state

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
