"""Materialize OpenWrite review artifacts as a hierarchical DoG query graph.

Role: a model-free materializer/presentation transformer. OpenWrite owns the
quality decision; this module only snapshots the review contract into
immutable, programmatically verifiable records. It never asks a model to
review manuscript text, and its v1 status adapters (`legacy_*`) are isolated
from the canonical v2 path (`decisionSource` records which produced each
manifest).
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from tools.review_dag_framework import instantiate_review_dag, review_dag_framework
from tools.review_rubric import DIMENSION_NAMES, QUALITY_DOMAINS


# Compatibility projection for the existing v2 artifact records. Membership,
# names, and weights now come from OpenWrite's canonical rubric.
REVIEW_DOMAINS: tuple[dict[str, Any], ...] = tuple(
    {
        "id": domain.id,
        "name": domain.name,
        "weight": domain.weight,
        "legacyCheckIds": sorted(domain.legacy_check_ids),
    }
    for domain in QUALITY_DOMAINS
)

HARD_SEVERITIES = {"critical", "blocker"}


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def _record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_dimension(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number in DIMENSION_NAMES else None


def _review_v2(review: dict[str, Any]) -> dict[str, Any]:
    value = review.get("review_v2")
    return value if isinstance(value, dict) else {}


def _selected_dimensions(review: dict[str, Any]) -> set[int]:
    v2 = _review_v2(review)
    selected = v2.get("requested_dimensions", review.get("dimensions"))
    if not isinstance(selected, list):
        return set(DIMENSION_NAMES)
    return {number for item in selected if (number := _as_dimension(item)) is not None}


def _review_severity(issue: dict[str, Any]) -> str:
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


def _revision_priority(issue: dict[str, Any]) -> str:
    raw = str(issue.get("revision_priority") or "").lower()
    if raw in {"blocker", "high", "medium", "low"}:
        return raw
    return {"critical": "blocker", "warning": "medium", "info": "low"}[_review_severity(issue)]


def _normalized_issue(issue: Any) -> dict[str, Any]:
    if not isinstance(issue, dict):
        issue = {"description": str(issue)}
    evidence = issue.get("evidence")
    severity = _review_severity(issue)
    return {
        "id": str(issue.get("id") or ""),
        "severity": severity,
        "reviewSeverity": severity,
        "revisionPriority": _revision_priority(issue),
        "category": str(issue.get("category") or ""),
        "description": str(issue.get("description") or issue.get("summary") or ""),
        "suggestion": str(issue.get("suggestion") or ""),
        "evidence": evidence if isinstance(evidence, dict) else {"quote": str(evidence or "")},
    }


def _verdict(status: str) -> str:
    if status in {"pass", "completed", "evaluated", "not_applicable"}:
        return "pass"
    if status in {"blocked", "fail", "failed", "revise"}:
        return "fail"
    return "inconclusive"


def legacy_gate_status(review: dict[str, Any]) -> str:
    """v1-only adapter: derive a gate from legacy severities.

    Never used when review_v2 is present; v2 records must carry the canonical
    gate_status computed by OpenWrite.
    """
    return "blocked" if any(
        isinstance(issue, dict) and _review_severity(issue) == "critical"
        for issue in review.get("issue_details") or []
    ) else "pass"


def legacy_delivery_status(review: dict[str, Any], threshold: int) -> str:
    """v1-only adapter: derive delivery from legacy score/passed semantics."""
    try:
        score = float(review.get("score") or 0)
    except (TypeError, ValueError, OverflowError):
        score = 0
    if legacy_gate_status(review) == "blocked":
        return "blocked"
    if review.get("passed") is False:
        return "revise"
    return "pass" if score >= threshold else "revise"


def _gate_status(review: dict[str, Any]) -> str:
    v2 = _review_v2(review)
    if v2:
        return str(v2.get("gate_status") or "inconclusive").lower()
    return legacy_gate_status(review)


def _delivery_status(review: dict[str, Any], threshold: int) -> str:
    v2 = _review_v2(review)
    if v2:
        return str(v2.get("delivery_status") or "inconclusive").lower()
    return legacy_delivery_status(review, threshold)


def _criterion_by_dimension(review: dict[str, Any]) -> dict[int, dict[str, Any]]:
    mapped: dict[int, dict[str, Any]] = {}
    for domain in _review_v2(review).get("domains") or []:
        for criterion in _record(domain).get("criteria") or []:
            criterion_record = _record(criterion)
            for raw_id in criterion_record.get("legacy_check_ids") or []:
                number = _as_dimension(raw_id)
                if number is not None:
                    mapped[number] = criterion_record
    return mapped


def build_review_manifest(
    review: dict[str, Any],
    chapter_id: str,
    threshold: int,
) -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
    """Return a v2 aggregate manifest and all 37 compatible leaf records."""
    if not 0 <= threshold <= 100:
        raise ValueError("review threshold must be between 0 and 100")
    selected = _selected_dimensions(review)
    grouped: dict[int, list[dict[str, Any]]] = {number: [] for number in DIMENSION_NAMES}
    unmapped: list[dict[str, Any]] = []
    for raw_issue in review.get("issue_details") or []:
        if not isinstance(raw_issue, dict):
            continue
        number = _as_dimension(raw_issue.get("dimension"))
        normalized = _normalized_issue(raw_issue)
        if number is None:
            unmapped.append(normalized)
        else:
            grouped[number].append(normalized)

    criteria = _criterion_by_dimension(review)
    gate_status = _gate_status(review)
    dimensions: dict[int, dict[str, Any]] = {}
    for number, name in DIMENSION_NAMES.items():
        issues = grouped[number]
        criterion = criteria.get(number, {})
        criterion_status = str(criterion.get("status") or "")
        if number not in selected:
            verdict = "inconclusive"
            status = "not_requested"
        elif any(item["reviewSeverity"] == "critical" for item in issues):
            verdict = "fail"
            status = "blocked"
        elif number == 27:
            verdict = _verdict(gate_status)
            status = gate_status
        elif criterion:
            verdict = _verdict(criterion_status)
            status = criterion_status
        else:
            verdict = "pass"
            status = "legacy_evaluated"
        dimensions[number] = {
            "schemaVersion": "dsh-novel.review.dimension.v2",
            "recordType": "review-dimension",
            "chapterId": chapter_id,
            "dimension": number,
            "name": name,
            "verdict": verdict,
            "status": status,
            "criterionId": str(criterion.get("id") or ""),
            "issueCount": len(issues),
            "issues": issues,
            "sourceReviewPassed": bool(review.get("passed")),
            "sourceReviewScore": review.get("score"),
        }

    v2 = _review_v2(review)
    raw_domains = {
        str(_record(item).get("id") or ""): _record(item)
        for item in v2.get("domains") or []
    }
    domain_records: list[dict[str, Any]] = []
    for spec in REVIEW_DOMAINS:
        raw = raw_domains.get(spec["id"], {})
        domain_dimensions = [dimensions[number] for number in spec["legacyCheckIds"]]
        status = str(raw.get("status") or "")
        if not status:
            status = "inconclusive" if any(item["verdict"] == "inconclusive" for item in domain_dimensions) else "evaluated"
        verdict = "fail" if any(item["verdict"] == "fail" for item in domain_dimensions) else _verdict(status)
        domain_records.append({
            "schemaVersion": "dsh-novel.review.domain.v2",
            "recordType": "review-domain",
            "chapterId": chapter_id,
            "id": spec["id"],
            "name": spec["name"],
            "weight": spec["weight"],
            "verdict": verdict,
            "status": status,
            "earned": raw.get("earned"),
            "max": raw.get("max"),
            "potentialMax": raw.get("potential_max"),
            "coverage": raw.get("coverage"),
            "legacyCheckIds": list(spec["legacyCheckIds"]),
            "criteria": list(raw.get("criteria") or []),
            "issues": [issue for number in spec["legacyCheckIds"] for issue in grouped[number]],
        })

    delivery_status = _delivery_status(review, threshold)
    manifest = {
        "schemaVersion": "dsh-novel.review.manifest.v2",
        "recordType": "review",
        "chapterId": chapter_id,
        "threshold": threshold,
        "verdict": _verdict(delivery_status),
        "executionStatus": str(v2.get("execution_status") or ("completed" if review else "failed")),
        "qualityScore": v2.get("quality_score", review.get("score")),
        "coverage": v2.get("coverage", 1 if review else 0),
        "gateStatus": gate_status,
        "deliveryStatus": delivery_status,
        "sourceReviewPassed": bool(review.get("passed")),
        "score": review.get("score"),
        "summary": str(review.get("summary") or ""),
        "decisionSource": "v2" if v2 else "v1-adapter",
        "requestedDimensions": sorted(selected),
        "dimensionCount": len(DIMENSION_NAMES),
        "issueCount": sum(len(items) for items in grouped.values()) + len(unmapped),
        "unmappedIssueCount": len(unmapped),
        "unmappedIssues": unmapped,
        "sourceRevision": str(review.get("source_revision") or ""),
        "provenance": _record(v2.get("provenance")),
        "domains": domain_records,
        "dimensions": list(dimensions.values()),
    }
    return manifest, dimensions


def _workspace_project(workspace: dict[str, Any]) -> tuple[Path, str]:
    project = _record(workspace.get("project"))
    snapshot = _record(workspace.get("snapshot"))
    root_text = str(project.get("root") or "").strip()
    novel_id = str(snapshot.get("novel_id") or "").strip()
    if not root_text or not novel_id:
        raise ValueError("Studio workspace lacks project.root or snapshot.novel_id")
    root = Path(root_text).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Studio project root is not a directory: {root}")
    return root, novel_id


def _manuscript_revision(root: Path, novel_id: str, chapter_id: str) -> str:
    manuscript = root / "data" / "novels" / novel_id / "data" / "manuscript"
    matches = list(manuscript.glob(f"**/{chapter_id}.md"))
    if len(matches) != 1:
        return ""
    return "sha256:" + hashlib.sha256(matches[0].read_bytes()).hexdigest()


def write_review_artifacts(
    studio: Any,
    chapter_id: str,
    review: dict[str, Any],
    threshold: int,
) -> dict[str, Any]:
    """Persist review records and return a model-free DoG-compatible graph."""
    workspace = studio.get("/api/workspace")
    root, novel_id = _workspace_project(workspace)
    framework = review_dag_framework()
    manifest, dimensions = build_review_manifest(review, chapter_id, threshold)
    manifest["frameworkId"] = framework["id"]
    manifest["frameworkVersion"] = framework["version"]
    manifest["frameworkRevision"] = framework["revision"]
    current_revision = _manuscript_revision(root, novel_id, chapter_id)
    source_revision = str(manifest.get("sourceRevision") or current_revision)
    manifest["sourceRevision"] = source_revision
    manifest["currentRevision"] = current_revision
    manifest["stale"] = bool(source_revision and current_revision and source_revision != current_revision)
    if manifest["stale"]:
        manifest["verdict"] = "inconclusive"
        manifest["deliveryStatus"] = "stale"

    relative_dir = Path("data") / "novels" / novel_id / "data" / "dog" / "reviews" / chapter_id
    graph = instantiate_review_dag(chapter_id, relative_dir.as_posix(), framework=framework)
    artifact_dir = root / relative_dir
    _atomic_write_json(artifact_dir / "review.json", manifest)
    _atomic_write_json(artifact_dir / "context.json", {
        "schemaVersion": "dsh-novel.review.context.v2", "recordType": "review-context",
        "chapterId": chapter_id, "verdict": "inconclusive" if manifest["stale"] or not source_revision else "pass",
        "status": "stale" if manifest["stale"] else "current" if source_revision else "missing_revision",
        "sourceRevision": source_revision, "currentRevision": current_revision,
        "provenance": manifest["provenance"],
    })
    for domain in manifest["domains"]:
        _atomic_write_json(artifact_dir / f"domain_{domain['id']}.json", domain)
    _atomic_write_json(artifact_dir / "gate.json", {
        "schemaVersion": "dsh-novel.review.gate.v2", "recordType": "review-gate",
        "chapterId": chapter_id, "verdict": _verdict(str(manifest["gateStatus"])),
        "status": manifest["gateStatus"], "legacyCheckIds": [27],
        "issues": dimensions[27]["issues"],
    })
    _atomic_write_json(artifact_dir / "aggregate.json", {
        "schemaVersion": "dsh-novel.review.aggregate.v2", "recordType": "review-aggregate",
        "chapterId": chapter_id, "verdict": manifest["verdict"],
        "executionStatus": manifest["executionStatus"], "qualityScore": manifest["qualityScore"],
        "coverage": manifest["coverage"], "gateStatus": manifest["gateStatus"],
        "deliveryStatus": manifest["deliveryStatus"], "threshold": threshold,
    })
    for number, record in dimensions.items():
        _atomic_write_json(artifact_dir / f"dim_{number:02d}.json", record)

    target = lambda name: str((relative_dir / name).as_posix())
    graph_path = artifact_dir / "dog-graph.json"
    _atomic_write_json(graph_path, graph)
    return {
        "manifest": target("review.json"), "directory": str(artifact_dir), "graph_path": str(graph_path),
        "graph": graph, "dimensions": len(dimensions), "domains": len(REVIEW_DOMAINS),
        "framework": {
            "id": framework["id"],
            "version": framework["version"],
            "revision": framework["revision"],
        },
    }
