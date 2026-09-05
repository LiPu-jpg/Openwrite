from __future__ import annotations

import json
import time
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import pytest

from tools.init_project import init_project
from tools.manuscript_acceptance import ManuscriptAcceptanceService
from tools.project_registry import ProjectRegistry
from tools.studio import StudioApplication, StudioError, create_server
from tools.studio_http import POST_ROUTES


def _chapter(root: Path, text: str) -> Path:
    directory = root / "data" / "novels" / "demo" / "data" / "manuscript" / "arc_001"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "ch_001.md"
    path.write_text(f"# 第一章\n\n{text}\n", encoding="utf-8")
    return path


def _analyze(chapter_id: str, title: str, content: str, prior_context: str) -> dict:
    del title, prior_context
    state = "林岑已离开钟楼" if "离开" in content else "林岑仍在钟楼"
    return {
        "chapter_summary": f"{chapter_id}：{state}",
        "observations": state,
        "legacy_updates": {"current_state": state},
        "state_delta": {},
    }


def _analyze_existing(
    project_root: Path,
    novel_id: str,
    *,
    chapter_id: str,
    title: str,
    content: str,
    truth_context: str = "",
    profile: dict | None = None,
) -> dict:
    del project_root, novel_id, profile
    return _analyze(chapter_id, title, content, truth_context)


def _wait(app: StudioApplication, task_id: str, timeout: float = 3) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = app.get_task(task_id)["task"]
        if task["status"] in {"completed", "failed", "cancelled", "interrupted"}:
            return task
        time.sleep(0.01)
    raise AssertionError(f"task {task_id} did not finish")


def _request(opener, url: str, *, method: str = "GET", payload: dict | None = None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if method != "GET":
        headers["X-OpenWrite-Studio"] = "1"
    request = Request(url, method=method, data=data, headers=headers)
    with opener.open(request) as response:
        return json.loads(response.read())


def test_application_reconciles_acceptance_in_persistent_task_and_reports_chapters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    init_project(tmp_path, "demo")
    chapter = _chapter(tmp_path, "林岑仍在钟楼。")
    registry = ProjectRegistry(tmp_path / "registry.yaml", allow_ephemeral=True)
    app = StudioApplication(tmp_path, project_registry=registry)
    monkeypatch.setattr(app, "_operation_profile", lambda *args, **kwargs: None)
    monkeypatch.setattr("tools.settle_backfill.analyze_existing_chapter", _analyze_existing)
    try:
        surface = app.manuscript_acceptance()
        assert surface["status"] == "baseline_required"

        with pytest.raises(StudioError) as unconfirmed:
            app.establish_manuscript_baseline({"confirm": False})
        assert unconfirmed.value.code == "CONFIRMATION_REQUIRED"

        started = app.establish_manuscript_baseline({"confirm": True})
        operation_id = started["operation"]["operation_id"]
        queued = app.reconcile_manuscript_acceptance({"operation_id": operation_id})
        completed = _wait(app, queued["task_id"])

        assert completed["status"] == "completed", completed.get("error")
        assert completed["type"] == "manuscript_reconcile"
        assert completed["progress"] == {
            "completed_units": 1,
            "total_units": 1,
            "ratio": 1.0,
            "unit_kind": "chapters",
        }
        assert completed["result"]["operation_id"] == operation_id
        assert completed["result"]["acceptance"]["status"] == "current"
        assert app.task_surface()["tasks"][0]["progress"]["unit_kind"] == "chapters"

        events = app.get_task(queued["task_id"])["events"]
        progress = [
            item["details"]
            for item in events
            if item["event"] == "task_progress_updated"
        ]
        assert [item["completed_units"] for item in progress] == [0, 1]

        accepted_revision = app.manuscript_acceptance()["chapters"][0][
            "accepted_revision"
        ]
        chapter.write_text("# 第一章\n\n林岑离开钟楼。\n", encoding="utf-8")
        external = app.accept_external_manuscript(
            {"chapter_id": "ch_001", "confirm": True}
        )
        assert external["operation"]["source"] == "external_editor"
        assert external["operation"]["expected_previous_revision"] == accepted_revision

        external_task = app.reconcile_manuscript_acceptance(
            {"operation_id": external["operation"]["operation_id"]}
        )
        external_done = _wait(app, external_task["task_id"])
        assert external_done["status"] == "completed", external_done.get("error")
        assert external_done["result"]["acceptance"]["status"] == "needs_review"

        with pytest.raises(StudioError) as unconfirmed_ack:
            app.acknowledge_manuscript_acceptance(
                {
                    "operation_id": external["operation"]["operation_id"],
                    "domains": ["outline", "foreshadowing"],
                    "confirm": False,
                }
            )
        assert unconfirmed_ack.value.code == "CONFIRMATION_REQUIRED"
        acknowledged = app.acknowledge_manuscript_acceptance(
            {
                "operation_id": external["operation"]["operation_id"],
                "domains": ["outline", "foreshadowing"],
                "confirm": True,
            }
        )
        assert acknowledged["acceptance"]["status"] == "current"

        current_revision = acknowledged["acceptance"]["chapters"][0][
            "accepted_revision"
        ]
        chapter.write_text("# 第一章\n\n林岑再次进入钟楼。\n", encoding="utf-8")
        manual = app.start_manuscript_acceptance(
            {
                "chapter_id": "ch_001",
                "source": "manual",
                "expected_previous_revision": current_revision,
            }
        )
        assert manual["operation"]["source"] == "manual"
        assert manual["acceptance"]["status"] == "pending"
    finally:
        if app._task_runner is not None:
            app._task_runner.shutdown(wait=True)


def test_http_acceptance_routes_are_enveloped_and_reconcile_is_async(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    init_project(tmp_path, "demo")
    _chapter(tmp_path, "林岑仍在钟楼。")
    monkeypatch.setattr("tools.settle_backfill.analyze_existing_chapter", _analyze_existing)
    registry = ProjectRegistry(tmp_path / "registry.yaml", allow_ephemeral=True)
    server = create_server(tmp_path, port=0, project_registry=registry)
    monkeypatch.setattr(server.app, "_operation_profile", lambda *args, **kwargs: None)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    opener = build_opener(ProxyHandler({}))
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        surface = _request(opener, f"{base}/api/manuscript/acceptance")
        assert surface["data"]["status"] == "baseline_required"
        assert not ManuscriptAcceptanceService(tmp_path, "demo").state_path.exists()

        with pytest.raises(HTTPError) as rejected:
            _request(
                opener,
                f"{base}/api/manuscript/acceptance/baseline",
                method="POST",
                payload={"confirm": False},
            )
        assert rejected.value.code == 428
        error = json.loads(rejected.value.read())
        assert error["code"] == "CONFIRMATION_REQUIRED"
        assert error["recoverable"] is True

        started = _request(
            opener,
            f"{base}/api/manuscript/acceptance/baseline",
            method="POST",
            payload={"confirm": True},
        )
        operation_id = started["data"]["operation"]["operation_id"]
        queued = _request(
            opener,
            f"{base}/api/manuscript/acceptance/reconcile",
            method="POST",
            payload={"operation_id": operation_id},
        )
        task = _wait(server.app, queued["data"]["task_id"])
        assert task["status"] == "completed", task.get("error")
        assert _request(opener, f"{base}/api/manuscript/acceptance")["data"][
            "status"
        ] == "current"

        for route in (
            "/api/manuscript/acceptance/reconcile",
            "/api/manuscript/acceptance/ack",
            "/api/manuscript/acceptance/baseline",
            "/api/manuscript/acceptance/external",
        ):
            assert POST_ROUTES[route].envelope is True
        assert "/api/manuscript/acceptance/start" not in POST_ROUTES
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        if server.app._task_runner is not None:
            server.app._task_runner.shutdown(wait=True)
