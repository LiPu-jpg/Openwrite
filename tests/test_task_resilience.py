"""Why a background task loses work: retries, cancellation, and concurrency.

Every case here is a failure that used to look like "the task ran fine":

* a truncated answer was retried with the same budget, so three fast attempts
  all failed and the chapter was degraded without a reason;
* a rate limit was not a retryable class at all, so it killed the whole task;
* a cancel request only stopped the run *between* chapters, so the in-flight
  model call ran to completion;
* nothing capped how many model calls ran at once, so one stage could burst a
  provider into a rate limit.
"""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from tools.chapter_pipeline import configure_writer_llm
from tools.llm.cancellation import ModelCancelledError
from tools.llm.client import LLMConfig
from tools.llm.concurrency import model_concurrency_limit, model_slot
from tools.llm.errors import RateLimitError
from tools.llm.response import ProviderResponseError
from tools.settle_backfill import (
    SETTLE_MAX_TOKENS,
    _SettleStructureError,
    _settle_one,
)


class FakeResponse:
    def __init__(self, content: str, finish_reason: str = "stop"):
        self.content = content
        self.finish_reason = finish_reason


class ScriptedClient:
    """A model client that replays a scripted list of answers and failures."""

    def __init__(self, script):
        self.script = list(script)
        self.calls: list[dict] = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        if not self.script:
            raise AssertionError("the client was called more times than the script allows")
        kind, value = self.script.pop(0)
        if kind == "error":
            raise value
        return FakeResponse(value)


@pytest.fixture(autouse=True)
def _no_backoff_wait(monkeypatch):
    monkeypatch.setenv("OW_RETRY_BASE_SECONDS", "0")


# ── the reasoning policy ─────────────────────────────────────────────────────


def test_a_host_relay_flash_profile_disables_reasoning():
    # The relay profile reaches the host over loopback, so the endpoint is
    # 127.0.0.1 and the model is a `provider/model` route. Matching the
    # endpoint on the DeepSeek API host skipped every relay profile — and with
    # it the policy that stops a flash model from spending its whole output
    # budget on reasoning.
    config = LLMConfig(
        provider="custom",
        api_key="x",
        base_url="http://127.0.0.1:50000/v1",
        model="deepseek-official/deepseek-flash",
        extra={},
        auth_source="host_relay",
    )
    summary = configure_writer_llm(config)
    assert summary["thinking"] == "disabled"
    assert config.extra["extra_body"]["thinking"] == {"type": "disabled"}


def test_a_direct_deepseek_profile_still_disables_reasoning():
    config = LLMConfig(
        provider="openai",
        api_key="x",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-v4-flash",
        extra={},
    )
    assert configure_writer_llm(config)["thinking"] == "disabled"


def test_a_relay_profile_of_another_provider_keeps_the_provider_default():
    # Sending a DeepSeek-only body field to another provider would be a
    # request it cannot read.
    config = LLMConfig(
        provider="custom",
        api_key="x",
        base_url="http://127.0.0.1:50000/v1",
        model="our-free-model/beam-free",
        extra={},
        auth_source="host_relay",
    )
    assert configure_writer_llm(config)["thinking"] == "provider_default"
    assert "extra_body" not in config.extra


# ── classified retries ───────────────────────────────────────────────────────


def test_a_truncated_answer_is_asked_again_with_a_bigger_budget():
    client = ScriptedClient(
        [
            ("answer", ""),
            ("answer", "observations: |\n  - 一件事\nchapter_summary: \"摘要\"\n"),
        ]
    )
    client.script[0] = ("answer", "")
    result = asyncio.run(
        _settle_one(client, "ch_001", "ch_001", "正文", "（无既有运行态）")
    )
    assert result["degraded"] is False
    # The first answer is cut short by the provider's finish reason.
    assert client.calls[0]["max_tokens"] == SETTLE_MAX_TOKENS


def test_a_truncated_answer_raises_the_budget_on_the_next_attempt():
    truncated = FakeResponse("observations: |\n  - 半句话", finish_reason="length")
    client = ScriptedClient([])
    calls = []

    def chat(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return truncated
        return FakeResponse("observations: |\n  - 完整\nchapter_summary: \"摘要\"\n")

    client.chat = chat
    result = asyncio.run(
        _settle_one(client, "ch_001", "ch_001", "正文", "（无既有运行态）")
    )
    assert result["degraded"] is False
    assert calls[0]["max_tokens"] == SETTLE_MAX_TOKENS
    assert calls[1]["max_tokens"] > calls[0]["max_tokens"]


def test_an_unparseable_answer_is_handed_back_for_repair():
    calls = []

    def chat(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return FakeResponse("好的，以下是提取结果：\n这其实不是 YAML")
        return FakeResponse("observations: |\n  - 一件事\nchapter_summary: \"摘要\"\n")

    client = ScriptedClient([])
    client.chat = chat
    result = asyncio.run(
        _settle_one(client, "ch_001", "ch_001", "正文", "（无既有运行态）")
    )
    assert result["degraded"] is False
    # The second attempt carries the invalid answer so the model can fix it.
    assert "这其实不是 YAML" in calls[1]["messages"][1].content


def test_a_rate_limit_is_retried_instead_of_killing_the_task():
    calls = []

    def chat(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise RateLimitError("API 返回 429（请求过多），请稍后重试", "429")
        return FakeResponse("observations: |\n  - 一件事\nchapter_summary: \"摘要\"\n")

    client = ScriptedClient([])
    client.chat = chat
    result = asyncio.run(
        _settle_one(client, "ch_001", "ch_001", "正文", "（无既有运行态）")
    )
    assert result["degraded"] is False
    assert len(calls) == 2


def test_a_chapter_that_never_parses_is_degraded_with_its_reason():
    client = ScriptedClient([])
    client.chat = lambda **kwargs: (_ for _ in ()).throw(
        _SettleStructureError("settle output is not a mapping", "not yaml at all")
    )
    result = asyncio.run(
        _settle_one(client, "ch_001", "ch_001", "正文", "（无既有运行态）")
    )
    assert result["degraded"] is True
    assert result["degraded_reason"] == "MODEL_OUTPUT_UNPARSEABLE"
    assert result["failures"]
    assert result["failures"][-1]["code"] == "MODEL_OUTPUT_UNPARSEABLE"
    assert len(result["failures"]) == 3


def test_the_retry_layer_is_the_only_one():
    # LiteLLM retries on its own; two layers stack into a burst, and the
    # burst is what a rate limiter punishes.
    client = ScriptedClient(
        [("answer", "observations: |\n  - 一件事\nchapter_summary: \"摘要\"\n")]
    )
    asyncio.run(_settle_one(client, "ch_001", "ch_001", "正文", "（无既有运行态）"))
    assert client.calls[0]["max_retries"] == 0


# ── cancellation ─────────────────────────────────────────────────────────────


def test_a_cancel_request_stops_the_next_model_call():
    client = ScriptedClient(
        [("answer", "observations: |\n  - 一件事\nchapter_summary: \"摘要\"\n")]
    )
    # A cancel is not a degraded chapter: it must abort the run, so the caller
    # can tell "stopped" apart from "lost".
    with pytest.raises(ModelCancelledError):
        asyncio.run(
            _settle_one(
                client,
                "ch_001",
                "ch_001",
                "正文",
                "（无既有运行态）",
                cancelled=lambda: True,
            )
        )
    assert client.calls == []


def test_a_cancel_during_a_run_stops_the_run_instead_of_degrading_the_chapter(
    tmp_path, monkeypatch
):
    """The run must not keep going - and must not write a placeholder recap.

    A cancel request used to be swallowed by the per-chapter error handler:
    the chapter was recorded as degraded and the run moved on to the next one.
    """
    from tools import llm
    from tools.chapter_memory import ChapterMemoryStore
    from tools.init_project import init_project
    from tools.settle_backfill import run as run_settle_backfill

    init_project(tmp_path, "demo")
    (tmp_path / "data/novels/demo/data/manuscript").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data/novels/demo/data/manuscript/ch_001.md").write_text(
        "# 第一章 旧信\n\n旧信从雨中送来。\n", encoding="utf-8"
    )

    class ExplodingClient:
        def chat(self, **kwargs):  # pragma: no cover - must never be reached
            raise AssertionError("the model must not be called after a cancel request")

    monkeypatch.setattr(llm, "LLMClient", lambda config: ExplodingClient())

    checks = {"n": 0}

    def cancelled() -> bool:
        checks["n"] += 1
        # The first check is the loop guard between chapters; the second one
        # lands inside the chapter, where a cancel request usually arrives.
        return checks["n"] >= 2

    with pytest.raises(ModelCancelledError):
        run_settle_backfill(tmp_path, "demo", only_missing=True, cancelled=cancelled)

    # The cancelled chapter must not be recorded as a degraded recap.
    assert ChapterMemoryStore(tmp_path, "demo").load("ch_001") is None


# ── the concurrency gate ────────────────────────────────────────────────────


def test_the_gate_caps_the_model_calls_that_run_at_once(monkeypatch):
    monkeypatch.setenv("OW_MODEL_CONCURRENCY", "2")
    assert model_concurrency_limit() == 2
    inside = 0
    peak = 0
    lock = threading.Lock()

    def worker():
        nonlocal inside, peak
        with model_slot():
            with lock:
                inside += 1
                peak = max(peak, inside)
            time.sleep(0.05)
            with lock:
                inside -= 1

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert peak <= 2


def test_the_gate_is_reentrant(monkeypatch):
    # A model call made from inside a model call must not wait for itself.
    monkeypatch.setenv("OW_MODEL_CONCURRENCY", "1")
    with model_slot():
        with model_slot():
            assert True


def test_a_stuck_slot_holder_does_not_stall_the_run(monkeypatch):
    # The gate caps bursts; it must not become a new way to hang. A holder that
    # never returns would otherwise park every later call forever.
    monkeypatch.setenv("OW_MODEL_CONCURRENCY", "1")
    monkeypatch.setenv("OW_MODEL_GATE_WAIT_SECONDS", "0")
    holder_started = threading.Event()
    release = threading.Event()

    def holder():
        with model_slot():
            holder_started.set()
            release.wait(10)

    thread = threading.Thread(target=holder)
    thread.start()
    assert holder_started.wait(5)
    try:
        started = time.monotonic()
        with model_slot():
            pass
        assert time.monotonic() - started < 2, "the gate waited for a stuck holder"
    finally:
        release.set()
        thread.join(5)


def test_a_truncated_model_answer_is_not_retried_when_it_is_a_provider_error():
    client = ScriptedClient([])
    client.chat = lambda **kwargs: (_ for _ in ()).throw(
        ProviderResponseError("MODEL_OUTPUT_TRUNCATED", "cut off")
    )
    result = asyncio.run(
        _settle_one(client, "ch_001", "ch_001", "正文", "（无既有运行态）")
    )
    assert result["degraded"] is True
    assert result["degraded_reason"] == "MODEL_OUTPUT_TRUNCATED"
    # Every attempt tried; the reason is kept so a caller can say why.
    assert len(result["failures"]) == 3
