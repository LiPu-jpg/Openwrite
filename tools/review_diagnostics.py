"""Explain incomplete review decisions without changing delivery gate policy."""

from typing import Any


def add_review_diagnostics(review: dict[str, Any]) -> None:
    reasons: list[dict[str, Any]] = []
    if review.get("partial_review"):
        reasons.append(
            {
                "code": "partial_review",
                "missing": review.get("unreviewed_dimensions", []),
                "fix_hint": "Run a full review before requesting full-chapter delivery approval.",
            }
        )
    for domain in review.get("domains", []):
        missing = [
            str(c.get("id"))
            for c in domain.get("criteria", [])
            if c.get("status") == "inconclusive"
        ]
        if missing:
            reasons.append(
                {
                    "code": "review_checks_inconclusive",
                    "domain": domain.get("id"),
                    "missing": missing,
                    "fix_hint": (
                        "Inspect this domain's findings and provider errors, "
                        "then rerun the affected checks."
                    ),
                }
            )
    for gate in review.get("gates", []):
        if gate.get("status") == "inconclusive":
            reasons.append(
                {
                    "code": "gate_inconclusive",
                    "gate": gate.get("id"),
                    "missing": [gate.get("id")],
                    "error": gate.get("error"),
                    "fix_hint": "Resolve the gate's reported error and rerun the review.",
                }
            )
    canon = review.get("canon_gate")
    if isinstance(canon, dict):
        reasons.append(
            {
                "code": "canon_unverified",
                "missing": canon.get("missing", []),
                "fix_hint": canon.get("detail", "Inspect canon review findings."),
            }
        )
    if review.get("delivery_status") == "revise":
        reasons.append(
            {
                "code": "quality_below_threshold",
                "missing": [],
                "fix_hint": "Revise the reported issues and rerun review.",
            }
        )
    if review.get("delivery_status") == "blocked":
        reasons.append(
            {
                "code": "hard_gate_blocked",
                "missing": [],
                "fix_hint": "Resolve the hard-gate findings before delivery.",
            }
        )
    review["score_valid"] = review.get("quality_score") is not None and not any(
        r["code"]
        in {"partial_review", "review_checks_inconclusive", "gate_inconclusive", "canon_unverified"}
        for r in reasons
    )
    codes = {reason["code"] for reason in reasons}
    primary = next(
        (
            code
            for code in (
                "hard_gate_blocked",
                "gate_inconclusive",
                "partial_review",
                "canon_unverified",
            )
            if code in codes
        ),
        reasons[0]["code"] if reasons else "review_complete",
    )
    review["delivery_diagnostics"] = {
        "code": primary,
        "reasons": reasons,
    }
    if reasons:
        review["delivery_reason"] = primary
