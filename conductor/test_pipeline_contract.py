from __future__ import annotations

import pytest

from conductor.pipeline import StudioError, canonical_review_decision, review_gate


CANONICAL = {
    "schema_version": "openwrite.review.v2",
    "execution_status": "completed",
    "quality_score": 90,
    "coverage": 1,
    "gate_status": "pass",
    "delivery_status": "pass",
    "production_gate_status": "disabled_uncalibrated",
}


def test_conductor_uses_only_canonical_delivery_status() -> None:
    assert review_gate({"score": 0, "passed": False, "review_v2": CANONICAL}, 0) is True
    blocked = {**CANONICAL, "delivery_status": "blocked"}
    assert review_gate({"score": 100, "passed": True, "review_v2": blocked}, 0) is False


def test_conductor_rejects_legacy_only_review() -> None:
    with pytest.raises(StudioError) as error:
        canonical_review_decision({"score": 100, "passed": True})
    assert error.value.code == "REVIEW_V2_REQUIRED"


def test_conductor_rejects_incomplete_v2_review() -> None:
    with pytest.raises(StudioError) as error:
        canonical_review_decision({"review_v2": {"delivery_status": "pass"}})
    assert error.value.code == "INVALID_REVIEW_V2"


def test_dog_manifest_trusts_v2_over_legacy_fields() -> None:
    from conductor.dog_review import build_review_manifest

    review = {
        "score": 0, "passed": False,
        "issue_details": [{"dimension": 2, "severity": "critical", "review_severity": "critical"}],
        "review_v2": {
            "schema_version": "openwrite.review.v2",
            "execution_status": "completed",
            "quality_score": 90,
            "coverage": 1,
            "gate_status": "pass",
            "delivery_status": "pass",
            "production_gate_status": "disabled_uncalibrated",
            "requested_dimensions": [1, 2, 3],
        },
    }
    manifest, _ = build_review_manifest(review, "ch_090", 70)
    assert manifest["decisionSource"] == "v2"
    assert manifest["gateStatus"] == "pass"
    assert manifest["deliveryStatus"] == "pass"
