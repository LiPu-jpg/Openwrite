from __future__ import annotations

import json
import zipfile
from pathlib import Path
from threading import Event, Thread
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import ProxyHandler, build_opener

import pytest
import yaml

from tools.epub_export import validate_epub
from tools.export_preflight import ExportPreflightError, ExportPreflightService
from tools.init_project import init_project
from tools.manuscript_acceptance import ManuscriptAcceptanceService
from tools.novel_service import NovelApplicationService, NovelServiceError
from tools.project_lock import ProjectBusyError, ProjectWriteLock
from tools.project_registry import ProjectRegistry
from tools.review_store import ReviewStore
from tools.studio import StudioApplication, StudioError, create_server


def _chapter(root: Path, arc: str, chapter_id: str, text: str) -> Path:
    path = root / "data" / "novels" / "demo" / "data" / "manuscript" / arc / f"{chapter_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _project(tmp_path: Path) -> ExportPreflightService:
    init_project(tmp_path, "demo", "雾城来信")
    return ExportPreflightService(tmp_path, "demo")


def _accept_current(root: Path) -> None:
    service = ManuscriptAcceptanceService(root, "demo")
    operation = service.establish_baseline(confirm=True)
    service.resume(
        operation["operation_id"],
        analyzer=lambda *args: {
            "chapter_summary": "",
            "observations": "",
            "legacy_updates": {},
            "state_delta": {},
        },
    )
    assert service.inspect()["status"] == "current"


def test_preflight_uses_every_disk_chapter_and_reports_structure_defects(tmp_path: Path) -> None:
    service = _project(tmp_path)
    first = _chapter(tmp_path, "arc_002", "ch_001", "# 第一章\n\n雨落下来。\n")
    duplicate = _chapter(tmp_path, "arc_001", "ch_001", "# 第一章（旧）\n\n另一份正文。\n")
    empty = _chapter(tmp_path, "arc_002", "ch_003", "# 第三章\n")

    report = service.inspect(format_name="md", purpose="backup")

    assert [item["path"] for item in report["chapters"]] == sorted(
        [
            first.relative_to(tmp_path / "data" / "novels" / "demo").as_posix(),
            duplicate.relative_to(tmp_path / "data" / "novels" / "demo").as_posix(),
            empty.relative_to(tmp_path / "data" / "novels" / "demo").as_posix(),
        ],
        key=lambda value: (0 if "ch_001" in value else 1, value),
    )
    assert report["actual_order"] == ["ch_001", "ch_001", "ch_003"]
    assert report["structure"]["duplicates"] == {
        "ch_001": sorted([report["chapters"][0]["path"], report["chapters"][1]["path"]])
    }
    assert report["structure"]["missing"] == ["ch_002"]
    assert report["structure"]["empty"] == ["ch_003"]
    assert {item["code"] for item in report["blockers"]} == {"DUPLICATE_CHAPTER_ID"}
    assert report["can_export"] is False


def test_backup_ignores_review_gate_but_delivery_requires_current_review_and_metadata(
    tmp_path: Path,
) -> None:
    service = _project(tmp_path)
    _chapter(tmp_path, "arc_001", "ch_001", "# 第一章\n\n雨落下来。\n")

    backup = service.inspect(format_name="epub", purpose="backup")
    assert backup["can_export"] is True
    assert backup["reviews"]["missing"] == ["ch_001"]
    assert "REVIEW_MISSING" not in {item["code"] for item in backup["blockers"]}

    delivery = service.inspect(format_name="epub", purpose="delivery")
    assert delivery["can_export"] is False
    assert {item["code"] for item in delivery["blockers"]} >= {
        "METADATA_AUTHOR_MISSING",
        "REVIEW_MISSING",
    }

    config_path = tmp_path / "novel_config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["author"] = "测试作者"
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    ReviewStore(tmp_path, "demo").save("ch_001", {"score": 92, "passed": True})

    missing_facts = ExportPreflightService(tmp_path, "demo").inspect(
        format_name="epub", purpose="delivery"
    )
    assert missing_facts["manuscript_acceptance"]["status"] == "baseline_required"
    assert missing_facts["manuscript_acceptance"]["blocking"] is True
    assert "MANUSCRIPT_FACTS_NOT_CURRENT" in {item["code"] for item in missing_facts["blockers"]}

    _accept_current(tmp_path)
    ReviewStore(tmp_path, "demo").save("ch_001", {"score": 92, "passed": True})
    current = ExportPreflightService(tmp_path, "demo").inspect(
        format_name="epub", purpose="delivery"
    )
    assert current["reviews"]["current"] == ["ch_001"]
    assert current["reviews"]["approved"] == ["ch_001"]
    assert current["can_export"] is True

    chapter = next(
        (tmp_path / "data" / "novels" / "demo" / "data" / "manuscript").rglob("ch_001.md")
    )
    chapter.write_text(chapter.read_text(encoding="utf-8") + "又响了一声。\n", encoding="utf-8")
    stale = ExportPreflightService(tmp_path, "demo").inspect(format_name="epub", purpose="delivery")
    assert stale["reviews"]["stale"] == ["ch_001"]
    assert "REVIEW_STALE" in {item["code"] for item in stale["blockers"]}


def test_delivery_export_runs_preflight_and_epub_post_validation(tmp_path: Path) -> None:
    _project(tmp_path)
    _chapter(tmp_path, "arc_001", "ch_001", "# 第一章\n\n钟声落入雾里。\n")
    config_path = tmp_path / "novel_config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["author"] = "测试作者"
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    _accept_current(tmp_path)
    ReviewStore(tmp_path, "demo").save("ch_001", {"score": 95, "passed": True})
    output = tmp_path / "delivery.epub"

    path = NovelApplicationService(tmp_path).export_book(
        output, format_name="epub", purpose="delivery"
    )

    assert path == output
    assert validate_epub(output)["chapters"] == 1
    validated = ExportPreflightService(tmp_path, "demo").validate_output(output, format_name="epub")
    assert validated["valid"] is True
    assert validated["toc_titles"] == ["第一章"]
    assert validated["body_files"] == ["OEBPS/text/chapter-0001.xhtml"]
    with zipfile.ZipFile(output) as archive:
        assert "钟声落入雾里" in archive.read(validated["body_files"][0]).decode("utf-8")


def test_delivery_blocks_completed_facts_until_authored_impacts_are_acknowledged(
    tmp_path: Path,
) -> None:
    _project(tmp_path)
    chapter = _chapter(tmp_path, "arc_001", "ch_001", "# 第一章\n\n钟声落下。\n")
    acceptance = ManuscriptAcceptanceService(tmp_path, "demo")
    _accept_current(tmp_path)
    previous = acceptance.fingerprint(chapter.read_text(encoding="utf-8"))
    chapter.write_text("# 第一章\n\n钟声被人提前敲响。\n", encoding="utf-8")
    operation = acceptance.start_acceptance(
        "ch_001",
        source="manual",
        expected_previous_revision=previous,
    )
    acceptance.resume(
        operation["operation_id"],
        analyzer=lambda *args: {
            "chapter_summary": "钟声提前响起",
            "observations": "钟声提前响起",
            "legacy_updates": {},
            "state_delta": {},
        },
    )
    config_path = tmp_path / "novel_config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["author"] = "测试作者"
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    ReviewStore(tmp_path, "demo").save("ch_001", {"score": 95, "passed": True})

    blocked = ExportPreflightService(tmp_path, "demo").inspect(
        format_name="epub", purpose="delivery"
    )

    assert blocked["manuscript_acceptance"]["status"] == "needs_review"
    assert blocked["manuscript_acceptance"]["needs_review"] == [
        "foreshadowing",
        "outline",
    ]
    assert "MANUSCRIPT_FACTS_NOT_CURRENT" in {item["code"] for item in blocked["blockers"]}

    acceptance.acknowledge(
        operation["operation_id"],
        domains=["outline", "foreshadowing"],
        confirm=True,
    )
    assert (
        ExportPreflightService(tmp_path, "demo").inspect(format_name="epub", purpose="delivery")[
            "can_export"
        ]
        is True
    )


def test_duplicate_chapter_ids_are_never_silently_exported(tmp_path: Path) -> None:
    _project(tmp_path)
    _chapter(tmp_path, "arc_001", "ch_001", "# 第一份\n\n正文甲。\n")
    _chapter(tmp_path, "arc_002", "ch_001", "# 第二份\n\n正文乙。\n")
    output = tmp_path / "book.md"

    with pytest.raises(NovelServiceError) as error:
        NovelApplicationService(tmp_path).export_book(output, format_name="md")

    assert error.value.code == "EXPORT_PREFLIGHT_FAILED"
    assert not output.exists()


def test_validate_output_rejects_an_epub_with_toc_body_mismatch(tmp_path: Path) -> None:
    service = _project(tmp_path)
    path = tmp_path / "bad.epub"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("manifest.json", json.dumps({}))

    with pytest.raises(ExportPreflightError):
        service.validate_output(path, format_name="epub")


def test_studio_and_http_expose_revision_bound_preflight(tmp_path: Path) -> None:
    _project(tmp_path)
    _chapter(tmp_path, "arc_001", "ch_001", "# 第一章\n\n钟声落入雾里。\n")
    registry = ProjectRegistry(tmp_path / "registry.yaml", allow_ephemeral=True)
    app = StudioApplication(tmp_path, project_registry=registry)
    report = app.export_preflight("md", "backup")
    assert report["can_export"] is True
    with pytest.raises(StudioError) as changed:
        app.export_download("md", "backup", "sha256:" + "0" * 64)
    assert changed.value.code == "EXPORT_PREFLIGHT_CHANGED"

    server = create_server(tmp_path, port=0, project_registry=registry)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    opener = build_opener(ProxyHandler({}))
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with opener.open(f"{base}/api/export/preflight?format=md&purpose=backup") as response:
            payload = json.loads(response.read())
        assert payload["ok"] is True
        revision = payload["data"]["preflight_revision"]
        url = f"{base}/api/export?format=md&purpose=backup&preflight_revision={quote(revision)}"
        with opener.open(url) as response:
            assert response.headers.get_content_type() == "text/markdown"
            assert "钟声落入雾里" in response.read().decode("utf-8")
        with pytest.raises(HTTPError) as conflict:
            opener.open(f"{base}/api/export?format=md&purpose=backup&preflight_revision=stale")
        assert conflict.value.code == 409
        error = json.loads(conflict.value.read())
        assert error["code"] == "EXPORT_PREFLIGHT_CHANGED"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        if server.app._task_runner is not None:
            server.app._task_runner.shutdown(wait=True)


def test_export_rejects_a_project_change_after_preflight_and_preserves_old_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project(tmp_path)
    chapter = _chapter(tmp_path, "arc_001", "ch_001", "# 第一章\n\n旧正文。\n")
    output = tmp_path / "book.md"
    output.write_text("previous export\n", encoding="utf-8")
    service = NovelApplicationService(tmp_path)
    revision = service.export_preflight(format_name="md", purpose="backup")["preflight_revision"]

    import tools.novel_workspace as novel_workspace

    original = novel_workspace.export_manuscript

    def export_after_external_edit(*args, **kwargs):
        chapter.write_text("# 第一章\n\n导出期间变化的新正文。\n", encoding="utf-8")
        return original(*args, **kwargs)

    monkeypatch.setattr(novel_workspace, "export_manuscript", export_after_external_edit)

    with pytest.raises(NovelServiceError) as changed:
        service.export_book(
            output,
            format_name="md",
            purpose="backup",
            preflight_revision=revision,
        )

    assert changed.value.code == "EXPORT_PREFLIGHT_CHANGED"
    assert output.read_text(encoding="utf-8") == "previous export\n"
    assert not list(tmp_path.glob(".book.md.*.exporting"))


def test_project_lock_does_not_reclaim_an_owner_file_while_it_is_being_initialized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tools.project_lock as project_lock

    entered = Event()
    release = Event()
    original_dump = project_lock.json.dump

    def paused_dump(*args, **kwargs):
        entered.set()
        assert release.wait(timeout=3)
        return original_dump(*args, **kwargs)

    monkeypatch.setattr(project_lock.json, "dump", paused_dump)
    first = ProjectWriteLock(tmp_path, "demo", operation="export-a")
    second = ProjectWriteLock(tmp_path, "demo", operation="export-b")
    errors: list[BaseException] = []

    def acquire_first() -> None:
        try:
            first.acquire()
        except BaseException as exc:
            errors.append(exc)

    thread = Thread(target=acquire_first)
    thread.start()
    try:
        assert entered.wait(timeout=2)
        with pytest.raises(ProjectBusyError):
            second.acquire()
    finally:
        release.set()
        thread.join(timeout=3)
        first.release()

    assert errors == []
    assert second.acquired is False


def test_export_does_not_overwrite_a_destination_changed_at_publish_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project(tmp_path)
    chapter = _chapter(tmp_path, "arc_001", "ch_001", "# 第一章\n\n旧正文。\n")
    output = tmp_path / "book.md"
    output.write_text("previous export\n", encoding="utf-8")
    service = NovelApplicationService(tmp_path)

    import tools.novel_service as novel_service

    original_replace = novel_service.os.replace

    def replace_after_concurrent_writes(source, destination):
        if Path(source) == output:
            chapter.write_text("# 第一章\n\n发布窗口中的新正文。\n", encoding="utf-8")
            output.write_text("concurrent writer output\n", encoding="utf-8")
        return original_replace(source, destination)

    monkeypatch.setattr(novel_service.os, "replace", replace_after_concurrent_writes)

    with pytest.raises(NovelServiceError) as changed:
        service.export_book(output, format_name="md", purpose="backup")

    assert changed.value.code == "EXPORT_OUTPUT_CHANGED"
    assert output.read_text(encoding="utf-8") == "concurrent writer output\n"
    assert not list(tmp_path.glob(".book.md.*.exporting*"))


def test_export_keeps_a_recovery_copy_when_automatic_restore_is_not_possible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project(tmp_path)
    _chapter(tmp_path, "arc_001", "ch_001", "# 第一章\n\n旧正文。\n")
    output = tmp_path / "book.md"
    output.write_text("previous export\n", encoding="utf-8")
    service = NovelApplicationService(tmp_path)

    import tools.novel_service as novel_service

    def denied_link(*args, **kwargs):
        raise PermissionError("injected link failure")

    monkeypatch.setattr(novel_service.os, "link", denied_link)

    with pytest.raises(NovelServiceError) as recovery:
        service.export_book(output, format_name="md", purpose="backup")

    copies = list(tmp_path.glob(".book.md.*.exporting.previous"))
    assert recovery.value.code == "EXPORT_OUTPUT_RECOVERY_REQUIRED"
    assert output.exists() is False
    assert len(copies) == 1
    assert recovery.value.details["recovery_path"] == str(copies[0])
    assert copies[0].read_text(encoding="utf-8") == "previous export\n"


def test_export_rollback_never_removes_a_concurrent_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project(tmp_path)
    chapter = _chapter(tmp_path, "arc_001", "ch_001", "# 第一章\n\n旧正文。\n")
    output = tmp_path / "book.md"
    output.write_text("previous export\n", encoding="utf-8")
    service = NovelApplicationService(tmp_path)

    import tools.novel_service as novel_service

    original_replace = novel_service.os.replace

    def replace_then_publish_concurrently(source, destination):
        result = original_replace(source, destination)
        if Path(source) == output:
            output.write_text("concurrent writer output\n", encoding="utf-8")
            chapter.write_text("# 第一章\n\n并发写入后的正文。\n", encoding="utf-8")
        return result

    monkeypatch.setattr(novel_service.os, "replace", replace_then_publish_concurrently)

    with pytest.raises(NovelServiceError) as changed:
        service.export_book(output, format_name="md", purpose="backup")

    copies = list(tmp_path.glob(".book.md.*.exporting.previous"))
    assert changed.value.code == "EXPORT_OUTPUT_CHANGED"
    assert output.read_text(encoding="utf-8") == "concurrent writer output\n"
    assert len(copies) == 1
    assert copies[0].read_text(encoding="utf-8") == "previous export\n"
    assert changed.value.details["recovery_path"] == str(copies[0])


def test_committed_export_is_successful_when_only_temp_cleanup_is_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project(tmp_path)
    _chapter(tmp_path, "arc_001", "ch_001", "# 第一章\n\n已提交正文。\n")
    output = tmp_path / "book.md"
    output.write_text("previous export\n", encoding="utf-8")
    original_unlink = Path.unlink

    def deny_transaction_cleanup(path: Path, *args, **kwargs):
        if ".exporting" in path.name:
            raise PermissionError("injected cleanup failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", deny_transaction_cleanup)

    result = NovelApplicationService(tmp_path).export_book(
        output, format_name="md", purpose="backup"
    )

    assert result == output
    assert "已提交正文" in output.read_text(encoding="utf-8")
    assert list(tmp_path.glob(".book.md.*.exporting.previous"))
