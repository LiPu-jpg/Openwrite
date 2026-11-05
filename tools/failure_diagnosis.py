"""Name a failure so the next attempt - or the agent in front of it - can act.

Three kinds of failure need three different responses, and today they all
arrive as one flat string:

* the provider refused or fell over - the request was fine, so asking again
  is the whole answer;
* the model produced an answer nobody can use - the request has to change,
  because the same request produces the same unusable answer;
* a person has not confirmed something - no amount of retrying helps, and the
  right move is to stop and wait.

A retry that cannot tell them apart repeats the same mistake until the budget
runs out, and reports "failed" without saying why.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: The provider refused or fell over. The request itself was fine.
TRANSPORT = "transport"
#: The provider answered, but the answer cannot be used. The request must change.
CONTENT = "content"
#: A credential is missing or a confirmation is missing. Only a person can fix it.
PERMISSION = "permission"
#: Another operation holds the project. Waiting is enough.
BUSY = "busy"
#: The run was cancelled on purpose.
CANCELLED = "cancelled"
#: Nothing matched; treat it as final rather than burning a retry on it.
UNKNOWN = "unknown"

_TRANSPORT_CODES = frozenset(
    {
        "PROVIDER_RATE_LIMIT",
        "PROVIDER_NETWORK_ERROR",
        "PROVIDER_TIMEOUT",
        "PROVIDER_STREAM_ERROR",
        "PROVIDER_ERROR",
    }
)
_CONTENT_CODES = frozenset(
    {
        "MODEL_OUTPUT_TRUNCATED",
        "MODEL_EMPTY_RESPONSE",
        "MODEL_REASONING_ONLY",
        "MODEL_OUTPUT_UNPARSEABLE",
        "MALFORMED_STRUCTURED_OUTPUT",
        "MALFORMED_TOOL_ARGUMENTS",
        "INVALID_MODEL_OUTPUT",
        "CHAPTER_LENGTH_OUT_OF_RANGE",
    }
)
_PERMISSION_CODES = frozenset(
    {
        "PROVIDER_AUTH_ERROR",
        "MODEL_CREDENTIAL_MISSING",
        "INVALID_MODEL_PROFILE",
        "INVALID_MODEL_ROUTE",
        "CONFIRMATION_REQUIRED",
    }
)
_BUSY_CODES = frozenset({"PROJECT_BUSY"})

_HINTS = {
    TRANSPORT: "服务商暂时不可用；请求本身没有问题，稍后原样重试即可。",
    CONTENT: "上一次没能产出可用的结果；重试前先收紧要求或调整写法，不要原样再发一次。",
    PERMISSION: "缺少凭证或尚未获得确认；重试无用，需要人工处理。",
    BUSY: "项目正被另一项操作占用；稍后再试即可。",
    CANCELLED: "任务已取消。",
    UNKNOWN: "原因不明；重试前请先确认这一步的输入是否正确。",
}

#: Only these are worth repeating on their own.
_AUTO_RETRYABLE = frozenset({TRANSPORT, BUSY})


@dataclass(frozen=True)
class FailureDiagnosis:
    """What kind of failure this is, and what would move it forward."""

    category: str
    code: str
    message: str
    hint: str
    auto_retryable: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "code": self.code,
            "message": self.message,
            "hint": self.hint,
            "auto_retryable": self.auto_retryable,
        }

    def as_guidance(self) -> str:
        """The line a next attempt should read before it starts."""
        return guidance_for(self.as_dict(), self.message)


def guidance_for(diagnosis: dict[str, Any], message: str = "") -> str:
    """The line a next attempt should read before it starts.

    A retry that reads this is no longer the same request: it knows what went
    wrong last time and what would be different this time.
    """
    code = str(diagnosis.get("code") or "UNKNOWN")
    hint = str(diagnosis.get("hint") or "").strip()
    text = str(diagnosis.get("message") or message or "").strip()
    parts = [f"上一次失败（{code}）：{text or hint}"]
    if hint and hint != text:
        parts.append(hint)
    return "\n".join(parts)


def diagnose(code: str = "", message: str = "") -> FailureDiagnosis:
    """Classify a failure by its code."""
    clean = str(code or "").strip().upper()
    text = str(message or "").strip()
    if clean in _BUSY_CODES:
        category = BUSY
    elif clean in _TRANSPORT_CODES:
        category = TRANSPORT
    elif clean in _CONTENT_CODES:
        category = CONTENT
    elif clean in _PERMISSION_CODES:
        category = PERMISSION
    elif clean == "TASK_CANCELLED":
        category = CANCELLED
    else:
        category = UNKNOWN
    return FailureDiagnosis(
        category=category,
        code=clean or "UNKNOWN",
        message=text,
        hint=_HINTS[category],
        auto_retryable=category in _AUTO_RETRYABLE,
    )


def diagnose_exception(exc: BaseException) -> FailureDiagnosis:
    """Classify an exception by the code it carries."""
    code = str(getattr(exc, "code", "") or "")
    if not code:
        name = type(exc).__name__
        code = {
            "RateLimitError": "PROVIDER_RATE_LIMIT",
            "NetworkError": "PROVIDER_NETWORK_ERROR",
            "LLMTimeoutError": "PROVIDER_TIMEOUT",
            "AuthenticationError": "PROVIDER_AUTH_ERROR",
        }.get(name, "")
    return diagnose(code, str(exc))
