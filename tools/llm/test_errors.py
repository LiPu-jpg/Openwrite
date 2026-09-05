"""Shared connection-test error taxonomy for chat and embedding probes.

Both Studio connection-test endpoints classify provider failures through
:class:`ConnectionTestFailure` so chat and embedding probes emit the same
``MODEL_TEST_<KIND>`` codes, HTTP statuses, and recoverability flags.

Classification precedence:

1. Structured signals — provider HTTP status carried on the exception (or its
   ``__cause__``), ``tools.llm.errors`` exception types, builtin
   timeout/connection error types, ``ProviderResponseError`` codes, and
   profile-store error codes.
2. Message substring matching (last resort, case-insensitive).
3. Unrecognized failures degrade to ``provider_rejected`` when the exception
   type implies a provider exchange happened (wrapped LLM or embedding
   runtime errors), otherwise ``internal_error``.

Stable HTTP mapping:

- 400 ``unsupported_parameter`` (the request itself must change)
- 412 ``credential_missing`` / ``invalid_configuration`` (local precondition)
- 401 ``authentication_failed``, 403 ``permission_denied``, 404 ``model_not_found``
- 502 ``rate_limited`` / ``timeout`` / ``network_error`` / ``provider_rejected``
  / ``empty_response`` / ``invalid_response`` (upstream failures)
- 409 ``cancelled`` (client-side cancellation raced the probe)
- 500 ``internal_error``

User-facing messages are static sanitized strings; raw provider exception
text must only reach logs via ``tools.llm.response.redact_sensitive_text``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from http import HTTPStatus

from tools.embedding_runtime import EmbeddingRuntimeError
from tools.llm.errors import (
    APIError,
    AuthenticationError,
    ContextLengthError,
    InvalidRequestError,
    LLMTimeoutError,
    LLMWrappedError,
    NetworkError,
    RateLimitError,
)
from tools.llm.response import ProviderResponseError

TEST_ERROR_KINDS: tuple[str, ...] = (
    "invalid_configuration",
    "credential_missing",
    "authentication_failed",
    "permission_denied",
    "model_not_found",
    "rate_limited",
    "timeout",
    "network_error",
    "provider_rejected",
    "unsupported_parameter",
    "empty_response",
    "invalid_response",
    "cancelled",
    "internal_error",
)

RECOVERABLE_KINDS = frozenset(
    {
        "rate_limited",
        "timeout",
        "network_error",
        "provider_rejected",
        "empty_response",
        "invalid_response",
    }
)

_STATUS_BY_KIND: dict[str, HTTPStatus] = {
    "invalid_configuration": HTTPStatus.PRECONDITION_FAILED,
    "credential_missing": HTTPStatus.PRECONDITION_FAILED,
    "authentication_failed": HTTPStatus.UNAUTHORIZED,
    "permission_denied": HTTPStatus.FORBIDDEN,
    "model_not_found": HTTPStatus.NOT_FOUND,
    "rate_limited": HTTPStatus.BAD_GATEWAY,
    "timeout": HTTPStatus.BAD_GATEWAY,
    "network_error": HTTPStatus.BAD_GATEWAY,
    "provider_rejected": HTTPStatus.BAD_GATEWAY,
    "unsupported_parameter": HTTPStatus.BAD_REQUEST,
    "empty_response": HTTPStatus.BAD_GATEWAY,
    "invalid_response": HTTPStatus.BAD_GATEWAY,
    "cancelled": HTTPStatus.CONFLICT,
    "internal_error": HTTPStatus.INTERNAL_SERVER_ERROR,
}

_MESSAGES: dict[str, str] = {
    "invalid_configuration": "连接测试失败：配置无效，请检查模型与 Embedding 配置。",
    "credential_missing": "连接测试失败：缺少 API Key，请先保存凭证。",
    "authentication_failed": "连接测试失败：认证失败，请检查 API Key。",
    "permission_denied": "连接测试失败：没有访问权限，请检查账户权限与模型授权。",
    "model_not_found": "连接测试失败：模型或 API 地址不存在，请检查模型名称和 Base URL。",
    "rate_limited": "连接测试失败：服务商限流或额度不足，请稍后重试并检查账户额度。",
    "timeout": "连接测试失败：请求超时，请检查网络和 Base URL。",
    "network_error": "连接测试失败：无法连接到服务商，请检查网络和 Base URL。",
    "provider_rejected": "连接测试失败：服务商拒绝了请求，请检查模型配置与账户状态。",
    "unsupported_parameter": "连接测试失败：服务商不支持当前参数，请调整模型参数后重试。",
    "empty_response": "连接测试失败：模型返回空内容，请调大最大输出后重试。",
    "invalid_response": "连接测试失败：服务商返回了无法解析的响应。",
    "cancelled": "连接测试已取消。",
    "internal_error": "连接测试失败：内部错误，请检查模型配置。",
}

_HTTP_STATUS_TO_KIND: dict[int, str] = {
    400: "unsupported_parameter",
    401: "authentication_failed",
    403: "permission_denied",
    404: "model_not_found",
    408: "timeout",
    429: "rate_limited",
}

_MESSAGE_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("401", "unauthorized", "authentication", "api key"), "authentication_failed"),
    (("403", "forbidden", "permission"), "permission_denied"),
    (("404", "not found", "model_not_found"), "model_not_found"),
    (("429", "rate limit", "too many requests"), "rate_limited"),
    (("timeout", "timed out"), "timeout"),
    (("connection", "dns", "name resolution"), "network_error"),
    (("empty model reply", "模型返回空内容"), "empty_response"),
    (("unsupported parameter", "unsupported_parameter"), "unsupported_parameter"),
    (("形状无效", "实际维度"), "invalid_response"),
)


@dataclass(frozen=True)
class ConnectionTestFailure:
    kind: str
    code: str
    http_status: HTTPStatus
    recoverable: bool
    message: str


def _provider_http_status(exc: BaseException) -> int | None:
    for candidate in (exc, exc.__cause__):
        if candidate is None:
            continue
        for attribute in ("status_code", "http_status"):
            status = getattr(candidate, attribute, None)
            if isinstance(status, int) and not isinstance(status, bool):
                return status
    return None


def _message_kind(text: str) -> str | None:
    lowered = text.lower()
    for hints, kind in _MESSAGE_HINTS:
        if any(hint in lowered for hint in hints):
            return kind
    return None


def classify_connection_error(exc: BaseException) -> str:
    """Map a probe failure to one of ``TEST_ERROR_KINDS`` (structured first)."""
    status = _provider_http_status(exc)
    if status is not None:
        kind = _HTTP_STATUS_TO_KIND.get(status)
        if kind is not None:
            return kind
        if 500 <= status < 600:
            return "provider_rejected"
    if isinstance(exc, AuthenticationError):
        return "authentication_failed"
    if isinstance(exc, RateLimitError):
        return "rate_limited"
    if isinstance(exc, LLMTimeoutError):
        return "timeout"
    if isinstance(exc, NetworkError):
        return "network_error"
    if isinstance(exc, ContextLengthError):
        return "invalid_configuration"
    if isinstance(exc, (InvalidRequestError, APIError)):
        return "provider_rejected"
    if isinstance(exc, asyncio.CancelledError):
        return "cancelled"
    if isinstance(exc, TimeoutError):
        return "timeout"
    if isinstance(exc, ConnectionError):
        return "network_error"
    if isinstance(exc, ProviderResponseError):
        return (
            "empty_response"
            if str(exc.code or "") == "MODEL_EMPTY_RESPONSE"
            else "invalid_response"
        )
    code = str(getattr(exc, "code", "") or "")
    if code == "MODEL_PROFILE_NOT_FOUND":
        return "model_not_found"
    if code == "MODEL_CREDENTIAL_MISSING":
        return "credential_missing"
    if code == "INVALID_MODEL_PROFILE":
        return "invalid_configuration"
    kind = _message_kind(str(exc))
    if kind is not None:
        return kind
    if isinstance(exc, (LLMWrappedError, EmbeddingRuntimeError)):
        return "provider_rejected"
    return "internal_error"


def connection_test_failure(exc: BaseException) -> ConnectionTestFailure:
    """Classify ``exc`` into the wire contract for a failed connection test."""
    kind = classify_connection_error(exc)
    if kind not in TEST_ERROR_KINDS:  # pragma: no cover - defensive
        kind = "internal_error"
    return ConnectionTestFailure(
        kind=kind,
        code=f"MODEL_TEST_{kind.upper()}",
        http_status=_STATUS_BY_KIND[kind],
        recoverable=kind in RECOVERABLE_KINDS,
        message=_MESSAGES[kind],
    )
