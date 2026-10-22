"""LLM 客户端模块

核心 LLM 封装能力：
- 统一接口支持 OpenAI / Anthropic / 自定义
- 流式输出监控
- 流失败自动降级为同步
- 人性化错误处理
"""

from .client import LLMClient, LLMConfig, LLMResponse, Message, ToolCallResponse
from .context import ContextBudgetPlan, ContextBudgetPolicy
from .errors import (
    APIError,
    AuthenticationError,
    InvalidRequestError,
    LLMTimeoutError,
    LLMWrappedError,
    NetworkError,
    RateLimitError,
)

import os


def long_generation_stream() -> bool:
    """Use the same switch for long prose and structured generation."""
    return os.getenv("OW_AGENT_STREAM", "1") == "1"


__all__ = [
    "long_generation_stream",
    "LLMClient",
    "LLMConfig",
    "LLMResponse",
    "ToolCallResponse",
    "Message",
    "ContextBudgetPlan",
    "ContextBudgetPolicy",
    "LLMWrappedError",
    "APIError",
    "AuthenticationError",
    "RateLimitError",
    "InvalidRequestError",
    "NetworkError",
    "LLMTimeoutError",
]
