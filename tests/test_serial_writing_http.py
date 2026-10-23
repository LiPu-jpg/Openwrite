import json
import time
from threading import Thread
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import pytest

from tests.test_serial_writing import project
from tools.project_lock import ProjectWriteLock
from tools.project_registry import ProjectRegistry
from tools.studio import create_server
from tools.task_store import TaskStore


def test_identity_diagnostics_and_assets_remain_readable_during_project_write(tmp_path):
    root = project(tmp_path)
    registry_path = tmp_path / "isolated-registry.json"
    registry = ProjectRegistry(registry_path, allow_ephemeral=True)
    server = create_server(tmp_path, port=0, project_registry=registry)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    opener = build_opener(ProxyHandler({}))
    base = f"http://127.0.0.1:{server.server_port}"

    def get(path):
        with opener.open(base + path, timeout=2) as response:
            return json.loads(response.read()), response.headers

    try:
        status, headers = get("/api/status")
        assert status["project_path"] == str(tmp_path.resolve())
        assert status["port"] == server.server_port
        assert status["instance_id"] == headers["X-OpenWrite-Instance-Id"]
        with pytest.raises(HTTPError) as mismatch:
            get("/api/status?project_path=/different-project")
        assert mismatch.value.code == 409
        assert json.loads(mismatch.value.read())["code"] == "WORKSPACE_CONTEXT_MISMATCH"
        with server.app._write_lock, ProjectWriteLock(tmp_path, "demo", operation="long-write"):
            before = time.monotonic()
            metrics, _ = get("/api/manuscript/ch_001/metrics")
            audit, _ = get("/api/outline/audit?group_id=sec_001")
            assets, _ = get("/api/writing-assets")
            assert time.monotonic() - before < 2
            assert metrics["metrics"]["writing_units"] == 800
            assert len(audit["chapters"]) == 4
            assert assets["revision"] == ""
        # Reads must not materialize project assets or baselines.
        assert not (root / "src" / "writing").exists()
        assert not (root / "data" / "arc_audit").exists()
        body = json.dumps(
            {"assets": {"terms": [{"term": "钥匙", "min_occurrences": 1}]}, "expected_revision": ""}
        ).encode()
        request = Request(
            base + "/api/writing-assets",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "X-OpenWrite-Studio": "1"},
        )
        with opener.open(request) as response:
            assert json.loads(response.read())["data"]["revision"]
    finally:
        server.shutdown()
        server.workspace_manager.shutdown(wait=True)
        server.server_close()
        worker.join(timeout=2)


def test_task_heartbeat_is_separate_from_activity_and_real_units(tmp_path):
    project(tmp_path)
    store = TaskStore(tmp_path, "demo")
    task = store.create("manuscript_reconcile", {})
    task_id = task["task_id"]
    started = store.transition(
        task_id,
        status="running",
        phase="model",
        updates={
            "progress": {
                "completed_units": 0,
                "total_units": 2,
                "ratio": 0,
                "unit_kind": "chapters",
            }
        },
    )
    event_count = len(store.events(task_id))
    store.heartbeat(task_id)
    latest = store.load(task_id)
    assert latest["last_heartbeat_at"]
    assert latest["last_activity_at"] == started["last_activity_at"]
    assert latest["progress"]["completed_units"] == 0
    assert latest["model_call_elapsed_ms"] >= 0
    assert len(store.events(task_id)) == event_count
    done = store.transition(task_id, status="completed", phase="complete")
    assert done["model_call_elapsed_ms"] is None
