from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from tools.agent.react import ReActAgent, ToolDefinition
from tools.llm import Message
from tools.llm.response import ProviderResponseError


class RecordingClient:
    def __init__(self, responses: list[object]):
        self.responses = responses
        self.calls: list[dict[str, object]] = []

    def chat_with_tools(self, messages, tools, **kwargs):
        self.calls.append(
            {
                "messages": list(messages),
                "tools": list(tools),
                "kwargs": dict(kwargs),
            }
        )
        if self.responses:
            return self.responses.pop(0)
        return SimpleNamespace(content="", tool_calls=[])


def _tool_response(content: str = "", tool_calls: list[dict] | None = None):
    return SimpleNamespace(content=content, tool_calls=tool_calls or [])


def test_react_agent_direct_chat_uses_injected_context_messages():
    client = RecordingClient([_tool_response("继续")])
    agent = ReActAgent(
        client=client,
        model="demo",
        tools=[],
        system_prompt="系统提示",
    )

    result = asyncio.run(
        agent.run(
            "继续写",
            context_messages=[
                Message("assistant", "会话摘要: 已确认都市职场异能。"),
                Message("assistant", "最近轮次: user->我想写一个普通上班族觉醒术式的故事"),
            ],
        )
    )

    assert result == "继续"
    assert [message.role for message in client.calls[0]["messages"]] == [
        "system",
        "assistant",
        "assistant",
        "user",
    ]
    assert "会话摘要" in client.calls[0]["messages"][1].content
    assert "最近轮次" in client.calls[0]["messages"][2].content


def test_react_agent_supports_context_message_factory_callback():
    client = RecordingClient([_tool_response("继续")])
    agent = ReActAgent(
        client=client,
        model="demo",
        tools=[],
        system_prompt="系统提示",
    )
    calls = {"count": 0}

    def factory():
        calls["count"] += 1
        return [Message("assistant", "会话摘要: 由工厂注入。")]

    result = asyncio.run(
        agent.run(
            "继续写",
            context_message_factory=factory,
        )
    )

    assert result == "继续"
    assert calls["count"] == 1
    assert client.calls[0]["messages"][1].content == "会话摘要: 由工厂注入。"


def test_react_agent_direct_tool_call_uses_injected_context_messages():
    client = RecordingClient(
        [
            _tool_response(
                tool_calls=[
                    {
                        "id": "call_1",
                        "name": "get_status",
                        "arguments": "{}",
                    }
                ]
            ),
            _tool_response("状态正常"),
        ]
    )
    agent = ReActAgent(
        client=client,
        model="demo",
        tools=[
            ToolDefinition(
                name="get_status",
                description="获取状态",
                parameters={"type": "object", "properties": {}},
            )
        ],
        system_prompt="系统提示",
    )
    captured: list[dict[str, object]] = []
    agent._register_tool_executors(
        {
            "get_status": lambda args: captured.append(args)
            or {"ok": True, "stage": "rolling_outline"}
        }
    )

    result = asyncio.run(
        agent.run(
            "查看状态",
            context_messages=[Message("assistant", "会话摘要: 已确认章节范围。")],
        )
    )

    assert result == "状态正常"
    assert captured == [{}]
    assert len(client.calls) == 2
    assert client.calls[0]["messages"][1].content.startswith("会话摘要")
    assert any(message.role == "tool" for message in client.calls[1]["messages"])


def test_react_agent_action_tool_call_uses_injected_context_messages():
    client = RecordingClient(
        [
            _tool_response(
                tool_calls=[
                    {
                        "id": "call_1",
                        "name": "summarize_ideation",
                        "arguments": "{}",
                    }
                ]
            ),
            _tool_response("已汇总"),
        ]
    )
    agent = ReActAgent(
        client=client,
        model="demo",
        tools=[
            ToolDefinition(
                name="summarize_ideation",
                description="汇总想法",
                parameters={"type": "object", "properties": {}},
            )
        ],
        system_prompt="系统提示",
    )
    captured: list[dict[str, object]] = []
    agent._register_tool_executors(
        {
            "summarize_ideation": lambda args: captured.append(args) or {
                "ok": True,
                "action": "summarize_ideation",
            }
        }
    )

    result = asyncio.run(
        agent.run(
            "先帮我汇总一下当前想法",
            context_messages=[Message("assistant", "最近会话摘要: 设定已稳定。")],
        )
    )

    assert result == "已汇总"
    assert captured == [{}]
    assert len(client.calls) == 2
    assert client.calls[0]["messages"][1].content.startswith("最近会话摘要")
    assert any(message.role == "tool" for message in client.calls[1]["messages"])


def test_react_agent_stops_when_outline_draft_waits_for_confirmation():
    client = RecordingClient(
        [
            _tool_response(
                tool_calls=[
                    {
                        "id": "call_1",
                        "name": "generate_outline_draft",
                        "arguments": '{"request_text": "生成大纲"}',
                    }
                ]
            ),
            _tool_response("不应该继续调用模型"),
        ]
    )
    events: list[dict] = []
    agent = ReActAgent(
        client=client,
        model="demo",
        tools=[
            ToolDefinition(
                name="generate_outline_draft",
                description="生成大纲草案",
                parameters={"type": "object", "properties": {}},
            )
        ],
        system_prompt="系统提示",
        activity_callback=events.append,
    )
    agent._register_tool_executors(
        {
            "generate_outline_draft": lambda args: {
                "ok": True,
                "message": "大纲草案已生成。请确认可写范围。",
                "next_action": "request_outline_confirmation",
            }
        }
    )

    result = asyncio.run(agent.run("确认汇总并生成大纲"))

    assert result == "大纲草案已生成。请确认可写范围。"
    assert len(client.calls) == 1
    assert [event["event"] for event in events] == [
        "run_started",
        "model_started",
        "model_completed",
        "tool_started",
        "tool_completed",
        "response_ready",
        "run_completed",
    ]


def test_react_agent_does_not_return_intermediate_tool_call_content():
    client = RecordingClient(
        [
            _tool_response(
                "清理残留太碎。我丢弃重来，用更大的 old_text 块一次性完成。",
                tool_calls=[
                    {
                        "id": "call_1",
                        "name": "stage_outline_edits",
                        "arguments": "{}",
                    }
                ],
            )
        ]
    )
    agent = ReActAgent(
        client=client,
        model="demo",
        tools=[
            ToolDefinition(
                name="stage_outline_edits",
                description="暂存大纲修改",
                parameters={"type": "object", "properties": {}},
            )
        ],
        system_prompt="系统提示",
        max_turns=1,
    )
    agent._register_tool_executors(
        {
            "stage_outline_edits": lambda args: {
                "ok": True,
                "message": "大纲增量修改已暂存。",
            }
        }
    )

    result = asyncio.run(agent.run("修改大纲"))

    assert "old_text" not in result
    assert "清理残留" not in result
    assert "还没有整理出最终结果" in result


def test_react_agent_runs_sync_tools_outside_the_active_event_loop():
    client = RecordingClient(
        [
            _tool_response(
                tool_calls=[
                    {
                        "id": "call_1",
                        "name": "write_like_tool",
                        "arguments": "{}",
                    }
                ]
            ),
            _tool_response("写作完成"),
        ]
    )
    agent = ReActAgent(
        client=client,
        model="demo",
        tools=[
            ToolDefinition(
                name="write_like_tool",
                description="模拟内部使用 asyncio.run 的同步写作入口",
                parameters={"type": "object", "properties": {}},
            )
        ],
        system_prompt="系统提示",
    )

    def sync_tool(args):
        async def nested_write():
            return "nested-ok"

        return {"ok": True, "value": asyncio.run(nested_write())}

    agent._register_tool_executors({"write_like_tool": sync_tool})

    result = asyncio.run(agent.run("写一章"))

    assert result == "写作完成"
    tool_messages = [
        message.content
        for message in client.calls[1]["messages"]
        if message.role == "tool"
    ]
    assert tool_messages == ['{"ok": true, "value": "nested-ok"}']


def test_react_agent_emits_real_model_tool_and_completion_activity():
    client = RecordingClient(
        [
            _tool_response(
                "我先读取作品状态。",
                tool_calls=[
                    {
                        "id": "call_1",
                        "name": "get_status",
                        "arguments": '{"chapter_id": "ch_007"}',
                    }
                ]
            ),
            _tool_response("状态正常"),
        ]
    )
    events: list[dict] = []
    agent = ReActAgent(
        client=client,
        model="demo",
        tools=[
            ToolDefinition(
                name="get_status",
                description="获取状态",
                parameters={"type": "object", "properties": {}},
            )
        ],
        system_prompt="系统提示",
        activity_callback=events.append,
    )
    agent._register_tool_executors(
        {"get_status": lambda args: {"ok": True, "stage": "chapter_preflight"}}
    )

    result = asyncio.run(agent.run("查看状态"))

    assert result == "状态正常"
    assert [event["event"] for event in events] == [
        "run_started",
        "model_started",
        "model_completed",
        "tool_started",
        "tool_completed",
        "model_started",
        "model_completed",
        "response_ready",
        "run_completed",
    ]
    assert events[3]["tool"] == "get_status"
    assert events[2]["message"] == "我先读取作品状态。"
    assert events[3]["arguments"] == {"chapter_id": "ch_007"}
    assert events[4]["ok"] is True
    assert '"stage": "chapter_preflight"' in events[4]["result"]


def test_react_agent_repairs_malformed_tool_arguments_before_execution():
    client = RecordingClient(
        [
            _tool_response(
                tool_calls=[
                    {
                        "id": "broken",
                        "name": "stage_outline_edits",
                        "arguments": '{"base_revision":"rev-1","edits":[',
                    }
                ]
            ),
            _tool_response(
                tool_calls=[
                    {
                        "id": "fixed",
                        "name": "stage_outline_edits",
                        "arguments": (
                            '{"base_revision":"rev-1","edits":[],"final_batch":false}'
                        ),
                    }
                ]
            ),
            _tool_response("已按批次暂存"),
        ]
    )
    events: list[dict] = []
    calls: list[dict] = []
    agent = ReActAgent(
        client=client,
        model="demo",
        tools=[
            ToolDefinition(
                name="stage_outline_edits",
                description="分批暂存大纲",
                parameters={
                    "type": "object",
                    "properties": {
                        "base_revision": {"type": "string"},
                        "edits": {"type": "array"},
                        "final_batch": {"type": "boolean"},
                    },
                    "required": ["base_revision", "edits"],
                },
            )
        ],
        system_prompt="系统提示",
        activity_callback=events.append,
    )
    agent._register_tool_executors(
        {"stage_outline_edits": lambda args: calls.append(args) or {"ok": True}}
    )

    result = asyncio.run(agent.run("重排整卷大纲"))

    assert result == "已按批次暂存"
    assert calls == [{"base_revision": "rev-1", "edits": [], "final_batch": False}]
    assert len(client.calls) == 3
    repair_message = client.calls[1]["messages"][-1].content
    assert "stage_outline_edits" in repair_message
    assert "任何对应工具都没有执行" in repair_message
    assert "缩小单次修改范围" in repair_message
    assert any(event["event"] == "model_retry" for event in events)


def test_react_agent_reports_precise_error_after_repair_is_exhausted():
    malformed = _tool_response(
        tool_calls=[
            {
                "id": "broken",
                "name": "stage_outline_edits",
                "arguments": '{"edits":[{"old_text":"未闭合',
            }
        ]
    )
    events: list[dict] = []
    agent = ReActAgent(
        client=RecordingClient([malformed, malformed]),
        model="demo",
        tools=[],
        system_prompt="系统提示",
        max_model_repairs=1,
        activity_callback=events.append,
    )

    with pytest.raises(ProviderResponseError) as raised:
        asyncio.run(agent.run("重排整卷大纲"))

    assert raised.value.code == "MALFORMED_TOOL_ARGUMENTS"
    assert raised.value.details["attempts"] == 2
    assert "失败的工具调用没有执行" in str(raised.value)
    assert events[-1]["event"] == "run_failed"


def test_react_agent_increases_output_budget_when_truncated():
    class TruncatingClient(RecordingClient):
        def __init__(self):
            super().__init__([_tool_response("扩容后完成")])
            self.config = SimpleNamespace(max_tokens=24000, context_tokens=160000)
            self.attempts = 0

        def chat_with_tools(self, messages, tools, **kwargs):
            self.calls.append(
                {
                    "messages": list(messages),
                    "tools": list(tools),
                    "kwargs": dict(kwargs),
                }
            )
            self.attempts += 1
            if self.attempts == 1:
                raise ProviderResponseError(
                    "MODEL_OUTPUT_TRUNCATED",
                    "模型输出因长度限制被截断",
                )
            return self.responses.pop(0)

    client = TruncatingClient()
    events: list[dict] = []
    agent = ReActAgent(
        client=client,
        model="demo",
        tools=[],
        system_prompt="系统提示",
        activity_callback=events.append,
    )

    result = asyncio.run(agent.run("重排整卷大纲"))

    assert result == "扩容后完成"
    # The first attempt keeps the configured budget; the retry raises it.
    assert client.calls[0]["kwargs"].get("max_tokens") is None
    assert client.calls[1]["kwargs"]["max_tokens"] == 48000
    # The loop runs the classified retry policy, so LiteLLM's own retry is off.
    assert client.calls[0]["kwargs"]["max_retries"] == 0
    retry_event = next(event for event in events if event["event"] == "model_retry")
    assert "24,000" in retry_event["message"]
    assert "48,000" in retry_event["message"]
    repair_message = client.calls[1]["messages"][-1].content
    assert "最大输出从 24,000 提高到 48,000 Token" in repair_message


def test_truncation_output_budget_never_exceeds_half_context_window():
    client = RecordingClient([])
    client.config = SimpleNamespace(max_tokens=24000, context_tokens=64000)
    agent = ReActAgent(
        client=client,
        model="demo",
        tools=[],
        system_prompt="系统提示",
    )

    assert agent._next_truncation_output_budget(None) == (24000, 32000)
    assert agent._next_truncation_output_budget(32000) == (32000, 32000)


def test_react_agent_returns_field_level_schema_feedback_to_model():
    client = RecordingClient(
        [
            _tool_response(
                tool_calls=[
                    {
                        "id": "wrong-type",
                        "name": "stage_outline_edits",
                        "arguments": '{"base_revision":"rev-1","edits":"整卷"}',
                    }
                ]
            ),
            _tool_response("请按数组格式重试"),
        ]
    )
    calls: list[dict] = []
    agent = ReActAgent(
        client=client,
        model="demo",
        tools=[
            ToolDefinition(
                name="stage_outline_edits",
                description="分批暂存大纲",
                parameters={
                    "type": "object",
                    "properties": {
                        "base_revision": {"type": "string"},
                        "edits": {"type": "array"},
                    },
                    "required": ["base_revision", "edits"],
                },
            )
        ],
        system_prompt="系统提示",
    )
    agent._register_tool_executors(
        {"stage_outline_edits": lambda args: calls.append(args) or {"ok": True}}
    )

    result = asyncio.run(agent.run("修改大纲"))

    assert result == "请按数组格式重试"
    assert calls == []
    tool_feedback = next(
        message.content
        for message in client.calls[1]["messages"]
        if message.role == "tool"
    )
    assert "字段 $.edits 应为数组，实际为字符串" in tool_feedback


def test_react_agent_inherits_valid_required_fields_when_retry_fixes_one_field():
    client = RecordingClient(
        [
            _tool_response(
                tool_calls=[
                    {
                        "id": "wrong-anchor",
                        "name": "stage_outline_edits",
                        "arguments": (
                            '{"base_revision":"draft-1","edits":['
                            '{"old_text":"错误标题","new_text":"新内容"}],'
                            '"batch_label":"第二批","final_batch":false}'
                        ),
                    }
                ]
            ),
            _tool_response(
                tool_calls=[
                    {
                        "id": "fixed-anchor",
                        "name": "stage_outline_edits",
                        "arguments": (
                            '{"base_revision":"draft-1","edits":['
                            '{"old_text":"准确标题","new_text":"新内容"}],'
                            '"batch_label":"第二批"}'
                        ),
                    }
                ]
            ),
            _tool_response("已继续下一批"),
        ]
    )
    calls: list[dict] = []
    events: list[dict] = []

    def stage(args):
        calls.append(args)
        if len(calls) == 1:
            return {
                "ok": False,
                "error": "old_text_not_found",
                "message": "第 1 个修改的 old_text 未匹配当前待确认草稿。",
                "details": {"field_path": "$.edits[0].old_text"},
            }
        return {
            "ok": True,
            "batch_count": 2,
            "draft_revision": "draft-2",
            "final_batch": args["final_batch"],
        }

    agent = ReActAgent(
        client=client,
        model="demo",
        tools=[
            ToolDefinition(
                name="stage_outline_edits",
                description="分批暂存大纲",
                parameters={
                    "type": "object",
                    "properties": {
                        "base_revision": {"type": "string"},
                        "edits": {"type": "array"},
                        "batch_label": {"type": "string"},
                        "final_batch": {"type": "boolean"},
                    },
                    "required": ["base_revision", "edits", "final_batch"],
                },
            )
        ],
        system_prompt="系统提示",
        activity_callback=events.append,
    )
    agent._register_tool_executors({"stage_outline_edits": stage})

    result = asyncio.run(agent.run("继续分批修改大纲"))

    assert result == "已继续下一批"
    assert len(calls) == 2
    assert calls[1]["edits"][0]["old_text"] == "准确标题"
    assert calls[1]["final_batch"] is False
    repaired_call = next(
        event
        for event in events
        if event["event"] == "tool_started" and event["tool_call_id"] == "fixed-anchor"
    )
    assert repaired_call["message"].endswith("$.final_batch")
    repaired_result = next(
        message.content
        for message in client.calls[2]["messages"]
        if message.role == "tool" and message.tool_call_id == "fixed-anchor"
    )
    assert '"inherited_fields": ["$.final_batch"]' in repaired_result


def test_react_agent_applies_exact_old_text_suggestion_on_matching_retry():
    exact_old_text = "#### 第1章：拾荒者与潮涌\n\n> 戏剧位置: 起\n"
    replacement = "#### 第1章：潮涌来临\n\n> 预估字数: 6000\n"
    client = RecordingClient(
        [
            _tool_response(
                tool_calls=[
                    {
                        "id": "wrong-anchor",
                        "name": "stage_outline_edits",
                        "arguments": json.dumps(
                            {
                                "base_revision": "draft-1",
                                "edits": [
                                    {
                                        "old_text": "#### 第1章：拾荒者与潮涌\n戏剧位置: 起",
                                        "new_text": replacement,
                                    }
                                ],
                                "final_batch": False,
                            },
                            ensure_ascii=False,
                        ),
                    }
                ]
            ),
            _tool_response(
                tool_calls=[
                    {
                        "id": "still-guessed",
                        "name": "stage_outline_edits",
                        "arguments": json.dumps(
                            {
                                "base_revision": "draft-1",
                                "edits": [
                                    {
                                        "old_text": "#### 第1章：拾荒者与潮涌\n戏剧位置: 起",
                                        "new_text": replacement,
                                    }
                                ],
                            },
                            ensure_ascii=False,
                        ),
                    }
                ]
            ),
            _tool_response("已继续下一批"),
        ]
    )
    calls: list[dict] = []
    events: list[dict] = []

    def stage(args):
        calls.append(args)
        if len(calls) == 1:
            return {
                "ok": False,
                "error": "old_text_not_found",
                "message": "第 1 个修改的 old_text 未匹配当前正式大纲。",
                "details": {
                    "field_path": "$.edits[0].old_text",
                    "suggested_old_text": exact_old_text,
                    "suggested_old_text_truncated": False,
                    "retry_base_revision": "draft-1",
                },
            }
        return {
            "ok": True,
            "batch_count": 1,
            "draft_revision": "draft-2",
            "final_batch": args["final_batch"],
        }

    agent = ReActAgent(
        client=client,
        model="demo",
        tools=[
            ToolDefinition(
                name="stage_outline_edits",
                description="分批暂存大纲",
                parameters={
                    "type": "object",
                    "properties": {
                        "base_revision": {"type": "string"},
                        "edits": {"type": "array"},
                        "final_batch": {"type": "boolean"},
                    },
                    "required": ["base_revision", "edits", "final_batch"],
                },
            )
        ],
        system_prompt="系统提示",
        activity_callback=events.append,
    )
    agent._register_tool_executors({"stage_outline_edits": stage})

    result = asyncio.run(agent.run("继续分批修改大纲"))

    assert result == "已继续下一批"
    assert calls[1]["edits"][0]["old_text"] == exact_old_text
    assert calls[1]["final_batch"] is False
    repaired_call = next(
        event
        for event in events
        if event["event"] == "tool_started" and event["tool_call_id"] == "still-guessed"
    )
    assert "$.edits[0].old_text" in repaired_call["message"]
    repaired_result = next(
        message.content
        for message in client.calls[2]["messages"]
        if message.role == "tool" and message.tool_call_id == "still-guessed"
    )
    assert '"corrected_fields": ["$.edits[0].old_text"]' in repaired_result


def test_document_edit_failures_and_repairs_are_isolated_by_path():
    paths = ("src/foundation.md", "src/world/rules.md")
    wrong_old_text = ("错误的基础设定", "错误的规则设定")
    exact_old_text = ("准确的基础设定", "准确的规则设定")

    def calls(prefix: str):
        return [
            {
                "id": f"{prefix}-{index}",
                "name": "edit_project_document",
                "arguments": json.dumps(
                    {
                        "path": path,
                        "edits": [
                            {
                                "old_text": wrong_old_text[index],
                                "new_text": f"新内容-{index}",
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
            }
            for index, path in enumerate(paths)
        ]

    client = RecordingClient(
        [
            _tool_response(tool_calls=calls("first")),
            _tool_response(tool_calls=calls("retry")),
            _tool_response("两份设定均已成功预览"),
        ]
    )
    executed: list[dict] = []

    def edit_document(args):
        executed.append(args)
        path_index = paths.index(args["path"])
        if args["edits"][0]["old_text"] != exact_old_text[path_index]:
            return {
                "ok": False,
                "error": "old_text_not_found",
                "message": "old_text 不存在",
                "details": {
                    "field_path": "$.edits[0].old_text",
                    "suggested_old_text": exact_old_text[path_index],
                    "suggested_old_text_truncated": False,
                    "retry_revision": f"revision-{path_index}",
                },
            }
        return {"ok": True, "applied": False, "preview_token": str(path_index) * 24}

    agent = ReActAgent(
        client=client,
        model="demo",
        tools=[
            ToolDefinition(
                name="edit_project_document",
                description="预览文档编辑",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "revision": {"type": "string"},
                        "edits": {"type": "array"},
                    },
                    "required": ["path", "edits"],
                },
            )
        ],
        system_prompt="系统提示",
    )
    agent._register_tool_executors({"edit_project_document": edit_document})

    result = asyncio.run(agent.run("同时修改基础设定和规则设定"))

    assert result == "两份设定均已成功预览"
    assert len(executed) == 4
    assert executed[2]["edits"][0]["old_text"] == exact_old_text[0]
    assert executed[2]["revision"] == "revision-0"
    assert executed[3]["edits"][0]["old_text"] == exact_old_text[1]
    assert executed[3]["revision"] == "revision-1"


def test_retry_suggestion_is_not_applied_when_replacement_changed():
    repaired, corrected = ReActAgent._apply_retry_suggestions(
        "stage_outline_edits",
        {
            "edits": [
                {
                    "old_text": "模型重新设计的锚点",
                    "new_text": "另一套修改内容",
                }
            ]
        },
        {
            "edits": [
                {
                    "old_text": "首次错误锚点",
                    "new_text": "原修改内容",
                }
            ]
        },
        {"$.edits[0].old_text": "工具返回的准确原文"},
    )

    assert corrected == []
    assert repaired["edits"][0]["old_text"] == "模型重新设计的锚点"


def test_react_agent_does_not_inherit_the_field_identified_as_invalid():
    client = RecordingClient(
        [
            _tool_response(
                tool_calls=[
                    {
                        "id": "wrong-anchor",
                        "name": "stage_outline_edits",
                        "arguments": (
                            '{"base_revision":"draft-1","edits":['
                            '{"old_text":"错误标题","new_text":"新内容"}],'
                            '"final_batch":false}'
                        ),
                    }
                ]
            ),
            _tool_response(
                tool_calls=[
                    {
                        "id": "missing-edits",
                        "name": "stage_outline_edits",
                        "arguments": '{"base_revision":"draft-1","final_batch":false}',
                    }
                ]
            ),
        ]
    )
    calls: list[dict] = []

    def stage(args):
        calls.append(args)
        return {
            "ok": False,
            "error": "old_text_not_found",
            "message": "第 1 个修改的 old_text 未匹配当前待确认草稿。",
            "details": {"field_path": "$.edits[0].old_text"},
        }

    agent = ReActAgent(
        client=client,
        model="demo",
        tools=[
            ToolDefinition(
                name="stage_outline_edits",
                description="分批暂存大纲",
                parameters={
                    "type": "object",
                    "properties": {
                        "base_revision": {"type": "string"},
                        "edits": {"type": "array"},
                        "final_batch": {"type": "boolean"},
                    },
                    "required": ["base_revision", "edits", "final_batch"],
                },
            )
        ],
        system_prompt="系统提示",
    )
    agent._register_tool_executors({"stage_outline_edits": stage})

    result = asyncio.run(agent.run("继续分批修改大纲"))

    # The property under test: the server rejected `$.edits[0].old_text`, and the
    # retry must not blindly re-send the same edit. The retry here is malformed
    # (it drops `edits` entirely), so it never reaches the executor at all —
    # which `len(calls) == 1` establishes. Under per-batch failure keying that
    # malformed retry is a *different* edit set rather than "the same batch
    # failing twice", so it no longer consumes the first batch's retry budget and
    # the loop retries instead of aborting the turn; the final message is
    # therefore the max-turns notice rather than the failure-limit notice.
    assert len(calls) == 1
    assert calls[0]["edits"][0]["old_text"] == "错误标题"
    assert result


def test_react_agent_stops_after_repeated_tool_failures():
    client = RecordingClient(
        [
            _tool_response(
                tool_calls=[
                    {
                        "id": "call_1",
                        "name": "delegate_chapter_write",
                        "arguments": '{"chapter_id": "ch_007"}',
                    }
                ]
            ),
            _tool_response(
                tool_calls=[
                    {
                        "id": "call_2",
                        "name": "delegate_chapter_write",
                        "arguments": '{"chapter_id": "ch_007"}',
                    }
                ]
            ),
            _tool_response("不应该继续"),
        ]
    )
    agent = ReActAgent(
        client=client,
        model="demo",
        tools=[
            ToolDefinition(
                name="delegate_chapter_write",
                description="写章",
                parameters={"type": "object", "properties": {}},
            )
        ],
        system_prompt="系统提示",
    )
    calls = {"count": 0}

    def failing_tool(args):
        calls["count"] += 1
        return {"ok": False, "reason": "writer backend failed"}

    agent._register_tool_executors({"delegate_chapter_write": failing_tool})

    result = asyncio.run(agent.run("写下一章"))

    assert calls["count"] == 2
    assert len(client.calls) == 2
    assert "delegate_chapter_write 连续失败 2 次" in result
    assert "writer backend failed" in result


def test_react_agent_stops_after_repeated_tool_exceptions():
    client = RecordingClient(
        [
            _tool_response(
                tool_calls=[
                    {
                        "id": "call_1",
                        "name": "unstable_tool",
                        "arguments": "{}",
                    }
                ]
            ),
            _tool_response(
                tool_calls=[
                    {
                        "id": "call_2",
                        "name": "unstable_tool",
                        "arguments": "{}",
                    }
                ]
            ),
            _tool_response("不应该继续"),
        ]
    )
    agent = ReActAgent(
        client=client,
        model="demo",
        tools=[
            ToolDefinition(
                name="unstable_tool",
                description="不稳定工具",
                parameters={"type": "object", "properties": {}},
            )
        ],
        system_prompt="系统提示",
    )

    def failing_tool(args):
        raise RuntimeError("boom")

    agent._register_tool_executors({"unstable_tool": failing_tool})

    result = asyncio.run(agent.run("运行工具"))

    assert len(client.calls) == 2
    assert "unstable_tool 连续失败 2 次" in result
    assert "boom" in result


def test_react_agent_exposes_only_explicitly_requested_tool():
    client = RecordingClient([_tool_response("已完成")])
    agent = ReActAgent(
        client=client,
        model="demo",
        tools=[
            ToolDefinition(
                name="promote_source_pack",
                description="晋升来源包",
                parameters={"type": "object", "properties": {}},
            ),
            ToolDefinition(
                name="read_project_document",
                description="读取项目文档",
                parameters={"type": "object", "properties": {}},
            ),
        ],
        system_prompt="系统提示",
    )

    result = asyncio.run(
        agent.run("只调用 promote_source_pack，不要调用任何其他工具。")
    )

    assert result == "已完成"
    assert [
        item["function"]["name"] for item in client.calls[0]["tools"]
    ] == ["promote_source_pack"]


def test_react_agent_keeps_primary_success_when_followup_tool_repeatedly_fails():
    client = RecordingClient(
        [
            _tool_response(
                tool_calls=[
                    {
                        "id": "call_1",
                        "name": "promote_source_pack",
                        "arguments": '{"source_id": "source_a"}',
                    }
                ]
            ),
            _tool_response(
                tool_calls=[
                    {
                        "id": "call_2",
                        "name": "read_project_document",
                        "arguments": '{"path": "novel_config.yaml"}',
                    }
                ]
            ),
            _tool_response(
                tool_calls=[
                    {
                        "id": "call_3",
                        "name": "read_project_document",
                        "arguments": '{"path": "data/style/composed.md"}',
                    }
                ]
            ),
        ]
    )
    events: list[dict] = []
    agent = ReActAgent(
        client=client,
        model="demo",
        tools=[
            ToolDefinition(
                name="promote_source_pack",
                description="晋升来源包",
                parameters={"type": "object", "properties": {}},
            ),
            ToolDefinition(
                name="read_project_document",
                description="读取项目文档",
                parameters={"type": "object", "properties": {}},
            ),
        ],
        system_prompt="系统提示",
        activity_callback=events.append,
    )
    read_calls: list[dict] = []
    agent._register_tool_executors(
        {
            "promote_source_pack": lambda args: {
                "ok": True,
                "source_id": args["source_id"],
                "promoted": ["style"],
            },
            "read_project_document": lambda args: read_calls.append(args)
            or {"ok": True},
        }
    )

    result = asyncio.run(
        agent.run("只调用 promote_source_pack，晋升后报告结果。")
    )

    assert "主操作 promote_source_pack 已成功" in result
    assert '"promoted": ["style"]' in result
    assert "read_project_document 连续失败 2 次" in result
    assert read_calls == []
    assert not any(event["event"] == "run_failed" for event in events)
    assert events[-1]["event"] == "run_completed"


def test_partial_success_hides_read_payloads_and_summarizes_pending_outline_batch():
    response = ReActAgent._partial_success_response(
        [
            ("read_outline", '{"ok":true,"content":"' + "大纲" * 5000 + '"}'),
            (
                "stage_outline_edits",
                '{"ok":true,"batch_count":1,"draft_revision":"eeb55d09fbc4749f",'
                '"final_batch":false,"diff":"' + "很长" * 5000 + '"}',
            ),
            ("read_project_document", '{"ok":true,"content":"canonical"}'),
        ],
        failed_tool="stage_outline_edits",
        failure_reason="第 1 个修改的 old_text 未匹配当前待确认草稿",
        failure_count=2,
    )

    assert response.startswith("主操作 stage_outline_edits 已成功并保留")
    assert "draft_revision=eeb55d09fbc4" in response
    assert "final_batch=false" in response
    assert "正式大纲尚未写入" in response
    assert "read_outline" not in response
    assert "read_project_document" not in response
    assert "canonical" not in response
    assert len(response) < 600


def test_react_agent_does_not_abort_on_confirmation_policy_blocks():
    client = RecordingClient(
        [
            _tool_response(
                tool_calls=[
                    {
                        "id": "call_1",
                        "name": "edit_project_document",
                        "arguments": '{"confirm": true}',
                    }
                ]
            ),
            _tool_response(
                tool_calls=[
                    {
                        "id": "call_2",
                        "name": "edit_project_document",
                        "arguments": '{"confirm": true}',
                    }
                ]
            ),
            _tool_response("请明确回复“确认应用”后再写入。"),
        ]
    )
    agent = ReActAgent(
        client=client,
        model="demo",
        tools=[
            ToolDefinition(
                name="edit_project_document",
                description="编辑文档",
                parameters={"type": "object", "properties": {}},
            )
        ],
        system_prompt="系统提示",
        max_tool_failures=2,
    )

    def blocked_tool(args):
        return {
            "ok": False,
            "blocked": True,
            "error": "explicit_user_confirmation_required",
            "message": "尚未收到用户对本次 diff 的明确应用指令，项目文件未修改。",
            "next_action": "request_mutation_confirmation",
        }

    agent._register_tool_executors({"edit_project_document": blocked_tool})
    result = asyncio.run(agent.run("应用修改"))

    assert "连续失败" not in result
    assert "确认应用" in result
    assert len(client.calls) == 3
