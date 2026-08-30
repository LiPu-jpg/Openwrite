from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.canonical_contracts import (
    validate_benchmark_v1,
    validate_delivery_v2,
    validate_model_profile_surface,
    validate_review_v2,
)

FIXTURE = Path(__file__).parent / "fixtures" / "contracts" / "canonical_v2.json"


def test_cross_language_golden_fixture_validates_all_boundary_contracts() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    validate_review_v2(payload["review"])
    validate_delivery_v2(payload["delivery"])
    validate_model_profile_surface(payload["model_profile"])
    validate_benchmark_v1(payload["benchmark"])
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "api_key" not in serialized
    assert "secret" not in serialized


def test_review_contract_rejects_missing_independent_status() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))["review"]
    payload.pop("coverage")
    try:
        validate_review_v2(payload)
    except ValueError as error:
        assert "coverage" in str(error)
    else:  # pragma: no cover - assertion documents the contract boundary
        raise AssertionError("incomplete review contract was accepted")


def test_review_store_marks_changed_manuscript_stale_without_recomputing_score(
    tmp_path: Path,
) -> None:
    from tools.review_store import ReviewStore, canonical_review_decision

    manuscript = tmp_path / "data" / "novels" / "demo" / "data" / "manuscript" / "arc_001"
    manuscript.mkdir(parents=True)
    chapter = manuscript / "ch_001.md"
    chapter.write_text("# Chapter\n\noriginal\n", encoding="utf-8")
    store = ReviewStore(tmp_path, "demo")
    review = json.loads(FIXTURE.read_text(encoding="utf-8"))["review"]
    store.save("ch_001", {"review_v2": review, "issue_details": []})
    saved = store.load("ch_001")
    assert saved is not None
    assert saved["review_v2"]["freshness_status"] == "current"
    chapter.write_text("# Chapter\n\nchanged\n", encoding="utf-8")
    decision = canonical_review_decision(
        saved,
        current_source_revision=store._source_revision("ch_001"),
    )
    assert decision["quality_score"] == review["quality_score"]
    assert decision["freshness_status"] == "stale"
    assert decision["delivery_status"] == "stale"

def test_delivery_requires_verifiable_current_freshness(tmp_path: Path) -> None:
    from tools.review_store import ReviewStore, review_is_deliverable

    manuscript = tmp_path / "data" / "novels" / "demo" / "data" / "manuscript" / "arc_001"
    manuscript.mkdir(parents=True)
    chapter = manuscript / "ch_001.md"
    chapter.write_text("# Chapter\n\noriginal\n", encoding="utf-8")
    store = ReviewStore(tmp_path, "demo")
    review = json.loads(FIXTURE.read_text(encoding="utf-8"))["review"]
    store.save("ch_001", {"review_v2": review, "issue_details": []})
    saved = store.load("ch_001")
    assert saved is not None

    # Current SHA: deliverable.
    assert review_is_deliverable(
        saved, current_source_revision=store._source_revision("ch_001")
    ) is True

    # Old SHA: manuscript changed since review — not deliverable.
    chapter.write_text("# Chapter\n\nchanged\n", encoding="utf-8")
    assert review_is_deliverable(
        saved, current_source_revision=store._source_revision("ch_001")
    ) is False

    # Missing current SHA: freshness unknown — never a delivery approval.
    assert review_is_deliverable(saved, current_source_revision="") is False


def test_incomplete_v2_record_is_never_deliverable() -> None:
    from tools.review_store import review_is_deliverable

    partial = {"review_v2": {"delivery_status": "pass"}}
    assert review_is_deliverable(partial) is False
    assert review_is_deliverable(partial, current_source_revision="sha256:x") is False


@pytest.mark.parametrize("bad_v2", [None, [], "invalid", 42, True, {}])
def test_malformed_review_v2_never_deliverable_and_status_inconclusive(bad_v2) -> None:
    from tools.review_store import (
        canonical_review_decision,
        review_delivery_status,
        review_gate_status,
        review_is_deliverable,
        review_quality_score,
    )

    review = {"review_v2": bad_v2, "score": 95, "passed": True, "issue_details": []}
    # A present-but-malformed review_v2 can never ride legacy score/passed
    # fields into a delivery approval.
    assert review_is_deliverable(review, current_source_revision="sha256:x") is False
    assert review_is_deliverable(review) is False
    # Status helpers surface inconclusive instead of legacy-derived values.
    assert review_gate_status(review) == "inconclusive"
    assert review_delivery_status(review) == "inconclusive"
    assert review_quality_score(review) is None
    # The canonical decision adapter rejects the malformed payload outright.
    with pytest.raises(ValueError):
        canonical_review_decision(review)


def test_absent_review_v2_key_still_uses_legacy_adapter() -> None:
    from tools.review_store import (
        canonical_review_decision,
        review_is_deliverable,
    )

    legacy = {"score": 90, "passed": True, "issue_details": []}
    decision = canonical_review_decision(legacy)
    assert decision["schema_version"] == "openwrite.review.v1-adapter"
    assert review_is_deliverable(legacy) is True
    # null review_v2 is present, so it must NOT ride the legacy adapter.
    with pytest.raises(ValueError):
        canonical_review_decision({**legacy, "review_v2": None})
