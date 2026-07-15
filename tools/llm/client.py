"""LLM 客户端

支持:
- OpenAI (chat completions / responses API)
- Anthropic (messages API)
- 自定义 baseUrl (用于代理/兼容接口)
- 流式输出监控
- 流失败自动降级
"""

from __future__ import annotations

import os
import json
import time
import logging
from typing import Any, Optional, Callable, Literal
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

logger = logging.getLogger(__name__)


def _plain_usage(usage: Any) -> dict[str, Any]:
    """Convert SDK usage models into YAML/JSON-safe plain data."""

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
        return {}
    if isinstance(usage, dict):
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
                return {}
    converted = convert(raw)
    return converted if isinstance(converted, dict) else {}


@dataclass
class LLMResponse:
    """LLM 响应"""

    content: str
    usage: dict = field(default_factory=dict)
    model: str = ""
    provider: str = "openai"

    @property
    def prompt_tokens(self) -> int:
        return self.usage.get("prompt_tokens", 0)

    @property
    def completion_tokens(self) -> int:
        return self.usage.get("completion_tokens", 0)

    @property
    def total_tokens(self) -> int:
        return self.usage.get("total_tokens", 0)


@dataclass
class ToolCallResponse:
    """工具调用响应（Function Calling）"""

    content: str
    tool_calls: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    model: str = ""
    provider: str = "openai"

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


@dataclass
class Message:
    """对话消息"""

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    tool_call_id: str = ""


@dataclass
class LLMConfig:
    """LLM 配置"""

    provider: Literal["openai", "anthropic", "custom"] = "openai"
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    temperature: float = 0.7
    max_tokens: int = 24000
    stream: bool = True
    api_format: Literal["chat", "responses"] = "chat"
    timeout_seconds: float = 120.0
    max_retries: int = 3
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        self.base_url = self._normalize_base_url(self.base_url)

    @classmethod
    def from_env(cls) -> "LLMConfig":
        """从环境变量创建配置"""
        return cls(
            provider=os.getenv("LLM_PROVIDER", "openai"),
            api_key=os.getenv("LLM_API_KEY", ""),
            base_url=os.getenv("LLM_BASE_URL", "https://api.openai.com/v1"),
            model=os.getenv("LLM_MODEL", "gpt-4o-mini"),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.7")),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "24000")),
            stream=os.getenv("LLM_STREAM", "true").lower() == "true",
            api_format=os.getenv("LLM_API_FORMAT", "chat"),
            timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "120")),
            max_retries=int(os.getenv("LLM_MAX_RETRIES", "3")),
        )

    @staticmethod
    def _normalize_base_url(base_url: str) -> str:
        """把完整兼容端点折回到 SDK 需要的 API 根路径。"""
        if not base_url:
            return base_url

        normalized = base_url.rstrip("/")
        parsed = urlsplit(normalized)
        path = parsed.path.rstrip("/")
        endpoint_suffixes = ("/chat/completions", "/responses")

        for suffix in endpoint_suffixes:
            if path.endswith(suffix):
                path = path[: -len(suffix)] or "/"
                return urlunsplit(
                    (parsed.scheme, parsed.netloc, path, parsed.query, parsed.fragment)
                )

        return normalized


class StreamProgress:
    """流式输出进度"""

    def __init__(
        self,
        elapsed_ms: int = 0,
        total_chars: int = 0,
        chinese_chars: int = 0,
        status: str = "streaming",
    ):
        self.elapsed_ms = elapsed_ms
        self.total_chars = total_chars
        self.chinese_chars = chinese_chars
        self.status = status

    def __repr__(self):
        return (
            f"StreamProgress(elapsed={self.elapsed_ms}ms, "
            f"chars={self.total_chars}, chinese={self.chinese_chars})"
        )


OnStreamProgress = Optional[Callable[[StreamProgress], None]]


class LLMClient:
    """统一 LLM 客户端

    用法:
        config = LLMConfig.from_env()
        client = LLMClient(config)

        # 简单对话
        response = client.chat([
            Message("system", "你是一个助手"),
            Message("user", "你好")
        ])

        # 流式对话
        for chunk in client.stream_chat([...]):
            print(chunk, end="")
    """

    def __init__(self, config: LLMConfig, client: Any | None = None):
        self.config = config
        self._client = client if client is not None else self._init_client()

    def _init_client(self):
        """初始化底层客户端"""
        if self.config.provider == "anthropic":
            try:
                import anthropic

                return anthropic.Anthropic(
                    api_key=self.config.api_key,
                    base_url=self.config.base_url.rstrip("/") + "/v1",
                )
            except ImportError:
                raise ImportError("请安装 anthropic: pip install anthropic")

        # OpenAI 或自定义 (都使用 OpenAI SDK)
        try:
            import openai
        except ImportError:
            raise ImportError("请安装 openai: pip install openai")

        return openai.OpenAI(
            api_key=self.config.api_key,
            base_url=self.config.base_url,
            timeout=self.config.timeout_seconds,
            max_retries=self.config.max_retries,
        )

    def chat(
        self,
        messages: list[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        on_progress: OnStreamProgress = None,
    ) -> LLMResponse:
        """对话

        Args:
            messages: 对话消息列表
            temperature: 温度参数
            max_tokens: 最大 token 数
            stream: 是否流式输出
            on_progress: 进度回调

        Returns:
            LLMResponse 响应对象
        """
        temp = temperature if temperature is not None else self.config.temperature
        maxt = max_tokens if max_tokens is not None else self.config.max_tokens

        if self.config.provider == "anthropic":
            return self._chat_anthropic(messages, temp, maxt, stream, on_progress)
        if self.config.api_format == "responses":
            return self._chat_openai_responses(messages, temp, maxt, stream, on_progress)
        return self._chat_openai(messages, temp, maxt, stream, on_progress)

    def chat_with_tools(
        self,
        messages: list[Message],
        tools: list[dict],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> "ToolCallResponse":
        """带工具调用的对话（Function Calling）

        Args:
            messages: 对话消息列表
            tools: 工具定义列表
            temperature: 温度参数
            max_tokens: 最大 token 数

        Returns:
            ToolCallResponse 响应对象（包含 content 和 tool_calls）
        """
        temp = temperature if temperature is not None else self.config.temperature
        maxt = max_tokens if max_tokens is not None else self.config.max_tokens

        if self.config.provider == "anthropic":
            return self._chat_anthropic_with_tools(messages, tools, temp, maxt)

        try:
            return self._chat_openai_with_tools(messages, tools, temp, maxt)
        except Exception as e:
            # 如果工具调用失败，回退到普通聊天
            # 这对于某些不支持 tool calling 的 API 很有用
            error_msg = str(e)
            if "invalid tool type" in error_msg.lower() or "tool_calls" in error_msg.lower():
                logger.warning(f"Tool calling failed, falling back to regular chat: {e}")
                response = self.chat(messages, temperature=temp, max_tokens=maxt, stream=False)
                return ToolCallResponse(
                    content=response.content,
                    tool_calls=[],
                    usage=response.usage,
                    model=response.model,
                    provider=response.provider,
                )
            raise

    def _chat_openai_with_tools(
        self,
        messages: list[Message],
        tools: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> "ToolCallResponse":
        """OpenAI Chat API with Function Calling"""
        import openai

        openai_messages = []
        for m in messages:
            if m.role == "system":
                openai_messages.append({"role": "system", "content": m.content})
            elif m.role == "tool":
                openai_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": m.tool_call_id,
                        "content": m.content,
                    }
                )
            elif m.role == "assistant" and hasattr(m, "tool_calls"):
                raw_calls = getattr(m, "tool_calls", []) or []
                tool_calls = [
                    {
                        "id": tc.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": tc.get("name", ""),
                            "arguments": tc.get("arguments", "{}"),
                        },
                    }
                    for tc in raw_calls
                ]
                openai_messages.append(
                    {
                        "role": "assistant",
                        "content": m.content or "",
                        "tool_calls": tool_calls,
                    }
                )
            else:
                openai_messages.append({"role": m.role, "content": m.content})

        create_params = {
            "model": self.config.model,
            "messages": openai_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "tools": tools,
            **self.config.extra,
        }

        try:
            response = self._client.chat.completions.create(**create_params)
            message = response.choices[0].message

            # 解析 tool_calls
            tool_calls = []
            if hasattr(message, "tool_calls") and message.tool_calls:
                for tc in message.tool_calls:
                    func = tc.function
                    tool_calls.append(
                        {
                            "id": tc.id,
                            "name": func.name,
                            "arguments": func.arguments,
                        }
                    )

            return ToolCallResponse(
                content=message.content or "",
                tool_calls=tool_calls,
                usage=_plain_usage(getattr(response, "usage", None)),
                model=response.model,
                provider="openai",
            )
        except openai.APIError as e:
            raise self._wrap_error(e)

    def _chat_anthropic_with_tools(
        self,
        messages: list[Message],
        tools: list[dict],
        temperature: float,
        max_tokens: int,
    ) -> "ToolCallResponse":
        """Anthropic Messages API with Tools"""
        import anthropic

        anthropic_messages = []
        for m in messages:
            if m.role == "system":
                anthropic_messages.append(
                    {"role": "user", "content": f"<system>{m.content}</system>"}
                )
            elif m.role == "tool":
                anthropic_messages.append(
                    {
                        "role": "user",
                        "content": f"[tool result: {getattr(m, 'tool_call_id', '')}] {m.content}",
                    }
                )
            else:
                anthropic_messages.append({"role": m.role, "content": m.content})

        # Anthropic 的工具格式不同
        anthropic_tools = []
        for tool in tools:
            func = tool.get("function", {})
            anthropic_tools.append(
                {
                    "name": func.get("name"),
                    "description": func.get("description", ""),
                    "input_schema": func.get("parameters", {}),
                }
            )

        create_params = {
            "model": self.config.model,
            "messages": anthropic_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "tools": anthropic_tools,
        }

        try:
            response = self._client.messages.create(**create_params)
            content_blocks = response.content

            # 解析内容
            content = ""
            tool_calls = []
            for block in content_blocks:
                if hasattr(block, "text"):
                    content += block.text
                elif hasattr(block, "name"):  # tool_use
                    tool_calls.append(
                        {
                            "id": block.id,
                            "name": block.name,
                            "arguments": block.input if hasattr(block, "input") else "{}",
                        }
                    )

            return ToolCallResponse(
                content=content,
                tool_calls=tool_calls,
                usage={
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                    "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
                },
                model=response.model,
                provider="anthropic",
            )
        except anthropic.APIError as e:
            raise self._wrap_error(e)

    def _chat_openai(
        self,
        messages: list[Message],
        temperature: float,
        max_tokens: int,
        stream: bool,
        on_progress: OnStreamProgress,
    ) -> LLMResponse:
        """OpenAI Chat API"""
        import openai

        openai_messages = [{"role": m.role, "content": m.content} for m in messages]

        create_params = {
            "model": self.config.model,
            "messages": openai_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
            **self.config.extra,
        }

        try:
            if stream:
                return self._stream_response(
                    self._client.chat.completions.create(**create_params),
                    on_progress,
                )

            response = self._client.chat.completions.create(**create_params)
            return LLMResponse(
                content=response.choices[0].message.content or "",
                usage=_plain_usage(response.usage),
                model=response.model,
                provider="openai",
            )
        except openai.APIError as e:
            raise self._wrap_error(e)

    def _chat_openai_responses(
        self,
        messages: list[Message],
        temperature: float,
        max_tokens: int,
        stream: bool,
        on_progress: OnStreamProgress,
    ) -> LLMResponse:
        """OpenAI Responses API"""
        import openai

        input_text = "\n".join(f"{m.role}: {m.content}" for m in messages)

        create_params = {
            "model": self.config.model,
            "input": input_text,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
            **self.config.extra,
        }

        try:
            if stream:
                return self._stream_response(
                    self._client.responses.create(**create_params),
                    on_progress,
                )

            response = self._client.responses.create(**create_params)
            output_text = "\n".join(o.text for o in response.output if hasattr(o, "text"))
            return LLMResponse(
                content=output_text,
                usage=_plain_usage(getattr(response, "usage", None)),
                model=response.model,
                provider="openai",
            )
        except openai.APIError as e:
            raise self._wrap_error(e)

    def _chat_anthropic(
        self,
        messages: list[Message],
        temperature: float,
        max_tokens: int,
        stream: bool,
        on_progress: OnStreamProgress,
    ) -> LLMResponse:
        """Anthropic Messages API"""
        import anthropic

        # Anthropic 使用不同的消息格式
        anthropic_messages = []
        for m in messages:
            if m.role == "system":
                anthropic_messages.append(
                    {"role": "user", "content": f"<system>{m.content}</system>"}
                )
            else:
                anthropic_messages.append({"role": m.role, "content": m.content})

        create_params = {
            "model": self.config.model,
            "messages": anthropic_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }

        try:
            if stream:
                return self._stream_response_anthropic(
                    self._client.messages.create(**create_params),
                    on_progress,
                )

            response = self._client.messages.create(**create_params)
            content = ""
            if response.content and hasattr(response.content[0], "text"):
                content = response.content[0].text

            return LLMResponse(
                content=content,
                usage={
                    "prompt_tokens": response.usage.input_tokens,
                    "completion_tokens": response.usage.output_tokens,
                    "total_tokens": response.usage.input_tokens + response.usage.output_tokens,
                },
                model=response.model,
                provider="anthropic",
            )
        except anthropic.APIError as e:
            raise self._wrap_error(e)

    def _stream_response(self, stream, on_progress: OnStreamProgress) -> LLMResponse:
        """处理 OpenAI 流式响应"""
        chunks = []
        chinese_chars = 0
        start_time = time.time()

        def count_chinese(text: str) -> int:
            return sum(1 for c in text if "\u4e00" <= c <= "\u9fff")

        try:
            for chunk in stream:
                delta = chunk.choices[0].delta.content or ""
                chunks.append(delta)
                chinese_chars += count_chinese(delta)

                if on_progress:
                    on_progress(
                        StreamProgress(
                            elapsed_ms=int((time.time() - start_time) * 1000),
                            total_chars=sum(len(c) for c in chunks),
                            chinese_chars=chinese_chars,
                        )
                    )
        except Exception as e:
            # 流中断但有部分内容可用
            partial = "".join(chunks)
            if len(partial) > 100:  # 有意义的内容
                logger.warning(f"Stream interrupted: {e}, returning partial ({len(partial)} chars)")
                return LLMResponse(content=partial, provider="openai")
            raise

        return LLMResponse(
            content="".join(chunks),
            usage={},  # 流式响应不返回 usage
            provider="openai",
        )

    def _stream_response_anthropic(self, stream, on_progress: OnStreamProgress) -> LLMResponse:
        """处理 Anthropic 流式响应"""
        chunks = []
        chinese_chars = 0
        start_time = time.time()

        def count_chinese(text: str) -> int:
            return sum(1 for c in text if "\u4e00" <= c <= "\u9fff")

        try:
            for chunk in stream:
                if hasattr(chunk, "content_block") and hasattr(chunk.content_block, "text"):
                    delta = chunk.content_block.text
                    chunks.append(delta)
                    chinese_chars += count_chinese(delta)

                    if on_progress:
                        on_progress(
                            StreamProgress(
                                elapsed_ms=int((time.time() - start_time) * 1000),
                                total_chars=sum(len(c) for c in chunks),
                                chinese_chars=chinese_chars,
                            )
                        )
                elif hasattr(chunk, "message") and hasattr(chunk.message, "content"):
                    # 完整消息块
                    pass
        except Exception as e:
            partial = "".join(chunks)
            if len(partial) > 100:
                logger.warning(f"Anthropic stream interrupted: {e}")
                return LLMResponse(content=partial, provider="anthropic")
            raise

        return LLMResponse(
            content="".join(chunks),
            usage={},
            provider="anthropic",
        )

    def _wrap_error(self, error: Exception) -> Exception:
        """包装错误为更人性化的消息"""
        from .errors import (
            APIError,
            AuthenticationError,
            RateLimitError,
            InvalidRequestError,
            NetworkError,
        )

        error_msg = str(error)

        if "400" in error_msg:
            return InvalidRequestError(
                f"API 返回 400 (请求参数错误)。可能原因：\n"
                f"  1. 模型名称不正确（检查 LLM_MODEL）\n"
                f"  2. 提供方不支持某些参数（如 max_tokens、stream）\n"
                f"  3. 消息格式不兼容\n"
                f"建议：设置 LLM_STREAM=false 试试\n"
                f"原始错误: {error_msg}"
            )

        if "401" in error_msg or "api_key" in error_msg.lower():
            return AuthenticationError(
                f"API 返回 401 (未授权)。请检查 LLM_API_KEY 是否正确。\n原始错误: {error_msg}"
            )

        if "403" in error_msg or "forbidden" in error_msg.lower():
            return AuthenticationError(
                f"API 返回 403 (请求被拒绝)。可能原因：\n"
                f"  1. API Key 无效或过期\n"
                f"  2. API 提供方的内容审查拦截了请求\n"
                f"  3. 账户余额不足\n"
                f"原始错误: {error_msg}"
            )

        if "429" in error_msg or "rate_limit" in error_msg.lower():
            return RateLimitError(
                f"API 返回 429 (请求过多)。请稍后重试，或检查 API 配额。\n原始错误: {error_msg}"
            )

        if any(
            x in error_msg.lower()
            for x in ["connection", "econnrefused", "enotfound", "fetch failed"]
        ):
            return NetworkError(
                f"无法连接到 API 服务。可能原因：\n"
                f"  1. baseUrl 地址不正确（当前：{self.config.base_url}）\n"
                f"  2. 网络不通或被防火墙拦截\n"
                f"  3. API 服务暂时不可用\n"
                f"建议：检查 LLM_BASE_URL 是否包含完整路径（如 /v1）\n"
                f"原始错误: {error_msg}"
            )

        return APIError(f"LLM API 错误: {error_msg}")
