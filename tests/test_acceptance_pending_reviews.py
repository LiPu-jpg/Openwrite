"""An unacknowledged review must not vanish when a newer operation appears.

`inspect` derived `needs_review` only from `latest_operation_id`. Any later
operation moved that pointer, so an earlier operation's unacknowledged review
items became invisible: the surface flipped from `needs_review` to `current` and
`require_current` let the next chapter generate against an outline the author was
explicitly told to review.
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
    for index in (1, 2, 3):
        chapter = tmp_path / "data/novels/demo/data/manuscript/arc_001" / f"ch_{index:03d}.md"
        chapter.parent.mkdir(parents=True, exist_ok=True)
        chapter.write_text(f"# ch_{index:03d}\n\n旧信从雨中送来。\n", encoding="utf-8")
    return svc


def _baseline(service: ManuscriptAcceptanceService) -> str:
    operation = service.establish_baseline(confirm=True)
    service.resume(operation["operation_id"], analyzer=lambda *a: {"chapter_summary": "旧信抵达。"})
    return operation["operation_id"]


def _revise(service: ManuscriptAcceptanceService, chapter_id: str, previous: str) -> str:
    chapter = service.novel_root / "data/manuscript/arc_001" / f"{chapter_id}.md"
    chapter.write_text(f"# {chapter_id}\n\n修订后的正文。\n", encoding="utf-8")
    revision = service.fingerprint(chapter.read_bytes().decode("utf-8"))
    operation = service.start_acceptance(
        chapter_id, source="manual", expected_previous_revision=previous
    )
    service._write_operation(
        {
            **service.operation(operation["operation_id"]),
            "impacts": [
                {"kind": "outline", "status": "needs_review", "chapter_id": chapter_id},
                {"kind": "foreshadowing", "status": "needs_review", "chapter_id": chapter_id},
            ],
        }
    )
    return operation["operation_id"]


def test_a_newer_operation_does_not_hide_an_unacknowledged_review(service: ManuscriptAcceptanceService):
    _baseline(service)
    surface = service.inspect()
    previous = {
        item["chapter_id"]: item["accepted_revision"] for item in surface["chapters"]
    }
    revising = _revise(service, "ch_001", previous["ch_001"])
    # The head is pending, so the aggregate status is "pending" — but the review
    # items must be visible either way.
    assert len(service.inspect()["needs_review"]) == 2

    # A later operation moves `latest_operation_id` away from the revising one.
    later = _revise(service, "ch_002", previous["ch_002"])
    assert later != revising

    after = service.inspect()
    # The earlier operation still owns ch_001's head, so its review items must
    # still be visible and still block. Before the fix they were invisible here.
    assert len(after["needs_review"]) >= 2
    assert after["blocking"] is True
    with pytest.raises(Exception):
        service.require_current("ch_003")
