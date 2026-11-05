"""Regression guards for manuscript-import terminal-state handling.

Covers the invariants an adversarial review of ``tools/manuscript_import.py``
must hold around the ``discarded`` / ``awaiting_reconciliation`` states.
Entries that were ``xfail(strict=True)`` while a defect was open become hard
failures the moment it is fixed, so the marker has to be removed deliberately.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.init_project import init_project
from tools.manuscript_acceptance import ManuscriptAcceptanceService
from tools.manuscript_import import ManuscriptImportError, ManuscriptImportService
from tools.novel_workspace import list_chapters


def _source(root: Path) -> Path:
    path = root / "legacy.md"
    path.write_text(
        "# 第一章 雨夜\n\n林岑听见钟声。\n\n# 第二章 旧宅\n\n她推开旧宅的门。\n",
        encoding="utf-8",
    )
    return path


def _start(root: Path, arc_id: str = "arc_009") -> ManuscriptImportService:
    init_project(root, "demo")
    return ManuscriptImportService(root, "demo")


def test_discarded_import_stays_discarded_and_publishes_nothing(tmp_path: Path):
    service = _start(tmp_path)
    operation = service.start(_source(tmp_path), arc_id="arc_009", start_number=1)
    preview = service.preview(operation["import_id"])

    discarded = service.discard(operation["import_id"], confirm=True)
    assert discarded["status"] == "discarded"

    # A discarded operation is terminal: its preview stays readable for the
    # audit trail, but nothing may re-arm or re-run it.
    assert service.preview(operation["import_id"])["revision"] == preview["revision"]
    assert service.resume(operation["import_id"])["status"] == "discarded"
    assert service.discard(operation["import_id"], confirm=True)["status"] == "discarded"
    assert list_chapters(tmp_path, "demo") == []


def test_confirm_structure_cannot_revive_a_discarded_import(tmp_path: Path):
    service = _start(tmp_path)
    operation = service.start(_source(tmp_path), arc_id="arc_009", start_number=1)
    preview = service.preview(operation["import_id"])
    service.discard(operation["import_id"], confirm=True)

    with pytest.raises(ManuscriptImportError) as rejected:
        service.confirm_structure(
            operation["import_id"],
            expected_preview_revision=preview["revision"],
            confirm=True,
        )
    assert rejected.value.code != "CONFIRMATION_REQUIRED"
    assert service.operation(operation["import_id"])["status"] == "discarded"
    assert list_chapters(tmp_path, "demo") == []


def test_revise_preview_cannot_revive_a_discarded_import(tmp_path: Path):
    service = _start(tmp_path)
    operation = service.start(_source(tmp_path), arc_id="arc_009", start_number=1)
    preview = service.preview(operation["import_id"])
    service.discard(operation["import_id"], confirm=True)

    with pytest.raises(ManuscriptImportError):
        service.revise_preview(
            operation["import_id"],
            expected_preview_revision=preview["revision"],
            chapters=[
                {"chapter_id": "ch_001", "title": "一", "content": "甲甲甲"},
                {"chapter_id": "ch_002", "title": "二", "content": "乙乙乙"},
            ],
        )
    assert service.operation(operation["import_id"])["status"] == "discarded"
    assert list_chapters(tmp_path, "demo") == []


def test_abandoned_acceptance_does_not_dead_end_the_import(tmp_path: Path):
    service = _start(tmp_path)
    operation = service.start(_source(tmp_path), arc_id="arc_009", start_number=1)
    service.confirm_structure(
        operation["import_id"],
        expected_preview_revision=operation["preview_revision"],
        confirm=True,
    )
    published = service.resume(operation["import_id"])
    assert published["status"] == "awaiting_reconciliation"

    # Abandoning is the remediation the acceptance layer itself recommends for
    # STALE_ACCEPTED_REVISION; it must not strand the import transaction.
    ManuscriptAcceptanceService(tmp_path, "demo").abandon(
        str(published["acceptance_operation_id"]), confirm=True
    )

    with pytest.raises(ManuscriptImportError) as failed:
        service.resume(operation["import_id"])
    assert failed.value.code == "IMPORT_RECONCILIATION_ABANDONED"

    # The dead end is gone: the import now records a real, actionable failure
    # instead of waiting forever. `discard` stays forbidden on purpose — the
    # chapters are already live in the canonical manuscript, and discarding
    # would hide them. The author is told to start a new import instead.
    after = service.operation(operation["import_id"])
    assert after["status"] == "failed"
    assert (after.get("last_error") or {}).get("code") == "IMPORT_RECONCILIATION_ABANDONED"
    assert service._has_committed_canonical(after) is True
    with pytest.raises(ManuscriptImportError) as forbidden:
        service.discard(operation["import_id"], confirm=True)
    assert forbidden.value.code == "IMPORT_DISCARD_FORBIDDEN"
