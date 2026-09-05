"""Canonical, reusable DAG blueprint for chapter review materialization.

OpenWrite owns this topology.  Runtimes instantiate it with a chapter id and
an artifact directory; they do not rebuild the review graph or copy rubric
membership rules.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from functools import lru_cache
from pathlib import PurePosixPath
from typing import Any, Mapping

from tools.review_rubric import (
    DIMENSION_NAMES,
    GATE_CHECK_IDS,
    QUALITY_DOMAINS,
    RUBRIC_VERSION,
    rubric_payload,
)


FRAMEWORK_SCHEMA_VERSION = "openwrite.review-dag-framework.v1"
FRAMEWORK_ID = "openwrite.standard-chapter-review"
FRAMEWORK_VERSION = "1.0.0"
DOG_GRAPH_SCHEMA_VERSION = "0.9"
REVISION_FIELDS = (
    "schema_version",
    "id",
    "version",
    "rubric_version",
    "graph_schema_version",
    "root",
    "topology_locked",
    "topology",
)


def _ref(node_id: str) -> dict[str, str]:
    return {"op": "ref", "id": node_id}


def _content_revision(framework: Mapping[str, Any]) -> str:
    identity = {key: framework[key] for key in REVISION_FIELDS}
    canonical = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _build_framework() -> dict[str, Any]:
    domain_ids = [f"domain-{domain.id}" for domain in QUALITY_DOMAINS]
    root_children = ["context", *domain_ids, "gate", "aggregate"]
    nodes: dict[str, dict[str, Any]] = {
        "root": {
            "kind": "composite",
            "role": "review-root",
            "title": "章节审稿",
            "title_template": "{chapter_id} 评审 DAG",
            "constraint": "hard",
            "artifact": "review.json",
            "completion": {"op": "all", "items": [_ref(item) for item in root_children]},
            "verifier": {"mode": "programmatic", "script": "review-record"},
        },
        "context": {
            "kind": "leaf",
            "role": "context-preflight",
            "title": "上下文完整性",
            "constraint": "hard",
            "artifact": "context.json",
            "verifier": {"mode": "programmatic", "script": "review-record"},
        },
        "gate": {
            "kind": "composite",
            "role": "hard-gate",
            "title": "硬门禁",
            "constraint": "hard",
            "artifact": "gate.json",
            "completion": {
                "op": "all",
                "items": [_ref(f"dim-{check_id:02d}") for check_id in GATE_CHECK_IDS],
            },
            "verifier": {"mode": "programmatic", "script": "review-record"},
        },
        "aggregate": {
            "kind": "leaf",
            "role": "delivery-decision",
            "title": "聚合与交付判定",
            "constraint": "hard",
            "artifact": "aggregate.json",
            "verifier": {"mode": "programmatic", "script": "review-record"},
        },
    }
    contains: list[dict[str, Any]] = [
        {"parent": "root", "child": child, "required": True, "failure": "fatal"}
        for child in root_children
    ]
    for domain in QUALITY_DOMAINS:
        domain_id = f"domain-{domain.id}"
        nodes[domain_id] = {
            "kind": "composite",
            "role": "quality-domain",
            "domain_id": domain.id,
            "title": domain.name,
            "constraint": "soft",
            "artifact": f"domain_{domain.id}.json",
            "completion": {
                "op": "all",
                "items": [_ref(f"dim-{check_id:02d}") for check_id in domain.legacy_check_ids],
            },
            "verifier": {"mode": "programmatic", "script": "review-record"},
        }
        for check_id in domain.legacy_check_ids:
            node_id = f"dim-{check_id:02d}"
            nodes[node_id] = {
                "kind": "leaf",
                "role": "quality-check",
                "domain_id": domain.id,
                "legacy_check_id": check_id,
                "title": f"{check_id}. {DIMENSION_NAMES[check_id]}",
                "constraint": "soft",
                "artifact": f"dim_{check_id:02d}.json",
                "verifier": {"mode": "programmatic", "script": "review-dimension"},
            }
            contains.append(
                {"parent": domain_id, "child": node_id, "required": True, "failure": "warn"}
            )
    for check_id in GATE_CHECK_IDS:
        node_id = f"dim-{check_id:02d}"
        nodes[node_id] = {
            "kind": "leaf",
            "role": "gate-check",
            "legacy_check_id": check_id,
            "title": f"{check_id}. {DIMENSION_NAMES[check_id]}",
            "constraint": "hard",
            "artifact": f"dim_{check_id:02d}.json",
            "verifier": {"mode": "programmatic", "script": "review-dimension"},
        }
        contains.append(
            {"parent": "gate", "child": node_id, "required": True, "failure": "fatal"}
        )

    depends_on = [
        {"source": domain_id, "target": "context", "data": ["review-context"]}
        for domain_id in domain_ids
    ]
    depends_on.append({"source": "gate", "target": "context", "data": ["review-context"]})
    depends_on.extend(
        {"source": "aggregate", "target": domain_id, "data": ["domain-result"]}
        for domain_id in domain_ids
    )
    depends_on.append({"source": "aggregate", "target": "gate", "data": ["gate-result"]})

    framework: dict[str, Any] = {
        "schema_version": FRAMEWORK_SCHEMA_VERSION,
        "id": FRAMEWORK_ID,
        "version": FRAMEWORK_VERSION,
        "rubric_version": RUBRIC_VERSION,
        "title": "OpenWrite 标准章节审稿框架",
        "description": "一次定义、逐章实例化的六域 37 项审稿 DAG。",
        "graph_schema_version": DOG_GRAPH_SCHEMA_VERSION,
        "root": "root",
        "topology_locked": True,
        "selection_policy": {
            "mode": "retain-topology",
            "description": "局部审稿保留全部节点，未请求检查写为 inconclusive。",
        },
        "rubric": rubric_payload(),
        "topology": {
            "nodes": nodes,
            "contains": contains,
            "dependsOn": depends_on,
        },
        "extension_points": [
            {
                "id": "context-evidence",
                "stage": "context",
                "contract": "向 context.json 增补可追溯证据，不改变拓扑。",
            },
            {
                "id": "domain-evaluator",
                "stage": "quality-domains",
                "contract": "按 rubric.criteria 返回评分与证据，不自行聚合总分。",
            },
            {
                "id": "gate-evaluator",
                "stage": "hard-gate",
                "contract": "返回显式 pass/blocked/inconclusive，由聚合节点消费。",
            },
            {
                "id": "post-review-policy",
                "stage": "aggregate",
                "contract": "消费权威 review_v2 决策，不重新推导评分。",
            },
        ],
        "invariants": {
            "node_count": len(nodes),
            "contains_count": len(contains),
            "dependency_count": len(depends_on),
            "domain_count": len(QUALITY_DOMAINS),
            "criterion_count": sum(len(domain.criteria) for domain in QUALITY_DOMAINS),
            "legacy_check_count": len(DIMENSION_NAMES),
            "quality_weight_total": sum(domain.weight for domain in QUALITY_DOMAINS),
            "gate_check_ids": list(GATE_CHECK_IDS),
        },
    }
    validate_review_dag_framework(framework)
    framework["revision"] = _content_revision(framework)
    return framework


@lru_cache(maxsize=1)
def _cached_framework() -> dict[str, Any]:
    return _build_framework()


def review_dag_framework() -> dict[str, Any]:
    """Return a defensive copy of the process-wide canonical blueprint."""
    return deepcopy(_cached_framework())


def validate_review_dag_framework(framework: Mapping[str, Any]) -> None:
    """Reject incomplete, cyclic, or rubric-divergent review blueprints."""
    if framework.get("schema_version") != FRAMEWORK_SCHEMA_VERSION:
        raise ValueError("unsupported review DAG framework schema")
    if framework.get("rubric_version") != RUBRIC_VERSION or framework.get("rubric") != rubric_payload():
        raise ValueError("review DAG framework rubric diverges from the canonical rubric")
    topology = framework.get("topology")
    if not isinstance(topology, Mapping):
        raise ValueError("review DAG framework topology must be an object")
    nodes = topology.get("nodes")
    contains = topology.get("contains")
    depends_on = topology.get("dependsOn")
    if not isinstance(nodes, Mapping) or not nodes:
        raise ValueError("review DAG framework nodes must be a non-empty object")
    if not isinstance(contains, list) or not isinstance(depends_on, list):
        raise ValueError("review DAG framework edges must be arrays")
    root = str(framework.get("root") or "")
    if root not in nodes or nodes[root].get("kind") != "composite":
        raise ValueError("review DAG framework root must be a composite node")

    parent_by_child: dict[str, str] = {}
    for edge in contains:
        if not isinstance(edge, Mapping):
            raise ValueError("review DAG contains edge must be an object")
        parent, child = str(edge.get("parent") or ""), str(edge.get("child") or "")
        if parent not in nodes or child not in nodes:
            raise ValueError("review DAG contains edge references an unknown node")
        if child in parent_by_child:
            raise ValueError(f"review DAG node has multiple parents: {child}")
        parent_by_child[child] = parent
    if set(parent_by_child) != set(nodes) - {root}:
        raise ValueError("review DAG containment must form one rooted tree")
    for node_id in set(nodes) - {root}:
        cursor = node_id
        lineage: set[str] = set()
        while cursor != root:
            if cursor in lineage or cursor not in parent_by_child:
                raise ValueError("review DAG containment must form one rooted tree")
            lineage.add(cursor)
            cursor = parent_by_child[cursor]

    expected_checks = set(DIMENSION_NAMES)
    mapped_checks = {
        int(node.get("legacy_check_id"))
        for node in nodes.values()
        if isinstance(node, Mapping) and node.get("legacy_check_id") is not None
    }
    if mapped_checks != expected_checks:
        raise ValueError("review DAG framework must map all legacy checks exactly once")
    check_nodes = [
        node for node in nodes.values()
        if isinstance(node, Mapping) and node.get("legacy_check_id") is not None
    ]
    if len(check_nodes) != len(expected_checks):
        raise ValueError("review DAG framework contains duplicate legacy checks")
    for domain in QUALITY_DOMAINS:
        parent_id = f"domain-{domain.id}"
        for check_id in domain.legacy_check_ids:
            if parent_by_child.get(f"dim-{check_id:02d}") != parent_id:
                raise ValueError("review DAG quality check membership diverges from the rubric")
    for check_id in GATE_CHECK_IDS:
        if parent_by_child.get(f"dim-{check_id:02d}") != "gate":
            raise ValueError("review DAG gate membership diverges from the rubric")

    adjacency: dict[str, list[str]] = {str(node_id): [] for node_id in nodes}
    for edge in depends_on:
        if not isinstance(edge, Mapping):
            raise ValueError("review DAG dependency must be an object")
        source, target = str(edge.get("source") or ""), str(edge.get("target") or "")
        if source not in nodes or target not in nodes:
            raise ValueError("review DAG dependency references an unknown node")
        adjacency[target].append(source)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            raise ValueError("review DAG framework dependencies must be acyclic")
        if node_id in visited:
            return
        visiting.add(node_id)
        for successor in adjacency[node_id]:
            visit(successor)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in adjacency:
        visit(node_id)

    expected_invariants = {
        "node_count": len(nodes),
        "contains_count": len(contains),
        "dependency_count": len(depends_on),
        "domain_count": len(QUALITY_DOMAINS),
        "criterion_count": sum(len(domain.criteria) for domain in QUALITY_DOMAINS),
        "legacy_check_count": len(DIMENSION_NAMES),
        "quality_weight_total": sum(domain.weight for domain in QUALITY_DOMAINS),
        "gate_check_ids": list(GATE_CHECK_IDS),
    }
    if framework.get("invariants") != expected_invariants:
        raise ValueError("review DAG framework invariants do not match its topology")
    revision = framework.get("revision")
    if revision is not None:
        if revision != _content_revision(framework):
            raise ValueError("review DAG framework revision does not match its content")


def instantiate_review_dag(
    chapter_id: str,
    artifact_directory: str | PurePosixPath,
    *,
    framework: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind the canonical topology to one chapter's artifact paths."""
    if not re.fullmatch(r"ch_\d+", chapter_id):
        raise ValueError("chapter_id must match ch_<digits>")
    prefix = PurePosixPath(str(artifact_directory).replace("\\", "/"))
    if prefix.is_absolute() or not prefix.parts or ".." in prefix.parts:
        raise ValueError("artifact_directory must be a contained relative path")
    blueprint = review_dag_framework() if framework is None else deepcopy(dict(framework))
    validate_review_dag_framework(blueprint)
    topology = blueprint["topology"]
    nodes: dict[str, dict[str, Any]] = {}
    runtime_keys = {"kind", "title", "constraint", "completion", "verifier"}
    for node_id, template in topology["nodes"].items():
        node = {key: deepcopy(value) for key, value in template.items() if key in runtime_keys}
        title_template = template.get("title_template")
        if isinstance(title_template, str):
            node["title"] = title_template.format(chapter_id=chapter_id)
        artifact = str(template.get("artifact") or "")
        if not artifact or PurePosixPath(artifact).name != artifact:
            raise ValueError(f"invalid artifact binding for review DAG node {node_id}")
        node["target"] = (prefix / artifact).as_posix()
        nodes[str(node_id)] = node
    return {
        "schemaVersion": str(blueprint["graph_schema_version"]),
        "id": f"novel-review-{chapter_id}",
        "root": str(blueprint["root"]),
        "nodes": nodes,
        "contains": deepcopy(topology["contains"]),
        "dependsOn": deepcopy(topology["dependsOn"]),
    }
