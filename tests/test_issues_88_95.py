"""Regression contracts for deletion, recovery, model output and observability."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Thread
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import pytest

from tools.chapter_memory import ChapterMemoryStore
from tools.chapter_run_v2 import ChapterRunV2Store
from tools.export_preflight import ExportPreflightService
from tools.init_project import init_project
from tools.manuscript_acceptance import ManuscriptAcceptanceService
from tools.project_lock import ProjectWriteLock
from tools.project_registry import ProjectRegistry
from tools.reading_order import ReadingOrderService
from tools.runtime_diagnostics import RuntimeDiagnosticsService
from tools.studio import StudioApplication, create_server
from tools.task_store import TaskStore


def chapter(root, cid="ch_001", text="# 第一章\n\n旧信从雨中送来。\n"):
    path = root / "data/novels/demo/data/manuscript/arc_001" / f"{cid}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def baseline(root):
    service = ManuscriptAcceptanceService(root, "demo")
    operation = service.establish_baseline(confirm=True)
    service.resume(
        operation["operation_id"], analyzer=lambda *args: {"chapter_summary": "旧信抵达。"}
    )
    return service


def application(root, **kwargs):
    registry = ProjectRegistry(root / "isolated-registry.yaml", allow_ephemeral=True)
    return StudioApplication(root, project_registry=registry, **kwargs)


def test_delete_rewrite_five_rounds_archive_and_monotonic_ledger(tmp_path):
    init_project(tmp_path, "demo")
    path = chapter(tmp_path)
    service = baseline(tmp_path)
    app = application(tmp_path)
    data = path.parents[2]
    before = service.inspect()["revision"]
    try:
        for number in range(5):
            run_store = ChapterRunV2Store(tmp_path, "demo")
            run = run_store.create("ch_001")
            run_store.write_artifact(run, "context", {"chapter_id": "ch_001"})
            review = data / "reviews/history/ch_001/old.json"
            review.parent.mkdir(parents=True, exist_ok=True)
            review.write_text('{"chapter_id":"ch_001"}')
            graph = data / "dog/old.json"
            graph.parent.mkdir(exist_ok=True)
            graph.write_text('{"chapter_id":"ch_001"}')
            relative = path.relative_to(app.novel_root).as_posix()
            doc = app.read_document(relative)
            result = app.delete_chapter(
                {"path": relative, "version": doc["version"], "confirm": "ch_001"}
            )
            surface = service.inspect()
            assert surface["revision"] > before
            assert not surface["chapters"] and not surface["blocking"]
            assert (app.novel_root / result["backup"]["content_file"]).is_file()
            assert not run_store.path_for(run.run_id).exists()
            assert not graph.exists() and not review.exists()
            assert not run_store.list()
            path = chapter(tmp_path, text=f"# 第一章\n\n第{number}次新稿。\n")
            service.record_precomputed(
                "ch_001", source="chapter_write", fact={"chapter_summary": "新稿。"}
            )
            before = service.inspect()["revision"]
            assert service.inspect()["status"] == "current"
    finally:
        if app._task_runner:
            app._task_runner.shutdown(wait=True)


def test_missing_is_nonblocking_and_export_uses_reading_order(tmp_path):
    init_project(tmp_path, "demo")
    chapter(tmp_path)
    missing = chapter(tmp_path, "ch_002")
    service = baseline(tmp_path)
    frozen = missing.read_bytes()
    missing.unlink()
    surface = service.inspect()
    assert surface["chapters"][1]["status"] == "missing"
    assert not surface["blocking"]
    service.require_current("ch_003")
    order = ReadingOrderService(tmp_path, "demo").surface()
    report = ExportPreflightService(tmp_path, "demo").inspect(purpose="delivery")
    assert (
        set(report["structure"]["missing"])
        == {
            item["chapter_id"] for item in order["issues"] if item["code"] == "MISSING_CHAPTER_FILE"
        }
        == {"ch_002"}
    )
    assert "MANUSCRIPT_FACTS_NOT_CURRENT" not in {item["code"] for item in report["blockers"]}
    missing.write_bytes(frozen)
    assert service.inspect()["status"] == "current"


def test_settle_retries_full_prose_and_degrades_persistently(tmp_path, monkeypatch):
    from tools import llm
    from tools.settle_backfill import _DEGRADED_MARK, _settle_one

    init_project(tmp_path, "demo")
    path = chapter(tmp_path)
    calls = []

    def chat(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(content="模型没有返回映射")

    fake = SimpleNamespace(chat=chat)
    result = asyncio.run(_settle_one(fake, "ch_001", "旧信", "正文" * 5000, "旧事实"))
    assert result["degraded"] and result["observations"] == _DEGRADED_MARK
    assert len(calls) == 3
    assert [item["temperature"] for item in calls] == [0.2, 0, 0]
    assert all("正文" * 5000 in item["messages"][1].content for item in calls)
    monkeypatch.setattr(llm, "LLMClient", lambda config: fake)
    app = application(tmp_path)
    monkeypatch.setattr(app, "_operation_profile", lambda *a, **kw: None)
    try:
        op = app.establish_manuscript_baseline({"confirm": True})["operation"]
        queued = app.reconcile_manuscript_acceptance({"operation_id": op["operation_id"]})
        for _ in range(300):
            task = app.get_task(queued["task_id"])["task"]
            if task["status"] in {"completed", "failed"}:
                break
            time.sleep(0.01)
        assert task["status"] == "completed", task.get("error")
        assert task["result"]["degraded"]
        assert ChapterMemoryStore(tmp_path, "demo").load("ch_001")["observations"] == _DEGRADED_MARK
        assert task["finished_at"] and task["duration_ms"] > 0
        assert path.read_text().endswith("旧信从雨中送来。\n")
    finally:
        app._task_runner.shutdown(wait=True)


def test_draft_list_and_explicit_restore_reuse_run_and_exact_bytes(tmp_path):
    init_project(tmp_path, "demo")
    store = ChapterRunV2Store(tmp_path, "demo")
    expected = {}
    for index in range(1, 4):
        run = store.create(f"ch_{index:03d}")
        run.status = "drafted"
        store.save(run)
        path = store.root / "artifacts" / run.run_id / "uncommitted.md"
        path.parent.mkdir(parents=True)
        content = f"# Chapter {index}\r\n\r\n原始草稿 {index}。\r\n".encode()
        path.write_bytes(content)
        expected[run.run_id] = content
    app = application(tmp_path, writer_executor=lambda *a: pytest.fail("Recovery called a model"))
    drafts = app.manuscript_drafts()["drafts"]
    assert len(drafts) == 3
    selected = drafts[0]
    # The list's revision normalizes line endings, as the acceptance protocol does.
    selected_path = Path(selected["draft_path"])
    payload = {"run_id_v2": selected["run_id_v2"], "confirm": True}
    # Recovery must retain CRLF bytes too.
    result = app.restore_manuscript_draft(payload)
    assert Path(result["draft_path"]).read_bytes() == expected[selected["run_id_v2"]]
    assert result["run_id_v2"] == selected["run_id_v2"]
    assert result["requires_reconcile"]
    assert len(app.manuscript_drafts()["drafts"]) == 2
    assert selected_path.is_file()


def test_lock_heartbeat_tracks_stage_and_dead_owner_is_reclaimed(tmp_path, monkeypatch):
    with ProjectWriteLock(tmp_path, "demo", operation="write:ch_001") as lock:
        lock.heartbeat("draft")
        owner = json.loads(lock.path.read_text())
        assert owner["stage"] == "draft" and owner["heartbeat_at"]
        contender = ProjectWriteLock(tmp_path, "demo", operation="write:ch_002")
        assert not contender._is_stale()
        monkeypatch.setattr("tools.project_lock._process_alive", lambda pid: False)
        assert contender._is_stale()
    assert not lock.path.exists()


def test_diagnostics_expires_errors_and_success_resets_failure_streak(tmp_path):
    init_project(tmp_path, "demo")
    root = tmp_path / ".openwrite/transport-errors"
    root.mkdir(parents=True)
    old = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    (root / "old.json").write_text(json.dumps({"created_at": old, "code": "NETWORK_ERROR"}))
    store = TaskStore(tmp_path, "demo")
    for _ in range(2):
        task = store.create("chapter_write", {"chapter_id": "ch_001"}, chapter_id="ch_001")
        store.transition(task["task_id"], status="failed")
    service = RuntimeDiagnosticsService(tmp_path, "demo")
    report = service.run()
    assert "transport_error" not in {item.code for item in report.findings}
    assert report.historical_counts["transport_error"] == 1
    repeated = next(item for item in report.findings if item.code == "repeated_task_failure")
    assert repeated.first_seen and repeated.last_seen
    task = store.create("chapter_write", {}, chapter_id="ch_001")
    store.transition(task["task_id"], status="running")
    store.transition(task["task_id"], status="completed")
    assert "repeated_task_failure" not in {item.code for item in service.run().findings}
    assert "transport_error" in {item.code for item in service.run(window_hours=168).findings}


def test_http_routes_and_async_write_are_observable_while_model_waits(tmp_path):
    init_project(tmp_path, "demo")
    entered, release = Event(), Event()
    recovery = tmp_path / "draft.md"
    recovery.write_text("# 第一章\n\n保留草稿。")

    def writer(root, args):
        args["_task_stage"]("draft", "runv2_test12345678")
        entered.set()
        assert release.wait(5)
        return {
            "ok": False,
            "code": "MODEL_OUTPUT_TRUNCATED",
            "error": "interrupted",
            "run_id_v2": "runv2_test12345678",
            "draft_path": str(recovery),
            "uncommitted": True,
        }

    registry = ProjectRegistry(tmp_path / "registry.yaml", allow_ephemeral=True)
    server = create_server(tmp_path, port=0, project_registry=registry, writer_executor=writer)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    opener = build_opener(ProxyHandler({}))

    def request(path, method="GET", body=None):
        req = Request(
            base + path,
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"X-OpenWrite-Studio": "1", "Content-Type": "application/json"},
        )
        try:
            response = opener.open(req)
        except HTTPError as exc:
            response = exc
        with response:
            return response.status, response.headers, json.loads(response.read())

    try:
        status, headers, result = request("/api/nope-xyz")
        assert status == 404 and result["code"] == "ROUTE_NOT_FOUND"
        status, headers, result = request("/api/context", "POST", {})
        assert (
            status == 405 and result["code"] == "METHOD_NOT_ALLOWED" and headers["Allow"] == "GET"
        )
        status, _, queued = request(
            "/api/write", "POST", {"chapter_id": "ch_001", "target_words": 200}
        )
        assert status in {200, 202} and queued["task_id"]
        assert entered.wait(3)
        _, _, surface = request("/api/tasks")
        task = next(
            item for item in surface["data"]["tasks"] if item["task_id"] == queued["task_id"]
        )
        assert task["status"] == "running" and task["stage"] == "draft"
        release.set()
        for _ in range(300):
            _, _, detail = request(f"/api/tasks/{queued['task_id']}")
            task = detail["data"]["task"]
            if task["status"] == "failed":
                break
            time.sleep(0.01)
        assert task["error"]["details"]["draft_path"] == str(recovery)
        assert task["error"]["details"]["uncommitted"]
        assert task["finished_at"] and task["duration_ms"] > 0
        assert request("/api/diagnostics")[0] == 200
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        server.app._task_runner.shutdown(wait=True)
        thread.join(timeout=3)


@pytest.mark.parametrize("cancelled", [False, True])
def test_partial_and_cancelled_model_outputs_remain_discoverable(tmp_path, monkeypatch, cancelled):
    from tools import llm
    import tools.agent as agents
    from tools.chapter_pipeline import execute_write_chapter
    from tools.llm.response import ProviderResponseError

    init_project(tmp_path, "demo")
    cancel = {"requested": False}
    prose = "# 第一章\n\n刚收到的草稿。"

    class Writer:
        def __init__(self, context):
            pass

        async def write_chapter(self, **kwargs):
            if not cancelled:
                error = ProviderResponseError("MODEL_OUTPUT_TRUNCATED", "interrupted")
                error.partial_content = prose
                raise error
            cancel["requested"] = True
            return SimpleNamespace(title="第一章", content="刚收到的草稿。", word_count=7)

    monkeypatch.setattr(agents, "WriterAgent", Writer)
    monkeypatch.setattr(llm, "LLMClient", lambda config: object())
    result = execute_write_chapter(
        tmp_path,
        {
            "chapter_id": "ch_001",
            "target_words": 200,
            "_cancel_requested": lambda: cancel["requested"],
        },
    )
    assert result["code"] == ("TASK_CANCELLED" if cancelled else "MODEL_OUTPUT_TRUNCATED")
    assert result["uncommitted"]
    assert Path(result["draft_path"]).read_text() == prose
    drafts = application(tmp_path).manuscript_drafts()["drafts"]
    assert len(drafts) == 1 and drafts[0]["run_id_v2"] == result["run_id_v2"]


def test_stream_has_read_idle_timeout_and_keeps_short_partial_content():
    from tools.llm import LLMClient, LLMConfig, Message

    calls = []

    def completion(**kwargs):
        calls.append(kwargs)

        def events():
            yield {"choices": [{"delta": {"content": "已收到"}}]}
            raise TimeoutError("read timeout between chunks")

        return events()

    backend = SimpleNamespace(completion=completion, token_counter=lambda **kw: 1)
    client = LLMClient(LLMConfig(model="fake", timeout_seconds=150), client=backend)
    response = client.chat([Message("user", "继续")], stream=True)
    assert response.content == "已收到" and response.finish_reason == "incomplete"
    assert calls[0]["timeout"].read == 150
    assert calls[0]["timeout"].connect == 30


def test_shared_length_bounds_avoid_rewriting_4200_unit_chapter(tmp_path):
    from tools.agent.base import AgentContext
    from tools.agent.writer import WriterAgent
    from tools.agent.reviewer import ReviewerAgent
    from tools.writing_policy import chapter_word_bounds, resolve_target_words
    from tools.novel_workspace import count_writing_units

    prose = "# 第一章\n\n" + "山" * 4200
    calls = []

    def chat(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(content=prose, usage={}, finish_reason="stop", total_tokens=0)

    writer = WriterAgent(AgentContext(SimpleNamespace(chat=chat), "fake", str(tmp_path)))
    result = asyncio.run(writer._creative_write({}, 1, 0.7, 5000))
    assert len(calls) == 1
    assert result["word_count"] == count_writing_units(prose) == 4200
    minimum, target, maximum = chapter_word_bounds(5000)
    assert resolve_target_words(5000)["minimum_words"] == minimum == 4000
    assert maximum == 7500 and target == 5000
    issues = ReviewerAgent.__new__(ReviewerAgent)._rule_based_check(prose, 5000)
    assert not any(issue.dimension == 7 for issue in issues)
