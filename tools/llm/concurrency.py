"""One gate for the model calls a single Core process makes at once.

The review stage fans six quality domains out at the same time and nothing
capped it: a provider that rate-limits then sees a burst of six similar
calls, the ones that fail are retried blind, and the retry burst makes the
limit worse. The gate keeps every burst inside a budget the provider can
answer.

The limit is process-wide, so the writer, the reviewer and a research run
share it instead of each opening their own burst.
"""

from __future__ import annotations

import logging
import os
import threading
from contextlib import contextmanager
from typing import Iterator

logger = logging.getLogger(__name__)

DEFAULT_LIMIT = 4

#: How long a caller waits for a slot before going ahead without one. The
#: point of the gate is to avoid a burst, not to queue forever: a stuck holder
#: must not turn into a stalled run.
DEFAULT_WAIT_SECONDS = 300.0

_local = threading.local()
_gate: threading.BoundedSemaphore | None = None
_gate_lock = threading.Lock()
_gate_limit = 0


def model_concurrency_limit() -> int:
    """The configured number of model calls allowed to run at once."""
    raw = os.getenv("OW_MODEL_CONCURRENCY", "").strip()
    if raw:
        try:
            value = int(raw)
        except ValueError:
            value = 0
        if value > 0:
            return value
    return DEFAULT_LIMIT


def model_gate_wait_seconds() -> float:
    """How long a caller waits for a slot before proceeding without one."""
    raw = os.getenv("OW_MODEL_GATE_WAIT_SECONDS", "").strip()
    if raw:
        try:
            value = float(raw)
        except ValueError:
            value = -1.0
        if value >= 0:
            return value
    return DEFAULT_WAIT_SECONDS


def _gate_for(limit: int) -> threading.BoundedSemaphore:
    global _gate, _gate_limit
    with _gate_lock:
        if _gate is None or _gate_limit != limit:
            _gate = threading.BoundedSemaphore(limit)
            _gate_limit = limit
        return _gate


@contextmanager
def model_slot() -> Iterator[None]:
    """Hold one model-call slot for the duration of the block.

    Re-entrant: a thread that already holds a slot takes another one without
    waiting, so a model call made from inside a model call cannot deadlock on
    its own gate.

    The wait is bounded. When the wait runs out the call goes ahead without a
    slot and says so: a run that stops waiting is a visible stall, while a run
    that waits forever looks exactly like the failure this gate exists to fix.
    """
    depth = getattr(_local, "depth", 0)
    if depth > 0:
        _local.depth = depth + 1
        try:
            yield
        finally:
            _local.depth = depth
        return
    gate = _gate_for(model_concurrency_limit())
    acquired = gate.acquire(timeout=model_gate_wait_seconds())
    if not acquired:
        logger.warning(
            "模型并发闸门等待超时（%.0fs），本次调用不再排队",
            model_gate_wait_seconds(),
        )
        yield
        return
    _local.depth = 1
    try:
        yield
    finally:
        _local.depth = 0
        gate.release()
