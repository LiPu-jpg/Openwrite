from pathlib import Path

from tools.review_store import (
    ReviewStore,
    normalize_review_issues,
    review_delivery_status,
    review_gate_status,
    review_is_deliverable,
    review_quality_score,
)


def test_review_issue_normalization_preserves_review_severity_and_priority():
    issues = normalize_review_issues(
        "ch_001",
        [
            {"dimension": 1, "severity": "critical", "description": "人物矛盾", "evidence": {"quote": "证据"}},
            {"dimension": 7, "severity": "warning", "description": "节奏偏慢"},
            {"dimension": 8, "severity": "info", "description": "可选润色"},
        ],
    )

    assert [item["severity"] for item in issues] == ["critical", "warning", "info"]
    assert [item["review_severity"] for item in issues] == ["critical", "warning", "info"]
    assert [item["revision_priority"] for item in issues] == ["blocker", "medium", "low"]
    assert [item["dimension"] for item in issues] == [1, 7, 8]


def test_legacy_normalized_issue_recovers_original_review_severity():
    issue = normalize_review_issues(
        "ch_001",
        [{"severity": "medium", "legacy_severity": "warning", "description": "旧问题"}],
    )[0]
    assert issue["review_severity"] == "warning"
    assert issue["revision_priority"] == "medium"


def test_review_status_helpers_prefer_v2_contract_over_legacy_fields():
    review = {
        "score": 5,
        "passed": True,
        "issue_details": [],
        "review_v2": {
            "quality_score": 86,
            "gate_status": "blocked",
            "delivery_status": "blocked",
        },
    }
    assert review_quality_score(review) == 86
    assert review_gate_status(review) == "blocked"
    assert review_delivery_status(review) == "blocked"
    assert review_is_deliverable(review) is False


def test_review_status_helpers_honor_legacy_failed_review():
    review = {"score": 82, "passed": False, "issue_details": []}
    assert review_quality_score(review) == 82
    assert review_gate_status(review) == "pass"
    assert review_delivery_status(review) == "revise"
    assert review_is_deliverable(review) is False


def test_review_status_helpers_accept_legacy_passed_review_above_threshold():
    review = {"score": 82, "passed": True, "issue_details": []}
    assert review_delivery_status(review) == "pass"
    assert review_is_deliverable(review) is True


def test_review_status_helpers_block_legacy_critical_issue_before_passed_flag():
    review = {
        "score": 90,
        "passed": False,
        "issue_details": [{"severity": "critical", "description": "事实冲突"}],
    }
    assert review_gate_status(review) == "blocked"
    assert review_delivery_status(review) == "blocked"
    assert review_is_deliverable(review) is False


def test_review_store_records_rereview_issue_delta(tmp_path: Path):
    store = ReviewStore(tmp_path, "demo")
    store.save(
        "ch_001",
        {
            "score": 70,
            "issue_details": [
                {"id": "issue_keep", "dimension": "pace", "summary": "节奏拖沓"},
                {"id": "issue_fixed", "dimension": "logic", "summary": "动机缺失"},
            ],
        },
    )

    store.save(
        "ch_001",
        {
            "score": 82,
            "issue_details": [
                {"id": "issue_keep", "dimension": "pace", "summary": "节奏拖沓"},
                {"id": "issue_new", "dimension": "voice", "summary": "语气漂移"},
            ],
        },
    )

    delta = store.load("ch_001")["issue_delta"]
    assert [item["id"] for item in delta["resolved"]] == ["issue_fixed"]
    assert [item["id"] for item in delta["remaining"]] == ["issue_keep"]
    assert [item["id"] for item in delta["new"]] == ["issue_new"]
