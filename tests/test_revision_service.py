from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.cli import _save_chapter
from tools.init_project import init_project
from tools.review_store import ReviewStore
from tools.revision_service import RevisionError, RevisionService
from tools.revision_store import RevisionStore


def _project(tmp_path: Path) -> tuple[Path, Path]:
    init_project(tmp_path, "demo")
    chapter = _save_chapter(
        tmp_path,
        "demo",
        "ch_001",
        "第一章：雨夜",
        "林舟推开钟楼的门。\n\n门后没有人，只有一只停摆的钟。",
    )
    return tmp_path, chapter


def _review_issue(root: Path, chapter: Path) -> tuple[str, str]:
    content = chapter.read_text(encoding="utf-8")
    quote = "门后没有人"
    start = content.index(quote)
    store = ReviewStore(root, "demo")
    store.save(
        "ch_001",
        {
            "ok": True,
            "score": 76,
            "passed": False,
            "issues": 1,
            "issue_details": [
                {
                    "id": "issue_door",
                    "dimension": "pacing.opening",
                    "severity": "high",
                    "summary": "判断落得过快",
                    "evidence": {"quote": quote},
                    "anchor": {"start_hint": start, "end_hint": start + len(quote)},
                    "suggestion": "保留一瞬迟疑",
                    "auto_fixable": True,
                }
            ],
        },
    )
    revisioned = store.load_revisioned("ch_001")
    assert revisioned is not None
    return revisioned[1], RevisionService.fingerprint(content)


def test_revision_store_persists_proposals_outside_canonical_source(tmp_path: Path):
    root, _ = _project(tmp_path)
    store = RevisionStore(root, "demo")
    proposal = {
        "proposal_id": store.create_id(),
        "chapter_id": "ch_001",
        "kind": "selection_rewrite",
        "status": "proposed",
        "source_revision": "sha256:test",
        "selection": {"start": 0, "end": 1, "original_text": "林"},
        "request": {},
        "review_issue_ids": [],
        "replacement_text": "他",
        "rationale": "",
        "risk_flags": [],
        "created_at": "2026-08-02T00:00:00+00:00",
        "applied_at": None,
    }

    path = store.save(proposal)

    assert path.is_file()
    assert "data/revisions/ch_001" in path.as_posix()
    assert store.load(proposal["proposal_id"]) == proposal


def test_selection_revision_is_previewed_then_atomically_applied(tmp_path: Path):
    root, chapter = _project(tmp_path)
    original = chapter.read_text(encoding="utf-8")
    selected = "门后没有人"
    start = original.index(selected)

    service = RevisionService(
        root,
        "demo",
        generator=lambda payload: {
            "replacement_text": "门后仍然没有人",
            "rationale": "保留事件结果，只增加迟疑感。",
            "risk_flags": ["节奏轻微放慢"],
        },
    )
    proposal = service.create_selection(
        chapter_id="ch_001",
        start=start,
        end=start + len(selected),
        original_text=selected,
        action="rewrite",
        instruction="让判断更迟疑",
    )

    assert chapter.read_text(encoding="utf-8") == original
    assert proposal["status"] == "proposed"
    assert proposal["diff"]["hunks"]

    applied = service.apply(proposal["proposal_id"])

    assert applied["status"] == "applied"
    assert applied["history_version_id"].startswith("ver_")
    assert "门后仍然没有人" in chapter.read_text(encoding="utf-8")
    acceptance = applied["acceptance"]
    assert acceptance["source"] == "revision"
    assert acceptance["chapter_id"] == "ch_001"
    assert acceptance["expected_previous_revision"] == service.fingerprint(original)
    assert acceptance["accepted_revision"] == ""
    assert acceptance["target_revision"] == applied["applied_revision"]
    assert acceptance["status"] == "pending"
    mutation = applied["mutation_summary"]
    assert mutation["execution_status"] == "committed"
    assert mutation["source_revision"] == proposal["source_revision"]
    assert mutation["result_revision"] == applied["applied_revision"]
    assert mutation["items"][0]["entity_kind"] == "manuscript"
    assert mutation["items"][0]["field"] == "content.selection"
    assert mutation["items"][0]["before"]["value"] == selected
    assert mutation["items"][0]["after"]["value"] == "门后仍然没有人"
    backup = root / "data" / "novels" / "demo" / applied["backup_path"]
    assert backup.read_text(encoding="utf-8") == original


def test_revision_apply_accepts_reviewed_subset_and_records_hunks(tmp_path: Path):
    root, chapter = _project(tmp_path)
    original = chapter.read_text(encoding="utf-8")
    selected = "林舟推开钟楼的门。\n\n门后没有人，只有一只停摆的钟。"
    start = original.index(selected)
    service = RevisionService(
        root,
        "demo",
        generator=lambda payload: "林舟缓缓推开钟楼的门。\n\n门后仍然没有人，只有一只停摆的钟。",
    )
    proposal = service.create_selection(
        chapter_id="ch_001",
        start=start,
        end=start + len(selected),
        original_text=selected,
    )

    assert len(proposal["diff"]["hunks"]) == 2
    accepted = "林舟缓缓推开钟楼的门。\n\n门后没有人，只有一只停摆的钟。"
    applied = service.apply(
        proposal["proposal_id"],
        replacement_text=accepted,
        selected_hunk_ids=["hunk_0"],
    )

    assert accepted in chapter.read_text(encoding="utf-8")
    assert applied["accepted_replacement_text"] == accepted
    assert applied["selected_hunk_ids"] == ["hunk_0"]


def test_revision_apply_composes_selected_hunks_when_client_omits_replacement(
    tmp_path: Path,
):
    root, chapter = _project(tmp_path)
    original = chapter.read_text(encoding="utf-8")
    selected = "林舟推开钟楼的门。\n\n门后没有人，只有一只停摆的钟。"
    start = original.index(selected)
    service = RevisionService(
        root,
        "demo",
        generator=lambda payload: "林舟缓缓推开钟楼的门。\n\n门后仍然没有人，只有一只停摆的钟。",
    )
    proposal = service.create_selection(
        chapter_id="ch_001",
        start=start,
        end=start + len(selected),
        original_text=selected,
    )

    applied = service.apply(
        proposal["proposal_id"], selected_hunk_ids=["hunk_0"]
    )

    accepted = "林舟缓缓推开钟楼的门。\n\n门后没有人，只有一只停摆的钟。"
    assert applied["accepted_replacement_text"] == accepted
    assert accepted in chapter.read_text(encoding="utf-8")


def test_revision_apply_rejects_text_that_does_not_match_selected_hunks(
    tmp_path: Path,
):
    root, chapter = _project(tmp_path)
    original = chapter.read_text(encoding="utf-8")
    selected = "林舟推开钟楼的门。\n\n门后没有人，只有一只停摆的钟。"
    start = original.index(selected)
    service = RevisionService(
        root,
        "demo",
        generator=lambda payload: "林舟缓缓推开钟楼的门。\n\n门后仍然没有人，只有一只停摆的钟。",
    )
    proposal = service.create_selection(
        chapter_id="ch_001",
        start=start,
        end=start + len(selected),
        original_text=selected,
    )

    with pytest.raises(RevisionError) as mismatch:
        service.apply(
            proposal["proposal_id"],
            replacement_text="客户端提交了另一个完整改写。",
            selected_hunk_ids=["hunk_0"],
        )

    assert mismatch.value.code == "HUNK_SELECTION_MISMATCH"
    assert chapter.read_text(encoding="utf-8") == original
    assert service.get(proposal["proposal_id"])["status"] == "proposed"


def test_revision_apply_is_idempotently_blocked_after_first_commit(tmp_path: Path):
    root, chapter = _project(tmp_path)
    original = chapter.read_text(encoding="utf-8")
    selected = "停摆的钟"
    start = original.index(selected)
    service = RevisionService(root, "demo", generator=lambda payload: "生锈的钟")
    proposal = service.create_selection(
        chapter_id="ch_001",
        start=start,
        end=start + len(selected),
        original_text=selected,
    )

    first = service.apply(proposal["proposal_id"])
    first_content = chapter.read_text(encoding="utf-8")
    version_root = (
        root
        / "data"
        / "novels"
        / "demo"
        / "data"
        / "manuscript_versions"
        / "ch_001"
    )
    first_versions = list(
        version_root.glob("*.json")
    )
    with pytest.raises(RevisionError) as duplicate:
        service.apply(proposal["proposal_id"])

    assert duplicate.value.code == "REVISION_NOT_PROPOSED"
    assert chapter.read_text(encoding="utf-8") == first_content
    assert first["applied_revision"] == service.fingerprint(first_content)
    assert len(list((first_versions[0].parent).glob("*.json"))) == len(first_versions)


def test_revision_apply_marks_proposal_stale_when_source_changed(tmp_path: Path):
    root, chapter = _project(tmp_path)
    original = chapter.read_text(encoding="utf-8")
    selected = "停摆的钟"
    start = original.index(selected)
    service = RevisionService(root, "demo", generator=lambda payload: "生锈的钟")
    proposal = service.create_selection(
        chapter_id="ch_001",
        start=start,
        end=start + len(selected),
        original_text=selected,
    )
    chapter.write_text(original + "\n\n窗外传来脚步声。", encoding="utf-8")

    with pytest.raises(RevisionError) as conflict:
        service.apply(proposal["proposal_id"])

    assert conflict.value.code == "DOCUMENT_CONFLICT"
    assert conflict.value.recoverable is True
    assert service.get(proposal["proposal_id"])["status"] == "stale"


def test_review_issue_revision_uses_quote_anchor_and_invalidates_review(tmp_path: Path):
    root, chapter = _project(tmp_path)
    content = chapter.read_text(encoding="utf-8")
    quote = "门后没有人"
    start = content.index(quote)
    ReviewStore(root, "demo").save(
        "ch_001",
        {
            "ok": True,
            "score": 76,
            "passed": False,
            "issues": 1,
            "issue_details": [
                {
                    "id": "issue_door",
                    "dimension": "pacing.opening",
                    "severity": "high",
                    "summary": "判断落得过快",
                    "evidence": {"quote": quote},
                    "anchor": {"start_hint": start, "end_hint": start + len(quote)},
                    "suggestion": "保留一瞬迟疑",
                    "auto_fixable": True,
                }
            ],
        },
    )
    captured: dict = {}

    def generator(payload: dict) -> dict:
        captured.update(payload)
        return {
            "replacement_text": "门后看起来没有人",
            "rationale": "把绝对判断改成现场观察。",
            "risk_flags": [],
        }

    service = RevisionService(root, "demo", generator=generator)
    proposal = service.create_from_review(
        chapter_id="ch_001",
        issue_ids=["issue_door"],
    )
    applied = service.apply(proposal["proposal_id"])

    assert captured["review_issues"][0]["dimension"] == "pacing.opening"
    assert "门后看起来没有人" in chapter.read_text(encoding="utf-8")
    review = ReviewStore(root, "demo").load("ch_001")
    assert review is not None and review["stale"] is True
    history = review["revision_history"][0]
    assert history["proposal_id"] == applied["proposal_id"]
    assert history["applied_revision"] == applied["applied_revision"]
    assert history["issue_ids"] == ["issue_door"]
    assert history["original_issue_ids"] == ["issue_door"]
    assert history["review_revision"] == proposal["review_revision"]
    assert history["source_revision"] == proposal["source_revision"]

    ReviewStore(root, "demo").save(
        "ch_001",
        {
            "source_revision": applied["applied_revision"],
            "score": 84,
            "passed": True,
            "issue_details": [],
        },
    )
    rereview = ReviewStore(root, "demo").load_revisioned("ch_001")
    assert rereview is not None
    closure = rereview[0]["revision_closures"][-1]
    assert closure["proposal_id"] == applied["proposal_id"]
    assert closure["rereview_review_revision"] == rereview[1]
    assert closure["issue_outcomes"] == [
        {"issue_id": "issue_door", "outcome": "resolved"}
    ]
    assert closure["regressions"] == []


def test_review_revision_packet_binds_review_document_issues_and_hunks(tmp_path: Path):
    root, chapter = _project(tmp_path)
    review_revision, document_revision = _review_issue(root, chapter)
    service = RevisionService(
        root,
        "demo",
        generator=lambda payload: {
            "replacement_text": "门后看起来没有人",
            "rationale": "保留现场观察",
            "risk_flags": [],
        },
    )

    proposal = service.create_from_review(
        chapter_id="ch_001",
        issue_ids=["issue_door"],
        expected_review_revision=review_revision,
        expected_document_revision=document_revision,
    )

    assert proposal["review_revision"] == review_revision
    assert proposal["review_source_revision"] == document_revision
    assert proposal["review_issue_provenance"][0]["issue_id"] == "issue_door"
    assert proposal["issue_hunk_provenance"] == [
        {
            "issue_id": "issue_door",
            "hunk_ids": ["hunk_0"],
            "relation": "generated_in_shared_proposal_scope",
            "review_revision": review_revision,
            "source_revision": document_revision,
        }
    ]


def test_review_revision_rejects_stale_packet_before_calling_model(tmp_path: Path):
    root, chapter = _project(tmp_path)
    review_revision, document_revision = _review_issue(root, chapter)
    called = False

    def generator(payload: dict) -> str:
        nonlocal called
        called = True
        return "门后看起来没有人"

    ReviewStore(root, "demo").save(
        "ch_001",
        {"score": 91, "passed": True, "issue_details": []},
    )
    service = RevisionService(root, "demo", generator=generator)

    with pytest.raises(RevisionError) as conflict:
        service.create_from_review(
            chapter_id="ch_001",
            issue_ids=["issue_door"],
            expected_review_revision=review_revision,
            expected_document_revision=document_revision,
        )

    assert conflict.value.code == "REVIEW_CONFLICT"
    assert conflict.value.recoverable is True
    assert called is False


def test_review_revision_discards_generation_when_document_changes_during_model_call(
    tmp_path: Path,
):
    root, chapter = _project(tmp_path)
    review_revision, document_revision = _review_issue(root, chapter)
    original = chapter.read_text(encoding="utf-8")

    def generator(payload: dict) -> str:
        chapter.write_text(original + "\n\n外部编辑。\n", encoding="utf-8")
        return "门后看起来没有人"

    service = RevisionService(root, "demo", generator=generator)
    with pytest.raises(RevisionError) as conflict:
        service.create_from_review(
            chapter_id="ch_001",
            issue_ids=["issue_door"],
            expected_review_revision=review_revision,
            expected_document_revision=document_revision,
        )

    assert conflict.value.code == "DOCUMENT_CONFLICT"
    assert conflict.value.recoverable is True
    assert service.list(chapter_id="ch_001") == []


def test_revision_validation_failure_keeps_document_and_proposal_unapplied(tmp_path: Path):
    root, chapter = _project(tmp_path)
    original = chapter.read_text(encoding="utf-8")
    selected = "门后没有人"
    start = original.index(selected)
    service = RevisionService(
        root,
        "demo",
        generator=lambda payload: "不是没人，而是所有人都藏了起来",
    )
    proposal = service.create_selection(
        chapter_id="ch_001",
        start=start,
        end=start + len(selected),
        original_text=selected,
    )

    with pytest.raises(RevisionError) as invalid:
        service.apply(proposal["proposal_id"])

    assert invalid.value.code == "REVISION_VALIDATION_FAILED"
    assert chapter.read_text(encoding="utf-8") == original
    stored = json.loads(
        RevisionStore(root, "demo")
        .path_for(proposal["proposal_id"], chapter_id="ch_001")
        .read_text(encoding="utf-8")
    )
    assert stored["status"] == "proposed"
