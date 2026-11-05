"""One retry policy for model calls that have to survive a bad answer.

A blind retry repeats the same request: a truncated answer stays truncated and
an invalid structure stays invalid, so three fast attempts all fail and the
work is lost. The policy here changes one lever per attempt and keeps the
reason of every failure, so a caller can report *why* an answer was dropped
instead of only that it was.
"""

from __future__ import annotations

import asyncio
import os
import random
import time
from dataclasses import dataclass
from typing import Any

import yaml

from .errors import LLMTimeoutError, NetworkError, RateLimitError
from .response import ProviderResponseError

#: The first wait before a retry. Kept small: the point of the wait is to
#: outlast a burst, not to pace the whole run.
DEFAULT_BASE_DELAY = 1.5

#: A truncated answer needs a bigger budget; an empty or reasoning-only answer
#: is worth asking again; an unparseable structure needs the model to repair
#: its own output.
BUDGET_RETRYABLE = frozenset(
    {"MODEL_OUTPUT_TRUNCATED", "MODEL_EMPTY_RESPONSE", "MODEL_REASONING_ONLY"}
)
STRUCTURE_RETRYABLE = frozenset({"MODEL_OUTPUT_UNPARSEABLE"})
TRANSPORT_RETRYABLE = frozenset(
    {"PROVIDER_RATE_LIMIT", "PROVIDER_NETWORK_ERROR", "PROVIDER_TIMEOUT"}
)

#: What a *generation* call may retry: the provider hiccuped, or the answer was
#: cut short and a bigger budget fixes that. The answer-shape errors are not
#: here on purpose - repeating the same request reproduces the same shape, and
#: the caller's own parsing stage handles them.
GENERATION_RETRYABLE = frozenset(
    {"MODEL_OUTPUT_TRUNCATED"} | set(TRANSPORT_RETRYABLE)
)


@dataclass(frozen=True)
class AttemptFailure:
    """Why one attempt failed, in a form a caller can store and show."""

    code: str
    message: str
    attempt: int
    retryable: bool
    detail: str = ""

    @property
    def needs_wait(self) -> bool:
        """Whether the next attempt has to wait for the provider.

        Only a transport failure needs time: the provider said no or fell over.
        A bad *answer* does not - the next attempt changes the request itself
        (a bigger budget, a repair prompt), and waiting only delays the fix.
        """
        return self.code in TRANSPORT_RETRYABLE

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "attempt": self.attempt,
            "retryable": self.retryable,
            "detail": self.detail,
        }


def classify_failure(exc: BaseException, *, attempt: int = 1) -> AttemptFailure:
    """Name a failure and say whether repeating it could help."""
    if isinstance(exc, ProviderResponseError):
        code = str(exc.code or "MODEL_OUTPUT_INVALID")
        detail = str(exc.details.get("context") or "")[:200]
        return AttemptFailure(
            code=code,
            message=str(exc),
            attempt=attempt,
            retryable=(
                code in BUDGET_RETRYABLE
                or code in STRUCTURE_RETRYABLE
                or code in TRANSPORT_RETRYABLE
            ),
            detail=detail,
        )
    if isinstance(exc, RateLimitError):
        return AttemptFailure("PROVIDER_RATE_LIMIT", str(exc), attempt, True)
    if isinstance(exc, NetworkError):
        return AttemptFailure("PROVIDER_NETWORK_ERROR", str(exc), attempt, True)
    if isinstance(exc, LLMTimeoutError):
        return AttemptFailure("PROVIDER_TIMEOUT", str(exc), attempt, True)
    if isinstance(exc, (ValueError, yaml.YAMLError)):
        return AttemptFailure(
            "MODEL_OUTPUT_UNPARSEABLE",
            str(exc) or exc.__class__.__name__,
            attempt,
            True,
        )
    return AttemptFailure("MODEL_CALL_FAILED", str(exc), attempt, False)


def backoff_delay(
    attempt: int,
    *,
    base: float = 1.5,
    cap: float = 20.0,
    jitter: float = 0.3,
) -> float:
    """Exponential delay with jitter.

    Jitter matters here: several chapters fail at once (the same provider
    hiccup hits every in-flight call), and a fixed delay would retry them in
    lockstep, repeating the burst that caused the failure.
    """
    delay = min(cap, base * (2 ** max(0, attempt - 1)))
    spread = 1 - jitter + 2 * jitter * random.random()
    return max(0.0, delay * spread)


def retry_delay(
    attempt: int,
    *,
    base: float | None = None,
    cap: float = 20.0,
    jitter: float = 0.3,
) -> float:
    """The delay before the next attempt, without sleeping."""
    if base is None:
        raw = os.getenv("OW_RETRY_BASE_SECONDS", "").strip()
        base = DEFAULT_BASE_DELAY
        if raw:
            try:
                value = float(raw)
            except ValueError:
                value = -1.0
            if value >= 0:
                base = value
    return backoff_delay(attempt, base=base, cap=cap, jitter=jitter)


def wait_before_retry(
    attempt: int,
    *,
    base: float | None = None,
    cap: float = 20.0,
    jitter: float = 0.3,
    sleep: Any = time.sleep,
) -> float:
    """Sleep out the backoff and return the delay that was used."""
    delay = retry_delay(attempt, base=base, cap=cap, jitter=jitter)
    if delay > 0:
        sleep(delay)
    return delay


async def wait_before_retry_async(
    attempt: int,
    *,
    base: float | None = None,
    cap: float = 20.0,
    jitter: float = 0.3,
    sleep: Any = None,
) -> float:
    """Wait out the backoff without blocking the event loop.

    The agent loop is asynchronous: sleeping there with `time.sleep` would
    stop every other coroutine of the turn, including the review fan-out.
    """
    delay = retry_delay(attempt, base=base, cap=cap, jitter=jitter)
    if delay > 0:
        if sleep is None:
            await asyncio.sleep(delay)
        else:
            await sleep(delay)
    return delay
