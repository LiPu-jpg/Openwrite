from __future__ import annotations

import hashlib
import json
import os
import zipfile
from pathlib import Path

import pytest
import yaml

from tools.init_project import init_project
from tools.manuscript_import import ManuscriptImportService
from tools.novel_archive import NovelArchiveError, NovelArchiveService
from tools.task_store import TaskStore


def _project(root: Path) -> Path:
    init_project(root, "demo", "归档测试")
    novel = root / "data" / "novels" / "demo"
    chapter = novel / "data" / "manuscript" / "arc_001" / "ch_001.md"
    chapter.write_bytes("# 第一章\n\n门外有人。\n".encode())
    (novel / "data" / "manuscript_versions" / "ch_001").mkdir(parents=True)
    (novel / "data" / "manuscript_versions" / "ch_001" / "ver_001.md").write_bytes(
        b"# historical chapter\n"
    )
    (novel / "data" / "revisions" / "ch_001").mkdir(parents=True)
    (novel / "data" / "revisions" / "ch_001" / "rev_001.json").write_bytes(
        b'{"status":"applied"}\n'
    )
    (novel / "data" / "reviews").mkdir(parents=True, exist_ok=True)
    (novel / "data" / "reviews" / "ch_001.json").write_bytes(
        '{"score":92,"summary":"通过"}\n'.encode()
    )
    (novel / "data" / "sources" / "clock").mkdir(parents=True)
    (novel / "data" / "sources" / "clock" / "source.md").write_bytes(
        "# 钟表资料\n\n每天慢十三秒。\n".encode()
    )
    (novel / "data" / "sources" / "clock" / "citations.json").write_bytes(
        b'{"source":"clock","line":3}\n'
    )
    (novel / "data" / "world").mkdir(parents=True, exist_ok=True)
    (novel / "data" / "world" / "references.json").write_text(
        json.dumps(
            {
                "novel_id": "demo",
                "chapter_path": ("data/novels/demo/data/manuscript/arc_001/ch_001.md"),
                "ambiguous_label": "demo",
                "absolute_path": str(chapter.resolve()),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    TaskStore(root, "demo").create(
        "chapter_write",
        {"chapter_id": "ch_002", "guidance": "continue"},
        chapter_id="ch_002",
    )

    (novel / ".env").write_text("OPENAI_API_KEY=must-not-leave\n", encoding="utf-8")
    (novel / "data" / "cache").mkdir(parents=True)
    (novel / "data" / "cache" / "vectors.bin").write_bytes(b"cache")
    (novel / ".openwrite" / "lightrag" / "search-test").mkdir(parents=True)
    (novel / ".openwrite" / "lightrag" / "search-test" / "vectors.json").write_text(
        '{"derived": true}\n', encoding="utf-8"
    )
    (novel / ".openwrite" / "character-state-index.json").write_text(
        '{"derived": true}\n', encoding="utf-8"
    )
    benchmark_root = novel / "data" / "benchmarks"
    (benchmark_root / "bench_demo" / "workspaces" / "candidate").mkdir(parents=True)
    (benchmark_root / "bench_demo" / "workspaces" / "candidate" / "scratch.md").write_text(
        "derived candidate workspace\n", encoding="utf-8"
    )
    (benchmark_root / "bench_demo.json").write_text(
        '{"status": "completed"}\n', encoding="utf-8"
    )
    (novel / "data" / "logs").mkdir(parents=True)
    (novel / "data" / "logs" / "studio-debug.log").write_text(
        "runtime log\n", encoding="utf-8"
    )
    (novel / "data" / "foreshadowing" / "logs").mkdir(parents=True, exist_ok=True)
    (novel / "data" / "foreshadowing" / "logs" / "fs_001.jsonl").write_text(
        '{"action": "planted"}\n', encoding="utf-8"
    )
    project_lock = novel / "data" / "workflows" / "project.lock"
    project_lock.write_text("locked")
    os.utime(project_lock, (1, 1))
    (novel / "data" / "scratch.tmp").write_text("temporary")
    (novel / "exports").mkdir()
    (novel / "exports" / "demo.epub").write_bytes(b"export")
    return novel


def _tree(root: Path) -> dict[str, bytes]:
    if not root.is_dir():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _rewrite_zip(
    source: Path,
    output: Path,
    *,
    replace: dict[str, bytes] | None = None,
    omit: set[str] | None = None,
) -> None:
    replacements = replace or {}
    omitted = omit or set()
    with zipfile.ZipFile(source, "r") as archive:
        entries = {
            info.filename: archive.read(info)
            for info in archive.infolist()
            if info.filename not in omitted
        }
    entries.update(replacements)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(entries.items()):
            archive.writestr(name, content)


def test_archive_manifest_is_explicit_and_restore_is_byte_exact(tmp_path: Path) -> None:
    source = tmp_path / "source-project"
    novel = _project(source)
    package = tmp_path / "backups" / "demo.owarchive.zip"

    service = NovelArchiveService(source, "demo")
    preflight = service.preflight(package)
    assert preflight == service.preflight(package)
    assert preflight["preflight_revision"].startswith("sha256:")
    created = service.create_archive(
        package,
        expected_preflight_revision=preflight["preflight_revision"],
    )
    inspected = NovelArchiveService.inspect_archive(package)
    manifest = inspected["manifest"]

    assert created["schema_version"] == "openwrite.novel-archive.v1"
    assert created["archive_sha256"].startswith("sha256:")
    assert created["preflight_revision"] == preflight["preflight_revision"]
    assert preflight["includes"] == manifest["includes"]
    assert preflight["excludes"] == manifest["excludes"]
    assert preflight["missing"] == manifest["missing"]
    assert manifest["version"] == 1
    assert manifest["source"]["novel_id"] == "demo"
    assert manifest["policies"] == {
        "novel_id": {
            "default": "preserve",
            "remap_requires": "rewrite_novel_id",
        },
        "references": {
            "default": "preserve_relative",
            "supported": ["preserve_relative", "rewrite_novel_id"],
        },
        "tasks": "archive_no_resume",
        "target": "new_or_empty",
    }
    records = {item["path"]: item for item in manifest["includes"]["files"]}
    expected_categories = {
        "novel_config.yaml": "config",
        "data/novels/demo/src/outline.md": "source",
        "data/novels/demo/data/manuscript/arc_001/ch_001.md": "manuscript",
        "data/novels/demo/data/manuscript_versions/ch_001/ver_001.md": "history",
        "data/novels/demo/data/revisions/ch_001/rev_001.json": "history",
        "data/novels/demo/data/reviews/ch_001.json": "review",
        "data/novels/demo/data/sources/clock/source.md": "references",
        "data/novels/demo/data/hierarchy.yaml": "structured_data",
        "data/novels/demo/data/benchmarks/bench_demo.json": "structured_data",
        "data/novels/demo/data/foreshadowing/logs/fs_001.jsonl": "structured_data",
    }
    for path, category in expected_categories.items():
        assert records[path]["category"] == category
    assert any(item["category"] == "tasks" for item in records.values())
    excluded = {item["path"]: item["reason"] for item in manifest["excludes"]["entries"]}
    assert excluded["data/novels/demo/.env"] == "credentials"
    assert excluded["data/novels/demo/data/cache/"] == "cache"
    assert excluded["data/novels/demo/.openwrite/"] == "cache"
    assert excluded[
        "data/novels/demo/data/benchmarks/bench_demo/workspaces/"
    ] == "cache"
    assert excluded["data/novels/demo/data/logs/"] == "cache"
    assert excluded["data/novels/demo/data/workflows/project.lock"] == "lock"
    assert excluded["data/novels/demo/data/scratch.tmp"] == "temporary"
    assert excluded["data/novels/demo/exports/"] == "export"
    assert manifest["missing"]["required"] == []
    assert any(
        item["path"] == "data/novels/demo/data/manuscript_acceptance"
        for item in manifest["missing"]["optional"]
    )

    with zipfile.ZipFile(package, "r") as archive:
        infos = archive.infolist()
        assert [info.filename for info in infos] == sorted(info.filename for info in infos)
        assert len({info.filename.casefold() for info in infos}) == len(infos)
        assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in infos)
        for item in records.values():
            content = archive.read(item["archive_path"])
            assert len(content) == item["size"]
            assert "sha256:" + hashlib.sha256(content).hexdigest() == item["sha256"]

    target = tmp_path / "different-parent" / "restored-project"
    preview = NovelArchiveService.preview_restore(package, target)
    assert preview["can_restore"] is True
    assert preview["target_novel_id"] == "demo"
    assert preview["auto_resume_tasks"] is False
    with pytest.raises(NovelArchiveError) as confirmation:
        NovelArchiveService.restore_archive(
            package,
            target,
            expected_archive_sha256=preview["archive_sha256"],
        )
    assert confirmation.value.code == "CONFIRMATION_REQUIRED"

    restored = NovelArchiveService.restore_archive(
        package,
        target,
        expected_archive_sha256=preview["archive_sha256"],
        confirm=True,
    )

    restored_novel = target / "data" / "novels" / "demo"
    assert (target / "novel_config.yaml").read_bytes() == (
        source / "novel_config.yaml"
    ).read_bytes()
    for relative in (
        "src",
        "data/manuscript",
        "data/manuscript_versions",
        "data/revisions",
        "data/reviews",
        "data/sources",
    ):
        assert _tree(restored_novel / relative) == _tree(novel / relative)
    assert (restored_novel / "data" / "hierarchy.yaml").read_bytes() == (
        novel / "data" / "hierarchy.yaml"
    ).read_bytes()
    assert not (restored_novel / ".env").exists()
    assert not (restored_novel / "data" / "cache").exists()
    assert not (restored_novel / "exports").exists()
    assert not (restored_novel / "data" / "workflows" / "tasks").exists()
    task_archive = target / restored["task_archive_path"]
    assert _tree(task_archive) == _tree(novel / "data" / "workflows" / "tasks")
    assert TaskStore(target, "demo").list() == []
    assert restored["auto_resume_tasks"] is False


def test_restore_rejects_tampered_file_and_preview_checksum_swap(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _project(source)
    package = tmp_path / "clean.zip"
    NovelArchiveService(source, "demo").create_archive(package)
    preview = NovelArchiveService.preview_restore(package, tmp_path / "target")
    manifest = NovelArchiveService.inspect_archive(package)["manifest"]
    chapter = next(
        item for item in manifest["includes"]["files"] if item["category"] == "manuscript"
    )
    tampered = tmp_path / "tampered.zip"
    _rewrite_zip(package, tampered, replace={chapter["archive_path"]: b"tampered"})

    with pytest.raises(NovelArchiveError) as mismatch:
        NovelArchiveService.preview_restore(tampered, tmp_path / "target")
    assert mismatch.value.code == "CHECKSUM_MISMATCH"
    with pytest.raises(NovelArchiveError) as changed:
        NovelArchiveService.restore_archive(
            tampered,
            tmp_path / "target",
            expected_archive_sha256=preview["archive_sha256"],
            confirm=True,
        )
    assert changed.value.code == "ARCHIVE_CHANGED"


def test_restore_rejects_missing_manifest_entry(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _project(source)
    package = tmp_path / "clean.zip"
    NovelArchiveService(source, "demo").create_archive(package)
    manifest = NovelArchiveService.inspect_archive(package)["manifest"]
    required = next(
        item
        for item in manifest["includes"]["files"]
        if item["path"] == "data/novels/demo/src/outline.md"
    )
    incomplete = tmp_path / "incomplete.zip"
    _rewrite_zip(package, incomplete, omit={required["archive_path"]})

    with pytest.raises(NovelArchiveError) as missing:
        NovelArchiveService.preview_restore(incomplete, tmp_path / "target")
    assert missing.value.code == "ARCHIVE_ENTRY_MISSING"


def test_restore_rejects_zip_slip_without_writing_outside_target(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _project(source)
    package = tmp_path / "unsafe.zip"
    NovelArchiveService(source, "demo").create_archive(package)
    with zipfile.ZipFile(package, "a") as archive:
        archive.writestr("../escaped.txt", "owned")

    target = tmp_path / "target"
    with pytest.raises(NovelArchiveError) as unsafe:
        NovelArchiveService.preview_restore(package, target)
    assert unsafe.value.code == "UNSAFE_ARCHIVE_PATH"
    assert not (tmp_path / "escaped.txt").exists()
    assert not target.exists()


def test_restore_refuses_nonempty_target_and_requires_explicit_remap_policy(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _project(source)
    package = tmp_path / "clean.zip"
    NovelArchiveService(source, "demo").create_archive(package)
    target = tmp_path / "target"
    target.mkdir()
    (target / "keep.txt").write_text("keep", encoding="utf-8")

    preview = NovelArchiveService.preview_restore(package, target)
    assert preview["can_restore"] is False
    assert preview["conflicts"] == ["TARGET_NOT_EMPTY"]
    with pytest.raises(NovelArchiveError) as conflict:
        NovelArchiveService.restore_archive(
            package,
            target,
            expected_archive_sha256=preview["archive_sha256"],
            confirm=True,
        )
    assert conflict.value.code == "TARGET_NOT_EMPTY"
    assert (target / "keep.txt").read_text(encoding="utf-8") == "keep"

    with pytest.raises(NovelArchiveError) as novel_id:
        NovelArchiveService.preview_restore(
            package,
            tmp_path / "renamed",
            target_novel_id="renamed",
        )
    assert novel_id.value.code == "NOVEL_ID_POLICY_CONFLICT"
    with pytest.raises(NovelArchiveError) as references:
        NovelArchiveService.preview_restore(
            package,
            tmp_path / "references",
            reference_policy="rewrite",
        )
    assert references.value.code == "REFERENCE_POLICY_UNSUPPORTED"


def test_restore_remaps_id_paths_and_known_references_with_visible_warnings(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    novel = _project(source)
    package = tmp_path / "clean.zip"
    NovelArchiveService(source, "demo").create_archive(package)
    target = tmp_path / "renamed"

    preview = NovelArchiveService.preview_restore(
        package,
        target,
        target_novel_id="restored_demo",
        reference_policy="rewrite_novel_id",
    )

    assert preview["can_restore"] is True
    assert preview["reference_conflicts"] == []
    assert preview["task_archive_path"].startswith(
        "data/novels/restored_demo/data/workflows/task_archive/"
    )
    assert {(item["source"], item["target"]) for item in preview["path_rewrites"]} >= {
        (
            "data/novels/demo/data/world/references.json",
            "data/novels/restored_demo/data/world/references.json",
        ),
    }
    rewritten_locations = {
        (item["path"], item["location"], item["kind"]) for item in preview["rewritten_references"]
    }
    assert ("novel_config.yaml", "$.novel_id", "novel_id") in rewritten_locations
    assert (
        "data/novels/demo/data/world/references.json",
        "$.chapter_path",
        "project_relative_path",
    ) in rewritten_locations
    warnings = {
        (item["path"], item["location"], item["kind"]) for item in preview["reference_warnings"]
    }
    assert (
        "data/novels/demo/data/world/references.json",
        "$.absolute_path",
        "absolute_reference_preserved",
    ) in warnings
    assert (
        "data/novels/demo/data/world/references.json",
        "$.ambiguous_label",
        "ambiguous_novel_id_preserved",
    ) in warnings

    restored = NovelArchiveService.restore_archive(
        package,
        target,
        expected_archive_sha256=preview["archive_sha256"],
        confirm=True,
        target_novel_id="restored_demo",
        reference_policy="rewrite_novel_id",
    )

    assert restored["source_novel_id"] == "demo"
    assert restored["novel_id"] == "restored_demo"
    assert not (target / "data" / "novels" / "demo").exists()
    restored_novel = target / "data" / "novels" / "restored_demo"
    config = yaml.safe_load((target / "novel_config.yaml").read_text(encoding="utf-8"))
    assert config["novel_id"] == "restored_demo"
    references_path = restored_novel / "data" / "world" / "references.json"
    references = json.loads(references_path.read_text(encoding="utf-8"))
    assert references["novel_id"] == "restored_demo"
    assert references["chapter_path"].startswith("data/novels/restored_demo/")
    assert references["ambiguous_label"] == "demo"
    assert references["absolute_path"] == str(
        (novel / "data" / "manuscript" / "arc_001" / "ch_001.md").resolve()
    )
    assert not (restored_novel / "data" / "workflows" / "tasks").exists()
    assert TaskStore(target, "restored_demo").list() == []


def test_create_archive_rejects_changed_preflight_revision(tmp_path: Path) -> None:
    source = tmp_path / "source"
    novel = _project(source)
    package = tmp_path / "changed.zip"
    service = NovelArchiveService(source, "demo")
    preflight = service.preflight(package)
    chapter = novel / "data" / "manuscript" / "arc_001" / "ch_001.md"
    chapter.write_text("# 已在预检后变更\n", encoding="utf-8")

    with pytest.raises(NovelArchiveError) as changed:
        service.create_archive(
            package,
            expected_preflight_revision=preflight["preflight_revision"],
        )

    assert changed.value.code == "PREFLIGHT_CHANGED"
    assert changed.value.recoverable is True
    assert changed.value.details["expected"] == preflight["preflight_revision"]
    assert changed.value.details["current"] != preflight["preflight_revision"]
    assert not package.exists()


def test_export_rejects_missing_required_outline(tmp_path: Path) -> None:
    source = tmp_path / "source"
    novel = _project(source)
    (novel / "src" / "outline.md").unlink()

    with pytest.raises(NovelArchiveError) as missing:
        NovelArchiveService(source, "demo").create_archive(tmp_path / "bad.zip")
    assert missing.value.code == "REQUIRED_CONTENT_MISSING"
    assert missing.value.details["missing"] == ["data/novels/demo/src/outline.md"]


def test_export_refuses_credentials_embedded_in_required_config(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _project(source)
    config = source / "novel_config.yaml"
    config.write_text(
        config.read_text(encoding="utf-8") + "provider:\n  api_key: sk-private\n",
        encoding="utf-8",
    )
    output = tmp_path / "must-not-exist.zip"

    with pytest.raises(NovelArchiveError) as credentials:
        NovelArchiveService(source, "demo").create_archive(output)
    assert credentials.value.code == "CREDENTIALS_PRESENT"
    assert credentials.value.details["keys"] == ["provider.api_key"]
    assert not output.exists()


def test_restored_import_preview_is_rebound_and_cannot_modify_source_workspace(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _project(source)
    legacy = source / "legacy.txt"
    legacy.write_text("第一章 雾中来信\n\n旧稿正文。\n", encoding="utf-8")
    source_imports = ManuscriptImportService(source, "demo")
    operation = source_imports.start(legacy, arc_id="arc_009", start_number=9)
    import_id = operation["import_id"]
    source_preview_path = source_imports.operation_root(import_id) / "preview.json"
    source_preview_bytes = source_preview_path.read_bytes()

    package = tmp_path / "with-import.zip"
    NovelArchiveService(source, "demo").create_archive(package)
    target = tmp_path / "restored"
    preview = NovelArchiveService.preview_restore(package, target)
    NovelArchiveService.restore_archive(
        package,
        target,
        expected_archive_sha256=preview["archive_sha256"],
        confirm=True,
    )

    restored_imports = ManuscriptImportService(target, "demo")
    restored_preview = restored_imports.preview(import_id)
    chapters = [dict(item) for item in restored_preview["chapters"]]
    chapters[0]["content"] = "恢复工作区中的修订正文。"
    revised = restored_imports.revise_preview(
        import_id,
        expected_preview_revision=restored_preview["revision"],
        chapters=chapters,
    )

    restored_preview_path = restored_imports.operation_root(import_id) / "preview.json"
    assert source_preview_path != restored_preview_path
    assert source_preview_path.read_bytes() == source_preview_bytes
    assert restored_preview_path.read_bytes() != source_preview_bytes
    assert revised["chapters"][0]["content"] == "恢复工作区中的修订正文。"
    assert source_imports.preview(import_id)["chapters"][0]["content"] == "旧稿正文。"
