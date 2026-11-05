"""A stale review must never be deliverable, on either contract version.

The v2 path enforced freshness through ``freshness_status``; the v1 path had no
equivalent, so a review explicitly marked stale — the manuscript changed after it
— was still reported deliverable, and export preflight / acceptance approved the
chapter on the strength of a review that no longer described its text.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.init_project import init_project
from tools.review_store import (
    ReviewStore,
    canonical_review_decision,
    review_is_deliverable,
)


@pytest.fixture()
def store(tmp_path: Path) -> ReviewStore:
    init_project(tmp_path, "demo")
    chapter = tmp_path / "data" / "novels" / "demo" / "data" / "manuscript" / "arc_001" / "ch_001.md"
    chapter.parent.mkdir(parents=True, exist_ok=True)
    chapter.write_text("第一章 正文。\n", encoding="utf-8")
    return ReviewStore(tmp_path, "demo")


def test_a_fresh_v1_review_is_deliverable(store: ReviewStore):
    store.save("ch_001", {"score": 99, "passed": True})
    current = store._source_revision("ch_001")
    assert review_is_deliverable(store.load("ch_001"), current_source_revision=current)


def test_a_stale_v1_review_is_not_deliverable(store: ReviewStore):
    store.save("ch_001", {"score": 99, "passed": True})
    current = store._source_revision("ch_001")
    store.mark_stale("ch_001", reason="chapter_changed")
    review = store.load("ch_001")
    assert review.get("stale") is True
    # The score still says pass; the staleness must win.
    assert not review_is_deliverable(review, current_source_revision=current)
    decision = canonical_review_decision(review, current_source_revision=current)
    assert decision["delivery_status"] == "stale"


def test_the_v1_adapter_computes_freshness_instead_of_assuming_unknown(store: ReviewStore):
    store.save("ch_001", {"score": 99, "passed": True})
    current = store._source_revision("ch_001")
    decision = canonical_review_decision(store.load("ch_001"), current_source_revision=current)
    # It used to be hardcoded to "unknown", which hid a real mismatch.
    assert decision["freshness_status"] == "current"
    stale_decision = canonical_review_decision(
        store.load("ch_001"), current_source_revision="sha256:" + "0" * 64
    )
    assert stale_decision["freshness_status"] == "stale"


def test_save_recomputes_the_source_revision_from_the_manuscript(store: ReviewStore):
    real = store._source_revision("ch_001")
    store.save("ch_001", {"score": 99, "passed": True, "source_revision": "sha256:" + "0" * 64})
    # A caller-supplied revision used to be stored verbatim, letting a review be
    # stamped current for text it never reviewed.
    assert store.load("ch_001")["source_revision"] == real
