from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.llm.client import LLMClient, LLMConfig, Message, _plain_usage


class FakeLiteLLM:
    def __init__(self) -> None:
        self.completion_calls: list[dict] = []
        self.responses_calls: list[dict] = []
        self.trim_calls: list[dict] = []

    def token_counter(self, *, messages, tools=None, **kwargs) -> int:
        message_tokens = sum(len(str(item.get("content", ""))) for item in messages)
        return message_tokens + (200 if tools else 0)

    def trim_messages(self, *, messages, max_tokens, **kwargs):
        self.trim_calls.append({"messages": messages, "max_tokens": max_tokens, **kwargs})
        system = [item for item in messages if item["role"] == "system"]
        return system + messages[-1:]

    def completion(self, **kwargs):
        self.completion_calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="完成", reasoning_content=""),
                    finish_reason="stop",
                )
            ],
            usage={"prompt_tokens": 11, "completion_tokens": 5, "total_tokens": 16},
            model=kwargs["model"],
        )

    def responses(self, **kwargs):
        self.responses_calls.append(kwargs)
        return SimpleNamespace(
            output_text="Responses 完成",
            output=[],
            usage={"input_tokens": 9, "output_tokens": 3},
            model=kwargs["model"],
            status="completed",
        )


def test_usage_models_are_converted_to_serializable_plain_data():
    class TokenDetails:
        def model_dump(self, mode: str = "python"):
            assert mode == "json"
            return {"cached_tokens": 7, "audio_tokens": None}

    usage = _plain_usage(
        {
            "prompt_tokens": 11,
            "completion_tokens": 5,
            "total_tokens": 16,
            "prompt_tokens_details": TokenDetails(),
        }
    )

    assert usage == {
        "prompt_tokens": 11,
        "completion_tokens": 5,
        "total_tokens": 16,
        "prompt_tokens_details": {"cached_tokens": 7, "audio_tokens": None},
        "cost_reported": False,
    }


def test_responses_usage_is_normalized_to_shared_token_names():
    assert _plain_usage(
        {
            "input_tokens": 8,
            "output_tokens": 3,
            "output_tokens_details": {"reasoning_tokens": 2},
        }
    ) == {
        "input_tokens": 8,
        "output_tokens": 3,
        "output_tokens_details": {"reasoning_tokens": 2},
        "prompt_tokens": 8,
        "completion_tokens": 3,
        "total_tokens": 11,
        "completion_tokens_details": {"reasoning_tokens": 2},
        "cost_reported": False,
    }


@pytest.mark.parametrize("cost", [0, 0.00012345])
def test_openrouter_usage_cost_is_canonicalized_without_losing_raw_cost(cost: float):
    usage = _plain_usage(
        {
            "prompt_tokens": 8,
            "completion_tokens": 3,
            "total_tokens": 11,
            "cost": cost,
            "cost_details": {"upstream_inference_cost": cost},
        }
    )

    assert usage["cost"] == cost
    assert usage["cost_usd"] == cost
    assert usage["cost_reported"] is True
    assert usage["cost_details"] == {"upstream_inference_cost": cost}


def test_litellm_hidden_response_cost_is_merged_into_chat_usage():
    backend = FakeLiteLLM()

    def completion(**kwargs):
        backend.completion_calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="完成", reasoning_content=""),
                    finish_reason="stop",
                )
            ],
            usage={"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6},
            model="openrouter/model",
            _hidden_params={
                "response_cost": 0.0000042,
                "response_cost_details": {"prompt_cost": 0.000003},
                "api_key": "must-not-be-copied",
            },
        )

    backend.completion = completion
    response = LLMClient(LLMConfig(model="openrouter/model"), client=backend).chat(
        [Message("user", "继续")]
    )

    assert response.usage["response_cost"] == 0.0000042
    assert response.usage["cost_usd"] == 0.0000042
    assert response.usage["cost_reported"] is True
    assert response.usage["response_cost_details"] == {"prompt_cost": 0.000003}
    assert "api_key" not in response.usage
def test_provider_cost_wins_over_stale_normalized_alias():
    usage = _plain_usage({
        "prompt_tokens": 1,
        "completion_tokens": 1,
        "cost": 0,
        "response_cost": 0.25,
        "cost_usd": 9.99,
    })

    assert usage["cost_usd"] == 0
    assert usage["cost_reported"] is True


def test_llm_config_normalizes_full_chat_completions_endpoint():
    config = LLMConfig(
        provider="openai",
        api_key="test-key",
        base_url="https://open.bigmodel.cn/api/paas/v4/chat/completions",
        model="glm-5",
    )

    assert config.base_url == "https://open.bigmodel.cn/api/paas/v4"


def test_llm_config_reads_context_timeout_and_retry_from_env(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("LLM_API_KEY", "env-key")
    monkeypatch.setenv("LLM_BASE_URL", "https://open.bigmodel.cn/api/paas/v4/chat/completions")
    monkeypatch.setenv("LLM_MODEL", "glm-5")
    monkeypatch.setenv("OPENWRITE_CONTEXT_TOKENS", "128000")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "600")
    monkeypatch.setenv("LLM_MAX_RETRIES", "0")

    config = LLMConfig.from_env()

    assert config.base_url == "https://open.bigmodel.cn/api/paas/v4"
    assert config.context_tokens == 128000
    assert config.timeout_seconds == 600.0
    assert config.max_retries == 0


def test_chat_routes_openai_compatible_provider_through_litellm():
    backend = FakeLiteLLM()
    client = LLMClient(
        LLMConfig(
            provider="openai",
            api_key="test-key",
            base_url="https://open.bigmodel.cn/api/paas/v4/chat/completions",
            model="glm-5",
            timeout_seconds=600.0,
            max_retries=0,
        ),
        client=backend,
    )

    response = client.chat([Message("user", "写一段")])

    assert response.content == "完成"
    assert response.total_tokens == 16
    request = backend.completion_calls[0]
    assert request["custom_llm_provider"] == "openai"
    assert request["base_url"] == "https://open.bigmodel.cn/api/paas/v4"
    assert request["timeout"] == 600.0
    assert request["max_retries"] == 0
    assert request["drop_params"] is True


def test_anthropic_uses_same_litellm_completion_contract():
    backend = FakeLiteLLM()
    client = LLMClient(
        LLMConfig(
            provider="anthropic",
            api_key="test-key",
            base_url="https://api.anthropic.com",
            model="claude-sonnet-4-5",
        ),
        client=backend,
    )

    response = client.chat([Message("system", "系统"), Message("user", "继续")])

    assert response.provider == "anthropic"
    request = backend.completion_calls[0]
    assert request["custom_llm_provider"] == "anthropic"
    assert request["messages"][0] == {"role": "system", "content": "系统"}


def test_tool_calls_are_normalized_and_keep_tool_history():
    backend = FakeLiteLLM()

    def tool_completion(**kwargs):
        backend.completion_calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="",
                        tool_calls=[
                            SimpleNamespace(
                                id="call-1",
                                function=SimpleNamespace(
                                    name="get_status", arguments='{"chapter": "ch_007"}'
                                ),
                            )
                        ],
                    ),
                    finish_reason="tool_calls",
                )
            ],
            usage={},
            model="glm-5",
        )

    backend.completion = tool_completion
    client = LLMClient(LLMConfig(model="glm-5"), client=backend)
    assistant = Message("assistant", "")
    assistant.tool_calls = [
        {"id": "previous", "name": "get_status", "arguments": "{}"}
    ]

    response = client.chat_with_tools(
        [assistant, Message("tool", "ok", tool_call_id="previous")],
        [{"type": "function", "function": {"name": "get_status", "parameters": {}}}],
    )

    assert response.tool_calls == [
        {
            "id": "call-1",
            "name": "get_status",
            "arguments": '{"chapter": "ch_007"}',
        }
    ]
    request_messages = backend.completion_calls[0]["messages"]
    assert request_messages[0]["tool_calls"][0]["id"] == "previous"
    assert request_messages[1]["tool_call_id"] == "previous"


def test_responses_api_is_dispatched_through_litellm():
    backend = FakeLiteLLM()
    client = LLMClient(
        LLMConfig(model="gpt-5", api_format="responses"),
        client=backend,
    )

    response = client.chat([Message("user", "继续")])

    assert response.content == "Responses 完成"
    assert response.total_tokens == 12
    assert backend.responses_calls[0]["max_output_tokens"] == 24000


def test_chat_stream_normalizes_litellm_chunks_and_reports_progress():
    backend = FakeLiteLLM()

    def streaming_completion(**kwargs):
        backend.completion_calls.append(kwargs)
        return iter(
            [
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(content="流式", reasoning_content=""),
                            finish_reason=None,
                        )
                    ],
                    usage=None,
                    model="glm-5",
                ),
                SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            delta=SimpleNamespace(content="完成", reasoning_content=""),
                            finish_reason="stop",
                        )
                    ],
                    usage={"prompt_tokens": 4, "completion_tokens": 2},
                    model="glm-5",
                ),
            ]
        )

    backend.completion = streaming_completion
    client = LLMClient(LLMConfig(model="glm-5"), client=backend)
    progress = []

    response = client.chat(
        [Message("user", "继续")],
        stream=True,
        on_progress=progress.append,
    )

    assert response.content == "流式完成"
    assert response.finish_reason == "stop"
    assert response.total_tokens == 6
    assert progress[-1].total_chars == 4


def test_responses_stream_normalizes_output_text_events():
    backend = FakeLiteLLM()

    def streaming_responses(**kwargs):
        backend.responses_calls.append(kwargs)
        return iter(
            [
                SimpleNamespace(type="response.output_text.delta", delta="分段", model="gpt-5"),
                SimpleNamespace(type="response.output_text.delta", delta="响应", model="gpt-5"),
            ]
        )

    backend.responses = streaming_responses
    client = LLMClient(
        LLMConfig(model="gpt-5", api_format="responses"),
        client=backend,
    )

    response = client.chat([Message("user", "继续")], stream=True)

    assert response.content == "分段响应"
    assert backend.responses_calls[0]["stream"] is True


def test_real_litellm_backend_accepts_openwrite_request_shape_without_network():
    client = LLMClient(
        LLMConfig(
            provider="openai",
            model="gpt-4o-mini",
            api_key="not-used",
            extra={"mock_response": "LiteLLM mock ok"},
        )
    )

    response = client.chat([Message("user", "ping")])

    assert response.content == "LiteLLM mock ok"
    assert response.provider == "openai"


def test_thinking_is_scoped_to_the_configured_operation():
    backend = FakeLiteLLM()
    client = LLMClient(
        LLMConfig(
            model="deepseek-v4-flash",
            extra={"thinking_modes": {"review": "disabled", "chapter_write": "omit"}},
        ),
        client=backend,
    )

    client.chat([Message("user", "正文")], operation="chapter_write")
    client.chat([Message("user", "审稿")], operation="review")

    assert "extra_body" not in backend.completion_calls[0]
    assert backend.completion_calls[1]["extra_body"] == {"thinking": {"type": "disabled"}}


def test_unconfigured_thinking_is_not_sent_to_provider():
    backend = FakeLiteLLM()
    client = LLMClient(LLMConfig(model="gpt-4o-mini"), client=backend)

    client.chat([Message("user", "普通请求")], operation="review")

    assert "extra_body" not in backend.completion_calls[0]


def test_request_context_is_trimmed_at_the_proportional_tier():
    backend = FakeLiteLLM()
    client = LLMClient(
        LLMConfig(model="glm-5", context_tokens=2000, max_tokens=500),
        client=backend,
    )

    client.chat(
        [
            Message("system", "s" * 100),
            Message("assistant", "old" * 250),
            Message("user", "u" * 100),
        ]
    )

    assert client.last_context_plan["level"] == 2
    assert client.last_context_plan["target_ratio"] == 0.8
    assert client.last_context_plan["original_message_count"] == 3
    assert client.last_context_plan["final_message_count"] == 3
    assert client.last_context_plan["trimmed"] is True
    assert client.last_context_plan["within_budget"] is True
    assert "context compressed proportionally" in backend.completion_calls[0]["messages"][1][
        "content"
    ]
    assert backend.completion_calls[0]["messages"][-1]["role"] == "user"


def test_test_module_does_not_depend_on_default_project_registry(tmp_path: Path):
    # This test intentionally has no project setup: LLM routing is process-local.
    assert not (tmp_path / "data").exists()
