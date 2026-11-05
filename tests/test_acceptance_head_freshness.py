"""An abandoned head must not claim a freshness its facts do not have.

`accept_without_model` deliberately sets `accepted_revision` to the new bytes
while leaving `facts_revision` at the previous one. `abandon` used to see the
non-empty `accepted_revision` and promote the head to `current`, so the head then
claimed the new text was both accepted and fact-current — while the facts, chapter
memory and runtime state still described the old text. The next acceptance on any
chapter then failed with ACCEPTED_SOURCE_CHANGED, whose prescribed remedy (start a
new operation) cannot repair it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.init_project import init_project
from tools.manuscript_acceptance import ManuscriptAcceptanceService


@pytest.fixture()
def service(tmp_path: Path) -> ManuscriptAcceptanceService:
    init_project(tmp_path, "demo")
    svc = ManuscriptAcceptanceService(tmp_path, "demo")
    chapter = tmp_path / "data" / "novels" / "demo" / "data" / "manuscript" / "arc_001" / "ch_001.md"
    chapter.parent.mkdir(parents=True, exist_ok=True)
    chapter.write_text("# ch_001\n\n林岑走下钟楼。\n", encoding="utf-8")
    svc.__dict__["_probe_chapter"] = chapter
    return svc


def _start(service: ManuscriptAcceptanceService) -> dict:
    chapter: Path = service.__dict__["_probe_chapter"]
    before = service.fingerprint(chapter.read_bytes().decode("utf-8"))
    return service.start_acceptance("ch_001", source="manual", expected_previous_revision=before)


def test_abandon_does_not_promote_a_facts_pending_head_to_current(service: ManuscriptAcceptanceService):
    operation = _start(service)
    service.accept_without_model(operation["operation_id"])
    # The accepted bytes differ from the facts, which still describe the old text.
    head = service.inspect()["chapters"][0]
    assert head["accepted_revision"]
    assert head["facts_revision"] != head["accepted_revision"]

    service.abandon(operation["operation_id"], confirm=True)

    after = service.inspect()
    head = after["chapters"][0]
    # It must stay honest about the pending facts, not claim `current`.
    assert head["status"] == "stale"
    assert head["operation_id"] == ""
    assert after["blocking"] is True
