from __future__ import annotations

import json
import time
import urllib.error
from pathlib import Path
from threading import Thread
from urllib.request import ProxyHandler, Request, build_opener

from tools.chapter_pipeline import _save_chapter as _save_chapter_file
from tools.cli import _save_chapter
from tools.init_project import init_project
from tools.manuscript_acceptance import ManuscriptAcceptanceService
from tools.model_profiles import ModelProfileStore, active_model_profile
from tools.studio import StudioApplication, create_server


def _wait(app: StudioApplication, task_id: str, statuses: set[str], timeout: float = 3) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = app.get_task(task_id)["task"]
        if task["status"] in statuses:
            return task
        time.sleep(0.01)
    raise AssertionError(f"task {task_id} did not reach {statuses}")


def _post_task(opener, base: str, path: str, payload: dict) -> tuple[int, dict]:
    request = Request(
        f"{base}{path}",
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-OpenWrite-Studio": "1"},
    )
    try:
        with opener.open(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _get_task_http(opener, base: str, task_id: str) -> tuple[int, dict]:
    try:
        with opener.open(f"{base}/api/tasks/{task_id}") as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _wait_http_task(
    opener, base: str, task_id: str, statuses: set[str], timeout: float = 5
) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status, payload = _get_task_http(opener, base, task_id)
        if status == 200 and payload["data"]["task"]["status"] in statuses:
            return payload["data"]["task"]
        time.sleep(0.02)
    raise AssertionError(f"task {task_id} did not reach {statuses}")


def _save_accepted_chapter(
    root: Path,
    chapter_id: str,
    title: str,
    content: str,
) -> tuple[Path, dict]:
    """Simulate a writer extension that commits prose and its derived facts."""
    path = _save_chapter_file(root, "demo", chapter_id, title, content)
    acceptance = ManuscriptAcceptanceService(root, "demo").record_precomputed(
        chapter_id,
        source="chapter_write",
        expected_previous_revision="",
        fact={},
    )
    return path, acceptance


def test_studio_runs_write_and_review_through_persistent_tasks(tmp_path: Path):
    init_project(tmp_path, "demo")

    def writer(root: Path, args: dict) -> dict:
        path = _save_chapter(root, "demo", args["chapter_id"], "第一章", "门外有人。")
        return {
            "ok": True,
            "chapter_id": args["chapter_id"],
            "title": "第一章",
            "word_count": 5,
            "draft_path": str(path),
        }

    def reviewer(root: Path, args: dict) -> dict:
        del root
        return {
            "ok": True,
            "chapter_id": args["chapter_id"],
            "passed": True,
            "score": 92,
            "issues": 0,
            "issue_details": [],
        }

    app = StudioApplication(tmp_path, writer_executor=writer, review_executor=reviewer)
    try:
        write_task = app.create_task(
            {
                "type": "chapter_write",
                "input": {"chapter_id": "ch_001", "target_words": 800},
            }
        )
        written = _wait(app, write_task["task_id"], {"completed"})
        assert written["result"]["chapter_id"] == "ch_001"

        review_task = app.create_task(
            {
                "type": "chapter_review",
                "input": {"path": "data/manuscript/arc_001/ch_001.md"},
            }
        )
        reviewed = _wait(app, review_task["task_id"], {"completed"})
        assert reviewed["result"]["score"] == 92
        surface = app.task_surface()
        assert surface["counts"]["completed"] == 2
        assert app.get_task(review_task["task_id"])["events"][-1]["event"] == "task_completed"
    finally:
        if app._task_runner is not None:
            app._task_runner.shutdown(wait=True)


def test_studio_routes_write_and_review_tasks_to_different_profiles(tmp_path: Path):
    init_project(tmp_path, "demo")
    profiles = ModelProfileStore(tmp_path / "model-settings")
    for profile_id, model in (("prose", "writer-model"), ("critic", "review-model")):
        profiles.save_profile(
            {
                "id": profile_id,
                "label": profile_id,
                "provider": "openai",
                "base_url": "https://models.example/v1",
                "model": model,
                "api_format": "chat",
                "context_tokens": 64000,
                "max_output_tokens": 4096,
            },
            api_key=f"{profile_id}-secret",
        )
    profiles.save_routes({"chapter_write": "prose", "review": "critic"})
    observed: list[tuple[str, str]] = []

    def writer(root: Path, args: dict) -> dict:
        active = active_model_profile() or {}
        observed.append(("write", str(active.get("model"))))
        path = _save_chapter(root, "demo", args["chapter_id"], "第一章", "门外有人。")
        return {
            "ok": True,
            "chapter_id": args["chapter_id"],
            "title": "第一章",
            "word_count": 5,
            "draft_path": str(path),
        }

    def reviewer(root: Path, args: dict) -> dict:
        del root
        active = active_model_profile() or {}
        observed.append(("review", str(active.get("model"))))
        return {
            "ok": True,
            "chapter_id": args["chapter_id"],
            "passed": True,
            "score": 92,
            "issues": 0,
            "issue_details": [],
        }

    app = StudioApplication(
        tmp_path,
        writer_executor=writer,
        review_executor=reviewer,
        model_profile_store=profiles,
    )
    try:
        write_task = app.create_task(
            {
                "type": "chapter_write",
                "input": {"chapter_id": "ch_001", "target_words": 800},
            }
        )
        _wait(app, write_task["task_id"], {"completed"})
        review_task = app.create_task(
            {
                "type": "chapter_review",
                "input": {"path": "data/manuscript/arc_001/ch_001.md"},
            }
        )
        _wait(app, review_task["task_id"], {"completed"})
        assert observed == [("write", "writer-model"), ("review", "review-model")]

        app.save_model_routes(
            {"routes": {"chapter_write": "critic", "review": "prose"}}
        )
        assert profiles.resolve("chapter_write")["model"] == "review-model"
        assert profiles.resolve("review")["model"] == "writer-model"
    finally:
        if app._task_runner is not None:
            app._task_runner.shutdown(wait=True)


def test_controlled_continuous_write_waits_for_confirmation_and_resumes(tmp_path: Path):
    init_project(tmp_path, "demo")

    def writer(root: Path, args: dict) -> dict:
        number = int(args["chapter_id"].split("_")[1])
        path, acceptance = _save_accepted_chapter(
            root,
            args["chapter_id"],
            f"第{number}章",
            f"第{number}章正文。",
        )
        return {
            "ok": True,
            "chapter_id": args["chapter_id"],
            "title": f"第{number}章",
            "word_count": 6,
            "draft_path": str(path),
            "acceptance": acceptance,
        }

    def reviewer(root: Path, args: dict) -> dict:
        del root
        return {
            "ok": True,
            "chapter_id": args["chapter_id"],
            "passed": True,
            "score": 90,
            "issues": 0,
            "issue_details": [],
        }

    app = StudioApplication(tmp_path, writer_executor=writer, review_executor=reviewer)
    outline = app.read_document("src/outline.md")
    app.write_document(
        outline["path"],
        """# 第一卷

## 第一幕

### 第一节

#### 第一章

开场。

#### 第二章

推进。
""",
        outline["version"],
    )
    try:
        task = app.create_task(
            {
                "type": "continuous_write",
                "input": {
                    "max_chapters": 2,
                    "minimum_review_score": 82,
                    "require_confirmation_after_each_chapter": True,
                },
            }
        )
        waiting = _wait(app, task["task_id"], {"awaiting_confirmation"})
        assert [item["chapter_id"] for item in waiting["result"]["completed_chapters"]] == [
            "ch_001"
        ]

        resumed = app.confirm_task(task["task_id"], {})
        completed = _wait(app, resumed["task_id"], {"completed"})
        assert [item["chapter_id"] for item in completed["result"]["completed_chapters"]] == [
            "ch_001",
            "ch_002",
        ]
        assert completed["result"]["stop_reason"] == "max_chapters_reached"
    finally:
        if app._task_runner is not None:
            app._task_runner.shutdown(wait=True)


def test_studio_task_http_api_persists_across_refresh(tmp_path: Path):
    init_project(tmp_path, "demo")

    def writer(root: Path, args: dict) -> dict:
        path = _save_chapter(root, "demo", args["chapter_id"], "第一章", "正文。")
        return {
            "ok": True,
            "chapter_id": args["chapter_id"],
            "title": "第一章",
            "word_count": 3,
            "draft_path": str(path),
        }

    server = create_server(tmp_path, port=0, writer_executor=writer)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    opener = build_opener(ProxyHandler({}))
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        request = Request(
            f"{base}/api/tasks",
            method="POST",
            data=json.dumps(
                {
                    "type": "chapter_write",
                    "input": {"chapter_id": "ch_001", "target_words": 800},
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json", "X-OpenWrite-Studio": "1"},
        )
        with opener.open(request) as response:
            created = json.loads(response.read())
        task_id = created["data"]["task_id"]
        _wait(server.app, task_id, {"completed"})

        with opener.open(f"{base}/api/tasks") as response:
            refreshed = json.loads(response.read())
        assert refreshed["ok"] is True
        assert refreshed["data"]["tasks"][0]["task_id"] == task_id
        with opener.open(f"{base}/api/tasks/{task_id}") as response:
            detail = json.loads(response.read())
        assert detail["data"]["events"][-1]["event"] == "task_completed"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        if server.app._task_runner is not None:
            server.app._task_runner.shutdown(wait=True)


def test_studio_task_confirm_via_http_resumes_and_rejects_non_awaiting(tmp_path: Path):
    init_project(tmp_path, "demo")

    def writer(root: Path, args: dict) -> dict:
        number = int(args["chapter_id"].split("_")[1])
        path, acceptance = _save_accepted_chapter(
            root,
            args["chapter_id"],
            f"第{number}章",
            f"第{number}章正文。",
        )
        return {
            "ok": True,
            "chapter_id": args["chapter_id"],
            "title": f"第{number}章",
            "word_count": 6,
            "draft_path": str(path),
            "acceptance": acceptance,
        }

    def reviewer(root: Path, args: dict) -> dict:
        del root
        return {
            "ok": True,
            "chapter_id": args["chapter_id"],
            "passed": True,
            "score": 90,
            "issues": 0,
            "issue_details": [],
        }

    server = create_server(tmp_path, port=0, writer_executor=writer, review_executor=reviewer)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    opener = build_opener(ProxyHandler({}))
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        outline = server.app.read_document("src/outline.md")
        server.app.write_document(
            outline["path"],
            """# 第一卷

## 第一幕

### 第一节

#### 第一章

开场。

#### 第二章

推进。
""",
            outline["version"],
        )

        status, created = _post_task(
            opener,
            base,
            "/api/tasks",
            {
                "type": "continuous_write",
                "input": {
                    "max_chapters": 2,
                    "minimum_review_score": 82,
                    "require_confirmation_after_each_chapter": True,
                },
            },
        )
        assert status == 200, created
        task_id = created["data"]["task_id"]
        waiting = _wait_http_task(opener, base, task_id, {"awaiting_confirmation"})
        # A non-benchmark task DTO never fabricates progress.
        assert waiting["progress"] is None

        # A task that is not awaiting confirmation cannot be confirmed.
        status, conflict = _post_task(opener, base, f"/api/tasks/{task_id}/retry", {})
        assert status == 409, conflict
        assert conflict["code"] == "TASK_CONFLICT"

        # Confirm resumes the run as a NEW task record over HTTP.
        status, resumed = _post_task(opener, base, f"/api/tasks/{task_id}/confirm", {})
        assert status == 200, resumed
        assert resumed["ok"] is True
        resumed_id = resumed["data"]["task_id"]
        assert resumed_id != task_id
        completed = _wait_http_task(opener, base, resumed_id, {"completed"})
        assert [item["chapter_id"] for item in completed["result"]["completed_chapters"]] == [
            "ch_001",
            "ch_002",
        ]
        assert completed["progress"] is None

        # The resumed (now completed) task is no longer confirmable.
        status, conflict = _post_task(opener, base, f"/api/tasks/{resumed_id}/confirm", {})
        assert status == 409, conflict
        assert conflict["code"] == "TASK_CONFLICT"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        if server.app._task_runner is not None:
            server.app._task_runner.shutdown(wait=True)


def test_studio_task_routes_fail_closed_on_unknown_ids(tmp_path: Path):
    init_project(tmp_path, "demo")
    server = create_server(tmp_path, port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    opener = build_opener(ProxyHandler({}))
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        # Well-formed but nonexistent ids: 404 TASK_NOT_FOUND on every verb.
        status, payload = _get_task_http(opener, base, "tsk_missing_12345678")
        assert status == 404
        assert payload["code"] == "TASK_NOT_FOUND"
        for verb in ("cancel", "retry", "confirm"):
            status, payload = _post_task(
                opener, base, f"/api/tasks/tsk_missing_12345678/{verb}", {}
            )
            assert status == 404, (verb, payload)
            assert payload["code"] == "TASK_NOT_FOUND", (verb, payload)

        # Malformed ids never reach a task handler at all: the route simply
        # does not exist (404 fail closed, no task data crosses).
        status, payload = _get_task_http(opener, base, "not-a-task")
        assert status == 404
        assert payload["code"] == "STATIC_ASSET_NOT_FOUND"
        for verb in ("cancel", "retry", "confirm"):
            status, payload = _post_task(opener, base, f"/api/tasks/not-a-task/{verb}", {})
            assert status == 404, (verb, payload)
            assert payload["code"] == "ROUTE_NOT_FOUND", (verb, payload)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        if server.app._task_runner is not None:
            server.app._task_runner.shutdown(wait=True)


def test_studio_task_error_dto_carries_code_and_recoverable_without_extras(tmp_path: Path):
    init_project(tmp_path, "demo")

    def writer(root: Path, args: dict) -> dict:
        del root, args
        raise RuntimeError("模型超时")

    server = create_server(tmp_path, port=0, writer_executor=writer)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    opener = build_opener(ProxyHandler({}))
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        status, created = _post_task(
            opener,
            base,
            "/api/tasks",
            {"type": "chapter_write", "input": {"chapter_id": "ch_001", "target_words": 10}},
        )
        assert status == 200, created
        failed = _wait_http_task(opener, base, created["data"]["task_id"], {"failed"})
        error = failed["error"]
        assert error["code"] == "TASK_FAILED"
        assert error["message"] == "模型超时"
        assert error["recoverable"] is True
        # The wire error carries only the documented fields: no stack traces,
        # environment dumps, or other secret-bearing material.
        assert set(error) <= {"code", "message", "recoverable", "failed_stage"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        if server.app._task_runner is not None:
            server.app._task_runner.shutdown(wait=True)
