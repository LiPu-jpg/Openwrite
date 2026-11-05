"""Why a turn died on a provider hiccup.

The agent loop repaired a malformed answer, raised the budget for a truncated
one, and even fixed the arguments of a failed tool call - but a rate limit, a
network blip or a timeout went straight through and ended the whole turn.
The provider said nothing about the request, so ending the run on it was the
one failure the loop could have avoided.

These cases pin the classification: the provider hiccup is retried, a bad key
is not, and the retry never stacks on LiteLLM's own.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from tools.agent.base import AgentContext
from tools.agent.react import ReActAgent
from tools.agent.writer import WriterAgent
from tools.llm.client import LLMClient, LLMConfig
from tools.llm.errors import AuthenticationError, RateLimitError


@pytest.fixture(autouse=True)
def _no_backoff_wait(monkeypatch):
    monkeypatch.setenv("OW_RETRY_BASE_SECONDS", "0")


def _tool_response(content: str = "", tool_calls: list[dict] | None = None):
    return SimpleNamespace(content=content, tool_calls=tool_calls or [])


class ScriptedToolClient:
    """A tool client that replays a scripted list of answers and failures."""

    def __init__(self, script):
        self.script = list(script)
        self.calls: list[dict] = []

    def chat_with_tools(self, messages, tools, **kwargs):
        self.calls.append({"messages": list(messages), "kwargs": dict(kwargs)})
        if not self.script:
            raise AssertionError("the client was called more times than the script allows")
        kind, value = self.script.pop(0)
        if kind == "error":
            raise value
        return value


def _agent(client, **kwargs) -> ReActAgent:
    return ReActAgent(
        client=client,
        model="demo",
        tools=[],
        system_prompt="系统提示",
        **kwargs,
    )


# ── the tool loop ────────────────────────────────────────────────────────────


def test_a_rate_limit_does_not_end_the_turn():
    # The provider said no; the request was fine. Asking again a moment later
    # is the whole point of a retry.
    client = ScriptedToolClient(
        [
            ("error", RateLimitError("API 返回 429（请求过多），请稍后重试", "429")),
            ("answer", _tool_response("已经查完了")),
        ]
    )
    result = asyncio.run(_agent(client).run("继续写"))
    assert result == "已经查完了"
    assert len(client.calls) == 2


def test_a_network_blip_does_not_end_the_turn():
    from tools.llm.errors import NetworkError

    client = ScriptedToolClient(
        [
            ("error", NetworkError("连接被重置")),
            ("answer", _tool_response("重连后完成")),
        ]
    )
    assert asyncio.run(_agent(client).run("继续写")) == "重连后完成"


def test_a_bad_key_is_not_retried():
    # Retrying a 401 just asks the provider to say no again.
    client = ScriptedToolClient(
        [("error", AuthenticationError("API Key 无效", "401")) for _ in range(3)]
    )
    with pytest.raises(AuthenticationError):
        asyncio.run(_agent(client).run("继续写"))
    assert len(client.calls) == 1


def test_a_provider_that_stays_down_does_not_loop_forever():
    client = ScriptedToolClient(
        [("error", RateLimitError("API 返回 429", "429")) for _ in range(20)]
    )
    agent = _agent(client, max_transport_failures=2)
    with pytest.raises(RateLimitError):
        asyncio.run(agent.run("继续写"))
    # One call plus the two allowed retries.
    assert len(client.calls) == 3


def test_the_retry_layer_is_the_only_one():
    # LiteLLM retries on its own; two layers stack into a burst, and the burst
    # is what a rate limiter punishes.
    client = ScriptedToolClient([("answer", _tool_response("好"))])
    asyncio.run(_agent(client).run("继续写"))
    assert client.calls[0]["kwargs"]["max_retries"] == 0


def test_a_client_without_the_keyword_still_works():
    # A custom client may not know `max_retries` at all. Passing it anyway
    # would turn a working setup into a TypeError.
    class OldClient:
        def __init__(self):
            self.calls = 0

        def chat_with_tools(self, messages, tools):
            self.calls += 1
            return _tool_response("老客户端")

    client = OldClient()
    assert asyncio.run(_agent(client).run("继续写")) == "老客户端"
    assert client.calls == 1


# ── chapter writing ──────────────────────────────────────────────────────────


def test_the_writer_survives_a_rate_limit(tmp_path):
    calls = []

    def chat(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RateLimitError("API 返回 429（请求过多），请稍后重试", "429")
        return SimpleNamespace(
            content="# 第一章\n\n" + "甲" * 1000,
            usage={},
            finish_reason="stop",
            total_tokens=0,
        )

    writer = WriterAgent(AgentContext(SimpleNamespace(chat=chat), "fake", str(tmp_path)))
    result = asyncio.run(writer._creative_write({}, 1, 0.7, 1000))
    assert result["word_count"] == 1000
    assert len(calls) == 2


def test_the_writer_does_not_retry_a_bad_key(tmp_path):
    calls = []

    def chat(**kwargs):
        calls.append(kwargs)
        raise AuthenticationError("API Key 无效", "401")

    writer = WriterAgent(AgentContext(SimpleNamespace(chat=chat), "fake", str(tmp_path)))
    with pytest.raises(AuthenticationError):
        asyncio.run(writer._creative_write({}, 1, 0.7, 1000))
    assert len(calls) == 1


def test_the_writer_turns_off_the_inner_retry(tmp_path):
    # The writer runs the classified retry policy, so LiteLLM's own retry has
    # to be off: two retry layers stack into a burst.
    calls = []

    def chat(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            content="# 第一章\n\n" + "甲" * 1000,
            usage={},
            finish_reason="stop",
            total_tokens=0,
        )

    writer = WriterAgent(AgentContext(SimpleNamespace(chat=chat), "fake", str(tmp_path)))
    asyncio.run(writer._creative_write({}, 1, 0.7, 1000))
    assert calls[0]["max_retries"] == 0


def test_a_client_without_the_retry_keyword_still_works(tmp_path):
    class NarrowClient:
        def chat(self, messages, temperature=None, max_tokens=None, stream=False,
                 on_progress=None, operation=""):
            return SimpleNamespace(
                content="# 第一章\n\n" + "甲" * 1000,
                usage={},
                finish_reason="stop",
                total_tokens=0,
            )

    writer = WriterAgent(AgentContext(NarrowClient(), "fake", str(tmp_path)))
    result = asyncio.run(writer._creative_write({}, 1, 0.7, 1000))
    assert result["word_count"] == 1000


# ── the client ───────────────────────────────────────────────────────────────


def test_the_tool_call_path_can_turn_off_the_inner_retry(monkeypatch):
    sent = []
    config = LLMConfig(model="fake", max_tokens=8192)
    client = LLMClient(config)

    def completion(**params):
        sent.append(params)
        return {
            "choices": [{"message": {"content": "正文"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }

    monkeypatch.setattr(client, "_completion", completion)
    client.chat_with_tools([], [{"type": "function", "function": {"name": "x"}}], max_retries=0)
    assert sent[0]["max_retries"] == 0

    sent.clear()
    client.chat_with_tools([], [{"type": "function", "function": {"name": "x"}}])
    # Without an override the configured count is used.
    assert sent[0]["max_retries"] == config.max_retries
