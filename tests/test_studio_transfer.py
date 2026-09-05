from __future__ import annotations

import json
import time
from pathlib import Path
from threading import Thread
from urllib.request import ProxyHandler, Request, build_opener

import pytest
import yaml

from tools.init_project import init_project
from tools.project_registry import ProjectRegistry
from tools.studio import StudioApplication, StudioError, create_server
from tools.studio_http import POST_ROUTES


def _request(opener, url: str, *, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    method = "GET" if payload is None else "POST"
    if payload is not None:
        headers["X-OpenWrite-Studio"] = "1"
    with opener.open(Request(url, method=method, data=data, headers=headers)) as response:
        return json.loads(response.read())


def _wait(app: StudioApplication, task_id: str, timeout: float = 5) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = app.get_task(task_id)["task"]
        if task["status"] in {"completed", "failed", "cancelled", "interrupted"}:
            return task
        time.sleep(0.01)
    raise AssertionError(f"task {task_id} did not finish")


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
    del project_root, novel_id, profile, truth_context
    return {
        "chapter_summary": f"{chapter_id} {title}：{content.strip()}",
        "observations": content.strip(),
        "legacy_updates": {},
        "state_delta": {},
    }


def test_studio_resumable_import_uses_confirmed_structure_and_persistent_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    init_project(tmp_path, "demo", "旧稿测试")
    registry = ProjectRegistry(tmp_path / "registry.yaml", allow_ephemeral=True)
    app = StudioApplication(tmp_path, project_registry=registry)
    monkeypatch.setattr(app, "_operation_profile", lambda *args, **kwargs: None)
    monkeypatch.setattr("tools.settle_backfill.analyze_existing_chapter", _analyze_existing)
    try:
        prepared = app.prepare_manuscript_import(
            {
                "filename": "旧稿.md",
                "content": "# 第一章 雨夜\n\n门外有人。\n\n# 第二章 回声\n\n门后无人。",
                "arc_id": "arc_003",
                "start_number": 5,
            }
        )
        import_id = prepared["operation"]["import_id"]
        assert prepared["operation"]["status"] == "awaiting_confirmation"
        assert app.manuscript_import_surface()["operations"][0]["import_id"] == import_id
        preview = app.manuscript_import_surface(import_id)["preview"]

        revised = app.revise_manuscript_import_structure(
            {
                "import_id": import_id,
                "expected_preview_revision": preview["revision"],
                "chapters": [
                    {
                        "chapter_id": "ch_005",
                        "title": "雨夜来信",
                        "content": "门外有人。\n\n门后无人。",
                    }
                ],
            }
        )
        with pytest.raises(StudioError) as unconfirmed:
            app.confirm_manuscript_import_structure(
                {
                    "import_id": import_id,
                    "expected_preview_revision": revised["preview"]["revision"],
                    "confirm": False,
                }
            )
        assert unconfirmed.value.code == "CONFIRMATION_REQUIRED"
        app.confirm_manuscript_import_structure(
            {
                "import_id": import_id,
                "expected_preview_revision": revised["preview"]["revision"],
                "confirm": True,
            }
        )
        queued = app.run_manuscript_import({"import_id": import_id})
        completed = _wait(app, queued["task_id"])

        assert completed["status"] == "completed", completed.get("error")
        assert completed["result_ref"] == {"type": "import", "id": import_id}
        detail = app.manuscript_import_surface(import_id)
        assert detail["operation"]["status"] == "completed"
        chapter = (
            tmp_path / "data" / "novels" / "demo" / "data" / "manuscript" / "arc_003" / "ch_005.md"
        )
        assert "雨夜来信" in chapter.read_text(encoding="utf-8")
        synthesis = json.loads(Path(detail["operation"]["synthesis_path"]).read_text())
        assert synthesis["fact_coverage"]["covered"] == 1
        assert synthesis["chapter_facts"][0]["chapter_summary"].startswith("ch_005")
    finally:
        if app._task_runner is not None:
            app._task_runner.shutdown(wait=True)


def test_transfer_http_routes_are_enveloped_and_archive_is_downloadable(
    tmp_path: Path,
) -> None:
    init_project(tmp_path, "demo", "迁移接口")
    registry = ProjectRegistry(tmp_path / "registry.yaml", allow_ephemeral=True)
    server = create_server(tmp_path, port=0, project_registry=registry)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    opener = build_opener(ProxyHandler({}))
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        assert _request(opener, f"{base}/api/manuscript-imports")["data"]["operations"] == []
        prepared = _request(
            opener,
            f"{base}/api/manuscript-imports/prepare",
            payload={
                "filename": "mine.md",
                "content": "# 第一章\n\n门外有人。",
                "arc_id": "arc_001",
            },
        )
        import_id = prepared["data"]["operation"]["import_id"]
        detail = _request(opener, f"{base}/api/manuscript-imports/{import_id}")
        assert detail["data"]["preview"]["chapters"][0]["chapter_id"] == "ch_001"

        preflight = _request(opener, f"{base}/api/project-archives/preflight")["data"]
        created = _request(
            opener,
            f"{base}/api/project-archives/create",
            payload={"expected_preflight_revision": preflight["preflight_revision"]},
        )["data"]["archive"]
        archive_id = created["archive_id"]
        archives = _request(opener, f"{base}/api/project-archives")["data"]["archives"]
        assert archives[0]["archive_id"] == archive_id
        with opener.open(f"{base}/api/project-archives/{archive_id}/download") as response:
            assert response.headers.get_content_type() == "application/zip"
            assert response.read().startswith(b"PK")
        assert POST_ROUTES["/api/manuscript-imports/run"].envelope is True
        assert POST_ROUTES["/api/project-archives/restore"].envelope is True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        if server.app._task_runner is not None:
            server.app._task_runner.shutdown(wait=True)


def test_studio_import_discard_is_explicit_and_never_touches_reference_library(
    tmp_path: Path,
) -> None:
    init_project(tmp_path, "demo")
    reference_root = tmp_path / "reference-library"
    registry = ProjectRegistry(tmp_path / "registry.yaml", allow_ephemeral=True)
    app = StudioApplication(
        tmp_path,
        project_registry=registry,
        reference_library_root=reference_root,
    )
    prepared = app.prepare_manuscript_import(
        {
            "filename": "mine.txt",
            "content": "第一章 归来\n这是作者自己的旧稿。",
            "arc_id": "arc_001",
        }
    )
    import_id = prepared["operation"]["import_id"]

    with pytest.raises(StudioError) as confirmation:
        app.discard_manuscript_import({"import_id": import_id, "confirm": False})
    assert confirmation.value.code == "CONFIRMATION_REQUIRED"
    discarded = app.discard_manuscript_import({"import_id": import_id, "confirm": True})
    assert discarded["operation"]["status"] == "discarded"
    assert not reference_root.exists()


def test_studio_archive_task_and_confirmed_cross_path_restore(tmp_path: Path) -> None:
    source = tmp_path / "source"
    init_project(source, "demo", "迁移测试")
    chapter = source / "data" / "novels" / "demo" / "data" / "manuscript" / "arc_001" / "ch_001.md"
    chapter.write_text("# 第一章\n\n门外有人。\n", encoding="utf-8")
    registry = ProjectRegistry(tmp_path / "registry.yaml", allow_ephemeral=True)
    app = StudioApplication(source, project_registry=registry)
    try:
        preflight = app.project_archive_preflight()
        assert preflight["missing"]["required"] == []
        assert preflight["includes"]["file_count"] > 0
        created = app.create_project_archive(
            {"expected_preflight_revision": preflight["preflight_revision"]}
        )
        archive_id = created["archive"]["archive_id"]
        listed = app.project_archive_surface()
        assert listed["archives"][0]["archive_id"] == archive_id

        with pytest.raises(StudioError) as unsafe_target:
            app.project_restore_preview(
                {"archive_id": archive_id, "target_root": "relative/project"}
            )
        assert unsafe_target.value.code == "RESTORE_TARGET_INVALID"

        target = tmp_path / "restored" / "novel-project"
        preview = app.project_restore_preview(
            {
                "archive_id": archive_id,
                "target_root": str(target),
                "target_novel_id": "restored_demo",
                "reference_policy": "rewrite_novel_id",
            }
        )
        assert preview["can_restore"] is True
        assert preview["auto_resume_tasks"] is False
        with pytest.raises(StudioError) as confirmation:
            app.restore_project_archive(
                {
                    "archive_id": archive_id,
                    "target_root": str(target),
                    "target_novel_id": "restored_demo",
                    "reference_policy": "rewrite_novel_id",
                    "archive_sha256": preview["archive_sha256"],
                    "confirm": False,
                }
            )
        assert confirmation.value.code == "CONFIRMATION_REQUIRED"
        restore_task = app.restore_project_archive(
            {
                "archive_id": archive_id,
                "target_root": str(target),
                "target_novel_id": "restored_demo",
                "reference_policy": "rewrite_novel_id",
                "archive_sha256": preview["archive_sha256"],
                "confirm": True,
            }
        )
        restored = _wait(app, restore_task["task_id"])
        assert restored["status"] == "completed", restored.get("error")
        assert restored["result_ref"] == {"type": "archive", "id": archive_id}
        restored_config = yaml.safe_load((target / "novel_config.yaml").read_text(encoding="utf-8"))
        assert restored_config["novel_id"] == "restored_demo"
        restored_chapter = (
            target
            / "data"
            / "novels"
            / "restored_demo"
            / "data"
            / "manuscript"
            / "arc_001"
            / "ch_001.md"
        )
        assert restored_chapter.read_bytes() == chapter.read_bytes()
        restored_app = StudioApplication(
            target,
            project_registry=ProjectRegistry(
                tmp_path / "restored-registry.yaml", allow_ephemeral=True
            ),
        )
        assert restored_app.workspace()["project"]["root"] == str(target)
    finally:
        if app._task_runner is not None:
            app._task_runner.shutdown(wait=True)
