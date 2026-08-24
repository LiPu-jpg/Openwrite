"""Build a chapter delivery DoG graph from OpenWrite's canonical artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


HARD_SEVERITIES = {"critical", "blocker"}


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _revision(path: Path | None) -> str:
    if path is None or not path.is_file():
        return ""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"sha256:{digest}"


def _gate_passed(review: dict[str, Any], threshold: int) -> bool:
    try:
        score = int(review.get("score") or 0)
    except (TypeError, ValueError, OverflowError):
        score = 0
    hard = any(
        isinstance(item, dict)
        and str(item.get("severity") or "").lower() in HARD_SEVERITIES
        for item in review.get("issue_details") or []
    )
    return score >= threshold and not hard


def _stage(chapter_id: str, name: str, verdict: str, status: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": "dsh-novel.delivery.stage.v1",
        "recordType": "delivery-stage",
        "chapterId": chapter_id,
        "stage": name,
        "verdict": verdict,
        "status": status,
        "evidence": evidence,
    }


def write_delivery_artifacts(
    project_root: Path,
    novel_id: str,
    chapter_id: str,
    threshold: int | None = None,
) -> dict[str, Any]:
    """Rebuild one delivery graph without mutating manuscript domain state."""
    root = Path(project_root).expanduser().resolve()
    if not root.is_dir() or not novel_id:
        raise ValueError("chapter delivery lacks a valid project root or novel id")
    if not chapter_id.startswith("ch_") or not chapter_id[3:].isdigit():
        raise ValueError(f"invalid chapter id: {chapter_id}")

    novel_root = root / "data" / "novels" / novel_id
    relative_dir = Path("data") / "novels" / novel_id / "data" / "dog" / "deliveries" / chapter_id
    artifact_dir = root / relative_dir
    previous = _load_json(artifact_dir / "delivery.json")
    effective_threshold = int(threshold if threshold is not None else previous.get("threshold") or 70)
    if not 0 <= effective_threshold <= 100:
        raise ValueError("delivery threshold must be between 0 and 100")

    manuscript_matches = list((novel_root / "data" / "manuscript").glob(f"**/{chapter_id}.md"))
    manuscript = manuscript_matches[0] if len(manuscript_matches) == 1 else None
    fallback = novel_root / "data" / "manuscript" / "arc_001" / f"{chapter_id}.md"
    manuscript_target = (manuscript or fallback).relative_to(root).as_posix()
    current_revision = _revision(manuscript)

    review = _load_json(novel_root / "data" / "reviews" / f"{chapter_id}.json")
    review_source_revision = str(review.get("source_revision") or "")
    review_stale = bool(review.get("stale")) or bool(
        review and current_revision and review_source_revision != current_revision
    )
    review_current = bool(review) and bool(current_revision) and not review_stale
    review_passed = review_current and _gate_passed(review, effective_threshold)
    issues = [item for item in review.get("issue_details") or [] if isinstance(item, dict)]
    issue_ids = [str(item.get("id") or "") for item in issues if item.get("id")]
    hard_issue_ids = [
        str(item.get("id") or "")
        for item in issues
        if item.get("id") and str(item.get("severity") or "").lower() in HARD_SEVERITIES
    ]

    revision_dir = novel_root / "data" / "revisions" / chapter_id
    proposals = [
        value
        for path in sorted(revision_dir.glob("rev_*.json")) if revision_dir.is_dir()
        if (value := _load_json(path)).get("kind") == "review_fix"
    ]
    applied = [item for item in proposals if item.get("status") == "applied"]
    pending = [item for item in proposals if item.get("status") == "proposed"]
    applied_to_current = [
        item for item in applied if str(item.get("applied_revision") or "") == current_revision
    ]

    if not review:
        review_stage = _stage(chapter_id, "review", "inconclusive", "missing", {})
    elif not review_current:
        review_stage = _stage(chapter_id, "review", "inconclusive", "stale" if review_stale else "unverifiable", {
            "sourceRevision": review_source_revision,
            "currentRevision": current_revision,
            "staleReason": review.get("stale_reason"),
        })
    else:
        review_stage = _stage(chapter_id, "review", "pass", "current", {
            "score": review.get("score"),
            "threshold": effective_threshold,
            "passedGate": review_passed,
            "issueIds": issue_ids,
            "hardIssueIds": hard_issue_ids,
            "sourceRevision": review_source_revision,
        })

    if review_passed:
        revision_stage = _stage(chapter_id, "revision", "pass", "not_required", {
            "appliedProposalIds": [str(item.get("proposal_id") or "") for item in applied],
        })
    elif review_stale and applied_to_current:
        revision_stage = _stage(chapter_id, "revision", "pass", "applied_requires_rereview", {
            "appliedProposalIds": [str(item.get("proposal_id") or "") for item in applied_to_current],
            "addressedIssueIds": sorted({
                str(issue_id)
                for item in applied_to_current
                for issue_id in item.get("review_issue_ids") or []
            }),
        })
    elif pending:
        revision_stage = _stage(chapter_id, "revision", "inconclusive", "proposal_pending", {
            "proposalIds": [str(item.get("proposal_id") or "") for item in pending],
            "requiredIssueIds": issue_ids,
        })
    else:
        revision_stage = _stage(chapter_id, "revision", "inconclusive", "revision_required", {
            "requiredIssueIds": issue_ids,
        })

    if review_passed:
        closure_stage = _stage(chapter_id, "closure", "pass", "closed", {
            "score": review.get("score"),
            "sourceRevision": review_source_revision,
            "resolvedIssueIds": [
                str(item.get("id") or "")
                for item in (review.get("issue_delta") or {}).get("resolved") or []
                if isinstance(item, dict) and item.get("id")
            ],
        })
    elif review_stale and applied_to_current:
        closure_stage = _stage(chapter_id, "closure", "inconclusive", "rereview_required", {
            "currentRevision": current_revision,
            "appliedProposalIds": [str(item.get("proposal_id") or "") for item in applied_to_current],
        })
    elif review_current:
        closure_stage = _stage(chapter_id, "closure", "fail", "review_failed", {
            "score": review.get("score"),
            "threshold": effective_threshold,
            "issueIds": issue_ids,
            "hardIssueIds": hard_issue_ids,
        })
    else:
        closure_stage = _stage(chapter_id, "closure", "inconclusive", "review_required", {})

    stages = {"review": review_stage, "revision": revision_stage, "closure": closure_stage}
    for name, record in stages.items():
        _atomic_write_json(artifact_dir / f"{name}.json", record)

    manifest = {
        "schemaVersion": "dsh-novel.delivery.manifest.v1",
        "recordType": "chapter-delivery",
        "chapterId": chapter_id,
        "novelId": novel_id,
        "threshold": effective_threshold,
        "manuscriptTarget": manuscript_target,
        "currentRevision": current_revision,
        "readyForDelivery": bool(current_revision) and closure_stage["verdict"] == "pass",
        "stages": stages,
        "revisionTrail": [
            {
                "proposalId": str(item.get("proposal_id") or ""),
                "status": str(item.get("status") or ""),
                "issueIds": [str(value) for value in item.get("review_issue_ids") or []],
                "sourceRevision": str(item.get("source_revision") or ""),
                "appliedRevision": str(item.get("applied_revision") or ""),
            }
            for item in proposals
        ],
    }
    _atomic_write_json(artifact_dir / "delivery.json", manifest)

    nodes: dict[str, dict[str, Any]] = {
        "root": {
            "kind": "composite",
            "title": f"{chapter_id} 章节交付",
            "constraint": "hard",
            "target": (relative_dir / "delivery.json").as_posix(),
            "completion": {"op": "all", "items": [
                {"op": "ref", "id": name} for name in ("manuscript", "review", "revision", "closure")
            ]},
            "verifier": {
                "mode": "agentic",
                "instruction": (
                    "只检查章节交付 manifest 的整体自洽性：正文、当前评审、修订应用与复评关闭"
                    "是否形成完整链路。不要修改文件，也不要重新进行 37 维正文审查。"
                ),
            },
        },
        "manuscript": {
            "kind": "leaf", "title": "正文已成形", "constraint": "hard",
            "target": manuscript_target,
            "verifier": {"mode": "programmatic", "script": "import-chapter"},
        },
    }
    for name, title in (("review", "当前正文已评审"), ("revision", "修订动作已结算"), ("closure", "问题经复评关闭")):
        nodes[name] = {
            "kind": "leaf", "title": title, "constraint": "hard",
            "target": (relative_dir / f"{name}.json").as_posix(),
            "verifier": {"mode": "programmatic", "script": "delivery-stage"},
        }
    contains = [
        {"parent": "root", "child": name, "required": True, "failure": "fatal"}
        for name in ("manuscript", "review", "revision", "closure")
    ]
    graph = {
        "schemaVersion": "0.9",
        "id": f"novel-delivery-{chapter_id}",
        "root": "root",
        "nodes": nodes,
        "contains": contains,
        "dependsOn": [
            {"source": "review", "target": "manuscript", "data": ["manuscript"]},
            {"source": "revision", "target": "review", "data": ["review"]},
            {"source": "closure", "target": "revision", "data": ["revision"]},
        ],
    }
    graph_path = artifact_dir / "dog-graph.json"
    _atomic_write_json(graph_path, graph)
    return {
        "status": "ready",
        "manifest": (relative_dir / "delivery.json").as_posix(),
        "graph_path": str(graph_path),
        "graph": graph,
        "ready_for_delivery": manifest["readyForDelivery"],
        "stages": {name: value["status"] for name, value in stages.items()},
    }


def write_delivery_artifacts_from_studio(
    studio: Any,
    chapter_id: str,
    threshold: int | None = None,
) -> dict[str, Any]:
    workspace = studio.get("/api/workspace")
    project = workspace.get("project") if isinstance(workspace.get("project"), dict) else {}
    snapshot = workspace.get("snapshot") if isinstance(workspace.get("snapshot"), dict) else {}
    root_text = str(project.get("root") or "").strip()
    novel_id = str(snapshot.get("novel_id") or "").strip()
    if not root_text or not novel_id:
        raise ValueError("Studio workspace lacks project.root or snapshot.novel_id")
    return write_delivery_artifacts(Path(root_text), novel_id, chapter_id, threshold)
