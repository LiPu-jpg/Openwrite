import json
from pathlib import Path

from tools.review_rubric import QUALITY_DOMAINS, aggregate_review


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "review_v2"


def _cases() -> list[dict]:
    payload = json.loads((FIXTURE_ROOT / "golden_cases.json").read_text(encoding="utf-8"))
    assert payload["annotation_status"] == "synthetic_contract_fixture_not_human_calibration"
    return payload["cases"]


def _domain_results(case: dict) -> list[dict]:
    criteria = case["criteria"]
    return [
        {
            "id": domain.id,
            "criteria": [
                {
                    "id": spec.id,
                    "status": criteria[spec.id]["status"],
                    "earned": criteria[spec.id]["earned"],
                    "evidence": criteria[spec.id]["evidence"],
                    "rationale": "Synthetic calibration annotation",
                }
                for spec in domain.criteria
            ],
        }
        for domain in QUALITY_DOMAINS
    ]


def _historical_v1(issues: list[dict]) -> dict:
    critical = sum(item["review_severity"] == "critical" for item in issues)
    warnings = sum(item["review_severity"] == "warning" for item in issues)
    return {
        "critical_count": critical,
        "warning_count": warnings,
        "score": max(0, 100 - critical * 20 - warnings * 5),
        "passed": critical == 0,
    }


def test_golden_review_cases_have_locatable_positive_evidence_and_expected_scores():
    observed_scores = {}
    for case in _cases():
        manuscript = (FIXTURE_ROOT / case["manuscript"]).read_text(encoding="utf-8")
        assert set(case["criteria"]) == {
            criterion.id for domain in QUALITY_DOMAINS for criterion in domain.criteria
        }
        for criterion in case["criteria"].values():
            if criterion["earned"] > 0:
                assert criterion["status"] == "evaluated"
                assert criterion["evidence"]
                assert all(quote in manuscript for quote in criterion["evidence"])

        result = aggregate_review(
            _domain_results(case),
            case["issues"],
            gates=case["gates"],
        )
        expected = case["expected_v2"]
        assert result["quality_score"] == expected["quality_score"]
        assert result["coverage"] == expected["coverage"]
        assert result["gate_status"] == expected["gate_status"]
        assert result["delivery_status"] == expected["delivery_status"]
        assert _historical_v1(case["issues"]) == case["historical_v1"]
        observed_scores[case["id"]] = result["quality_score"]

    assert observed_scores["high_quality"] > observed_scores["current_quality"]
    assert observed_scores["current_quality"] > observed_scores["corrupted"]


def test_golden_dual_track_exposes_legacy_pass_v2_revise_migration_case():
    current = next(case for case in _cases() if case["id"] == "current_quality")
    assert current["historical_v1"]["passed"] is True
    result = aggregate_review(
        _domain_results(current),
        current["issues"],
        gates=current["gates"],
    )
    assert result["delivery_status"] == "revise"
