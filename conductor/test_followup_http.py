"""Exercise follow-up contracts through the candidate Core's real HTTP transport."""

import json
from pathlib import Path
from threading import Thread
from urllib.request import ProxyHandler, Request, build_opener

import pytest

from tools.chapter_lifecycle import archive_chapter_artifacts
from tools.chapter_run_v2 import ChapterRunV2Store
from tools.init_project import init_project
from tools.project_registry import ProjectRegistry
from tools.studio import create_server


@pytest.fixture
def studio(tmp_path):
    init_project(tmp_path, "demo")
    registry = ProjectRegistry(tmp_path / "registry.yaml", allow_ephemeral=True)

    def writer(*_args):
        pytest.fail("HTTP dry-run must never invoke a writer")

    server = create_server(
        tmp_path, port=0, project_registry=registry, writer_executor=writer
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    opener = build_opener(ProxyHandler({}))

    def request(path, payload=None):
        req = Request(
            f"http://127.0.0.1:{server.server_port}{path}",
            data=json.dumps(payload).encode() if payload is not None else None,
            headers={"X-OpenWrite-Studio": "1", "Content-Type": "application/json"},
        )
        with opener.open(req, timeout=10) as response:
            return response.headers, json.loads(response.read())

    try:
        yield tmp_path, request
    finally:
        server.shutdown()
        server.server_close()
        server.app._task_runner.shutdown(wait=True)
        thread.join(timeout=3)


def test_http_dry_run_keeps_tasks_empty_and_reports_no_public_mutation(studio):
    _, request = studio
    _, before = request("/api/tasks")
    headers, result = request(
        "/api/write",
        {
            "dry_run": True,
            "chapter_id": "ch_001",
            "target_words": 2000,
            "guidance": "雨停之后再开门。",
        },
    )
    assert headers["X-OpenWrite-Mutated"] == "0"
    assert result["dry_run"] and result["model_call_count"] == 0
    assert "task_id" not in result
    assert result["context"]["agent_payload"]["target_words"] == 2000
    assert "雨停之后再开门。" in str(result["context"]["writer_messages"])
    _, after = request("/api/tasks")
    assert before["data"]["tasks"] == after["data"]["tasks"] == []


def test_http_archived_history_returns_original_artifacts(studio):
    root, request = studio
    store = ChapterRunV2Store(root, "demo")
    run = store.create("ch_001")
    store.start_stage(run, "context")
    artifact = store.write_artifact(run, "context", {"original": "原始上下文"})
    store.complete_stage(run, "context", artifact=artifact)
    archive_chapter_artifacts(root / "data/novels/demo", "ch_001", "http_delete_test")
    _, current = request("/api/chapter-runs-v2", {"action": "list"})
    assert current["runs"] == []
    _, history = request(
        "/api/chapter-runs-v2", {"action": "list", "include_archived": True}
    )
    assert history["count"] == 1
    old = history["runs"][0]
    assert old["run_id"] == run.run_id and old["archived"]
    assert old["next_stage"] is None
    assert json.loads(Path(old["stages"]["context"]["artifact"]).read_text()) == {
        "original": "原始上下文"
    }
