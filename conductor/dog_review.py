"""Materialize an OpenWrite 37-dimension review as a DoG query graph.

OpenWrite remains the owner of the review judgment.  This module only turns
the returned report into immutable, file-backed records that dsh-dog can
query, inherit, and aggregate without running the 37-dimension model review
again.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


DIMENSION_NAMES: dict[int, str] = {
    1: "OOC检查",
    2: "时间线检查",
    3: "设定冲突",
    4: "战力崩坏",
    5: "数值检查",
    6: "伏笔检查",
    7: "节奏检查",
    8: "文风检查",
    9: "信息越界",
    10: "词汇疲劳",
    11: "利益链断裂",
    12: "年代考据",
    13: "配角降智",
    14: "配角工具人化",
    15: "爽点虚化",
    16: "台词失真",
    17: "流水账",
    18: "知识库污染",
    19: "视角一致性",
    20: "段落等长",
    21: "套话密度",
    22: "公式化转折",
    23: "列表式结构",
    24: "支线停滞",
    25: "弧线平坦",
    26: "节奏单调",
    27: "敏感词检查",
    28: "正传事件冲突",
    29: "未来信息泄露",
    30: "世界规则跨书一致性",
    31: "番外伏笔隔离",
    32: "读者期待管理",
    33: "大纲偏离检测",
    34: "角色还原度",
    35: "世界规则遵守",
    36: "关系动态",
    37: "正典事件一致性",
}

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


def _as_dimension(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number in DIMENSION_NAMES else None


def _selected_dimensions(review: dict[str, Any]) -> set[int]:
    selected = review.get("dimensions")
    if not isinstance(selected, list):
        return set(DIMENSION_NAMES)
    return {number for item in selected if (number := _as_dimension(item)) is not None}


def _normalized_issue(issue: Any) -> dict[str, Any]:
    if not isinstance(issue, dict):
        return {"severity": "warning", "description": str(issue)}
    evidence = issue.get("evidence")
    return {
        "id": str(issue.get("id") or ""),
        "severity": str(issue.get("severity") or "warning").lower(),
        "category": str(issue.get("category") or ""),
        "description": str(issue.get("description") or issue.get("summary") or ""),
        "suggestion": str(issue.get("suggestion") or ""),
        "evidence": evidence if isinstance(evidence, dict) else {"quote": str(evidence or "")},
    }


def _gate_passed(review: dict[str, Any], threshold: int) -> bool:
    score = int(review.get("score") or 0)
    has_hard_issue = any(
        isinstance(issue, dict)
        and str(issue.get("severity") or "").lower() in HARD_SEVERITIES
        for issue in review.get("issue_details") or []
    )
    return score >= threshold and not has_hard_issue


def build_review_manifest(
    review: dict[str, Any],
    chapter_id: str,
    threshold: int,
) -> tuple[dict[str, Any], dict[int, dict[str, Any]]]:
    """Return one aggregate manifest and the 37 dimension records.

    A selected-dimension review cannot prove omitted dimensions. Those records
    are marked ``inconclusive`` so the DoG graph never turns a partial audit
    into a false pass.
    """
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

    dimensions: dict[int, dict[str, Any]] = {}
    for number, name in DIMENSION_NAMES.items():
        issues = grouped[number]
        if number not in selected:
            verdict = "inconclusive"
        elif any(issue["severity"] in HARD_SEVERITIES for issue in issues):
            verdict = "fail"
        else:
            verdict = "pass"
        dimensions[number] = {
            "schemaVersion": "dsh-novel.review.dimension.v1",
            "recordType": "dimension",
            "chapterId": chapter_id,
            "dimension": number,
            "name": name,
            "verdict": verdict,
            "issueCount": len(issues),
            "issues": issues,
            "sourceReviewPassed": bool(review.get("passed")),
            "sourceReviewScore": review.get("score"),
        }

    manifest = {
        "schemaVersion": "dsh-novel.review.manifest.v1",
        "recordType": "review",
        "chapterId": chapter_id,
        "threshold": threshold,
        "verdict": "pass" if _gate_passed(review, threshold) else "fail",
        "sourceReviewPassed": bool(review.get("passed")),
        "score": review.get("score"),
        "summary": str(review.get("summary") or ""),
        "requestedDimensions": sorted(selected),
        "dimensionCount": len(DIMENSION_NAMES),
        "issueCount": sum(len(items) for items in grouped.values()) + len(unmapped),
        "unmappedIssueCount": len(unmapped),
        "unmappedIssues": unmapped,
        "dimensions": list(dimensions.values()),
    }
    return manifest, dimensions


def _workspace_project(workspace: dict[str, Any]) -> tuple[Path, str]:
    project = workspace.get("project") if isinstance(workspace.get("project"), dict) else {}
    snapshot = workspace.get("snapshot") if isinstance(workspace.get("snapshot"), dict) else {}
    root_text = str(project.get("root") or "").strip()
    novel_id = str(snapshot.get("novel_id") or "").strip()
    if not root_text or not novel_id:
        raise ValueError("Studio workspace lacks project.root or snapshot.novel_id")
    root = Path(root_text).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Studio project root is not a directory: {root}")
    return root, novel_id


def write_review_artifacts(
    studio: Any,
    chapter_id: str,
    review: dict[str, Any],
    threshold: int,
) -> dict[str, Any]:
    """Persist manifest/dimension files and return a DoG-compatible graph."""
    workspace = studio.get("/api/workspace")
    root, novel_id = _workspace_project(workspace)
    manifest, dimensions = build_review_manifest(review, chapter_id, threshold)
    relative_dir = Path("data") / "novels" / novel_id / "data" / "dog" / "reviews" / chapter_id
    artifact_dir = root / relative_dir
    manifest_path = artifact_dir / "review.json"
    _atomic_write_json(manifest_path, manifest)
    for number, record in dimensions.items():
        _atomic_write_json(artifact_dir / f"dim_{number:02d}.json", record)

    manifest_target = str((relative_dir / "review.json").as_posix())
    nodes: dict[str, dict[str, Any]] = {
        "root": {
            "kind": "composite",
            "title": f"{chapter_id} 37维审查",
            "constraint": "hard",
            "target": manifest_target,
            "completion": {
                "op": "all",
                "items": [{"op": "ref", "id": f"dim-{number:02d}"} for number in DIMENSION_NAMES],
            },
            "verifier": {
                "mode": "agentic",
                "instruction": (
                    "只检查这份 OpenWrite 37 维审查 manifest 的聚合一致性：确认 dimensionCount、"
                    "requestedDimensions、unmappedIssues、各维 verdict、总分与总体 verdict 没有互相矛盾。"
                    "不要重新审查正文；给出证据。"
                ),
            },
        }
    }
    contains = []
    for number, name in DIMENSION_NAMES.items():
        node_id = f"dim-{number:02d}"
        nodes[node_id] = {
            "kind": "leaf",
            "title": f"{number}. {name}",
            "constraint": "hard",
            "target": str((relative_dir / f"dim_{number:02d}.json").as_posix()),
            "verifier": {"mode": "programmatic", "script": "review-dimension"},
        }
        contains.append({"parent": "root", "child": node_id, "required": True, "failure": "fatal"})

    graph = {
        "schemaVersion": "0.9",
        "id": f"novel-review-{chapter_id}",
        "root": "root",
        "nodes": nodes,
        "contains": contains,
        "dependsOn": [],
    }
    graph_path = artifact_dir / "dog-graph.json"
    _atomic_write_json(graph_path, graph)
    return {
        "manifest": manifest_target,
        "directory": str(artifact_dir),
        "graph_path": str(graph_path),
        "graph": graph,
        "dimensions": len(dimensions),
    }
