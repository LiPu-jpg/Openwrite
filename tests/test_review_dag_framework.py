from __future__ import annotations

from copy import deepcopy

import pytest

from tools.review_dag_framework import (
    FRAMEWORK_ID,
    FRAMEWORK_SCHEMA_VERSION,
    instantiate_review_dag,
    review_dag_framework,
    validate_review_dag_framework,
)


def test_standard_review_framework_is_complete_versioned_and_stable() -> None:
    first = review_dag_framework()
    second = review_dag_framework()

    assert first == second
    assert first is not second
    assert first["schema_version"] == FRAMEWORK_SCHEMA_VERSION
    assert first["id"] == FRAMEWORK_ID
    assert first["revision"].startswith("sha256:")
    assert first["topology_locked"] is True
    assert first["invariants"] == {
        "node_count": 47,
        "contains_count": 46,
        "dependency_count": 14,
        "domain_count": 6,
        "criterion_count": 20,
        "legacy_check_count": 37,
        "quality_weight_total": 100.0,
        "gate_check_ids": [27],
    }

    first["topology"]["nodes"].clear()
    assert len(review_dag_framework()["topology"]["nodes"]) == 47


def test_standard_review_framework_instantiates_without_rebuilding_topology() -> None:
    framework = review_dag_framework()
    graph = instantiate_review_dag(
        "ch_007",
        "data/novels/demo/data/dog/reviews/ch_007",
        framework=framework,
    )

    assert graph["schemaVersion"] == "0.9"
    assert graph["id"] == "novel-review-ch_007"
    assert graph["nodes"]["root"]["title"] == "ch_007 评审 DAG"
    assert graph["nodes"]["dim-01"]["target"].endswith("/dim_01.json")
    assert graph["nodes"]["dim-27"]["constraint"] == "hard"
    assert len(graph["nodes"]) == framework["invariants"]["node_count"]
    assert graph["contains"] == framework["topology"]["contains"]
    assert graph["dependsOn"] == framework["topology"]["dependsOn"]


def test_review_framework_rejects_duplicate_checks_cycles_and_unsafe_bindings() -> None:
    duplicate = review_dag_framework()
    duplicate["topology"]["nodes"]["duplicate"] = deepcopy(
        duplicate["topology"]["nodes"]["dim-01"]
    )
    duplicate["topology"]["contains"].append(
        {"parent": "domain-character", "child": "duplicate", "required": True, "failure": "warn"}
    )
    with pytest.raises(ValueError, match="duplicate legacy checks"):
        validate_review_dag_framework(duplicate)

    cyclic = review_dag_framework()
    cyclic["topology"]["dependsOn"].append(
        {"source": "context", "target": "aggregate", "data": ["cycle"]}
    )
    with pytest.raises(ValueError, match="acyclic"):
        validate_review_dag_framework(cyclic)

    tampered = review_dag_framework()
    tampered["topology"]["nodes"]["context"]["title"] = "tampered"
    with pytest.raises(ValueError, match="revision does not match"):
        validate_review_dag_framework(tampered)

    with pytest.raises(ValueError, match="contained relative path"):
        instantiate_review_dag("ch_001", "../outside")
    with pytest.raises(ValueError, match="ch_<digits>"):
        instantiate_review_dag("../../etc", "data/reviews")
