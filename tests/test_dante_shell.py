from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from tools.agent.book_state import BookStage, BookStateStore
from tools.agent.react import ToolDefinition
from tools.agent.session_state import (
    DanteSessionState,
    SessionTurn,
    MAX_RECENT_TURNS,
    MAX_SESSION_BYTES,
)


@dataclass
class FakePromptSession:
    inputs: list[str]

    def __post_init__(self) -> None:
        self.prompts: list[str] = []

    def prompt(self, text: str) -> str:
        self.prompts.append(text)
        if not self.inputs:
            raise AssertionError("prompt() called more times than expected")
        return self.inputs.pop(0)


class FakeReActAgent:
    def __init__(self, responses: list[str] | None = None, error: Exception | None = None):
        self.instructions: list[str] = []
        self.calls: list[dict[str, object]] = []
        self.responses = responses or ["收到"]
        self.error = error

    def run(self, instruction: str, **kwargs):
        self.instructions.append(instruction)
        self.calls.append({"instruction": instruction, "kwargs": kwargs})
        if self.error is not None:
            raise self.error
        if not self.responses:
            return "收到"
        return self.responses.pop(0)


def _write_session_state(project_root: Path, novel_id: str) -> None:
    session_path = (
        project_root / "data" / "novels" / novel_id / "data" / "workflows" / "agent_session.yaml"
    )
    session_path.parent.mkdir(parents=True, exist_ok=True)
    session_path.write_text(
        yaml.safe_dump(
            {
                "session_id": "session-123",
                "active_agent": "dante",
                "conversation_summary": "已确认当前题材是都市职场异能。",
                "recent_turns": [
                    {"role": "user", "content": "我想写一个普通上班族觉醒术式的故事"},
                    {"role": "assistant", "content": "我先帮你整理成共识摘要。"},
                ],
                "working_memory": {"topic": "都市职场异能"},
                "open_questions": ["主角是否主动入局"],
                "recent_files": ["src/outline.md"],
                "last_action": "summarize_ideation",
                "compression_markers": [
                    {
                        "compressed_at": "2026-03-30T10:00:00",
                        "dropped_turns": 2,
                        "kept_turns": 2,
                        "reason": "count",
                    }
                ],
                "updated_at": "2026-03-30T10:05:00",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _write_book_state(project_root: Path, novel_id: str) -> None:
    book_path = (
        project_root / "data" / "novels" / novel_id / "data" / "workflows" / "book_state.yaml"
    )
    book_path.parent.mkdir(parents=True, exist_ok=True)
    book_path.write_text(
        yaml.safe_dump(
            {
                "novel_id": novel_id,
                "stage": BookStage.ROLLING_OUTLINE.value,
                "current_arc": "arc_001",
                "current_section": "sec_001",
                "current_chapter": "ch_006",
                "pending_confirmation": "outline_scope",
                "blocking_reason": "等待用户确认当前可写范围",
                "last_agent_action": "generate_outline_draft",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_dante_startup_loads_session_and_book_state(tmp_path: Path):
    from tools.agent.dante import DanteChatAgent

    _write_session_state(tmp_path, "demo")
    _write_book_state(tmp_path, "demo")

    agent = DanteChatAgent(
        project_root=tmp_path,
        novel_id="demo",
        prompt_session_factory=lambda **kwargs: FakePromptSession(["exit"]),
        react_agent=FakeReActAgent(),
    )

    startup = agent.startup()

    assert startup.session_state.session_id == "session-123"
    assert startup.book_state.stage == BookStage.ROLLING_OUTLINE
    assert startup.recovery_prompt.startswith("Dante 已恢复")
    assert "ch_006" in startup.recovery_prompt
    assert agent.session_state.session_id == "session-123"
    assert agent.book_state.current_chapter == "ch_006"


def test_dante_enters_prompt_loop_and_persists_turns(tmp_path: Path):
    from tools.agent.dante import DanteChatAgent

    _write_session_state(tmp_path, "demo")
    _write_book_state(tmp_path, "demo")

    prompt_session = FakePromptSession(["我想先看当前状态", "exit"])
    react_agent = FakeReActAgent(responses=["我已经记住了。"])
    agent = DanteChatAgent(
        project_root=tmp_path,
        novel_id="demo",
        prompt_session_factory=lambda **kwargs: prompt_session,
        react_agent=react_agent,
    )

    result = agent.run()

    assert result.success is True
    assert result.exit_reason == "exit"
    assert react_agent.instructions == ["我想先看当前状态"]
    assert prompt_session.prompts
    assert "Dante" in prompt_session.prompts[0]

    persisted = yaml.safe_load(agent.session_store.path.read_text(encoding="utf-8"))
    assert persisted["recent_turns"][-2:] == [
        {"role": "user", "content": "我想先看当前状态"},
        {"role": "assistant", "content": "我已经记住了。"},
    ]
    transcript = agent.session_store.transcript_path.read_text(encoding="utf-8").splitlines()
    assert '"role": "user"' in transcript[-2]
    assert '"role": "assistant"' in transcript[-1]
    assert persisted["last_action"] == "exit"


def test_dante_respond_supports_persisted_web_turn(tmp_path: Path):
    from tools.agent.dante import DanteChatAgent

    react_agent = FakeReActAgent(responses=["先检查当前章，再继续写作。"])
    agent = DanteChatAgent(
        project_root=tmp_path,
        novel_id="demo",
        react_agent=react_agent,
    )

    response = agent.respond("帮我继续正文")

    assert response == "先检查当前章，再继续写作。"
    persisted = yaml.safe_load(agent.session_store.path.read_text(encoding="utf-8"))
    assert persisted["recent_turns"][-2:] == [
        {"role": "user", "content": "帮我继续正文"},
        {"role": "assistant", "content": "先检查当前章，再继续写作。"},
    ]


def test_goethe_respond_supports_persisted_web_turn(tmp_path: Path):
    from tools.goethe import GoetheChatAgent

    react_agent = FakeReActAgent(responses=["先补齐主角矛盾与第一篇大纲。"])
    agent = GoetheChatAgent(
        project_root=tmp_path,
        novel_id="demo",
        react_agent=react_agent,
        tool_layer_factory=lambda *args: {},
    )

    response = agent.respond("检查目前还缺什么")

    assert response == "先补齐主角矛盾与第一篇大纲。"
    persisted = yaml.safe_load(agent.session_store.path.read_text(encoding="utf-8"))
    assert persisted["recent_turns"][-2:] == [
        {"role": "user", "content": "检查目前还缺什么"},
        {"role": "assistant", "content": "先补齐主角矛盾与第一篇大纲。"},
    ]
    transcript = agent.session_store.transcript_path.read_text(encoding="utf-8").splitlines()
    assert '"agent": "goethe"' in transcript[-1]
    assert '"role": "assistant"' in transcript[-1]


def test_goethe_confirmation_with_handoff_text_still_runs_react(tmp_path: Path):
    from tools.goethe import GoetheChatAgent

    react_agent = FakeReActAgent(responses=["已确认应用大纲修改，交接材料已准备。"])
    agent = GoetheChatAgent(
        project_root=tmp_path,
        novel_id="demo",
        react_agent=react_agent,
        tool_layer_factory=lambda *args: {
            "action_tool_executors": {
                "prepare_dante_handoff": lambda args: {
                    "ok": False,
                    "missing_items": ["outline_confirmation"],
                }
            }
        },
    )

    response = agent.respond("确认应用以上大纲修改，并准备交接给 Dante。")

    assert response == "已确认应用大纲修改，交接材料已准备。"
    assert react_agent.instructions == ["确认应用以上大纲修改，并准备交接给 Dante。"]
    transcript = agent.session_store.transcript_path.read_text(encoding="utf-8")
    assert "确认应用以上大纲修改" in transcript


def test_goethe_handoff_shortcut_persists_web_turn(tmp_path: Path):
    from tools.goethe import GoetheChatAgent

    react_agent = FakeReActAgent(responses=["不应调用"])
    agent = GoetheChatAgent(
        project_root=tmp_path,
        novel_id="demo",
        react_agent=react_agent,
        tool_layer_factory=lambda *args: {
            "action_tool_executors": {
                "prepare_dante_handoff": lambda args: {
                    "ok": False,
                    "missing_items": ["foundation"],
                }
            }
        },
    )

    response = agent.respond("现在交接给 Dante")

    assert response == "暂时不能交接给 Dante，还缺少：foundation。"
    assert react_agent.instructions == []
    transcript = agent.session_store.transcript_path.read_text(encoding="utf-8")
    assert "现在交接给 Dante" in transcript
    assert "foundation" in transcript


def test_goethe_explicit_handoff_tool_name_runs_react(tmp_path: Path):
    from tools.goethe import GoetheChatAgent

    react_agent = FakeReActAgent(responses=["工具测试完成"])
    agent = GoetheChatAgent(
        project_root=tmp_path,
        novel_id="demo",
        react_agent=react_agent,
        tool_layer_factory=lambda *args: {
            "action_tool_executors": {
                "prepare_dante_handoff": lambda args: {
                    "ok": False,
                    "missing_items": ["foundation"],
                }
            }
        },
    )

    response = agent.respond("请实际调用 get_goethe_handoff 做只读工具测试")

    assert response == "工具测试完成"
    assert react_agent.instructions == ["请实际调用 get_goethe_handoff 做只读工具测试"]


def test_goethe_pending_confirmation_with_handoff_text_runs_react(tmp_path: Path):
    from tools.goethe import GoetheChatAgent

    state_store = BookStateStore(tmp_path, "demo")
    state = state_store.load_or_create()
    state.pending_confirmation = "ideation_summary"
    state_store.save(state)
    react_agent = FakeReActAgent(responses=["已确认这版汇总。"])
    agent = GoetheChatAgent(
        project_root=tmp_path,
        novel_id="demo",
        react_agent=react_agent,
        tool_layer_factory=lambda *args: {
            "action_tool_executors": {
                "prepare_dante_handoff": lambda args: {
                    "ok": False,
                    "missing_items": ["ideation_summary"],
                }
            }
        },
    )

    response = agent.respond("确认这版汇总，并准备交接给 Dante。")

    assert response == "已确认这版汇总。"
    assert react_agent.instructions == ["确认这版汇总，并准备交接给 Dante。"]


def test_goethe_exposes_incremental_outline_react_tools():
    from tools.goethe import DEFAULT_GOETHE_SYSTEM_PROMPT, _build_goethe_tool_definitions

    tool_names = {tool.name for tool in _build_goethe_tool_definitions()}

    assert {
        "confirm_ideation_summary",
        "read_outline",
        "stage_outline_edits",
        "confirm_outline_edits",
        "discard_outline_edits",
    }.issubset(tool_names)
    assert "confirm_ideation_summary" in DEFAULT_GOETHE_SYSTEM_PROMPT
    assert "已有大纲时绝不整篇重写" in DEFAULT_GOETHE_SYSTEM_PROMPT
    assert "未提及内容必须逐字保留" in DEFAULT_GOETHE_SYSTEM_PROMPT
    assert "必须按幕或最多 4 节分批" in DEFAULT_GOETHE_SYSTEM_PROMPT
    assert "final_batch=false" in DEFAULT_GOETHE_SYSTEM_PROMPT
    stage_tool = next(
        tool for tool in _build_goethe_tool_definitions() if tool.name == "stage_outline_edits"
    )
    assert "batch_label" in stage_tool.parameters["properties"]
    assert "final_batch" in stage_tool.parameters["properties"]
    edit_schema = stage_tool.parameters["properties"]["edits"]["items"]
    assert "section_heading" in edit_schema["properties"]
    assert "start_text" in edit_schema["properties"]
    assert "end_text" in edit_schema["properties"]
    assert edit_schema["required"] == ["new_text"]
    assert "禁止为长段、整章或整节提交 old_text" in DEFAULT_GOETHE_SYSTEM_PROMPT
    assert "edit_world_relation" in DEFAULT_GOETHE_SYSTEM_PROMPT
    assert "confirm=false" in DEFAULT_GOETHE_SYSTEM_PROMPT


def test_dante_exposes_outline_scope_confirmation_tool():
    from tools.agent.dante import (
        DEFAULT_DANTE_SYSTEM_PROMPT,
        _build_dante_tool_definitions,
    )

    tool_names = {tool.name for tool in _build_dante_tool_definitions()}

    assert "confirm_outline_scope" in tool_names
    assert "pending_confirmation=outline_scope" in DEFAULT_DANTE_SYSTEM_PROMPT
    assert "confirm_outline_scope" in DEFAULT_DANTE_SYSTEM_PROMPT


def test_goethe_blocks_outline_confirmation_without_explicit_user_intent(
    tmp_path: Path,
):
    from tools.goethe import GoetheChatAgent

    calls: list[dict] = []
    agent = GoetheChatAgent(
        project_root=tmp_path,
        novel_id="demo",
        react_agent=FakeReActAgent(),
        tool_layer_factory=lambda *args: {},
    )

    def executor(args: dict) -> dict:
        calls.append(args)
        return {"ok": True}

    agent._active_user_instruction = "你觉得这个修改怎么样？"
    blocked = agent._confirm_outline_if_explicit(executor, {})
    agent._active_user_instruction = "确认应用这版修改"
    confirmed = agent._confirm_outline_if_explicit(executor, {})
    agent._active_user_instruction = "确认"
    short_confirmation = agent._confirm_outline_if_explicit(executor, {})

    assert blocked["ok"] is False
    assert blocked["error"] == "explicit_user_confirmation_required"
    assert confirmed["ok"] is True
    assert short_confirmation["ok"] is True
    assert calls == [{}, {}]


def test_goethe_shared_confirmation_guard_blocks_all_unconfirmed_mutations(
    tmp_path: Path,
):
    from tools.goethe import GoetheChatAgent
    from tools.init_project import init_project

    init_project(tmp_path, "demo")
    called: list[tuple[str, dict]] = []
    executors = {
        name: (lambda args, tool=name: called.append((tool, args)) or {"ok": True})
        for name in (
            "edit_project_document",
            "edit_world_relation",
            "edit_world_relations",
            "edit_outline_structure",
        )
    }
    agent = GoetheChatAgent(
        tmp_path,
        "demo",
        tool_layer_factory=lambda *args: {
            "tool_executors": executors,
            "action_tool_executors": {},
        },
    )

    agent._active_user_instruction = "先看看这些修改是否合适"
    guarded = agent._combined_tool_executors()
    blocked = {
        name: guarded[name]({"confirm": True})
        for name in executors
    }

    assert called == []
    assert {
        result["error"] for result in blocked.values()
    } == {"explicit_user_confirmation_required"}

    agent._active_user_instruction = "确认应用这些修改"
    confirmed = agent._combined_tool_executors()["edit_world_relations"](
        {"confirm": True}
    )
    assert confirmed["ok"] is True
    assert called == [("edit_world_relations", {"confirm": True})]


def test_dante_shared_confirmation_guard_allows_preview_then_explicit_apply(
    tmp_path: Path,
):
    from tools.agent.dante import DanteChatAgent
    from tools.init_project import init_project

    init_project(tmp_path, "demo")
    calls: list[dict] = []
    agent = DanteChatAgent(
        tmp_path,
        "demo",
        tool_executors={
            "edit_project_document": lambda args: calls.append(args) or {"ok": True}
        },
        action_executors={},
    )

    agent._active_user_instruction = "帮我完善角色档案"
    guarded = agent._combined_tool_executors()["edit_project_document"]
    preview = guarded({"confirm": False})
    blocked = guarded({"confirm": True})

    assert preview["ok"] is True
    assert blocked["error"] == "explicit_user_confirmation_required"
    assert calls == [{"confirm": False}]

    agent._active_user_instruction = "直接应用这版修改"
    applied = agent._combined_tool_executors()["edit_project_document"](
        {"confirm": True}
    )
    assert applied["ok"] is True
    assert calls[-1] == {"confirm": True}


def test_shared_confirmation_guard_scopes_mixed_document_and_relation_intent(
    tmp_path: Path,
):
    from tools.goethe import GoetheChatAgent

    calls: list[str] = []
    agent = GoetheChatAgent(
        project_root=tmp_path,
        novel_id="demo",
        tool_layer_factory=lambda *args: {
            "tool_executors": {
                "edit_project_document": lambda args: calls.append("document")
                or {"ok": True},
                "edit_world_relation": lambda args: calls.append("relation")
                or {"ok": True},
            },
            "action_tool_executors": {},
        },
    )
    agent._active_user_instruction = (
        "确认应用上一轮文档编辑预览。关系只重新预览，不要在本轮确认。"
    )
    guarded = agent._combined_tool_executors()

    document = guarded["edit_project_document"]({"confirm": True})
    relation = guarded["edit_world_relation"]({"confirm": True})

    assert document["ok"] is True
    assert relation["error"] == "explicit_user_confirmation_required"
    assert calls == ["document"]


@pytest.mark.parametrize("command", ["quit", "exit", "q", "退出"])
def test_dante_exit_commands_stop_without_tool_turn(tmp_path: Path, command: str):
    from tools.agent.dante import DanteChatAgent

    _write_session_state(tmp_path, "demo")
    _write_book_state(tmp_path, "demo")

    prompt_session = FakePromptSession([command])
    react_agent = FakeReActAgent()
    agent = DanteChatAgent(
        project_root=tmp_path,
        novel_id="demo",
        prompt_session_factory=lambda **kwargs: prompt_session,
        react_agent=react_agent,
    )

    result = agent.run()

    assert result.success is True
    assert result.exit_reason == command
    assert react_agent.instructions == []
    assert yaml.safe_load(agent.session_store.path.read_text(encoding="utf-8"))["recent_turns"][-1]["role"] == "assistant"


def test_dante_recovery_prompt_mentions_loaded_state(tmp_path: Path):
    from tools.agent.dante import DanteChatAgent

    _write_session_state(tmp_path, "demo")
    _write_book_state(tmp_path, "demo")

    agent = DanteChatAgent(
        project_root=tmp_path,
        novel_id="demo",
        prompt_session_factory=lambda **kwargs: FakePromptSession(["exit"]),
        react_agent=FakeReActAgent(),
    )

    agent.startup()
    prompt = agent.build_recovery_prompt()

    assert "rolling_outline" in prompt
    assert "ch_006" in prompt
    assert "outline_scope" in prompt
    assert "都市职场异能" in prompt
    assert "主角是否主动入局" in prompt


def test_dante_run_compresses_session_after_many_turns(tmp_path: Path):
    from tools.agent.dante import DanteChatAgent

    _write_session_state(tmp_path, "demo")
    _write_book_state(tmp_path, "demo")

    prompt_session = FakePromptSession(
        [f"第{index:02d}轮追问" for index in range(MAX_RECENT_TURNS + 1)] + ["exit"]
    )
    react_agent = FakeReActAgent(
        responses=[f"回应-{index:02d}" for index in range(MAX_RECENT_TURNS + 1)]
    )
    agent = DanteChatAgent(
        project_root=tmp_path,
        novel_id="demo",
        prompt_session_factory=lambda **kwargs: prompt_session,
        react_agent=react_agent,
    )

    result = agent.run()
    persisted = yaml.safe_load(agent.session_store.path.read_text(encoding="utf-8"))

    assert result.success is True
    assert persisted["compression_markers"][-1]["reason"] == "count"
    assert len(persisted["recent_turns"]) == MAX_RECENT_TURNS
    assert persisted["conversation_summary"]
    assert "第00轮追问" in persisted["conversation_summary"]


def test_dante_run_compresses_session_after_large_response(tmp_path: Path):
    from tools.agent.dante import DanteChatAgent

    _write_session_state(tmp_path, "demo")
    _write_book_state(tmp_path, "demo")

    huge_text = "x" * (MAX_SESSION_BYTES * 2)
    prompt_session = FakePromptSession(["请展开当前设定", "exit"])
    react_agent = FakeReActAgent(responses=[f"章节内容:{huge_text}"])
    agent = DanteChatAgent(
        project_root=tmp_path,
        novel_id="demo",
        prompt_session_factory=lambda **kwargs: prompt_session,
        react_agent=react_agent,
    )

    result = agent.run()
    persisted = yaml.safe_load(agent.session_store.path.read_text(encoding="utf-8"))
    persisted_size = len(agent.session_store.path.read_text(encoding="utf-8").encode("utf-8"))

    assert result.success is True
    assert persisted["compression_markers"][-1]["reason"] == "size"
    assert persisted_size <= MAX_SESSION_BYTES
    assert len(persisted["recent_turns"]) >= 1
    assert persisted["conversation_summary"]


def test_dante_startup_after_compression_keeps_summary_and_recent_window(tmp_path: Path):
    from tools.agent.dante import DanteChatAgent
    from tools.agent.session_state import SessionStateStore

    session_store = SessionStateStore(tmp_path, "demo")
    state = DanteSessionState(session_id="demo")
    state.recent_turns = [
        SessionTurn(role="user", content=f"old-{index:02d}")
        for index in range(MAX_RECENT_TURNS + 4)
    ]
    session_store.save(state)
    _write_book_state(tmp_path, "demo")

    agent = DanteChatAgent(
        project_root=tmp_path,
        novel_id="demo",
        react_agent=FakeReActAgent(),
    )

    startup = agent.startup()

    assert startup.session_state.conversation_summary
    assert startup.session_state.recent_turns
    assert len(startup.session_state.recent_turns) == MAX_RECENT_TURNS
    assert "old-00" in startup.recovery_prompt or "old-00" in startup.session_state.conversation_summary


def test_dante_passes_session_memory_and_book_state_into_react(
    tmp_path: Path,
):
    from tools.agent.dante import DanteChatAgent

    _write_session_state(tmp_path, "demo")
    _write_book_state(tmp_path, "demo")

    prompt_session = FakePromptSession(["继续推进", "exit"])
    react_agent = FakeReActAgent(responses=["已接住上下文。"])
    agent = DanteChatAgent(
        project_root=tmp_path,
        novel_id="demo",
        prompt_session_factory=lambda **kwargs: prompt_session,
        react_agent=react_agent,
        action_executors={
            "summarize_ideation": lambda args: {"ok": True, "action": "summarize_ideation"}
        },
    )

    result = agent.run()

    assert result.success is True
    assert react_agent.instructions == ["继续推进"]
    assert react_agent.calls[0]["kwargs"]["context_messages"]
    context_text = "\n".join(
        message.content for message in react_agent.calls[0]["kwargs"]["context_messages"]
    )
    assert "会话摘要" in context_text
    assert "最近轮次" in context_text
    assert "rolling_outline" in context_text
    assert "ch_006" in context_text


def test_dante_default_react_agent_has_direct_and_action_tool_surface(
    tmp_path: Path,
):
    from tools.agent.dante import DanteChatAgent

    _write_session_state(tmp_path, "demo")
    _write_book_state(tmp_path, "demo")

    agent = DanteChatAgent(
        project_root=tmp_path,
        novel_id="demo",
        prompt_session_factory=lambda **kwargs: FakePromptSession(["exit"]),
        react_agent=None,
        llm_client_factory=lambda: SimpleNamespace(
            config=SimpleNamespace(model="fake-model")
        ),
        tool_executors={
            "get_status": lambda args: {"ok": True},
            "get_context": lambda args: {"ok": True},
            "list_chapters": lambda args: {"ok": True},
            "get_truth_files": lambda args: {"ok": True},
            "query_world": lambda args: {"ok": True},
            "get_world_relations": lambda args: {"ok": True},
        },
        action_executors={
            "summarize_ideation": lambda args: {"ok": True, "action": "summarize_ideation"},
            "confirm_ideation_summary": lambda args: {"ok": True, "action": "confirm_ideation_summary"},
            "generate_outline_draft": lambda args: {"ok": True, "action": "generate_outline_draft"},
            "run_chapter_preflight": lambda args: {"ok": True, "action": "run_chapter_preflight"},
        },
    )

    react_agent = agent._get_react_agent()

    tool_names = {tool.name for tool in react_agent.tools}
    assert "get_status" in tool_names
    assert "summarize_ideation" in tool_names
    assert hasattr(react_agent, "_tool_get_status")
    assert hasattr(react_agent, "_tool_summarize_ideation")


def test_dante_default_constructor_registers_project_tool_executors(tmp_path: Path):
    from tools.agent.dante import DanteChatAgent
    from tools.init_project import init_project

    init_project(tmp_path, "demo")
    agent = DanteChatAgent(
        project_root=tmp_path,
        novel_id="demo",
        llm_client_factory=lambda: SimpleNamespace(
            config=SimpleNamespace(model="fake-model")
        ),
    )

    react_agent = agent._get_react_agent()

    assert hasattr(react_agent, "_tool_get_context")
    assert hasattr(react_agent, "_tool_get_truth_files")


def test_dante_persists_user_turn_when_react_raises(tmp_path: Path):
    from tools.agent.dante import DanteChatAgent

    _write_session_state(tmp_path, "demo")
    _write_book_state(tmp_path, "demo")

    prompt_session = FakePromptSession(["我想继续推进"])
    react_agent = FakeReActAgent(error=RuntimeError("boom"))
    agent = DanteChatAgent(
        project_root=tmp_path,
        novel_id="demo",
        prompt_session_factory=lambda **kwargs: prompt_session,
        react_agent=react_agent,
    )

    with pytest.raises(RuntimeError, match="boom"):
        agent.run()

    persisted = yaml.safe_load(agent.session_store.path.read_text(encoding="utf-8"))
    assert persisted["recent_turns"][-1] == {
        "role": "user",
        "content": "我想继续推进",
    }


def test_dante_model_context_excludes_recovery_prompt_but_keeps_structured_state(
    tmp_path: Path,
):
    from tools.agent.dante import DanteChatAgent

    _write_session_state(tmp_path, "demo")
    _write_book_state(tmp_path, "demo")

    prompt_session = FakePromptSession(["查看当前状态", "exit"])
    react_agent = FakeReActAgent(responses=["收到"])
    agent = DanteChatAgent(
        project_root=tmp_path,
        novel_id="demo",
        prompt_session_factory=lambda **kwargs: prompt_session,
        react_agent=react_agent,
    )

    result = agent.run()

    assert result.success is True
    assert react_agent.instructions == ["查看当前状态"]
    context_text = "\n".join(
        message.content for message in react_agent.calls[0]["kwargs"]["context_messages"]
    )
    assert "Dante 已恢复，可以继续上次的长会话。" not in context_text
    assert "会话: session-123 / active_agent=dante" not in context_text
    assert "会话摘要" in context_text
    assert "最近轮次" in context_text
    assert "rolling_outline" in context_text
    assert "等待用户确认当前可写范围" in context_text
    assert "generate_outline_draft" in context_text
    assert "current" not in context_text


def test_dante_injected_real_react_agent_gets_tool_definitions_and_surface(
    tmp_path: Path,
):
    from tools.agent.dante import DanteChatAgent
    from tools.agent.react import ReActAgent

    _write_session_state(tmp_path, "demo")
    _write_book_state(tmp_path, "demo")

    class RecordingClient:
        def __init__(self):
            self.calls: list[dict[str, object]] = []

        def chat_with_tools(self, messages, tools, **kwargs):
            self.calls.append({"messages": list(messages), "tools": list(tools)})
            return type("Resp", (), {"content": "退出", "tool_calls": []})()

    react_agent = ReActAgent(
        client=RecordingClient(),
        model="demo",
        tools=[
            ToolDefinition(
                name="get_status",
                description="旧描述",
                parameters={
                    "type": "object",
                    "properties": {"legacy": {"type": "string"}},
                },
            ),
            ToolDefinition(
                name="retain_me",
                description="保留的外部工具",
                parameters={"type": "object", "properties": {}},
            ),
        ],
        system_prompt="系统提示",
    )

    DanteChatAgent(
        project_root=tmp_path,
        novel_id="demo",
        prompt_session_factory=lambda **kwargs: FakePromptSession(["exit"]),
        react_agent=react_agent,
        tool_executors={
            "get_status": lambda args: {"ok": True},
            "get_context": lambda args: {"ok": True},
            "list_chapters": lambda args: {"ok": True},
            "get_truth_files": lambda args: {"ok": True},
            "query_world": lambda args: {"ok": True},
            "get_world_relations": lambda args: {"ok": True},
        },
        action_executors={
            "summarize_ideation": lambda args: {"ok": True, "action": "summarize_ideation"},
            "confirm_ideation_summary": lambda args: {"ok": True, "action": "confirm_ideation_summary"},
            "generate_outline_draft": lambda args: {"ok": True, "action": "generate_outline_draft"},
            "run_chapter_preflight": lambda args: {"ok": True, "action": "run_chapter_preflight"},
        },
    )

    tool_map = {tool.name: tool for tool in react_agent.tools}
    assert tool_map["get_status"].description == "获取项目状态概览。"
    assert tool_map["get_status"].parameters == {
        "type": "object",
        "properties": {},
    }
    assert tool_map["summarize_ideation"].description == "汇总当前收集到的想法，生成会话共识摘要。"
    assert tool_map["summarize_ideation"].parameters == {
        "type": "object",
        "properties": {},
    }
    assert tool_map["retain_me"].description == "保留的外部工具"
    assert hasattr(react_agent, "_tool_get_status")
    assert hasattr(react_agent, "_tool_summarize_ideation")


def test_confirmation_markers_accept_short_and_english_forms():
    from tools.agent.confirmation import is_explicit_mutation_confirmation

    assert is_explicit_mutation_confirmation("好的")
    assert is_explicit_mutation_confirmation("yes")
    assert is_explicit_mutation_confirmation("ok")
    assert is_explicit_mutation_confirmation("不要再确认，直接应用")
    assert is_explicit_mutation_confirmation("确认执行关系 revision 冲突测试")
    assert not is_explicit_mutation_confirmation("先不要改")


def test_dante_and_goethe_cold_start_prompts_include_onboarding(tmp_path: Path):
    from tools.agent.dante import DanteChatAgent, DEFAULT_DANTE_SYSTEM_PROMPT
    from tools.goethe import GoetheChatAgent, DEFAULT_GOETHE_SYSTEM_PROMPT
    from tools.init_project import init_project

    init_project(tmp_path, "demo", "雾城来信")
    goethe = GoetheChatAgent(tmp_path, "demo", react_agent=FakeReActAgent())
    dante = DanteChatAgent(tmp_path, "demo", react_agent=FakeReActAgent())

    goethe_prompt = goethe.startup().recovery_prompt
    dante_prompt = dante.startup().recovery_prompt

    assert "首次规划会话" in goethe_prompt
    assert "当前作品：雾城来信（小说 ID：demo）" in goethe_prompt
    assert "不要把小说 ID 当作书名" in goethe_prompt
    assert "资产缺口" in goethe_prompt
    assert "首次写作会话" in dante_prompt
    assert "Goethe" in dante_prompt
    assert "edit_project_document" in DEFAULT_DANTE_SYSTEM_PROMPT
    assert "edit_world_relations" in DEFAULT_DANTE_SYSTEM_PROMPT
    assert "首次冷启动" in DEFAULT_GOETHE_SYSTEM_PROMPT


def test_dante_redirects_manuscript_deletion_to_manual_studio_control(tmp_path: Path):
    from tools.agent.dante import DanteChatAgent
    from tools.agent.manuscript_safety import manual_chapter_delete_guidance
    from tools.goethe import GoetheChatAgent
    from tools.init_project import init_project

    init_project(tmp_path, "demo", "雾城来信")
    react_agent = FakeReActAgent()
    dante = DanteChatAgent(tmp_path, "demo", react_agent=react_agent)

    response = dante.respond("现在的剧情不满意，帮我把现有章节都删掉吧，我重写大纲")

    assert "不会直接删除正文章节" in response
    assert "删除正文" in response
    assert "从最新章开始依次向前删除" in response
    assert react_agent.instructions == []
    assert dante.session_state is not None
    assert dante.session_state.last_action == "manual_chapter_delete_guidance"
    assert manual_chapter_delete_guidance("删除大纲里的第三章") == ""

    goethe_react = FakeReActAgent()
    goethe = GoetheChatAgent(tmp_path, "demo", react_agent=goethe_react)
    goethe_response = goethe.respond("请清空所有正文，我要重写")
    assert "删除正文" in goethe_response
    assert goethe_react.instructions == []


def test_goethe_passes_project_title_and_id_to_react_context(tmp_path: Path):
    from tools.goethe import GoetheChatAgent
    from tools.init_project import init_project

    init_project(tmp_path, "bushi", "我不是坏人")
    react_agent = FakeReActAgent()
    goethe = GoetheChatAgent(tmp_path, "bushi", react_agent=react_agent)

    assert goethe.respond("我想写轻松的修仙故事") == "收到"

    context_text = "\n".join(
        message.content for message in react_agent.calls[0]["kwargs"]["context_messages"]
    )
    assert "当前作品：我不是坏人（小说 ID：bushi）" in context_text
    assert "不要把小说 ID 当作书名" in context_text


def test_goethe_cli_refuses_without_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from tools.goethe import run_goethe

    monkeypatch.chdir(tmp_path)
    assert (tmp_path / "novel_config.yaml").exists() is False
    exit_code = run_goethe()
    assert exit_code == 1


def test_dante_context_messages_reflect_the_current_book_state(tmp_path: Path):
    """The context prompt must not describe a state the book has left.

    `startup()` loads the book state once; every tool action can advance it after
    that, and a stale snapshot made the prompt report a stage and chapter the book
    had already left.
    """
    from tools.agent.book_state import BookState, BookStateStore
    from tools.agent.dante import DanteChatAgent

    _write_session_state(tmp_path, "demo")
    state_store = BookStateStore(tmp_path, "demo")
    seeded = state_store.load_or_create()
    seeded.stage = BookStage.ROLLING_OUTLINE
    seeded.current_chapter = "ch_006"
    state_store.save(seeded)

    agent = DanteChatAgent(
        project_root=tmp_path,
        novel_id="demo",
        prompt_session_factory=lambda **kwargs: FakePromptSession(["exit"]),
        react_agent=FakeReActAgent(),
    )
    agent.startup()
    assert agent.book_state.current_chapter == "ch_006"

    # A tool action advances the book on disk after startup.
    advanced = state_store.load_or_create()
    advanced.stage = BookStage.REVIEW_AND_REVISE
    advanced.current_chapter = "ch_007"
    state_store.save(advanced)

    messages = agent._build_context_messages()
    book_state = next(
        message for message in messages if message.content.startswith("书状态: ")
    )
    assert "stage=review_and_revise" in book_state.content
    assert "chapter=ch_007" in book_state.content
    assert "chapter=ch_006" not in book_state.content


def test_goethe_handoff_shortcut_fails_closed_when_the_book_state_is_unreadable(tmp_path: Path):
    """An unreadable book state must not unlock the handoff shortcut.

    The shortcut bypasses the outline-scope confirmation gate, so returning True
    on a read failure let an author skip a confirmation that was still pending -
    the opposite of the fail-closed rule used everywhere else.
    """
    from tools.agent.book_state import BookStateStore
    from tools.goethe import GoetheChatAgent
    from tools.init_project import init_project

    init_project(tmp_path, "demo")
    agent = GoetheChatAgent(
        project_root=tmp_path,
        novel_id="demo",
        react_agent=object(),
    )

    # A pending confirmation blocks the shortcut.
    store = BookStateStore(tmp_path, "demo")
    state = store.load_or_create()
    state.pending_confirmation = "outline_scope"
    store.save(state)
    assert agent._should_use_handoff_shortcut("开始写正文") is False

    # Confirming it unblocks the shortcut.
    state = store.load_or_create()
    state.pending_confirmation = ""
    store.save(state)
    assert agent._should_use_handoff_shortcut("开始写正文") is True

    # An unreadable state file must not unlock it either.
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("pending_confirmation: [broken\n", encoding="utf-8")
    assert agent._should_use_handoff_shortcut("开始写正文") is False, (
        "an unreadable book state must fail closed, not unlock the shortcut"
    )


def test_an_empty_book_state_file_also_fails_the_gate_closed(tmp_path: Path):
    """A truncated-to-nothing state file is not "no pending confirmation"."""
    from tools.agent.book_state import BookStateError, BookStateStore
    from tools.goethe import GoetheChatAgent
    from tools.init_project import init_project

    init_project(tmp_path, "demo")
    store = BookStateStore(tmp_path, "demo")
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("", encoding="utf-8")

    with pytest.raises(BookStateError):
        store.load_strict()

    agent = GoetheChatAgent(project_root=tmp_path, novel_id="demo", react_agent=object())
    assert agent._should_use_handoff_shortcut("开始写正文") is False
