"""Bounded dispatch with cancellation observation while requests are in flight."""

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Any, Callable, Iterable

from tools.llm.cancellation import model_cancellation


def run_bounded(
    jobs: Iterable[tuple[Any, ...]],
    execute: Callable[..., dict[str, Any]],
    *,
    concurrency: int,
    cancelled: Callable[[], bool],
    completed: Callable[[dict[str, Any], int], None],
    draining: Callable[[int], None],
) -> None:
    remaining = iter(jobs)
    stopped = False

    def call(args: tuple[Any, ...]) -> dict[str, Any]:
        with model_cancellation(cancelled):
            return execute(*args)

    # At most concurrency jobs are submitted. No hidden executor backlog can
    # start after cancellation, and in-flight results are drained and persisted.
    with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="openwrite-benchmark") as pool:
        active = set()
        exhausted = False
        while active or not exhausted:
            if cancelled():
                stopped = True
            while not stopped and not exhausted and len(active) < concurrency:
                args = next(remaining, None)
                if args is None:
                    exhausted = True
                else:
                    active.add(pool.submit(call, args))
            if stopped:
                draining(len(active))
                exhausted = True
            if not active:
                break
            ready, active = wait(active, timeout=0.1, return_when=FIRST_COMPLETED)
            for index, future in enumerate(ready):
                completed(future.result(), len(active) + len(ready) - index - 1)
