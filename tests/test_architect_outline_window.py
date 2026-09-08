import asyncio
import json
from types import SimpleNamespace

import pytest

from tools.architect import ArchitectAgent


def _response(numbers, **metadata):
    return SimpleNamespace(
        content=json.dumps(
            [{"number": number, "title": f"章节{number}", "summary": "规划"} for number in numbers]
        ),
        **metadata,
    )


class FakeClient:
    def __init__(self, *responses):
        self.responses = iter(responses)
        self.messages = []

    def chat(self, messages, **_kwargs):
        self.messages.append(messages)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def test_outline_window_output_budget_scales_and_respects_profile_cap():
    received = []
    client = FakeClient(_response([20]))
    client.config = SimpleNamespace(max_tokens=12000)
    original = client.chat

    def chat(messages, **kwargs):
        received.append(kwargs["max_tokens"])
        return original(messages, **kwargs)

    client.chat = chat
    agent = ArchitectAgent(SimpleNamespace(client=client))
    asyncio.run(agent.generate_outline("书名", "悬疑", "", 20, planning_context="规划事实"))
    assert received == [12000]


def test_outline_window_preserves_absolute_chapter_numbers_and_complete_context():
    client = FakeClient(_response([42, 43]))
    agent = ArchitectAgent(SimpleNamespace(client=client))
    context = "已冻结的规划事实" * 500 + "上下文末尾必须保留"

    result = asyncio.run(
        agent.generate_outline(
            "书名",
            "悬疑",
            "不应混入的旧摘要",
            2,
            start_chapter=42,
            planning_context=context,
        )
    )

    assert [item.number for item in result] == [42, 43]
    system, user = [item.content for item in client.messages[0]]
    assert '"number": 42' in system
    assert "必须恰好返回 2 章，连续编号" in system
    assert "起始章节（含）：第42章" in user
    assert "结束章节（含）：第43章" in user
    assert context in user
    assert "不应混入的旧摘要" not in user


def test_legacy_four_positional_arguments_keep_the_two_thousand_character_summary():
    client = FakeClient(_response([1]))
    agent = ArchitectAgent(SimpleNamespace(client=client))
    bible = "旧设定" * 1000 + "截断后不可见"

    result = asyncio.run(agent.generate_outline("书", "悬疑", bible, 1))

    assert [item.number for item in result] == [1]
    assert bible[:2000] in client.messages[0][1].content
    assert "截断后不可见" not in client.messages[0][1].content
    assert "起始章节（含）：第1章" in client.messages[0][1].content


def test_wrong_model_range_is_not_silently_renumbered_for_the_caller():
    client = FakeClient(_response([1, 1, 100]))
    agent = ArchitectAgent(SimpleNamespace(client=client))

    result = asyncio.run(agent.generate_outline("书", "悬疑", "设定", 2, start_chapter=42))

    # The benchmark validates the exact set; do not hide malformed model ranges.
    assert [item.number for item in result] == [1, 1, 100]


@pytest.mark.parametrize("start", [0, -1, True, False, 1.5, "42", None])
def test_invalid_start_is_rejected_before_any_model_call(start):
    client = FakeClient()
    agent = ArchitectAgent(SimpleNamespace(client=client))

    with pytest.raises(ValueError, match="positive integer"):
        asyncio.run(agent.generate_outline("书", "悬疑", "设定", 2, start_chapter=start))

    assert client.messages == []


def test_response_metadata_includes_empty_retry_usage_without_sensitive_response_fields():
    first = SimpleNamespace(
        content="",
        usage={"prompt_tokens": 10, "completion_tokens": 2},
        finish_reason="stop",
        model="model-one",
        provider="openai",
    )
    second = _response(
        [8],
        usage={"prompt_tokens": 20, "completion_tokens": 5, "response_cost": 0.1},
        finish_reason="stop",
        model="model-two",
        provider="openai",
        reasoning="private thought",
        api_key="private credential",
    )
    client = FakeClient(first, second, _response([9]))
    agent = ArchitectAgent(SimpleNamespace(client=client))

    asyncio.run(agent.generate_outline("书", "悬疑", "设定", 1, start_chapter=8))

    assert agent.response_attempt_count == 2
    assert len(agent.response_metadata_history) == 2
    assert agent.response_metadata_history[0]["usage"]["prompt_tokens"] == 10
    assert agent.last_response_metadata == {
        "usage": {"prompt_tokens": 20, "completion_tokens": 5, "response_cost": 0.1},
        "finish_reason": "stop",
        "model": "model-two",
        "provider": "openai",
    }
    second.usage["prompt_tokens"] = 999
    assert agent.last_response_metadata["usage"]["prompt_tokens"] == 20
    assert "private" not in json.dumps(agent.response_metadata_history)

    asyncio.run(agent.generate_outline("书", "悬疑", "设定", 1, start_chapter=9))
    assert agent.response_attempt_count == 1
    assert len(agent.response_metadata_history) == 1
    assert agent.last_response_metadata["usage"] == {}


def test_failed_provider_calls_do_not_reuse_previous_metadata():
    client = FakeClient(_response([1], usage={"total_tokens": 4}), RuntimeError(), RuntimeError())
    agent = ArchitectAgent(SimpleNamespace(client=client))
    asyncio.run(agent.generate_outline("书", "悬疑", "设定", 1))

    assert asyncio.run(agent.generate_outline("书", "悬疑", "设定", 1, start_chapter=2)) == []
    assert agent.response_attempt_count == 2
    assert agent.last_response_metadata == {}
    assert agent.response_metadata_history == []
