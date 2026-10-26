"""Request-local cancellation propagated through benchmark worker calls."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

_cancel: ContextVar[Callable[[], bool] | None] = ContextVar("openwrite_model_cancel", default=None)


class ModelCancelledError(RuntimeError):
    code = "TASK_CANCELLED"


@contextmanager
def model_cancellation(check: Callable[[], bool]) -> Iterator[None]:
    token = _cancel.set(check)
    try:
        yield
    finally:
        _cancel.reset(token)


def cancellation_bound() -> bool:
    return _cancel.get() is not None


def check_model_cancellation() -> None:
    check = _cancel.get()
    if check and check():
        raise ModelCancelledError("MODEL_CANCELLED: no further model requests will be scheduled")


def close_model_stream(stream: Any) -> bool:
    """Close this request's sync transport, including LiteLLM stream wrappers."""
    visited: set[int] = set()
    while stream is not None and id(stream) not in visited:
        visited.add(id(stream))
        close = getattr(stream, "close", None)
        if callable(close):
            close()
            return True
        # CustomStreamWrapper exposes aclose(), but sync OpenAI completions
        # retain their owned openai.Stream here. Never close a shared client.
        stream = getattr(stream, "completion_stream", None)
    return False
