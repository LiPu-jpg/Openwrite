from __future__ import annotations

import json
import os
import time
import urllib.error
from pathlib import Path
from threading import Thread
from urllib.request import ProxyHandler, Request, build_opener

import pytest
import yaml

from tools.init_project import init_project
from tools.model_profiles import ModelProfileStore
from tools.project_registry import ProjectRegistry
from tools.studio import create_server
from tools.studio_preferences import StudioModelSettingsStore
from tools.workspace_manager import (
    WorkspaceManager,
    canonicalize_workspace_root,
)

WRITE_HEADERS = {"X-OpenWrite-Studio": "1"}
DOC_PATH = "data/manuscript/arc_001/ch_001.md"


def _real(path: Path) -> Path:
    return Path(os.path.realpath(path))


def _context_headers(
    root: Path,
    *,
    workspace_id: str = "ws-test",
    session_id: str = "sess-test",
    epoch: int | None = None,
) -> dict[str, str]:
    headers = {
        "X-OpenWrite-Workspace-Root": str(root),
        "X-OpenWrite-Workspace-Id": workspace_id,
        "X-OpenWrite-Session-Id": session_id,
    }
    if epoch is not None:
        headers["X-OpenWrite-Context-Epoch"] = str(epoch)
    return headers


def _writer(root: Path, args: dict) -> dict:
    from tools.cli import _save_chapter

    path = _save_chapter(root, "demo", args["chapter_id"], "第一章", "正文。")
    return {
        "ok": True,
        "chapter_id": args["chapter_id"],
        "title": "第一章",
        "word_count": 3,
        "draft_path": str(path),
    }


def _start_server(launch_root: Path, state_dir: Path, *, writer=None):
    registry_path = state_dir / "recent.yaml"
    server = create_server(
        launch_root,
        port=0,
        writer_executor=writer,
        model_settings_store=StudioModelSettingsStore(state_dir / "prefs"),
        model_profile_store=ModelProfileStore(state_dir / "profiles"),
        project_registry=ProjectRegistry(registry_path, allow_ephemeral=True),
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    return server, thread, base, registry_path


def _stop_server(server, thread: Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)
    manager = getattr(server, "workspace_manager", None)
    if manager is not None:
        manager.shutdown(wait=True)
    else:
        runner = getattr(server.app, "_task_runner", None)
        if runner is not None:
            runner.shutdown(wait=True)


def _request(
    opener,
    base: str,
    method: str,
    path: str,
    payload: dict | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict]:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request_headers = dict(headers or {})
    if data is not None:
        request_headers.setdefault("Content-Type", "application/json")
    request = Request(f"{base}{path}", method=method, data=data, headers=request_headers)
    try:
        with opener.open(request) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def _put_document(opener, base: str, root: Path, content: str, path: str = DOC_PATH):
    headers = {**WRITE_HEADERS, **_context_headers(root)}
    return _request(
        opener, base, "PUT", "/api/document", {"path": path, "content": content}, headers
    )


def _author_workbench_project(root: Path, marker: str) -> None:
    init_project(root, "demo")
    novel = root / "data" / "novels" / "demo"
    (novel / "src" / "outline.md").write_text(
        "# 第一卷\n\n## 第一幕\n\n### 第一节\n\n"
        "#### 第1章：ch_001\n\n起点。\n\n"
        "# 第二卷\n\n## 第二幕\n\n### 第二节\n\n"
        "#### 第2章：ch_002\n\n终点。\n",
        encoding="utf-8",
    )
    for arc_id, chapter_id in (("arc_001", "ch_001"), ("arc_002", "ch_002")):
        path = novel / "data" / "manuscript" / arc_id / f"{chapter_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {chapter_id}\n\n{marker}-{chapter_id}\n", encoding="utf-8")


def _wait_task(
    opener,
    base: str,
    task_id: str,
    headers: dict[str, str],
    *,
    timeout: float = 5.0,
) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status, payload = _request(opener, base, "GET", f"/api/tasks/{task_id}", headers=headers)
        if status == 200 and payload["data"]["task"]["status"] in {
            "completed",
            "failed",
            "cancelled",
        }:
            return payload["data"]["task"]
        time.sleep(0.02)
    raise AssertionError(f"task {task_id} did not finish")


@pytest.fixture()
def opener():
    return build_opener(ProxyHandler({}))


def test_canonicalize_workspace_root_unit(tmp_path: Path):
    assert canonicalize_workspace_root(str(tmp_path)) == _real(tmp_path)
    with pytest.raises(Exception) as not_absolute:
        canonicalize_workspace_root("relative/dir")
    assert not_absolute.value.code == "WORKSPACE_ROOT_INVALID"
    assert not_absolute.value.details["reason"] == "not_absolute"
    with pytest.raises(Exception) as traversal:
        canonicalize_workspace_root(str(tmp_path / "a" / ".." / "b"))
    assert traversal.value.details["reason"] == "traversal"
    with pytest.raises(Exception) as missing:
        canonicalize_workspace_root(str(tmp_path / "missing"))
    assert missing.value.details["reason"] == "not_found"
    file_path = tmp_path / "file.txt"
    file_path.write_text("x", encoding="utf-8")
    with pytest.raises(Exception) as not_directory:
        canonicalize_workspace_root(str(file_path))
    assert not_directory.value.details["reason"] == "not_directory"
    with pytest.raises(Exception) as empty:
        canonicalize_workspace_root("")
    assert empty.value.code == "WORKSPACE_CONTEXT_MISSING"


def test_ab_roots_are_isolated(tmp_path: Path, opener):
    launch = tmp_path / "server"
    launch.mkdir()
    root_a = tmp_path / "alpha"
    root_b = tmp_path / "beta"
    root_a.mkdir()
    init_project(root_b, "demo")
    server, thread, base, _registry = _start_server(launch, tmp_path / "state", writer=_writer)
    try:
        # Initialize A through the context-mode init route.
        status, payload = _request(
            opener,
            base,
            "POST",
            "/api/project/init",
            {"project_path": str(root_a), "novel_id": "demo", "title": "甲"},
            {**WRITE_HEADERS, **_context_headers(root_a)},
        )
        assert status == 200, payload

        # Same chapter path, different content per root.
        status, _ = _put_document(opener, base, root_a, "甲的章节内容")
        assert status == 200
        status, _ = _put_document(opener, base, root_b, "乙的章节内容")
        assert status == 200

        status, doc_a = _request(
            opener,
            base,
            "GET",
            f"/api/document?path={DOC_PATH}",
            headers=_context_headers(root_a),
        )
        status_b, doc_b = _request(
            opener,
            base,
            "GET",
            f"/api/document?path={DOC_PATH}",
            headers=_context_headers(root_b),
        )
        assert status == 200 and status_b == 200
        assert doc_a["content"] == "甲的章节内容"
        assert doc_b["content"] == "乙的章节内容"

        _, ws_a = _request(opener, base, "GET", "/api/workspace", headers=_context_headers(root_a))
        _, ws_b = _request(opener, base, "GET", "/api/workspace", headers=_context_headers(root_b))
        assert ws_a["project"]["root"] == str(_real(root_a))
        assert ws_b["project"]["root"] == str(_real(root_b))

        # Create a task in A; B must not see it.
        status, created = _request(
            opener,
            base,
            "POST",
            "/api/tasks",
            {"type": "chapter_write", "input": {"chapter_id": "ch_002", "target_words": 10}},
            {**WRITE_HEADERS, **_context_headers(root_a)},
        )
        assert status == 200, created
        task_id = created["data"]["task_id"]
        _wait_task(opener, base, task_id, _context_headers(root_a))

        _, tasks_a = _request(opener, base, "GET", "/api/tasks", headers=_context_headers(root_a))
        _, tasks_b = _request(opener, base, "GET", "/api/tasks", headers=_context_headers(root_b))
        assert [t["task_id"] for t in tasks_a["data"]["tasks"]] == [task_id]
        assert tasks_b["data"]["tasks"] == []

        status, _ = _request(
            opener, base, "GET", f"/api/tasks/{task_id}", headers=_context_headers(root_b)
        )
        assert status == 404
    finally:
        _stop_server(server, thread)


def test_concurrent_contexts_do_not_cross_roots(tmp_path: Path, opener):
    launch = tmp_path / "server"
    launch.mkdir()
    root_a = tmp_path / "alpha"
    root_b = tmp_path / "beta"
    init_project(root_a, "demo")
    init_project(root_b, "demo")
    server, thread, base, _registry = _start_server(launch, tmp_path / "state")
    errors: list[str] = []

    def hammer(root: Path, tag: str) -> None:
        local = build_opener(ProxyHandler({}))
        headers = _context_headers(root)
        for index in range(20):
            status, workspace = _request(local, base, "GET", "/api/workspace", headers=headers)
            if status != 200 or workspace["project"]["root"] != str(_real(root)):
                errors.append(f"{tag}: workspace root drift {status} {workspace}")
                return
            content = f"{tag} 内容 {index}"
            status, _ = _request(
                local,
                base,
                "PUT",
                "/api/document",
                {"path": DOC_PATH, "content": content},
                {**WRITE_HEADERS, **headers},
            )
            if status != 200:
                errors.append(f"{tag}: put failed {status}")
                return
            status, doc = _request(
                local, base, "GET", f"/api/document?path={DOC_PATH}", headers=headers
            )
            if status != 200 or doc["content"] != content:
                errors.append(f"{tag}: document crossed roots {status}")
                return

    threads = [
        Thread(target=hammer, args=(root_a, "甲")),
        Thread(target=hammer, args=(root_b, "乙")),
    ]
    try:
        for item in threads:
            item.start()
        for item in threads:
            item.join(timeout=60)
        assert errors == []
        assert server.app.project_root == _real(launch)
        manager = server.workspace_manager
        assert manager._contexts[_real(root_a)].project_root == _real(root_a)
        assert manager._contexts[_real(root_b)].project_root == _real(root_b)
    finally:
        _stop_server(server, thread)


def test_context_fail_closed_matrix(tmp_path: Path, opener):
    launch = tmp_path / "server"
    launch.mkdir()
    initialized = tmp_path / "initialized"
    init_project(initialized, "demo")
    uninitialized = tmp_path / "uninitialized"
    uninitialized.mkdir()
    server, thread, base, _registry = _start_server(launch, tmp_path / "state")
    try:
        # Relative path.
        status, payload = _request(
            opener,
            base,
            "GET",
            "/api/workspace",
            headers={"X-OpenWrite-Workspace-Root": "relative/dir"},
        )
        assert status == 400
        assert payload["code"] == "WORKSPACE_ROOT_INVALID"
        assert payload["details"]["reason"] == "not_absolute"

        # Traversal segment.
        status, payload = _request(
            opener,
            base,
            "GET",
            "/api/workspace",
            headers={"X-OpenWrite-Workspace-Root": str(tmp_path / "a" / ".." / "b")},
        )
        assert status == 400
        assert payload["details"]["reason"] == "traversal"

        # Missing directory.
        status, payload = _request(
            opener,
            base,
            "GET",
            "/api/workspace",
            headers={"X-OpenWrite-Workspace-Root": str(tmp_path / "missing")},
        )
        assert status == 400
        assert payload["details"]["reason"] == "not_found"

        # File instead of directory.
        file_path = tmp_path / "file.txt"
        file_path.write_text("x", encoding="utf-8")
        status, payload = _request(
            opener,
            base,
            "GET",
            "/api/workspace",
            headers={"X-OpenWrite-Workspace-Root": str(file_path)},
        )
        assert status == 400
        assert payload["details"]["reason"] == "not_directory"

        # Forged framework root.
        fake = tmp_path / "fakefw"
        (fake / "tools").mkdir(parents=True)
        (fake / "pyproject.toml").write_text('[project]\nname = "openwrite"\n', encoding="utf-8")
        (fake / "tools" / "studio.py").write_text("", encoding="utf-8")
        status, payload = _request(
            opener, base, "GET", "/api/workspace", headers=_context_headers(fake)
        )
        assert status == 403
        assert payload["code"] == "WORKSPACE_FRAMEWORK_ROOT"

        # Symlink to an uninitialized directory canonicalizes to its target.
        real_dir = tmp_path / "real-uninit"
        real_dir.mkdir()
        link = tmp_path / "link-uninit"
        link.symlink_to(real_dir)
        status, payload = _request(
            opener, base, "GET", "/api/workspace/context", headers=_context_headers(link)
        )
        assert status == 200
        assert payload["workspace_root"] == str(_real(real_dir))
        assert payload["initialized"] is False
        status, payload = _request(
            opener, base, "GET", "/api/workspace", headers=_context_headers(link)
        )
        assert status == 428
        assert payload["code"] == "WORKSPACE_NOT_INITIALIZED"

        # Uninitialized root hitting a business route.
        status, payload = _request(
            opener, base, "GET", "/api/workspace", headers=_context_headers(uninitialized)
        )
        assert status == 428
        assert payload["code"] == "WORKSPACE_NOT_INITIALIZED"

        # Nested root inside an activated context root.
        status, _ = _request(
            opener,
            base,
            "GET",
            "/api/workspace/context",
            headers=_context_headers(initialized),
        )
        assert status == 200
        nested = initialized / "sub"
        nested.mkdir()
        status, payload = _request(
            opener, base, "GET", "/api/workspace/context", headers=_context_headers(nested)
        )
        assert status == 400
        assert payload["code"] == "WORKSPACE_ROOT_INVALID"
        assert payload["details"]["reason"] == "nested"

        # The reverse order is unsafe too: activating a parent after a child
        # must not create overlapping context applications.
        parent = tmp_path / "child-first-parent"
        parent.mkdir()
        child = parent / "child-first"
        child.mkdir()
        init_project(child, "demo")
        init_project(parent, "demo")
        status, _ = _request(
            opener,
            base,
            "GET",
            "/api/workspace/context",
            headers=_context_headers(child),
        )
        assert status == 200
        status, payload = _request(
            opener,
            base,
            "GET",
            "/api/workspace/context",
            headers=_context_headers(parent),
        )
        assert status == 400
        assert payload["code"] == "WORKSPACE_ROOT_INVALID"
        assert payload["details"]["reason"] == "nested"

        # Context mode forbids open/delete.
        for route in ("/api/project/open", "/api/project/delete"):
            status, payload = _request(
                opener,
                base,
                "POST",
                route,
                {"project_path": str(initialized)},
                {**WRITE_HEADERS, **_context_headers(initialized)},
            )
            assert status == 409, payload
            assert payload["code"] == "WORKSPACE_SWITCH_FORBIDDEN"

        # Init payload path must equal the context root.
        status, payload = _request(
            opener,
            base,
            "POST",
            "/api/project/init",
            {"project_path": str(initialized), "novel_id": "demo", "title": "错位"},
            {**WRITE_HEADERS, **_context_headers(uninitialized)},
        )
        assert status == 409
        assert payload["code"] == "WORKSPACE_CONTEXT_MISMATCH"

        # Init payload must be absolute in context mode.
        status, payload = _request(
            opener,
            base,
            "POST",
            "/api/project/init",
            {"project_path": "relative/dir", "novel_id": "demo", "title": "相对"},
            {**WRITE_HEADERS, **_context_headers(uninitialized)},
        )
        assert status == 400
        assert payload["code"] == "WORKSPACE_ROOT_INVALID"
    finally:
        _stop_server(server, thread)


def _task_snapshot(root: Path, task_id: str) -> dict:
    path = (
        root / "data" / "novels" / "demo" / "data" / "workflows" / "tasks" / f"task_{task_id}.yaml"
    )
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_task_records_are_pinned_to_their_root(tmp_path: Path, opener):
    launch = tmp_path / "server"
    launch.mkdir()
    root_a = tmp_path / "alpha"
    root_b = tmp_path / "beta"
    init_project(root_a, "demo")
    init_project(root_b, "demo")
    headers_a = _context_headers(root_a, workspace_id="ws-a", session_id="sess-a", epoch=7)
    server, thread, base, _registry = _start_server(launch, tmp_path / "state", writer=_writer)
    try:
        status, created = _request(
            opener,
            base,
            "POST",
            "/api/tasks",
            {"type": "chapter_write", "input": {"chapter_id": "ch_001", "target_words": 10}},
            {**WRITE_HEADERS, **headers_a},
        )
        assert status == 200, created
        task_id = created["data"]["task_id"]
        finished = _wait_task(opener, base, task_id, headers_a)
        assert finished["status"] == "completed"

        record = _task_snapshot(_real(root_a), task_id)
        assert record["workspace_root"] == str(_real(root_a))
        assert record["workspace_id"] == "ws-a"
        assert record["session_id"] == "sess-a"
        assert record["context_epoch"] == 7

        status, _ = _request(
            opener, base, "GET", f"/api/tasks/{task_id}", headers=_context_headers(root_b)
        )
        assert status == 404
    finally:
        _stop_server(server, thread)

    # Tamper with the record as if it belonged to B, then "restart" the server.
    snapshot_path = (
        _real(root_a)
        / "data"
        / "novels"
        / "demo"
        / "data"
        / "workflows"
        / "tasks"
        / f"task_{task_id}.yaml"
    )
    tampered = yaml.safe_load(snapshot_path.read_text(encoding="utf-8"))
    tampered["status"] = "running"
    tampered["workspace_root"] = str(_real(root_b))
    snapshot_path.write_text(
        yaml.safe_dump(tampered, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    server2, thread2, base2, _registry2 = _start_server(launch, tmp_path / "state2", writer=_writer)
    try:
        # First A-context request builds the app and runs recovery.
        status, _ = _request(opener, base2, "GET", "/api/tasks", headers=headers_a)
        assert status == 200
        record = _task_snapshot(_real(root_a), task_id)
        assert record["status"] == "failed"
        assert record["error"]["code"] == "WORKSPACE_CONTEXT_MISMATCH"

        # Reads of a mismatched record are rejected with the stable code.
        status, payload = _request(opener, base2, "GET", f"/api/tasks/{task_id}", headers=headers_a)
        assert status == 409
        assert payload["code"] == "WORKSPACE_CONTEXT_MISMATCH"

        # Recovery never leaks into B.
        status, _ = _request(
            opener, base2, "GET", f"/api/tasks/{task_id}", headers=_context_headers(root_b)
        )
        assert status == 404
        _, tasks_b = _request(opener, base2, "GET", "/api/tasks", headers=_context_headers(root_b))
        assert tasks_b["data"]["tasks"] == []

        # Retry of a mismatched record is rejected.
        status, payload = _request(
            opener,
            base2,
            "POST",
            f"/api/tasks/{task_id}/retry",
            {},
            {**WRITE_HEADERS, **headers_a},
        )
        assert status == 409
        assert payload["code"] == "WORKSPACE_CONTEXT_MISMATCH"

        # Cancel and confirm of a mismatched record are rejected the same way.
        for verb in ("cancel", "confirm"):
            status, payload = _request(
                opener,
                base2,
                "POST",
                f"/api/tasks/{task_id}/{verb}",
                {},
                {**WRITE_HEADERS, **headers_a},
            )
            assert status == 409, (verb, payload)
            assert payload["code"] == "WORKSPACE_CONTEXT_MISMATCH", (verb, payload)
    finally:
        _stop_server(server2, thread2)


def test_task_mutation_routes_reject_foreign_roots(tmp_path: Path, opener):
    """A task that only exists under root A is invisible to root B's verbs."""
    launch = tmp_path / "server"
    launch.mkdir()
    root_a = tmp_path / "alpha"
    root_b = tmp_path / "beta"
    init_project(root_a, "demo")
    init_project(root_b, "demo")
    headers_a = _context_headers(root_a)
    headers_b = {**WRITE_HEADERS, **_context_headers(root_b)}
    server, thread, base, _registry = _start_server(launch, tmp_path / "state", writer=_writer)
    try:
        status, created = _request(
            opener,
            base,
            "POST",
            "/api/tasks",
            {"type": "chapter_write", "input": {"chapter_id": "ch_001", "target_words": 10}},
            {**WRITE_HEADERS, **headers_a},
        )
        assert status == 200, created
        task_id = created["data"]["task_id"]
        _wait_task(opener, base, task_id, headers_a)

        for verb in ("cancel", "retry", "confirm"):
            status, payload = _request(
                opener,
                base,
                "POST",
                f"/api/tasks/{task_id}/{verb}",
                {},
                headers_b,
            )
            assert status == 404, (verb, payload)
            assert payload["code"] == "TASK_NOT_FOUND", (verb, payload)
    finally:
        _stop_server(server, thread)


def test_legacy_mode_unchanged_and_registry_stays_clean(tmp_path: Path, opener):
    launch = tmp_path / "server"
    init_project(launch, "demo")
    root_a = tmp_path / "alpha"
    root_b = tmp_path / "beta"
    init_project(root_a, "demo")
    init_project(root_b, "demo")
    server, thread, base, registry_path = _start_server(launch, tmp_path / "state")
    try:
        status, workspace = _request(opener, base, "GET", "/api/workspace")
        assert status == 200
        assert workspace["project"]["root"] == str(_real(launch))

        status, listing = _request(opener, base, "GET", "/api/project/list")
        assert status == 200
        assert any(item["path"] == str(_real(launch)) for item in listing)

        # Exercise context roots, then confirm they never touch the registry.
        status, _ = _put_document(opener, base, root_a, "甲的内容")
        assert status == 200
        status, _ = _put_document(opener, base, root_b, "乙的内容")
        assert status == 200
        raw = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
        remembered = {item.get("path") for item in raw.get("projects", [])}
        assert str(_real(root_a)) not in remembered
        assert str(_real(root_b)) not in remembered

        # Legacy open still switches the default app.
        status, payload = _request(
            opener,
            base,
            "POST",
            "/api/project/open",
            {"project_path": str(root_b)},
            WRITE_HEADERS,
        )
        assert status == 200, payload
        status, workspace = _request(opener, base, "GET", "/api/workspace")
        assert status == 200
        assert workspace["project"]["root"] == str(_real(root_b))
    finally:
        _stop_server(server, thread)


def test_legacy_open_cannot_rebind_launch_root_context(tmp_path: Path, opener):
    """The default legacy app must never be reused for a dsh context root."""
    launch = tmp_path / "launch"
    root_b = tmp_path / "beta"
    init_project(launch, "demo")
    init_project(root_b, "demo")
    server, thread, base, _registry = _start_server(launch, tmp_path / "state")
    try:
        launch_root = _real(launch)
        context_headers = _context_headers(launch_root, workspace_id="ws-launch")

        # Materialize the context app while launch_root still points at A.
        status, payload = _request(
            opener, base, "GET", "/api/workspace", headers=context_headers
        )
        assert status == 200, payload
        assert payload["project"]["root"] == str(launch_root)
        manager = server.workspace_manager
        context_app = manager._context_apps[launch_root]
        assert context_app is not server.app

        # A legacy client is still allowed to switch its own default app.
        status, payload = _request(
            opener,
            base,
            "POST",
            "/api/project/open",
            {"project_path": str(root_b)},
            WRITE_HEADERS,
        )
        assert status == 200, payload
        assert server.app.project_root == _real(root_b)

        # The dsh context rooted at launch must remain on launch, not follow
        # the mutable legacy app's project switch.
        status, payload = _request(
            opener, base, "GET", "/api/workspace", headers=context_headers
        )
        assert status == 200, payload
        assert payload["project"]["root"] == str(launch_root)
        assert manager._context_apps[launch_root] is context_app
    finally:
        _stop_server(server, thread)


def test_context_epoch_tracks_writes_per_root(tmp_path: Path, opener):
    launch = tmp_path / "server"
    launch.mkdir()
    root_a = tmp_path / "alpha"
    root_b = tmp_path / "beta"
    root_c = tmp_path / "gamma"
    init_project(root_a, "demo")
    init_project(root_b, "demo")
    root_c.mkdir()
    server, thread, base, _registry = _start_server(launch, tmp_path / "state")
    try:
        _, before_a = _request(
            opener, base, "GET", "/api/workspace/context", headers=_context_headers(root_a)
        )
        _, before_b = _request(
            opener, base, "GET", "/api/workspace/context", headers=_context_headers(root_b)
        )
        status, _ = _put_document(opener, base, root_a, "甲写入")
        assert status == 200
        _, after_a = _request(
            opener, base, "GET", "/api/workspace/context", headers=_context_headers(root_a)
        )
        _, after_b = _request(
            opener, base, "GET", "/api/workspace/context", headers=_context_headers(root_b)
        )
        assert after_a["context_epoch"] > before_a["context_epoch"]
        assert after_b["context_epoch"] == before_b["context_epoch"]

        # A successful init bumps the fresh root's epoch to at least 1.
        status, _ = _request(
            opener,
            base,
            "POST",
            "/api/project/init",
            {"project_path": str(root_c), "novel_id": "demo", "title": "丙"},
            {**WRITE_HEADERS, **_context_headers(root_c)},
        )
        assert status == 200
        _, described_c = _request(
            opener, base, "GET", "/api/workspace/context", headers=_context_headers(root_c)
        )
        assert described_c["context_epoch"] >= 1
    finally:
        _stop_server(server, thread)


def test_workspace_context_diagnostics(tmp_path: Path, opener):
    launch = tmp_path / "server"
    init_project(launch, "demo")
    root_a = tmp_path / "alpha"
    init_project(root_a, "demo")
    server, thread, base, _registry = _start_server(launch, tmp_path / "state")
    try:
        status, payload = _request(
            opener,
            base,
            "GET",
            "/api/workspace/context",
            headers=_context_headers(root_a, workspace_id="ws-a"),
        )
        assert status == 200
        assert payload["mode"] == "workspace"
        assert payload["workspace_id"] == "ws-a"
        assert payload["workspace_root"] == str(_real(root_a))
        assert payload["initialized"] is True
        assert payload["novel_id"] == "demo"
        assert isinstance(payload["context_epoch"], int)

        status, payload = _request(opener, base, "GET", "/api/workspace/context")
        assert status == 200
        assert payload["mode"] == "legacy"
        assert payload["workspace_root"] == str(_real(launch))
        assert payload["initialized"] is True
        assert payload["novel_id"] == "demo"
    finally:
        _stop_server(server, thread)


def test_manager_epoch_and_request_context_unit(tmp_path: Path):
    manager = WorkspaceManager(tmp_path, {})
    root = _real(tmp_path)
    assert manager.epoch(root) == 1
    assert manager.bump_epoch(root) == 2
    assert manager.epoch(root) == 2
    other = _real(tmp_path / "other") if (tmp_path / "other").exists() else tmp_path / "other"
    assert manager.epoch(other) == 1
    assert manager.current_request_context() is None
    context = manager.parse_context(
        {
            "X-OpenWrite-Workspace-Root": str(tmp_path),
            "X-OpenWrite-Workspace-Id": "ws",
            "X-OpenWrite-Session-Id": "sess",
            "X-OpenWrite-Context-Epoch": "3",
            "X-OpenWrite-Tool-Call-Id": "call_1",
            "X-OpenWrite-Root-Call-Id": "root_1",
            "X-OpenWrite-Tool-Name": "novel_doc_write",
        }
    )
    assert context is not None
    assert context.root == root
    assert context.workspace_id == "ws"
    assert context.session_id == "sess"
    assert context.context_epoch == 3
    assert context.tool_call_id == "call_1"
    assert context.root_call_id == "root_1"
    assert context.tool_name == "novel_doc_write"
    manager.set_request_context(context)
    assert manager.current_request_context() == context
    manager.clear_request_context()
    assert manager.current_request_context() is None
    assert manager.parse_context({}) is None


def test_task_transitions_bump_context_epoch_in_context_mode(tmp_path: Path):
    launch = tmp_path / "server"
    launch.mkdir()
    root_a = tmp_path / "alpha"
    init_project(root_a, "demo")
    manager = WorkspaceManager(launch, {})
    context = manager.parse_context({"X-OpenWrite-Workspace-Root": str(root_a)})
    assert context is not None
    app = manager.app_for(context)
    try:
        assert app._task_change_listener is not None
        store = app._tasks().store
        before = manager.epoch(context.root)

        # Reads never bump the epoch.
        store.list()
        assert manager.epoch(context.root) == before

        task = store.create("research", {"query": "示例"})
        store.transition(task["task_id"], status="running", phase="reading", event="task_started")
        store.transition(
            task["task_id"],
            status="completed",
            phase="complete",
            updates={"result": {"report_id": "rep_1"}},
            event="task_completed",
        )
        after = manager.epoch(context.root)
        assert after >= before + 3
    finally:
        manager.shutdown(wait=True)


def test_legacy_mode_has_no_task_epoch_listener(tmp_path: Path):
    from tools.studio_application import StudioApplication

    init_project(tmp_path, "demo")
    app = StudioApplication(tmp_path)
    try:
        assert app._task_change_listener is None
        assert app._tasks().store.on_change is None
    finally:
        if app._task_runner is not None:
            app._task_runner.shutdown(wait=True)


def test_author_workbench_routes_are_canonical_root_isolated(tmp_path: Path):
    root_a = tmp_path / "workspaces" / "a"
    root_b = tmp_path / "workspaces" / "b"
    _author_workbench_project(root_a, "ONLY-A")
    _author_workbench_project(root_b, "ONLY-B")
    server, thread, base, _ = _start_server(
        tmp_path / "launch", tmp_path / "state"
    )
    opener = build_opener(ProxyHandler({}))
    try:
        status_a, envelope_a = _request(
            opener,
            base,
            "GET",
            "/api/reading-order",
            headers=_context_headers(root_a, workspace_id="ws-a"),
        )
        status_b, envelope_b = _request(
            opener,
            base,
            "GET",
            "/api/reading-order",
            headers=_context_headers(root_b, workspace_id="ws-b"),
        )
        assert status_a == status_b == 200
        order_a = envelope_a["data"]
        order_b = envelope_b["data"]
        assert order_a["novel_id"] == order_b["novel_id"] == "demo"
        # Restored/copy workspaces intentionally preserve logical identity;
        # their content revisions and mutations remain root-local.
        assert order_a["documents"][0]["document_id"] == order_b["documents"][0][
            "document_id"
        ]
        assert order_a["documents"][0]["revision"] != order_b["documents"][0][
            "revision"
        ]

        document_a = order_a["documents"][0]
        brief_status, brief_envelope = _request(
            opener,
            base,
            "GET",
            "/api/chapters/ch_001/work-brief?document_id="
            + document_a["document_id"],
            headers=_context_headers(root_a, workspace_id="ws-a"),
        )
        assert brief_status == 200
        brief = brief_envelope["data"]
        assert brief["document_id"] == document_a["document_id"]
        assert brief["manuscript"]["current_revision"] == document_a["revision"]

        move_status, move_envelope = _request(
            opener,
            base,
            "POST",
            "/api/reading-order/move",
            {
                "document_id": document_a["document_id"],
                "target_volume_id": order_a["volumes"][1]["volume_id"],
                "target_index": 1,
                "expected_revision": order_a["revision"],
            },
            {
                **WRITE_HEADERS,
                **_context_headers(root_a, workspace_id="ws-a"),
            },
        )
        assert move_status == 200
        moved = move_envelope["data"]["reading_order"]
        moved_a = next(
            item
            for item in moved["documents"]
            if item["document_id"] == document_a["document_id"]
        )
        assert moved_a["path"] == "data/manuscript/arc_002/ch_001.md"
        assert (
            root_b
            / "data"
            / "novels"
            / "demo"
            / "data"
            / "manuscript"
            / "arc_001"
            / "ch_001.md"
        ).read_text(encoding="utf-8").endswith("ONLY-B-ch_001\n")

        conflict_status, conflict = _request(
            opener,
            base,
            "POST",
            "/api/reading-order/move",
            {
                "document_id": document_a["document_id"],
                "target_volume_id": order_a["volumes"][0]["volume_id"],
                "target_index": 0,
                "expected_revision": order_a["revision"],
            },
            {
                **WRITE_HEADERS,
                **_context_headers(root_a, workspace_id="ws-a"),
            },
        )
        assert conflict_status == 409
        assert conflict["code"] == "READING_ORDER_CONFLICT"
    finally:
        _stop_server(server, thread)


def test_scene_routes_are_revision_bound_and_canonical_root_isolated(tmp_path: Path):
    root_a = tmp_path / "workspaces" / "scene-a"
    root_b = tmp_path / "workspaces" / "scene-b"
    _author_workbench_project(root_a, "ONLY-A")
    _author_workbench_project(root_b, "ONLY-B")
    chapter_a = (
        root_a
        / "data"
        / "novels"
        / "demo"
        / "data"
        / "manuscript"
        / "arc_001"
        / "ch_001.md"
    )
    chapter_a.write_text(
        "# ch_001\n\n## 场景一：出发\n\nONLY-A-ONE\n\n"
        "## 场景二：转折\n\nONLY-A-TWO\n",
        encoding="utf-8",
    )
    chapter_b_before = (
        root_b
        / "data"
        / "novels"
        / "demo"
        / "data"
        / "manuscript"
        / "arc_001"
        / "ch_001.md"
    ).read_bytes()
    server, thread, base, _ = _start_server(tmp_path / "launch", tmp_path / "state")
    opener = build_opener(ProxyHandler({}))
    headers_a = _context_headers(root_a, workspace_id="ws-scene-a")
    headers_b = _context_headers(root_b, workspace_id="ws-scene-b")
    write_a = {**WRITE_HEADERS, **headers_a}
    write_b = {**WRITE_HEADERS, **headers_b}
    try:
        status_a, absent_a = _request(opener, base, "GET", "/api/scenes", headers=headers_a)
        status_b, absent_b = _request(opener, base, "GET", "/api/scenes", headers=headers_b)
        assert status_a == status_b == 200
        assert absent_a["data"]["status"] == absent_b["data"]["status"] == "absent"

        preview_status, preview_envelope = _request(
            opener,
            base,
            "GET",
            "/api/scenes/migration-preview",
            headers=headers_a,
        )
        assert preview_status == 200
        preview = preview_envelope["data"]
        assert preview["schema_version"] == "openwrite.scene-migration-preview.v1"
        assert len(preview["plan"][0]["scenes"]) == 2

        apply_status, applied_envelope = _request(
            opener,
            base,
            "POST",
            "/api/scenes/migration/apply",
            {
                "expected_preview_revision": preview["preview_revision"],
                "confirm": True,
            },
            write_a,
        )
        assert apply_status == 200
        applied = applied_envelope["data"]
        surface = applied["scene_structure"]
        assert surface["status"] == "current"
        assert len(surface["scenes"]) == 3

        # The same endpoint in B remains root-local and read-only until B is migrated.
        b_status, b_surface = _request(opener, base, "GET", "/api/scenes", headers=headers_b)
        assert b_status == 200
        assert b_surface["data"]["status"] == "absent"
        assert (
            root_b
            / "data"
            / "novels"
            / "demo"
            / "data"
            / "manuscript"
            / "arc_001"
            / "ch_001.md"
        ).read_bytes() == chapter_b_before

        scene = surface["scenes"][0]
        metadata_status, metadata_envelope = _request(
            opener,
            base,
            "POST",
            "/api/scenes/metadata",
            {
                "scene_id": scene["scene_id"],
                "expected_revision": surface["revision"],
                "story_time_sort_key": "0010",
                "story_time_label": "十年前",
                "characters": ["林岚"],
                "locations": ["车站"],
                "events": ["出发"],
            },
            write_a,
        )
        assert metadata_status == 200
        metadata = metadata_envelope["data"]["scene_structure"]
        changed = next(item for item in metadata["scenes"] if item["scene_id"] == scene["scene_id"])
        assert changed["story_time"] == {"sort_key": "0010", "label": "十年前"}

        chapter_status, chapter_envelope = _request(
            opener,
            base,
            "GET",
            "/api/chapters/ch_001/scenes",
            headers=headers_a,
        )
        assert chapter_status == 200
        assert len(chapter_envelope["data"]["scenes"]) == 2

        source = next(item for item in metadata["chapters"] if item["chapter_id"] == "ch_001")
        target = next(item for item in metadata["chapters"] if item["chapter_id"] == "ch_002")
        moving = next(
            item
            for item in metadata["scenes"]
            if item["chapter"]["chapter_id"] == "ch_001" and item["scene_id"] != scene["scene_id"]
        )
        move_status, move_envelope = _request(
            opener,
            base,
            "POST",
            "/api/scenes/move",
            {
                "scene_id": moving["scene_id"],
                "target_chapter_id": "ch_002",
                "target_index": 0,
                "expected_revision": metadata["revision"],
                "expected_source_revision": source["revision"],
                "expected_target_revision": target["revision"],
            },
            write_a,
        )
        assert move_status == 200
        moved = move_envelope["data"]["scene_structure"]
        assert next(
            item for item in moved["scenes"] if item["scene_id"] == moving["scene_id"]
        )["chapter"]["chapter_id"] == "ch_002"

        conflict_status, conflict = _request(
            opener,
            base,
            "POST",
            "/api/scenes/metadata",
            {
                "scene_id": scene["scene_id"],
                "expected_revision": surface["revision"],
                "title": "过期标题",
            },
            write_a,
        )
        assert conflict_status == 409
        assert conflict["code"] == "SCENE_STRUCTURE_CONFLICT"

        # B can migrate and immediately roll back its own sidecar without touching A.
        _, preview_b_envelope = _request(
            opener, base, "GET", "/api/scenes/migration-preview", headers=headers_b
        )
        apply_b_status, apply_b_envelope = _request(
            opener,
            base,
            "POST",
            "/api/scenes/migration/apply",
            {
                "expected_preview_revision": preview_b_envelope["data"]["preview_revision"],
                "confirm": True,
            },
            write_b,
        )
        assert apply_b_status == 200
        applied_b = apply_b_envelope["data"]
        rollback_status, rollback_envelope = _request(
            opener,
            base,
            "POST",
            "/api/scenes/migration/rollback",
            {
                "migration_id": applied_b["migration_id"],
                "expected_revision": applied_b["scene_structure"]["revision"],
            },
            write_b,
        )
        assert rollback_status == 200
        assert rollback_envelope["data"]["scene_structure"]["status"] == "absent"
    finally:
        _stop_server(server, thread)
