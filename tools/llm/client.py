"""Provider-neutral LLM client backed by LiteLLM."""

from __future__ import annotations

import copy
import json
import logging
import math
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, cast
from urllib.parse import urlsplit, urlunsplit

from .context import ContextBudgetPolicy

logger = logging.getLogger(__name__)

ProviderName = Literal["openai", "anthropic", "custom"]
APIFormat = Literal["chat", "responses"]


def _provider_name(value: Any) -> ProviderName:
    normalized = str(value or "openai").strip().lower()
    if normalized not in {"openai", "anthropic", "custom"}:
        normalized = "openai"
    return cast(ProviderName, normalized)


def _api_format(value: Any) -> APIFormat:
    normalized = str(value or "chat").strip().lower()
    if normalized not in {"chat", "responses"}:
        normalized = "chat"
    return cast(APIFormat, normalized)


def _value(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _plain_usage(usage: Any, *, response: Any = None) -> dict[str, Any]:
    """Convert SDK usage models into YAML/JSON-safe, OpenAI-shaped data."""

    def convert(value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return {str(key): convert(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [convert(item) for item in value]
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            try:
                return convert(model_dump(mode="json"))
            except TypeError:
                return convert(model_dump())
        return str(value)

    if usage is None:
        raw = {}
    elif isinstance(usage, dict):
        raw = usage
    else:
        model_dump = getattr(usage, "model_dump", None)
        if callable(model_dump):
            try:
                raw = model_dump(mode="json")
            except TypeError:
                raw = model_dump()
        else:
            try:
                raw = dict(usage)
            except (TypeError, ValueError):
                raw = {}
    converted = convert(raw)
    if not isinstance(converted, dict):
        converted = {}

    hidden = convert(_value(response, "_hidden_params", {}))
    hidden = hidden if isinstance(hidden, dict) else {}
    if "response_cost" not in converted and "response_cost" in hidden:
        converted["response_cost"] = hidden["response_cost"]
    if "response_cost_details" not in converted and "response_cost_details" in hidden:
        converted["response_cost_details"] = hidden["response_cost_details"]

    prompt = converted.get("prompt_tokens", converted.get("input_tokens", 0))
    completion = converted.get(
        "completion_tokens", converted.get("output_tokens", 0)
    )
    if "prompt_tokens" not in converted and prompt:
        converted["prompt_tokens"] = prompt
    if "completion_tokens" not in converted and completion:
        converted["completion_tokens"] = completion
    if "total_tokens" not in converted and (prompt or completion):
        converted["total_tokens"] = int(prompt or 0) + int(completion or 0)
    if "completion_tokens_details" not in converted and isinstance(
        converted.get("output_tokens_details"), dict
    ):
        converted["completion_tokens_details"] = converted["output_tokens_details"]

    explicit_reported = converted.get("cost_reported")
    cost: float | None = None
    # Preserve provider truth first: OpenRouter usage.cost, LiteLLM
    # response_cost, then our normalized compatibility alias.
    for key in ("cost", "response_cost", "cost_usd"):
        if key not in converted:
            continue
        try:
            candidate = float(converted[key])
        except (TypeError, ValueError, OverflowError):
            continue
        if math.isfinite(candidate) and candidate >= 0:
            cost = candidate
            break
    if cost is not None:
        converted["cost_usd"] = cost
    converted["cost_reported"] = (
        explicit_reported
        if isinstance(explicit_reported, bool)
        else cost is not None
    )
    return converted


def _content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            text = _value(block, "text", _value(block, "content", ""))
            if text:
                parts.append(str(text))
        return "".join(parts)
    return str(content)


def _ensure_exception(value: Any) -> Exception:
    if isinstance(value, Exception):
        return value
    return Exception(str(value))


@dataclass
class LLMResponse:
    """Normalized LLM response."""

    content: str
    usage: dict[str, Any] = field(default_factory=dict)
    model: str = ""
    provider: str = "openai"
    finish_reason: str = ""
    reasoning: str = ""

    @property
    def prompt_tokens(self) -> int:
        return int(self.usage.get("prompt_tokens", 0) or 0)

    @property
    def completion_tokens(self) -> int:
        return int(self.usage.get("completion_tokens", 0) or 0)

    @property
    def total_tokens(self) -> int:
        return int(self.usage.get("total_tokens", 0) or 0)


@dataclass
class ToolCallResponse:
    """Normalized function-calling response."""

    content: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, Any] = field(default_factory=dict)
    model: str = ""
    provider: str = "openai"
    finish_reason: str = ""

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


@dataclass
class Message:
    """Conversation message used by OpenWrite agents."""

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str = ""


@dataclass
class LLMConfig:
    """Runtime model configuration."""

    provider: ProviderName = "openai"
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    temperature: float = 0.7
    max_tokens: int = 24000
    context_tokens: int = 64000
    stream: bool = True
    api_format: APIFormat = "chat"
    timeout_seconds: float = 120.0
    max_retries: int = 3
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.provider = _provider_name(self.provider)
        self.api_format = _api_format(self.api_format)
        self.base_url = self._normalize_base_url(self.base_url)

    @classmethod
    def from_env(cls) -> LLMConfig:
        """Build a configuration from the active profile or legacy environment."""
        from tools.model_profiles import active_model_profile

        profile = active_model_profile()
        if profile:
            return cls(
                provider=_provider_name(profile["provider"]),
                api_key=profile["api_key"],
                base_url=profile["base_url"],
                model=profile["model"],
                temperature=float(
                    0.7 if profile.get("temperature") in {None, ""} else profile["temperature"]
                ),
                max_tokens=int(profile.get("max_output_tokens") or 24000),
                context_tokens=int(profile.get("context_tokens") or 64000),
                stream=os.getenv("LLM_STREAM", "true").lower() == "true",
                api_format=_api_format(profile.get("api_format")),
                timeout_seconds=float(profile.get("timeout_seconds") or 120),
                max_retries=int(os.getenv("LLM_MAX_RETRIES", "3")),
                extra={"thinking_modes": dict(profile.get("thinking_modes") or {})},
            )
        return cls(
            provider=_provider_name(os.getenv("LLM_PROVIDER", "openai")),
            api_key=os.getenv("LLM_API_KEY", ""),
            base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
            model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.7")),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "24000")),
            context_tokens=int(os.getenv("OPENWRITE_CONTEXT_TOKENS", "64000")),
            stream=os.getenv("LLM_STREAM", "true").lower() == "true",
            api_format=_api_format(os.getenv("LLM_API_FORMAT", "chat")),
            timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "120")),
            max_retries=int(os.getenv("LLM_MAX_RETRIES", "3")),
        )

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        """Fold a full compatible endpoint back to the API root."""
        if not base_url:
            return base_url

        normalized = base_url.rstrip("/")
        parsed = urlsplit(normalized)
        path = parsed.path.rstrip("/")
        for suffix in ("/chat/completions", "/responses"):
            if path.endswith(suffix):
                path = path[: -len(suffix)] or "/"
                return urlunsplit(
                    (parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment)
                )
        return normalized


class StreamProgress:
    """Progress snapshot for a streaming response."""

    def __init__(
        self,
        elapsed_ms: int = 0,
        total_chars: int = 0,
        chinese_chars: int = 0,
        status: str = "streaming",
    ) -> None:
        self.elapsed_ms = elapsed_ms
        self.total_chars = total_chars
        self.chinese_chars = chinese_chars
        self.status = status

    def __repr__(self) -> str:
        return (
            f"StreamProgress(elapsed={self.elapsed_ms}ms, "
            f"chars={self.total_chars}, chinese={self.chinese_chars})"
        )


OnStreamProgress = Callable[[StreamProgress], None] | None


class LLMClient:
    """OpenWrite's LiteLLM adapter with request-time context planning."""

    def __init__(self, config: LLMConfig, client: Any | None = None):
        self.config = config
        if client is None:
            try:
                import litellm
            except ImportError as exc:
                raise ImportError("请安装 litellm: pip install litellm") from exc
            self._backend = litellm
        else:
            self._backend = client
        self._completion = (
            self._backend
            if callable(self._backend) and not hasattr(self._backend, "completion")
            else getattr(self._backend, "completion")
        )
        self.last_context_plan: dict[str, Any] = {}

    def chat(
        self,
        messages: list[Message],
        temperature: float | None = None,
        max_tokens: int | None = None,
        stream: bool = False,
        on_progress: OnStreamProgress = None,
        operation: str = "",
    ) -> LLMResponse:
        """Send one provider-neutral chat request."""
        temp = temperature if temperature is not None else self.config.temperature
        maxt = max_tokens if max_tokens is not None else self.config.max_tokens
        if self.config.api_format == "responses":
            return self._chat_responses(messages, temp, maxt, stream, on_progress, operation)
        return self._chat_completion(messages, temp, maxt, stream, on_progress, operation)

    def chat_with_tools(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> ToolCallResponse:
        """Send a normalized function-calling request through LiteLLM."""
        temp = temperature if temperature is not None else self.config.temperature
        maxt = max_tokens if max_tokens is not None else self.config.max_tokens
        try:
            return self._chat_completion_with_tools(messages, tools, temp, maxt)
        except Exception as exc:
            error_msg = str(exc).lower()
            if "invalid tool type" in error_msg or "tool_calls" in error_msg:
                logger.warning("Tool calling failed, falling back to regular chat: %s", exc)
                response = self.chat(messages, temperature=temp, max_tokens=maxt, stream=False)
                return ToolCallResponse(
                    content=response.content,
                    usage=response.usage,
                    model=response.model,
                    provider=response.provider,
                    finish_reason=response.finish_reason,
                )
            raise

    def _chat_completion(
        self,
        messages: list[Message],
        temperature: float,
        max_tokens: int,
        stream: bool,
        on_progress: OnStreamProgress,
        operation: str = "",
    ) -> LLMResponse:
        prepared = self._prepare_messages(messages, max_tokens=max_tokens)
        params = self._completion_params(
            prepared,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream,
            operation=operation,
        )
        response = self._call(self._completion, params)
        if stream:
            return self._stream_response(response, on_progress)

        choice = self._first_choice(response)
        message = _value(choice, "message", {})
        return LLMResponse(
            content=_content_text(_value(message, "content", "")),
            usage=_plain_usage(_value(response, "usage"), response=response),
            model=str(_value(response, "model", self.config.model) or self.config.model),
            provider=self.config.provider,
            finish_reason=str(_value(choice, "finish_reason", "") or ""),
            reasoning=str(_value(message, "reasoning_content", "") or ""),
        )

    def _chat_completion_with_tools(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
    ) -> ToolCallResponse:
        prepared = self._prepare_messages(
            messages,
            tools=tools,
            max_tokens=max_tokens,
        )
        params = self._completion_params(
            prepared,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
            tools=tools,
        )
        response = self._call(self._completion, params)
        choice = self._first_choice(response)
        message = _value(choice, "message", {})
        content = _content_text(_value(message, "content", ""))
        tool_calls = self._normalize_tool_calls(_value(message, "tool_calls", []) or [])

        from .response import classify_response, validate_tool_arguments

        validate_tool_arguments(tool_calls)
        finish_reason = str(_value(choice, "finish_reason", "") or "")
        classify_response(content, finish_reason=finish_reason, require_content=not tool_calls)
        return ToolCallResponse(
            content=content,
            tool_calls=tool_calls,
            usage=_plain_usage(_value(response, "usage"), response=response),
            model=str(_value(response, "model", self.config.model) or self.config.model),
            provider=self.config.provider,
            finish_reason=finish_reason,
        )

    def _chat_responses(
        self,
        messages: list[Message],
        temperature: float,
        max_tokens: int,
        stream: bool,
        on_progress: OnStreamProgress,
        operation: str = "",
    ) -> LLMResponse:
        responses = getattr(self._backend, "responses", None)
        if not callable(responses):
            return self._chat_completion(
                messages, temperature, max_tokens, stream, on_progress, operation
            )

        prepared = self._prepare_messages(messages, max_tokens=max_tokens)
        params = self._base_params()
        params.update(
            {
                "input": prepared,
                "temperature": temperature,
                "max_output_tokens": max_tokens,
                "stream": stream,
            }
        )
        params.update(self._request_extra(operation))
        response = self._call(responses, params)
        if stream:
            return self._stream_response(response, on_progress)

        output_text = _content_text(_value(response, "output_text", ""))
        if not output_text:
            output_text = self._responses_output_text(_value(response, "output", []) or [])
        return LLMResponse(
            content=output_text,
            usage=_plain_usage(_value(response, "usage"), response=response),
            model=str(_value(response, "model", self.config.model) or self.config.model),
            provider=self.config.provider,
            finish_reason=str(_value(response, "status", "") or ""),
        )

    def _base_params(self) -> dict[str, Any]:
        provider = "openai" if self.config.provider == "custom" else self.config.provider
        return {
            "model": self.config.model,
            "custom_llm_provider": provider,
            "api_key": self.config.api_key,
            "base_url": self.config.base_url or None,
            "timeout": self.config.timeout_seconds,
            "max_retries": self.config.max_retries,
            "drop_params": True,
        }

    def _completion_params(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float,
        max_tokens: int,
        stream: bool,
        tools: list[dict[str, Any]] | None = None,
        operation: str = "",
    ) -> dict[str, Any]:
        params = self._base_params()
        params.update(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": stream,
            }
        )
        if tools:
            params["tools"] = tools
        params.update(self._request_extra(operation))
        return params

    def _request_extra(self, operation: str) -> dict[str, Any]:
        """Return provider extras scoped to one operation without leaking config metadata."""
        if not isinstance(self.config.extra, dict):
            return {}
        extra = copy.deepcopy(self.config.extra)
        modes = extra.pop("thinking_modes", {})
        extra_body = dict(extra.pop("extra_body", {}) or {})
        mode = str(modes.get(operation) or "omit").lower() if isinstance(modes, dict) else "omit"
        if "thinking" not in extra_body and mode in {"enabled", "disabled"}:
            extra_body["thinking"] = {"type": mode}
        if extra_body:
            extra["extra_body"] = extra_body
        return extra

    def _call(self, operation: Callable[..., Any], params: dict[str, Any]) -> Any:
        try:
            return operation(**params)
        except Exception as exc:
            raise self._wrap_error(exc) from exc

    def _prepare_messages(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int,
    ) -> list[dict[str, Any]]:
        prepared = [self._message_dict(message) for message in messages]
        used_tokens = self._count_tokens(prepared, tools=tools)
        policy = ContextBudgetPolicy(self.config.context_tokens, max_tokens)
        plan = policy.plan(used_tokens)
        report = plan.as_dict()
        report["original_message_count"] = len(prepared)
        original_messages = copy.deepcopy(prepared)

        if plan.requires_compression:
            message_tokens = self._count_tokens(prepared)
            tool_tokens = max(0, used_tokens - message_tokens)
            message_target = max(256, plan.target_tokens - tool_tokens)
            prepared = self._trim_messages(prepared, message_target)

        final_tokens = self._count_tokens(prepared, tools=tools)
        if final_tokens > plan.input_budget_tokens:
            message_tokens = self._count_tokens(prepared)
            tool_tokens = max(0, final_tokens - message_tokens)
            hard_target = max(256, plan.input_budget_tokens - tool_tokens)
            prepared = self._fallback_trim_messages(prepared, hard_target)
            final_tokens = self._count_tokens(prepared, tools=tools)

        report["final_message_count"] = len(prepared)
        report["final_used_tokens"] = final_tokens
        report["trimmed"] = prepared != original_messages
        report["within_budget"] = final_tokens <= plan.input_budget_tokens
        self.last_context_plan = report
        if not report["within_budget"]:
            from .errors import ContextLengthError

            raise ContextLengthError(
                "系统提示词与工具定义已超过模型输入预算，请提高上下文窗口或减少工具"
            )
        return prepared

    def _count_tokens(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
    ) -> int:
        counter = getattr(self._backend, "token_counter", None)
        if callable(counter):
            try:
                return int(
                    counter(
                        model=self._tokenizer_model(),
                        messages=messages,
                        tools=tools,
                    )
                )
            except Exception as exc:
                logger.debug("LiteLLM token counter fallback: %s", exc)
        payload = json.dumps(
            {"messages": messages, "tools": tools or []},
            ensure_ascii=False,
            default=str,
        )
        return self._estimate_text_tokens(payload)

    def _trim_messages(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int,
    ) -> list[dict[str, Any]]:
        proportional = self._proportional_trim_messages(messages, max_tokens)
        if self._count_tokens(proportional) <= max_tokens:
            return proportional

        trimmer = getattr(self._backend, "trim_messages", None)
        if callable(trimmer):
            try:
                trimmed = trimmer(
                    messages=proportional,
                    model=self._tokenizer_model(),
                    max_tokens=max_tokens,
                )
                if isinstance(trimmed, list) and trimmed:
                    return trimmed
            except Exception as exc:
                logger.warning("LiteLLM message trimming fallback: %s", exc)
        return self._fallback_trim_messages(proportional, max_tokens)

    def _proportional_trim_messages(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int,
    ) -> list[dict[str, Any]]:
        """Keep message structure while distributing content by priority."""
        prepared = copy.deepcopy(messages)
        if self._count_tokens(prepared) <= max_tokens:
            return prepared

        content_tokens = [self._message_content_tokens(item) for item in prepared]
        overhead = max(0, self._count_tokens(prepared) - sum(content_tokens))
        content_budget = max(0, max_tokens - overhead)
        priorities = [
            self._message_priority(item, index, len(prepared))
            for index, item in enumerate(prepared)
        ]
        allocations = self._weighted_allocations(
            content_tokens,
            priorities,
            content_budget,
        )
        for item, original_tokens, allocated_tokens in zip(
            prepared,
            content_tokens,
            allocations,
            strict=True,
        ):
            if allocated_tokens >= original_tokens:
                continue
            item["content"] = self._fit_content_to_tokens(
                _content_text(item.get("content", "")),
                allocated_tokens,
                role=str(item.get("role", "")),
            )
        return prepared

    def _message_content_tokens(self, message: dict[str, Any]) -> int:
        content = _content_text(message.get("content", ""))
        if not content:
            return 0
        with_content = self._count_tokens([{"role": "user", "content": content}])
        empty = self._count_tokens([{"role": "user", "content": ""}])
        return max(1, with_content - empty)

    @staticmethod
    def _message_priority(
        message: dict[str, Any],
        index: int,
        total: int,
    ) -> float:
        role = str(message.get("role", ""))
        if role == "system":
            return 6.0
        if index == total - 1:
            return 8.0
        if role == "tool" or message.get("tool_calls"):
            return 5.0
        recency = index / max(1, total - 1)
        return 1.0 + 2.0 * recency

    @staticmethod
    def _weighted_allocations(
        token_counts: list[int],
        priorities: list[float],
        budget: int,
    ) -> list[int]:
        allocations = [0.0] * len(token_counts)
        remaining = {index for index, count in enumerate(token_counts) if count > 0}
        remaining_budget = float(max(0, budget))

        while remaining and remaining_budget > 0:
            denominator = sum(
                token_counts[index] * priorities[index] for index in remaining
            )
            if denominator <= 0:
                break
            shares = {
                index: remaining_budget
                * token_counts[index]
                * priorities[index]
                / denominator
                for index in remaining
            }
            saturated = {
                index for index, share in shares.items() if share >= token_counts[index]
            }
            if not saturated:
                for index, share in shares.items():
                    allocations[index] = share
                break
            for index in saturated:
                allocations[index] = float(token_counts[index])
                remaining_budget -= token_counts[index]
                remaining.remove(index)

        return [
            min(count, max(0, int(allocation)))
            for count, allocation in zip(token_counts, allocations, strict=True)
        ]

    def _fit_content_to_tokens(self, text: str, max_tokens: int, *, role: str) -> str:
        content = str(text or "")
        if not content or max_tokens <= 0:
            return ""
        current_tokens = self._message_content_tokens({"content": content})
        if current_tokens <= max_tokens:
            return content

        max_chars = max(1, int(len(content) * max_tokens / current_tokens))
        fitted = content
        for _ in range(8):
            if role == "tool":
                fitted = content[-max_chars:]
            else:
                head = max(1, int(max_chars * 0.6))
                tail = max(0, max_chars - head)
                marker = "\n...[context compressed proportionally]...\n"
                fitted = content[:head] + marker + (content[-tail:] if tail else "")
            actual_tokens = self._message_content_tokens({"content": fitted})
            if actual_tokens <= max_tokens:
                return fitted
            max_chars = max(1, int(max_chars * max_tokens / actual_tokens * 0.95))
        return fitted

    def _fallback_trim_messages(
        self,
        messages: list[dict[str, Any]],
        max_tokens: int,
    ) -> list[dict[str, Any]]:
        kept = [dict(message) for message in messages]
        while len(kept) > 2 and self._count_tokens(kept) > max_tokens:
            removable = next(
                (index for index, item in enumerate(kept[:-1]) if item.get("role") != "system"),
                None,
            )
            if removable is None:
                break
            kept.pop(removable)

        if self._count_tokens(kept) <= max_tokens:
            return kept

        for message in kept:
            content = _content_text(message.get("content", ""))
            if not content:
                continue
            share = max(64, int(max_tokens * 2 / max(1, len(kept))))
            if len(content) > share:
                message["content"] = (
                    content[: share // 2]
                    + "\n...[context trimmed]...\n"
                    + content[-share // 2 :]
                )
        return kept

    def _tokenizer_model(self) -> str:
        if "/" in self.config.model:
            return self.config.model
        provider = "openai" if self.config.provider == "custom" else self.config.provider
        return f"{provider}/{self.config.model}"

    @staticmethod
    def _estimate_text_tokens(text: str) -> int:
        total = 0.0
        for char in text:
            code = ord(char)
            if (
                0x3400 <= code <= 0x9FFF
                or 0x3040 <= code <= 0x30FF
                or 0xAC00 <= code <= 0xD7AF
            ):
                total += 1.5
            elif char.isascii():
                total += 0.25
            else:
                total += 0.75
        return max(1, int(total + 0.999))

    @staticmethod
    def _message_dict(message: Message) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": message.role, "content": message.content}
        if message.role == "tool":
            payload["tool_call_id"] = message.tool_call_id
        raw_calls = getattr(message, "tool_calls", None)
        if message.role == "assistant" and raw_calls:
            payload["tool_calls"] = [
                {
                    "id": call.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": call.get("name", ""),
                        "arguments": call.get("arguments", "{}"),
                    },
                }
                for call in raw_calls
            ]
        return payload

    @staticmethod
    def _normalize_tool_calls(raw_calls: list[Any]) -> list[dict[str, Any]]:
        calls: list[dict[str, Any]] = []
        for raw in raw_calls:
            function = _value(raw, "function", {})
            arguments = _value(function, "arguments", "{}")
            if isinstance(arguments, dict):
                arguments = json.dumps(arguments, ensure_ascii=False)
            calls.append(
                {
                    "id": str(_value(raw, "id", "") or ""),
                    "name": str(_value(function, "name", "") or ""),
                    "arguments": str(arguments or "{}"),
                }
            )
        return calls

    @staticmethod
    def _first_choice(response: Any) -> Any:
        choices = _value(response, "choices", []) or []
        if not choices:
            raise ValueError("LiteLLM response contains no choices")
        return choices[0]

    @staticmethod
    def _responses_output_text(output: list[Any]) -> str:
        parts: list[str] = []
        for item in output:
            for block in _value(item, "content", []) or []:
                text = _value(block, "text", "")
                if text:
                    parts.append(str(text))
        return "".join(parts)

    def _stream_response(self, stream: Any, on_progress: OnStreamProgress) -> LLMResponse:
        chunks: list[str] = []
        reasoning: list[str] = []
        usage: dict[str, Any] = {}
        finish_reason = ""
        response_model = self.config.model
        chinese_chars = 0
        start_time = time.time()

        try:
            for event in stream:
                delta = ""
                choices = _value(event, "choices", []) or []
                if choices:
                    choice = choices[0]
                    choice_delta = _value(choice, "delta", {})
                    delta = _content_text(_value(choice_delta, "content", ""))
                    reasoning_delta = _value(choice_delta, "reasoning_content", "")
                    if reasoning_delta:
                        reasoning.append(str(reasoning_delta))
                    finish_reason = str(
                        _value(choice, "finish_reason", finish_reason) or finish_reason
                    )
                elif str(_value(event, "type", "")).endswith("output_text.delta"):
                    delta = str(_value(event, "delta", "") or "")

                if delta:
                    chunks.append(delta)
                    chinese_chars += sum(1 for char in delta if "\u4e00" <= char <= "\u9fff")
                    if on_progress:
                        on_progress(
                            StreamProgress(
                                elapsed_ms=int((time.time() - start_time) * 1000),
                                total_chars=sum(len(chunk) for chunk in chunks),
                                chinese_chars=chinese_chars,
                            )
                        )
                event_usage = _plain_usage(_value(event, "usage"), response=event)
                if any(key != "cost_reported" for key in event_usage):
                    usage = event_usage
                response_model = str(
                    _value(event, "model", response_model) or response_model
                )
        except Exception as exc:
            partial = "".join(chunks)
            if len(partial) > 100:
                logger.warning("Stream interrupted: %s; returning partial content", exc)
                return LLMResponse(
                    content=partial,
                    usage=usage,
                    model=response_model,
                    provider=self.config.provider,
                    finish_reason="incomplete",
                    reasoning="".join(reasoning),
                )
            raise self._wrap_error(exc) from exc

        return LLMResponse(
            content="".join(chunks),
            usage=usage,
            model=response_model,
            provider=self.config.provider,
            finish_reason=finish_reason,
            reasoning="".join(reasoning),
        )

    def _wrap_error(self, error: Exception) -> Exception:
        """Map LiteLLM/provider failures to OpenWrite's stable error surface."""
        from .errors import (
            APIError,
            AuthenticationError,
            ContextLengthError,
            InvalidRequestError,
            LLMTimeoutError,
            NetworkError,
            RateLimitError,
        )
        from .response import redact_sensitive_text

        error_msg = redact_sensitive_text(error)
        lowered = error_msg.lower()
        if "context" in lowered and any(
            token in lowered for token in ("length", "window", "maximum", "too long")
        ):
            return _ensure_exception(
                ContextLengthError("模型上下文超限，请缩小输入或输出预算", error_msg)
            )
        if "timeout" in lowered or "timed out" in lowered:
            return _ensure_exception(
                LLMTimeoutError("模型服务请求超时，请稍后重试", error_msg)
            )
        if "400" in error_msg:
            return _ensure_exception(
                InvalidRequestError(
                    "API 返回 400（请求参数错误），请检查模型名称、接口格式与模型能力",
                    error_msg,
                )
            )
        if "401" in error_msg or "api_key" in lowered:
            return _ensure_exception(
                AuthenticationError("API 返回 401（未授权），请检查 API Key", error_msg)
            )
        if "403" in error_msg or "forbidden" in lowered:
            return _ensure_exception(
                AuthenticationError("API 返回 403（请求被拒绝）", error_msg)
            )
        if "429" in error_msg or "rate_limit" in lowered:
            return _ensure_exception(
                RateLimitError("API 返回 429（请求过多），请稍后重试", error_msg)
            )
        if any(
            token in lowered
            for token in ("connection", "econnrefused", "enotfound", "fetch failed")
        ):
            return _ensure_exception(
                NetworkError(
                    f"无法连接到 API 服务（Base URL: {self.config.base_url}）",
                    error_msg,
                )
            )
        return _ensure_exception(APIError("LLM API 错误", error_msg))
