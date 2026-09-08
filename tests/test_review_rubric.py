import pytest

from tools.review_rubric import (
    DIMENSION_NAMES,
    GATE_CHECK_IDS,
    QUALITY_DOMAINS,
    aggregate_review,
    attach_optional_criteria,
    legacy_adapter,
    optional_criteria_payload,
    rubric_payload,
    selected_domains,
)


def evaluated_domain(domain, earned=None):
    return {
        "id": domain.id,
        "criteria": [
            {
                "id": criterion.id,
                "status": "evaluated",
                "earned": criterion.max_points if earned is None else earned,
                "evidence": ["正文证据"],
                "rationale": "有明确正文证据",
            }
            for criterion in domain.criteria
        ],
    }


def test_rubric_maps_all_37_checks_once_and_weights_100():
    payload = rubric_payload()
    mapped = [
        check
        for domain in payload["domains"]
        for criterion in domain["criteria"]
        for check in criterion["legacy_check_ids"]
    ] + list(GATE_CHECK_IDS)
    assert sorted(mapped) == list(DIMENSION_NAMES)
    assert len(mapped) == len(set(mapped)) == 37
    assert sum(domain.weight for domain in QUALITY_DOMAINS) == 100


def test_additive_score_is_monotonic_and_issue_count_does_not_subtract():
    baseline = [evaluated_domain(domain, earned=2) for domain in QUALITY_DOMAINS]
    improved = [evaluated_domain(domain, earned=3) for domain in QUALITY_DOMAINS]
    many_warnings = [
        {"severity": "warning", "description": f"warning-{index}"}
        for index in range(50)
    ]
    baseline_result = aggregate_review(baseline, many_warnings)
    improved_result = aggregate_review(improved, many_warnings)
    assert baseline_result["quality_score"] < improved_result["quality_score"]
    assert aggregate_review(improved, [])["quality_score"] == improved_result["quality_score"]


def test_production_gate_is_disabled_until_human_thresholds_are_calibrated():
    raw = [evaluated_domain(domain) for domain in QUALITY_DOMAINS]
    advisory = aggregate_review(raw, [])
    assert advisory["delivery_status"] == "pass"
    assert advisory["threshold_calibration"] == {
        "status": "uncalibrated",
        "production_gate_enabled": False,
    }
    assert advisory["production_gate_status"] == "disabled_uncalibrated"

    with pytest.raises(ValueError, match="requires calibrated human thresholds"):
        aggregate_review(raw, [], production_gate_enabled=True)

    calibrated = aggregate_review(
        raw,
        [],
        production_gate_enabled=True,
        calibration_status="calibrated",
    )
    assert calibrated["production_gate_status"] == "pass"


def test_not_applicable_and_inconclusive_do_not_become_zero_quality():
    raw = [evaluated_domain(domain) for domain in QUALITY_DOMAINS]
    canon = next(item for item in raw if item["id"] == "canon")
    canon["criteria"][0]["status"] = "not_applicable"
    canon["criteria"][0]["earned"] = 0
    canon["criteria"][0]["evidence"] = []
    canon["criteria"][1]["status"] = "inconclusive"
    canon["criteria"][1]["earned"] = 0
    canon["criteria"][1]["evidence"] = []
    result = aggregate_review(raw, [])
    assert result["quality_score"] == 100
    assert 0 < result["coverage"] < 1
    assert result["delivery_status"] == "pass"


def test_blocker_changes_gate_not_quality_score():
    raw = [evaluated_domain(domain) for domain in QUALITY_DOMAINS]
    clean = aggregate_review(raw, [])
    blocked = aggregate_review(raw, [{"review_severity": "critical", "description": "正典冲突"}])
    assert blocked["quality_score"] == clean["quality_score"] == 100
    assert blocked["gate_status"] == "blocked"
    assert blocked["delivery_status"] == "blocked"
    assert legacy_adapter(blocked) == {"score": 100.0, "passed": False}


def test_positive_points_without_evidence_become_inconclusive():
    raw = [evaluated_domain(domain) for domain in QUALITY_DOMAINS]
    raw[0]["criteria"][0]["evidence"] = []
    result = aggregate_review(raw, [])
    criterion = result["domains"][0]["criteria"][0]
    assert criterion["status"] == "inconclusive"
    assert criterion["earned"] == 0
    assert result["quality_score"] == 100
    assert result["coverage"] == 0.95


def test_partial_dimension_selection_keeps_only_relevant_criteria():
    domains = selected_domains([1, 16, 27])
    assert [domain.id for domain in domains] == ["character"]
    assert [criterion.id for criterion in domains[0].criteria] == [
        "character_fidelity",
        "dialogue_behavior",
    ]


def test_web_novel_optional_criteria_do_not_score_or_consume_legacy_checks():
    catalog = optional_criteria_payload()
    assert catalog["scoring"] is False
    assert catalog["forms"] == ["web_novel"]
    names = {item["name"] for item in catalog["criteria"]}
    assert names == {"钩子", "黄金三章", "追读力"}
    assert all(item["max"] == 0 for item in catalog["criteria"])
    assert all(item["legacy_check_ids"] == [] for item in catalog["criteria"])

    payload = rubric_payload()
    mapped = [
        check
        for domain in payload["domains"]
        for criterion in domain["criteria"]
        for check in criterion["legacy_check_ids"]
    ] + list(GATE_CHECK_IDS)
    assert sorted(mapped) == list(DIMENSION_NAMES)
    assert sum(len(domain["criteria"]) for domain in payload["domains"]) == 20

    plain = attach_optional_criteria(QUALITY_DOMAINS, form=None)
    assert plain == QUALITY_DOMAINS
    literary = attach_optional_criteria(QUALITY_DOMAINS, form="literary")
    assert literary == QUALITY_DOMAINS

    opening = attach_optional_criteria(QUALITY_DOMAINS, form="网文", chapter_id="ch_001")
    plot = next(domain for domain in opening if domain.id == "plot")
    pacing = next(domain for domain in opening if domain.id == "pacing")
    assert [item.id for item in plot.criteria][-2:] == ["web_hook", "retention"]
    assert pacing.criteria[-1].id == "golden_opening"
    assert plot.weight == 20
    assert pacing.weight == 15
    assert all(
        item.max_points == 0
        for item in plot.criteria
        if item.id in {"web_hook", "retention"}
    )

    later = attach_optional_criteria(QUALITY_DOMAINS, form="web_novel", chapter_id="ch_010")
    later_pacing = next(domain for domain in later if domain.id == "pacing")
    assert "golden_opening" not in {item.id for item in later_pacing.criteria}
    later_plot = next(domain for domain in later if domain.id == "plot")
    assert {item.id for item in later_plot.criteria} >= {"web_hook", "retention"}

    baseline = [evaluated_domain(domain) for domain in QUALITY_DOMAINS]
    with_optional = [evaluated_domain(domain) for domain in opening]
    assert aggregate_review(baseline, [])["quality_score"] == 100
    optional_result = aggregate_review(with_optional, [], domains=opening)
    assert optional_result["quality_score"] == 100
    assert optional_result["coverage"] == 1
    assert optional_result["legacy_check_ids"] == list(DIMENSION_NAMES)
