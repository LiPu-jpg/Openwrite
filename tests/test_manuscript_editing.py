from __future__ import annotations

import json
import sys
from http import HTTPStatus
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from urllib.request import ProxyHandler, Request, build_opener

import pytest

import tools.cli as cli_module
from tools.agent.confirmation import guard_confirmable_executors
from tools.agent.tool_runtime import build_tool_executors
from tools.cli import _save_chapter
from tools.init_project import init_project
from tools.manuscript_acceptance import ManuscriptAcceptanceService
from tools.manuscript_editing import (
    ManuscriptAnnotationStore,
    ManuscriptEditingError,
    ManuscriptVersionStore,
)
from tools.project_lock import ProjectWriteLock
from tools.revision_service import RevisionService
from tools.studio import StudioApplication, create_server
from tools.studio_contracts import StudioError


def _project(tmp_path: Path, content: str = "# 第一章\n\n甲乙丙，钟声响起。\n") -> Path:
    init_project(tmp_path, "demo")
    return _save_chapter(tmp_path, "demo", "ch_001", "第一章", content)


def test_checkpoint_load_restore_and_metadata_identity_guards(tmp_path: Path) -> None:
    chapter = _project(tmp_path)
    store = ManuscriptVersionStore(tmp_path, "demo")
    original = chapter.read_text(encoding="utf-8")
    version = store.checkpoint("ch_001", label="初稿")

    loaded, content = store.load("ch_001", version.version_id)
    assert loaded == version
    assert content == original
    assert store.list("ch_001") == [version]

    changed = original + "\n新增一段。\n"
    chapter.write_text(changed, encoding="utf-8")
    ManuscriptAcceptanceService(tmp_path, "demo").start_acceptance(
        "ch_001",
        source="manual",
        expected_previous_revision=store.fingerprint(original),
    )
    with pytest.raises(ManuscriptEditingError) as confirmation:
        store.restore(
            "ch_001",
            version.version_id,
            current_revision=store.fingerprint(changed),
        )
    assert confirmation.value.code == "CONFIRMATION_REQUIRED"

    with pytest.raises(ManuscriptEditingError) as stale:
        store.restore(
            "ch_001",
            version.version_id,
            current_revision=version.source_revision,
            confirm=True,
        )
    assert stale.value.code == "STALE_REVISION"

    restored = store.restore(
        "ch_001",
        version.version_id,
        current_revision=store.fingerprint(changed),
        confirm=True,
    )
    assert restored.version_id == version.version_id
    assert isinstance(restored, type(version))
    assert chapter.read_text(encoding="utf-8") == original
    assert store.last_acceptance is not None
    assert store.last_acceptance["source"] == "history_restore"
    assert store.last_acceptance["chapter_id"] == "ch_001"
    assert store.last_acceptance["expected_previous_revision"] == store.fingerprint(changed)
    assert store.last_acceptance["accepted_revision"] == ""
    assert store.last_acceptance["target_revision"] == store.fingerprint(original)
    restore_checkpoint = store.list("ch_001")[0]
    assert restore_checkpoint.reason == "restore"
    assert store.load("ch_001", restore_checkpoint.version_id)[1] == changed

    metadata_path = store.root / "ch_001" / f"{version.version_id}.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["content_file"] = "data/manuscript_versions/ch_999/ver_abcdefgh.md"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(ManuscriptEditingError) as invalid:
        store.load("ch_001", version.version_id)
    assert invalid.value.code == "INVALID_VERSION"


def test_restore_participates_in_the_shared_project_write_lock(tmp_path: Path) -> None:
    chapter = _project(tmp_path)
    store = ManuscriptVersionStore(tmp_path, "demo")
    original = chapter.read_text(encoding="utf-8")
    version = store.checkpoint("ch_001", label="锁测试")
    changed = original + "\n锁外修改。\n"
    chapter.write_text(changed, encoding="utf-8")

    with ProjectWriteLock(tmp_path, "demo", operation="other-writer"):
        with pytest.raises(ManuscriptEditingError) as busy:
            store.restore(
                "ch_001",
                version.version_id,
                current_revision=store.fingerprint(changed),
                confirm=True,
            )

    assert busy.value.code == "PROJECT_BUSY"
    assert chapter.read_text(encoding="utf-8") == changed


def test_compare_version_previews_current_to_target_without_writing(tmp_path: Path) -> None:
    chapter = _project(tmp_path)
    store = ManuscriptVersionStore(tmp_path, "demo")
    original = chapter.read_text(encoding="utf-8")
    version = store.checkpoint("ch_001", label="初稿")
    changed = original.replace("钟声", "远处的钟声")
    chapter.write_text(changed, encoding="utf-8")

    preview = store.compare("ch_001", version.version_id)

    assert preview["version"]["version_id"] == version.version_id
    assert preview["current"]["revision"] == store.fingerprint(changed)
    assert preview["diff"]["hunks"]
    assert "远处的钟声" in preview["diff"]["hunks"][0]["before"]
    assert "远处的钟声" not in preview["diff"]["hunks"][0]["after"]
    assert chapter.read_text(encoding="utf-8") == changed


def test_annotations_relocate_only_on_one_exact_match_then_detach(tmp_path: Path) -> None:
    chapter = _project(tmp_path, "# 第一章\n\n甲乙丙，随后离开。\n")
    versions = ManuscriptVersionStore(tmp_path, "demo")
    annotations = ManuscriptAnnotationStore(tmp_path, "demo")
    original = chapter.read_text(encoding="utf-8")
    quote = "乙丙"
    start = original.index(quote)
    annotation = annotations.create(
        "ch_001",
        source_revision=versions.fingerprint(original),
        quote=quote,
        start_hint=start,
        end_hint=start + len(quote),
        note="检查节奏",
    )
    assert annotation.anchor_state == "attached"

    chapter.write_text("序章提示。\n" + original, encoding="utf-8")
    relocated = annotations.list("ch_001")[0]
    assert relocated.anchor_state == "relocated"
    assert relocated.current_start == start + len("序章提示。\n")

    chapter.write_text("乙丙。\n" + chapter.read_text(encoding="utf-8"), encoding="utf-8")
    detached = annotations.list("ch_001")[0]
    assert detached.anchor_state == "detached"
    assert detached.current_start is None and detached.current_end is None


def test_annotations_accept_document_reader_short_revision(tmp_path: Path) -> None:
    chapter = _project(tmp_path, "# 第一章\n\n甲乙丙，随后离开。\n")
    versions = ManuscriptVersionStore(tmp_path, "demo")
    annotations = ManuscriptAnnotationStore(tmp_path, "demo")
    content = chapter.read_text(encoding="utf-8")
    quote = "乙丙"
    start = content.index(quote)
    full_revision = versions.fingerprint(content)

    annotation = annotations.create(
        "ch_001",
        source_revision=full_revision.removeprefix("sha256:")[:16],
        quote=quote,
        start_hint=start,
        end_hint=start + len(quote),
        note="短 revision 兼容测试",
    )

    assert annotation.source_revision == full_revision
    assert annotations.list("ch_001")[0].anchor_state == "attached"


def test_ai_revision_creates_recoverable_checkpoint_before_apply(tmp_path: Path) -> None:
    chapter = _project(tmp_path, "林舟推开钟楼的门。")
    original = chapter.read_text(encoding="utf-8")
    selected = "钟楼的门"
    start = original.index(selected)
    revisions = RevisionService(tmp_path, "demo", generator=lambda payload: "钟楼那扇门")
    proposal = revisions.create_selection(
        chapter_id="ch_001",
        start=start,
        end=start + len(selected),
        original_text=selected,
    )

    revisions.apply(proposal["proposal_id"])

    versions = ManuscriptVersionStore(tmp_path, "demo").list("ch_001")
    assert len(versions) == 1
    assert versions[0].reason == "ai_revision"
    assert ManuscriptVersionStore(tmp_path, "demo").load(
        "ch_001", versions[0].version_id
    )[1] == original


def test_agent_tools_expose_versions_annotations_and_guard_restore(tmp_path: Path) -> None:
    _project(tmp_path)
    executors = build_tool_executors(tmp_path)
    assert {"manage_manuscript_versions", "manage_annotations"}.issubset(executors)
    created = executors["manage_manuscript_versions"](
        {"action": "checkpoint", "chapter_id": "ch_001", "label": "Agent 快照"}
    )
    assert created["reason"] == "manual"

    instruction = "先看看版本，不要恢复"
    guarded = guard_confirmable_executors(
        executors,
        instruction=lambda: instruction,
    )
    blocked = guarded["manage_manuscript_versions"](
        {
            "action": "restore",
            "chapter_id": "ch_001",
            "version_id": created["version_id"],
            "revision": created["source_revision"],
            "confirm": True,
        }
    )
    assert blocked["blocked"] is True
    instruction = "确认恢复这个版本"
    restored = guarded["manage_manuscript_versions"](
        {
            "action": "restore",
            "chapter_id": "ch_001",
            "version_id": created["version_id"],
            "revision": created["source_revision"],
            "confirm": True,
        }
    )
    assert restored["version_id"] == created["version_id"]
    assert restored["acceptance"]["source"] == "history_restore"


def test_studio_contract_and_cli_checkpoint_smoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    chapter = _project(tmp_path)
    app = StudioApplication(tmp_path)
    try:
        checkpoint = app.manuscript_editing_action(
            {"action": "checkpoint", "chapter_id": "ch_001", "label": "Studio"}
        )
        original = chapter.read_text(encoding="utf-8")
        changed = original + "\n恢复前新增。\n"
        chapter.write_text(changed, encoding="utf-8")
        changed_revision = ManuscriptVersionStore.fingerprint(changed)
        ManuscriptAcceptanceService(tmp_path, "demo").start_acceptance(
            "ch_001",
            source="manual",
            expected_previous_revision=ManuscriptVersionStore.fingerprint(original),
        )
        with pytest.raises(StudioError) as unconfirmed:
            app.manuscript_editing_action(
                {
                    "action": "restore",
                    "chapter_id": "ch_001",
                    "version_id": checkpoint["version_id"],
                    "revision": changed_revision,
                }
            )
        assert unconfirmed.value.status == HTTPStatus.PRECONDITION_REQUIRED
        restored = app.manuscript_editing_action(
            {
                "action": "restore",
                "chapter_id": "ch_001",
                "version_id": checkpoint["version_id"],
                "revision": changed_revision,
                "confirm": True,
            }
        )
        assert restored["document"]["revision"] == checkpoint["source_revision"]
        assert restored["acceptance"]["source"] == "history_restore"
        mutation = restored["mutation_summary"]
        assert mutation["source_revision"] == changed_revision
        assert mutation["result_revision"] == checkpoint["source_revision"]
        assert mutation["items"][0]["before"]["value"] == changed
        assert mutation["items"][0]["after"]["value"] == original
    finally:
        if app._task_runner is not None:
            app._task_runner.shutdown(wait=True)

    capsys.readouterr()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["openwrite", "version", "checkpoint", "ch_001", "--label", "CLI"],
    )
    assert cli_module.main() == 0
    assert json.loads(capsys.readouterr().out)["label"] == "CLI"


def test_annotation_cli_rejects_invalid_range(tmp_path: Path) -> None:
    _project(tmp_path)
    args = SimpleNamespace(
        annotation_action="create",
        chapter_id="ch_001",
        revision="sha256:" + "0" * 64,
        start=-1,
        end=2,
        note="bad",
    )
    assert cli_module._cmd_annotation(args) == 1


def test_manuscript_editing_http_api_round_trip(tmp_path: Path) -> None:
    _project(tmp_path)
    server = create_server(tmp_path, port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    opener = build_opener(ProxyHandler({}))
    request = Request(
        f"http://127.0.0.1:{server.server_port}/api/manuscript-editing",
        method="POST",
        data=json.dumps(
            {"action": "checkpoint", "chapter_id": "ch_001", "label": "HTTP"}
        ).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-OpenWrite-Studio": "1"},
    )
    try:
        with opener.open(request) as response:
            payload = json.loads(response.read())
        assert payload["label"] == "HTTP"
        assert payload["chapter_id"] == "ch_001"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_studio_annotation_dom_uses_form_and_safe_text_rendering() -> None:
    root = Path(__file__).parents[1] / "tools" / "studio_assets"
    html = (root / "index.html").read_text(encoding="utf-8")
    javascript = (root / "js" / "revisions.js").read_text(encoding="utf-8")
    assert 'id="manuscript-annotation-form"' in html
    assert 'id="manuscript-annotation-note"' in html
    assert "window.prompt" not in javascript
    assert "button.innerHTML" not in javascript
    assert "await reopenDocument(state.document.path)" in javascript
