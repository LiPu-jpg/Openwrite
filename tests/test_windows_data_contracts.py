"""Cross-platform regressions found by the Windows verification matrix."""

import hashlib
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from tools import file_ops
from tools.chapter_memory import ChapterMemoryStore
from tools.chapter_work_brief import ChapterWorkBriefService
from tools.character_state_index import CharacterStateIndex
from tools.export_preflight import ExportPreflightService
from tools.init_project import init_project
from tools.manuscript_acceptance import ManuscriptAcceptanceService
from tools.manuscript_editing import ManuscriptAnnotationStore, ManuscriptVersionStore
from tools.outline_tree import build_outline_structure, mutate_outline_structure
from tools.project_registry import ProjectRegistry
from tools.research_service import MAX_PROCESS_OUTPUT_BYTES, ResearchService
from tools.review_store import ReviewStore
from tools.studio_application import StudioApplication
from tools.task_runner import TaskCancelled


@pytest.mark.parametrize("winerror", [5, 32, 33])
def test_task_snapshot_replacement_retries_transient_windows_sharing(
    tmp_path, monkeypatch, winerror
):
    source, target = tmp_path / "temporary", tmp_path / "snapshot"
    source.write_bytes(b"new")
    target.write_bytes(b"old")
    original = file_ops.os.replace
    attempts = []

    def replace(a, b):
        attempts.append((a, b))
        if len(attempts) < 3:
            error = PermissionError("sharing violation")
            error.winerror = winerror
            raise error
        return original(a, b)

    monkeypatch.setattr(file_ops.os, "replace", replace)
    monkeypatch.setattr(file_ops.time, "sleep", lambda _: None)
    file_ops.replace_file(source, target)
    assert len(attempts) == 3 and target.read_bytes() == b"new"


def test_snapshot_replacement_does_not_hide_persistent_permission_errors(tmp_path, monkeypatch):
    calls = []

    def denied(*_args):
        calls.append(1)
        error = PermissionError("still denied")
        error.winerror = 5
        raise error

    monkeypatch.setattr(file_ops.os, "replace", denied)
    monkeypatch.setattr(file_ops.time, "sleep", lambda _: None)
    with pytest.raises(PermissionError, match="still denied"):
        file_ops.replace_file(tmp_path / "temporary", tmp_path / "snapshot")
    assert len(calls) == 7


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_work_brief_revision_hashes_exact_manuscript_bytes(tmp_path, newline):
    init_project(tmp_path, "demo")
    chapter = tmp_path / "data/novels/demo/data/manuscript/arc_001/ch_001.md"
    content = "# 第一章\n\n雨停，门开。\n".replace("\n", newline).encode()
    chapter.write_bytes(content)
    brief = ChapterWorkBriefService(tmp_path, "demo").get("ch_001")
    assert (
        brief["manuscript"]["current_revision"] == "sha256:" + hashlib.sha256(content).hexdigest()
    )


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_acceptance_history_and_review_use_the_same_exact_revision(tmp_path, newline):
    init_project(tmp_path, "demo")
    novel = tmp_path / "data/novels/demo"
    chapter = novel / "data/manuscript/arc_001/ch_001.md"
    content = "# 第一章\n\n门外有人。\n//**林舟[位置]：门内 -> 门外**\n".replace(
        "\n", newline
    ).encode()
    chapter.write_bytes(content)
    expected = "sha256:" + hashlib.sha256(content).hexdigest()
    service = ManuscriptAcceptanceService(tmp_path, "demo")
    operation = service.establish_baseline(confirm=True)
    frozen = operation["frozen_chapters"][0]
    assert frozen["revision"] == expected
    assert (service.root / frozen["snapshot"]).read_bytes() == content
    service.resume(operation["operation_id"], analyzer=lambda *_: {"chapter_summary": "门外有人。"})
    assert service.inspect()["chapters"][0]["accepted_revision"] == expected
    version = ManuscriptVersionStore(tmp_path, "demo").checkpoint("ch_001", reason="manual")
    assert version.source_revision == expected
    assert (novel / version.content_file).read_bytes() == content
    assert ReviewStore(tmp_path, "demo")._source_revision("ch_001") == expected
    assert ChapterMemoryStore(tmp_path, "demo").load("ch_001")["freshness_status"] == "current"
    assert CharacterStateIndex(tmp_path, "demo").query("林舟")["current"][0]["state"] == "门外"
    inventory, unreadable = ExportPreflightService(tmp_path, "demo")._inventory()
    assert not unreadable and inventory[0]["revision"] == expected


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_annotation_offsets_follow_exact_document_characters(tmp_path, newline):
    init_project(tmp_path, "demo")
    path = tmp_path / "data/novels/demo/data/manuscript/arc_001/ch_001.md"
    content = "# 第一章\n\n门外有人。\n".replace("\n", newline)
    path.write_bytes(content.encode())
    start = content.index("门外有人")
    annotations = ManuscriptAnnotationStore(tmp_path, "demo")
    annotations.create(
        "ch_001",
        source_revision=ManuscriptVersionStore.fingerprint(content),
        quote="门外有人",
        start_hint=start,
        end_hint=start + 4,
        note="核对",
    )
    prefix = "序章提示。" + newline
    path.write_bytes((prefix + content).encode())
    moved = annotations.list("ch_001")[0]
    assert moved.current_start == start + len(prefix)
    assert moved.current_end == start + len(prefix) + 4


def test_outline_mutations_keep_crlf_without_mixing_line_endings(tmp_path):
    path = tmp_path / "src/outline.md"
    path.parent.mkdir()
    path.write_bytes("# 卷\r\n## 幕\r\n### 节\r\n#### 第1章：门\r\n\r\n旧摘要。\r\n".encode())
    changes = [
        {"operation": "rename", "title": "第1章：雨后的门", "node_id": "ch_001"},
        {"operation": "update_summary", "summary": "新摘要。", "node_id": "ch_001"},
        {"operation": "add_after", "title": "第2章：信", "node_id": "ch_001"},
    ]
    for change in changes:
        structure = build_outline_structure(tmp_path)
        edited = mutate_outline_structure(tmp_path, revision=structure["revision"], **change)
        content = edited["content"]
        assert "\r\n" in content and "\n" not in content.replace("\r\n", "")
        path.write_bytes(content.encode())


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_structured_preview_apply_and_undo_preserve_source_bytes(tmp_path, newline):
    init_project(tmp_path, "demo")
    path = tmp_path / "data/novels/demo/src/story/current_focus.md"
    before = "# 当前目标\n\n守住门。\n".replace("\n", newline).encode()
    path.write_bytes(before)
    app = StudioApplication(
        tmp_path, project_registry=ProjectRegistry(tmp_path / "registry.yaml", allow_ephemeral=True)
    )
    try:
        preview = app.structured_change_plan(
            {"action": "preview", "change_kind": "focus", "change": {"goal": "送出信。"}}
        )
        assert path.read_bytes() == before
        applied = app.structured_change_plan(
            {"action": "apply", "preview_token": preview["preview_token"]}
        )
        assert (
            applied["result_revision"] == "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        )
        app.structured_change_plan(
            {"action": "undo", "preview_token": applied["undo_preview_token"]}
        )
        assert path.read_bytes() == before
    finally:
        app._task_runner.shutdown(wait=True)


def child(program):
    return subprocess.Popen(
        [sys.executable, "-c", program],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=os.name == "posix",
    )


def test_research_pipe_drain_is_bounded_and_keeps_final_output(tmp_path):
    process = child(
        f"import sys; sys.stdout.buffer.write(b'x'*{MAX_PROCESS_OUTPUT_BYTES + 10000}+b'END')"
    )
    output = ResearchService(tmp_path)._collect_process_output(
        process, SimpleNamespace(cancellation_requested=lambda: False)
    )
    assert len(output) == MAX_PROCESS_OUTPUT_BYTES and output.endswith(b"END")
    assert process.returncode == 0 and process.stdout.closed


def test_research_cancel_reaps_its_owned_process(tmp_path):
    process = child("import time; time.sleep(30)")
    with pytest.raises(TaskCancelled):
        ResearchService(tmp_path)._collect_process_output(
            process, SimpleNamespace(cancellation_requested=lambda: True)
        )
    assert process.poll() is not None and process.stdout.closed


@pytest.mark.parametrize("entry", ["pnpm/bin/pnpm.cjs", "corepack/dist/pnpm.js"])
def test_windows_pnpm_shim_uses_node_entry_without_shell(tmp_path, monkeypatch, entry):
    path = tmp_path / "node_modules" / entry
    path.parent.mkdir(parents=True)
    path.write_text("// fixture", encoding="utf-8")
    monkeypatch.setattr("tools.research_service.shutil.which", lambda _: "test-node.exe")
    assert ResearchService._command_prefix(str(tmp_path / "pnpm.cmd")) == [
        "test-node.exe",
        str(path),
    ]
