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
            {
                "dimension": 1,
                "severity": "critical",
                "description": "人物矛盾",
                "evidence": {"quote": "证据"},
            },
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


def test_rereview_closure_distinguishes_selected_outcomes_and_regressions(
    tmp_path: Path,
):
    store = ReviewStore(tmp_path, "demo")
    store.save(
        "ch_001",
        {
            "source_revision": "sha256:source-before",
            "score": 95,
            "issue_details": [
                {"id": "issue_fixed", "dimension": "logic", "summary": "动机缺失"},
                {"id": "issue_kept", "dimension": "pace", "summary": "节奏拖沓"},
                {"id": "issue_unselected", "dimension": "voice", "summary": "语气漂移"},
            ],
        },
    )
    source_review = store.load_revisioned("ch_001")
    assert source_review is not None
    source_review_revision = source_review[1]
    store.mark_stale(
        "ch_001",
        reason="chapter_revised",
        current_source_revision="sha256:applied-one",
        history_entry={
            "proposal_id": "rev_first",
            "review_revision": source_review_revision,
            "source_revision": "sha256:source-before",
            "applied_revision": "sha256:applied-one",
            "issue_ids": ["issue_fixed", "issue_kept"],
            "original_issue_ids": ["issue_fixed", "issue_kept"],
            "applied_at": "2026-09-05T01:00:00+00:00",
        },
    )
    stale_review = store.load_revisioned("ch_001")
    assert stale_review is not None

    # The score stays high on purpose: closure must come from issue IDs, not scores.
    store.save(
        "ch_001",
        {
            "source_revision": "sha256:applied-one",
            "score": 95,
            "issue_details": [
                {"id": "issue_kept", "dimension": "pace", "summary": "节奏拖沓"},
                {"id": "issue_unselected", "dimension": "voice", "summary": "语气漂移"},
                {"id": "issue_regressed", "dimension": "canon", "summary": "新事实冲突"},
            ],
        },
    )

    rereview = store.load_revisioned("ch_001")
    assert rereview is not None
    payload, rereview_revision = rereview
    closure = payload["revision_closures"][-1]
    assert closure["schema_version"] == "openwrite.review-closure.v1"
    assert closure["proposal_id"] == "rev_first"
    assert closure["source_review_revision"] == source_review_revision
    assert closure["stale_review_revision"] == stale_review[1]
    assert closure["source_revision"] == "sha256:source-before"
    assert closure["applied_revision"] == "sha256:applied-one"
    assert closure["rereview_source_revision"] == "sha256:applied-one"
    assert closure["rereview_review_revision"] == rereview_revision
    assert closure["selected_issue_ids"] == ["issue_fixed", "issue_kept"]
    assert closure["issue_outcomes"] == [
        {"issue_id": "issue_fixed", "outcome": "resolved"},
        {"issue_id": "issue_kept", "outcome": "retained"},
    ]
    assert [item["issue_id"] for item in closure["regressions"]] == [
        "issue_regressed"
    ]
    assert closure["regressions"][0]["outcome"] == "regressed"
    # The ordinary all-issue delta remains available for legacy consumers.
    assert [item["id"] for item in payload["issue_delta"]["resolved"]] == [
        "issue_fixed"
    ]


def test_consecutive_rereviews_close_only_their_own_revision_proposal(
    tmp_path: Path,
):
    store = ReviewStore(tmp_path, "demo")
    store.save(
        "ch_001",
        {
            "source_revision": "sha256:source-zero",
            "score": 40,
            "issue_details": [
                {"id": "issue_a", "dimension": "logic", "summary": "问题 A"}
            ],
        },
    )
    first_review = store.load_revisioned("ch_001")
    assert first_review is not None
    store.mark_stale(
        "ch_001",
        reason="chapter_revised",
        current_source_revision="sha256:applied-one",
        history_entry={
            "proposal_id": "rev_one",
            "review_revision": first_review[1],
            "source_revision": "sha256:source-zero",
            "applied_revision": "sha256:applied-one",
            "original_issue_ids": ["issue_a"],
            "issue_ids": ["issue_a"],
        },
    )
    store.save(
        "ch_001",
        {
            "source_revision": "sha256:applied-one",
            "score": 40,
            "issue_details": [
                {"id": "issue_a", "dimension": "logic", "summary": "问题 A"}
            ],
        },
    )
    second_review = store.load_revisioned("ch_001")
    assert second_review is not None
    assert second_review[0]["revision_closures"][-1]["proposal_id"] == "rev_one"

    store.mark_stale(
        "ch_001",
        reason="chapter_revised",
        current_source_revision="sha256:applied-two",
        history_entry={
            "proposal_id": "rev_two",
            "review_revision": second_review[1],
            "source_revision": "sha256:applied-one",
            "applied_revision": "sha256:applied-two",
            "original_issue_ids": ["issue_a"],
            "issue_ids": ["issue_a"],
        },
    )
    store.save(
        "ch_001",
        {
            "source_revision": "sha256:applied-two",
            "score": 40,
            "issue_details": [],
        },
    )

    final = store.load("ch_001")
    assert final is not None
    assert [item["proposal_id"] for item in final["revision_closures"]] == [
        "rev_one",
        "rev_two",
    ]
    assert final["revision_closures"][0]["issue_outcomes"] == [
        {"issue_id": "issue_a", "outcome": "retained"}
    ]
    assert final["revision_closures"][1]["issue_outcomes"] == [
        {"issue_id": "issue_a", "outcome": "resolved"}
    ]
    history = final["revision_history"]
    assert history[0]["closure_id"] == final["revision_closures"][0]["closure_id"]
    assert history[1]["closure_id"] == final["revision_closures"][1]["closure_id"]


def test_legacy_rereview_without_revision_history_keeps_issue_delta_only(
    tmp_path: Path,
):
    store = ReviewStore(tmp_path, "demo")
    store.save(
        "ch_001",
        {"score": 50, "issue_details": [{"id": "legacy", "summary": "旧问题"}]},
    )
    store.save("ch_001", {"score": 80, "issue_details": []})

    rereview = store.load("ch_001")
    assert rereview is not None
    assert rereview["revision_closures"] == []
    assert [item["id"] for item in rereview["issue_delta"]["resolved"]] == [
        "legacy"
    ]
