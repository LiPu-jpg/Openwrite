"""Persistent structured chapter review results."""

from __future__ import annotations

import hashlib
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def issue_review_severity(issue: dict[str, Any]) -> str:
    raw = str(
        issue.get("review_severity")
        or issue.get("legacy_severity")
        or issue.get("severity")
        or "warning"
    ).lower()
    if raw in {"critical", "blocker"}:
        return "critical"
    if raw in {"info", "low"}:
        return "info"
    return "warning"


def issue_revision_priority(issue: dict[str, Any]) -> str:
    explicit = str(issue.get("revision_priority") or "").lower()
    if explicit in {"blocker", "high", "medium", "low"}:
        return explicit
    raw = str(issue.get("legacy_severity") or issue.get("severity") or "warning").lower()
    return {
        "critical": "blocker",
        "blocker": "blocker",
        "error": "high",
        "high": "high",
        "warning": "medium",
        "medium": "medium",
        "info": "low",
        "low": "low",
    }.get(raw, "medium")

def has_review_v2_field(review: dict[str, Any]) -> bool:
    """True when the record carries a review_v2 key at all (including null or
    a malformed value). Legacy score/passed semantics are reserved for
    records without the key."""
    return "review_v2" in review


def review_v2_malformed(review: dict[str, Any]) -> bool:
    """True when review_v2 exists but is not a usable canonical object."""
    if not has_review_v2_field(review):
        return False
    value = review["review_v2"]
    return not isinstance(value, dict) or not value


def review_v2_contract(review: dict[str, Any]) -> dict[str, Any]:
    value = review.get("review_v2")
    return value if isinstance(value, dict) else {}


def validate_review_v2_record(review: dict[str, Any]) -> dict[str, Any] | None:
    """Validate a present review_v2 payload and return it.

    A missing key is the only case that permits the legacy adapter.  This
    helper is intentionally presence-based so ``null`` cannot be mistaken for
    an absent v2 decision at an HTTP or persistence boundary.
    """
    if not has_review_v2_field(review):
        return None
    value = review["review_v2"]
    if not isinstance(value, dict) or not value:
        raise ValueError("review_v2 must be a non-empty JSON object when present")
    from tools.contracts_generated import validate_review_v2

    return validate_review_v2(value)




def review_quality_score(review: dict[str, Any]) -> float | None:
    if review_v2_malformed(review):
        # A malformed v2 payload must never be re-scored from legacy fields.
        return None
    v2 = review_v2_contract(review)
    raw = v2.get("quality_score") if v2 else review.get("score")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError, OverflowError):
        return None


def review_gate_status(review: dict[str, Any]) -> str:
    if review_v2_malformed(review):
        return "inconclusive"
    v2 = review_v2_contract(review)
    if v2:
        return str(v2.get("gate_status") or "inconclusive").lower()
    return "blocked" if any(
        isinstance(item, dict) and issue_review_severity(item) == "critical"
        for item in review.get("issue_details") or []
    ) else "pass"


def review_delivery_status(
    review: dict[str, Any],
    *,
    quality_threshold: float = 70.0,
) -> str:
    if review_v2_malformed(review):
        return "inconclusive"
    v2 = review_v2_contract(review)
    if v2:
        return str(v2.get("delivery_status") or "inconclusive").lower()
    if review_gate_status(review) == "blocked":
        return "blocked"
    if review.get("passed") is False:
        return "revise"
    score = review_quality_score(review)
    if score is None:
        return "inconclusive"
    return "pass" if score >= quality_threshold else "revise"


def canonical_review_decision(
    review: dict[str, Any],
    *,
    current_source_revision: str = "",
) -> dict[str, Any]:
    """Return the canonical v2 decision; v1 fallback is explicit and isolated.

    The legacy adapter only runs for records that carry no review_v2 key at
    all. A present-but-malformed review_v2 (null/list/string/empty) raises.
    """
    if not has_review_v2_field(review):
        return {
            "schema_version": "openwrite.review.v1-adapter",
            "execution_status": "completed" if review else "failed",
            "quality_score": review_quality_score(review),
            "coverage": 1.0 if review else 0.0,
            "gate_status": review_gate_status(review),
            "delivery_status": review_delivery_status(review, quality_threshold=70.0),
            "production_gate_status": "disabled_uncalibrated",
            "freshness_status": "unknown",
            "source_revision": str(review.get("source_revision") or ""),
            "current_source_revision": str(current_source_revision or ""),
        }
    decision = validate_review_v2_record(review)
    assert decision is not None
    source_revision = str(review.get("source_revision") or "")
    current = str(current_source_revision or "")
    freshness = (
        "current" if source_revision and current and source_revision == current
        else "stale" if source_revision and current
        else "unknown"
    )
    return {
        "schema_version": decision["schema_version"],
        "execution_status": decision["execution_status"],
        "quality_score": decision["quality_score"],
        "coverage": decision["coverage"],
        "gate_status": decision["gate_status"],
        "delivery_status": "stale" if freshness == "stale" else decision["delivery_status"],
        "production_gate_status": decision["production_gate_status"],
        "freshness_status": freshness,
        "source_revision": source_revision,
        "current_source_revision": current,
    }


def review_is_deliverable(
    review: dict[str, Any],
    *,
    quality_threshold: float = 70.0,
    current_source_revision: str = "",
) -> bool:
    if review_v2_malformed(review):
        # A present-but-malformed review_v2 can never be a delivery approval,
        # no matter what legacy score/passed fields claim.
        return False
    if has_review_v2_field(review):
        try:
            validate_review_v2_record(review)
        except ValueError:
            return False
        decision = canonical_review_decision(
            review, current_source_revision=current_source_revision
        )
        # Delivery requires a verifiably current review: freshness "unknown"
        # (e.g. missing current manuscript SHA) must not count as deliverable.
        return (
            decision["delivery_status"] == "pass"
            and decision["freshness_status"] == "current"
        )
    return review_delivery_status(review, quality_threshold=quality_threshold) == "pass"


def normalize_review_issues(chapter_id: str, issues: Any) -> list[dict[str, Any]]:
    """Add stable revision-oriented fields while preserving legacy issue data."""
    if not isinstance(issues, list):
        return []
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(issues):
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        summary = str(item.get("summary") or item.get("description") or "").strip()
        dimension = item.get("dimension")
        if dimension in {None, ""}:
            dimension = str(item.get("category") or "general")
        evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
        quote = str(evidence.get("quote") or item.get("evidence") or item.get("quote") or "")
        digest_source = f"{chapter_id}\0{dimension}\0{summary}\0{quote}"
        issue_id = str(item.get("id") or "").strip() or (
            "issue_" + hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:12]
        )
        anchor = item.get("anchor") if isinstance(item.get("anchor"), dict) else {}
        review_severity = issue_review_severity(item)
        revision_priority = issue_revision_priority(item)
        normalized.append(
            {
                **item,
                "id": issue_id,
                "dimension": dimension,
                "severity": review_severity,
                "review_severity": review_severity,
                "revision_priority": revision_priority,
                "legacy_severity": str(item.get("severity") or "warning"),
                "summary": summary,
                "evidence": {
                    "quote": quote,
                    "context_before": str(evidence.get("context_before") or ""),
                    "context_after": str(evidence.get("context_after") or ""),
                },
                "anchor": {
                    "start_hint": anchor.get("start_hint"),
                    "end_hint": anchor.get("end_hint"),
                },
                "suggestion": str(item.get("suggestion") or ""),
                "auto_fixable": bool(item.get("auto_fixable", bool(quote or anchor))),
            }
        )
    return normalized


class ReviewStore:
    def __init__(self, project_root: Path, novel_id: str):
        self.project_root = Path(project_root).resolve()
        self.novel_id = novel_id
        self.review_dir = (
            self.project_root
            / "data"
            / "novels"
            / novel_id
            / "data"
            / "reviews"
        )

    def save(self, chapter_id: str, result: dict[str, Any]) -> Path:
        self.review_dir.mkdir(parents=True, exist_ok=True)
        previous_revisioned = self.load_revisioned(chapter_id)
        previous = previous_revisioned[0] if previous_revisioned is not None else None
        previous_review_revision = (
            previous_revisioned[1] if previous_revisioned is not None else ""
        )
        payload = dict(result)
        payload["issue_details"] = normalize_review_issues(
            chapter_id, payload.get("issue_details", [])
        )
        if previous is not None:
            before = normalize_review_issues(chapter_id, previous.get("issue_details", []))
            before_by_id = {str(item["id"]): item for item in before}
            after_by_id = {str(item["id"]): item for item in payload["issue_details"]}
            payload["issue_delta"] = {
                "resolved": [
                    item for issue_id, item in before_by_id.items()
                    if issue_id not in after_by_id
                ],
                "remaining": [
                    item for issue_id, item in after_by_id.items()
                    if issue_id in before_by_id
                ],
                "new": [
                    item for issue_id, item in after_by_id.items()
                    if issue_id not in before_by_id
                ],
            }
            if not payload.get("stale") or not isinstance(
                payload.get("revision_history"), list
            ):
                payload["revision_history"] = [
                    dict(item)
                    for item in previous.get("revision_history", [])
                    if isinstance(item, dict)
                ]
            if not payload.get("stale") or not isinstance(
                payload.get("revision_closures"), list
            ):
                payload["revision_closures"] = [
                    dict(item)
                    for item in previous.get("revision_closures", [])
                    if isinstance(item, dict)
                ]
        payload.setdefault("revision_closures", [])
        source_revision = str(payload.get("source_revision") or self._source_revision(chapter_id))
        payload["source_revision"] = source_revision
        review_v2 = review_v2_contract(payload)
        if review_v2:
            canonical = dict(review_v2)
            canonical["freshness_status"] = (
                "stale"
                if payload.get("stale")
                else "current" if source_revision else "unknown"
            )
            canonical["source_revision"] = source_revision
            payload["review_v2"] = canonical
        payload["reviewed_at"] = str(
            payload.get("reviewed_at") or datetime.now(timezone.utc).isoformat()
        )
        if previous is not None and previous.get("stale") and not payload.get("stale"):
            self._close_revision(
                chapter_id=chapter_id,
                previous=previous,
                previous_review_revision=previous_review_revision,
                payload=payload,
            )
        target = self.path_for(chapter_id)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=self.review_dir,
            prefix=f".{chapter_id}.", suffix=".tmp", delete=False,
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            temp_path = Path(handle.name)
        temp_path.replace(target)
        return target

    @staticmethod
    def _close_revision(
        *,
        chapter_id: str,
        previous: dict[str, Any],
        previous_review_revision: str,
        payload: dict[str, Any],
    ) -> None:
        """Close the one proposal whose applied bytes this rereview inspected.

        Matching the rereview source revision to the applied revision prevents
        an intervening edit from being attributed to the wrong proposal. Issue
        outcomes come only from stable issue-ID membership, never score changes.
        """
        history = payload.get("revision_history")
        if not isinstance(history, list):
            return
        rereview_source_revision = str(payload.get("source_revision") or "")
        pending_index = -1
        for index in range(len(history) - 1, -1, -1):
            entry = history[index]
            if not isinstance(entry, dict) or entry.get("closure_id"):
                continue
            applied_revision = str(entry.get("applied_revision") or "")
            if (
                entry.get("proposal_id")
                and applied_revision
                and applied_revision == rereview_source_revision
            ):
                pending_index = index
                break
        if pending_index < 0:
            return

        entry = dict(history[pending_index])
        selected_ids = ReviewStore._unique_strings(
            entry.get("original_issue_ids") or entry.get("issue_ids")
        )
        before = normalize_review_issues(
            chapter_id,
            previous.get("issue_details", []),
        )
        after = payload.get("issue_details")
        after = after if isinstance(after, list) else []
        before_ids = {str(item.get("id") or "") for item in before}
        after_by_id = {str(item.get("id") or ""): item for item in after}
        issue_outcomes = [
            {
                "issue_id": issue_id,
                "outcome": "retained" if issue_id in after_by_id else "resolved",
            }
            for issue_id in selected_ids
        ]
        regressions = [
            {
                "issue_id": issue_id,
                "outcome": "regressed",
                "issue": dict(issue),
            }
            for issue_id, issue in after_by_id.items()
            if issue_id and issue_id not in before_ids
        ]
        identity = "\0".join(
            (
                str(entry.get("proposal_id") or ""),
                str(entry.get("review_revision") or ""),
                str(entry.get("source_revision") or ""),
                str(entry.get("applied_revision") or ""),
                rereview_source_revision,
            )
        )
        closure_id = "closure_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
        closure = {
            "schema_version": "openwrite.review-closure.v1",
            "closure_id": closure_id,
            "proposal_id": str(entry.get("proposal_id") or ""),
            "source_review_revision": str(entry.get("review_revision") or ""),
            "stale_review_revision": previous_review_revision,
            # Filled at read time from the exact bytes containing this closure.
            "rereview_review_revision": "",
            "source_revision": str(entry.get("source_revision") or ""),
            "applied_revision": str(entry.get("applied_revision") or ""),
            "rereview_source_revision": rereview_source_revision,
            "selected_issue_ids": selected_ids,
            "issue_outcomes": issue_outcomes,
            "regressions": regressions,
            "closed_at": str(payload.get("reviewed_at") or ""),
        }
        closures = payload.setdefault("revision_closures", [])
        if not any(
            isinstance(item, dict) and item.get("closure_id") == closure_id
            for item in closures
        ):
            closures.append(closure)
        entry.update(
            {
                "closure_id": closure_id,
                "closure_status": "closed",
                "rereview_source_revision": rereview_source_revision,
                "closed_at": str(payload.get("reviewed_at") or ""),
            }
        )
        history[pending_index] = entry

    @staticmethod
    def _unique_strings(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        result: list[str] = []
        for item in value:
            clean = str(item or "").strip()
            if clean and clean not in result:
                result.append(clean)
        return result

    def mark_stale(
        self,
        chapter_id: str,
        *,
        reason: str,
        current_source_revision: str = "",
        history_entry: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        review = self.load(chapter_id)
        if review is None:
            return None
        if history_entry is not None:
            history = list(review.get("revision_history") or [])
            history.append(dict(history_entry))
            review["revision_history"] = history
        review.update(
            {
                "stale": True,
                "stale_at": datetime.now(timezone.utc).isoformat(),
                "stale_reason": str(reason or "chapter_changed"),
            }
        )
        review_v2 = review_v2_contract(review)
        if review_v2:
            review["review_v2"] = {
                **review_v2,
                "freshness_status": "stale",
                "current_source_revision": str(current_source_revision or ""),
            }
        self.save(chapter_id, review)
        return review

    def _source_revision(self, chapter_id: str) -> str:
        manuscript = (
            self.project_root
            / "data"
            / "novels"
            / self.novel_id
            / "data"
            / "manuscript"
        )
        matches = list(manuscript.glob(f"**/{chapter_id}.md"))
        if len(matches) != 1:
            return ""
        try:
            content = matches[0].read_text(encoding="utf-8")
        except OSError:
            return ""
        return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()

    def load(self, chapter_id: str) -> dict[str, Any] | None:
        revisioned = self.load_revisioned(chapter_id)
        return revisioned[0] if revisioned is not None else None

    def load_revisioned(self, chapter_id: str) -> tuple[dict[str, Any], str] | None:
        """Read one review and its exact persisted revision from the same bytes."""
        path = self.path_for(chapter_id)
        if not path.is_file():
            return None
        try:
            content = path.read_bytes()
            data = json.loads(content.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        revision = "sha256:" + hashlib.sha256(content).hexdigest()
        closures = data.get("revision_closures")
        if isinstance(closures, list):
            for closure in closures:
                if isinstance(closure, dict) and not closure.get(
                    "rereview_review_revision"
                ):
                    closure["rereview_review_revision"] = revision
        return data, revision

    def path_for(self, chapter_id: str) -> Path:
        if not chapter_id.startswith("ch_") or not chapter_id[3:].isdigit():
            raise ValueError(f"无效章节 ID: {chapter_id}")
        return self.review_dir / f"{chapter_id}.json"

    def analytics(self) -> dict[str, int | float]:
        scores: list[float] = []
        passed = 0
        if self.review_dir.exists():
            for path in self.review_dir.glob("ch_*.json"):
                record = self.load(path.stem)
                if not record:
                    continue
                try:
                    score = review_quality_score(record)
                    if score is None:
                        continue
                    scores.append(score)
                except (TypeError, ValueError):
                    continue
                passed += int(
                    review_is_deliverable(
                        record,
                        current_source_revision=self._source_revision(path.stem),
                    )
                )
        return {
            "reviewed_chapters": len(scores),
            "passed_chapters": passed,
            "average_score": round(sum(scores) / len(scores), 1) if scores else 0.0,
        }
