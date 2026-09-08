"""Request-local cancellation propagated through benchmark worker calls."""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable, Iterator

_cancel: ContextVar[Callable[[], bool] | None] = ContextVar("openwrite_model_cancel", default=None)


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
        raise RuntimeError("MODEL_CANCELLED: no further model requests will be scheduled")
