"""Cross-language contract parity tests.

The JSON Schemas under `contracts/` are the machine-readable source of truth;
these tests prove that (a) every valid fixture passes the schema, (b) every
invalid variant fails it, and (c) the hand-written Python validators and the
schema-derived generated validators (`tools/contracts_generated.py`, produced
by `tools/schema_codegen.py`) agree with the schema verdict on the same
matrix. The JavaScript mirror runs the same fixtures plus the generated
TypeScript validators (`npm run test:contracts` on the dsh side), giving
cross-language parity.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from tools import schema_codegen
from tools.canonical_contracts import (
    validate_benchmark_v1,
    validate_delivery_v2,
    validate_model_profile_surface,
    validate_review_manifest_v2,
    validate_review_v2,
)
from tools.contracts_generated import (
    validate_benchmark_v1 as generated_benchmark_v1,
)
from tools.contracts_generated import (
    validate_delivery_stage_v2 as generated_delivery_stage_v2,
)
from tools.contracts_generated import (
    validate_delivery_v2 as generated_delivery_v2,
)
from tools.contracts_generated import (
    validate_model_profile_surface as generated_model_profile_surface,
)
from tools.contracts_generated import (
    validate_review_manifest_v2 as generated_review_manifest_v2,
)
from tools.contracts_generated import (
    validate_review_v2 as generated_review_v2,
)
from tools.schema_lint import validate_or_raise, validate_schema

CONTRACTS = Path(__file__).resolve().parents[1] / "contracts"
FIXTURE = Path(__file__).parent / "fixtures" / "contracts" / "canonical_v2.json"


def _load(name: str) -> dict:
    return json.loads((CONTRACTS / name).read_text(encoding="utf-8"))


def _payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


SCHEMA_BY_KEY = {
    "review": ("review-v2-decision.schema.json", validate_review_v2),
    "delivery": ("delivery-manifest-v2.schema.json", validate_delivery_v2),
    "model_profile": ("model-profile-surface-v1.schema.json", validate_model_profile_surface),
    "benchmark": ("model-benchmark-v1.schema.json", validate_benchmark_v1),
}


@pytest.mark.parametrize("schema_name", [
    "review-v2-decision.schema.json",
    "review-manifest-v2.schema.json",
    "delivery-manifest-v2.schema.json",
    "delivery-stage-v2.schema.json",
    "model-benchmark-v1.schema.json",
    "model-profile-surface-v1.schema.json",
])
def test_contract_schemas_are_loadable_json_objects(schema_name: str) -> None:
    schema = _load(schema_name)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["type"] == "object"
    assert isinstance(schema["required"], list) and schema["required"]
    assert "$id" in schema


@pytest.mark.parametrize("key", sorted(SCHEMA_BY_KEY))
def test_golden_fixture_passes_schema_and_hand_validator(key: str) -> None:
    schema_name, hand_validator = SCHEMA_BY_KEY[key]
    value = _payload()[key]
    validate_or_raise(value, _load(schema_name))
    hand_validator(value)


def test_review_manifest_schema_accepts_real_shape() -> None:
    manifest = {
        "schemaVersion": "dsh-novel.review.manifest.v2",
        "recordType": "review",
        "chapterId": "ch_001",
        "verdict": "pass",
        "decisionSource": "v2",
        "threshold": 70,
        "coverage": 1.0,
        "qualityScore": 84,
    }
    validate_or_raise(manifest, _load("review-manifest-v2.schema.json"))
    validate_review_manifest_v2(manifest)


def test_stage_schema_rejects_bad_verdict_and_empty_status() -> None:
    schema = _load("delivery-stage-v2.schema.json")
    stage = {
        "schemaVersion": "dsh-novel.delivery.stage.v2",
        "recordType": "delivery-stage",
        "chapterId": "ch_001",
        "stage": "writing",
        "verdict": "pass",
        "status": "committed",
        "evidence": {},
    }
    validate_or_raise(stage, schema)
    for mutate in ({"verdict": "excellent"}, {"status": ""}):
        bad = {**stage, **mutate}
        assert validate_schema(bad, schema), mutate


def test_review_v2_schema_rejects_unknown_version_and_bad_enums() -> None:
    schema = _load("review-v2-decision.schema.json")
    base = _payload()["review"]
    for mutate in (
        {"schema_version": "openwrite.review.v999"},
        {"execution_status": "finished"},
        {"gate_status": "ok"},
        {"delivery_status": "maybe"},
        {"coverage": 1.5},
        {"quality_score": 120},
    ):
        bad = {**base, **mutate}
        assert validate_schema(bad, schema), mutate
        with pytest.raises(ValueError):
            validate_review_v2(bad)


def test_review_v2_missing_schema_fails_both_layers() -> None:
    bad = {k: v for k, v in _payload()["review"].items() if k != "schema_version"}
    assert validate_schema(bad, _load("review-v2-decision.schema.json"))
    with pytest.raises(ValueError):
        validate_review_v2(bad)


def test_benchmark_schema_rejects_bad_status_and_types() -> None:
    schema = _load("model-benchmark-v1.schema.json")
    base = _payload()["benchmark"]
    for mutate in (
        {"status": "done"},
        {"candidates": "nope"},
        {"evaluations": None},
        {"schema_version": "openwrite.model-benchmark.v9"},
    ):
        bad = {**base, **mutate}
        assert validate_schema(bad, schema), mutate
        with pytest.raises(ValueError):
            validate_benchmark_v1(bad)


def test_profile_schema_rejects_credentials() -> None:
    schema = _load("model-profile-surface-v1.schema.json")
    base = _payload()["model_profile"]
    validate_or_raise(base, schema)
    leaked = copy.deepcopy(base)
    leaked["profiles"][0]["api_key"] = "must-not-appear"
    assert validate_schema(leaked, schema)
    with pytest.raises(ValueError):
        validate_model_profile_surface(leaked)

def test_review_manifest_schema_and_validator_reject_negatives() -> None:
    schema = _load("review-manifest-v2.schema.json")
    base = {
        "schemaVersion": "dsh-novel.review.manifest.v2",
        "recordType": "review",
        "chapterId": "ch_001",
        "verdict": "pass",
    }
    for mutate in (
        {"schemaVersion": "dsh-novel.review.manifest.v999"},
        {"recordType": "review-batch"},
        {"chapterId": "chapter-1"},
        {"verdict": "excellent"},
    ):
        bad = {**base, **mutate}
        assert validate_schema(bad, schema), mutate
        with pytest.raises(ValueError):
            validate_review_manifest_v2(bad)
    for key in ("schemaVersion", "recordType", "chapterId", "verdict"):
        bad = {k: v for k, v in base.items() if k != key}
        assert validate_schema(bad, schema), key
        with pytest.raises(ValueError):
            validate_review_manifest_v2(bad)


def test_delivery_manifest_schema_rejects_bad_stage() -> None:
    schema = _load("delivery-manifest-v2.schema.json")
    base = _payload()["delivery"]
    validate_or_raise(base, schema)
    bad_stage = copy.deepcopy(base)
    bad_stage["stages"]["writing"]["verdict"] = "excellent"
    assert validate_schema(bad_stage, schema)
    with pytest.raises(ValueError):
        validate_delivery_v2(bad_stage)


# ── generated validators: schema-derived runtime path ────────────────────────

GENERATED_BY_KEY = {
    "review": ("review-v2-decision.schema.json", generated_review_v2),
    "delivery": ("delivery-manifest-v2.schema.json", generated_delivery_v2),
    "model_profile": ("model-profile-surface-v1.schema.json", generated_model_profile_surface),
    "benchmark": ("model-benchmark-v1.schema.json", generated_benchmark_v1),
}


@pytest.mark.parametrize("key", sorted(GENERATED_BY_KEY))
def test_generated_validator_matches_schema_and_hand_validator_on_golden(key: str) -> None:
    schema_name, hand_validator = SCHEMA_BY_KEY[key]
    generated_validator = GENERATED_BY_KEY[key][1]
    value = _payload()[key]
    validate_or_raise(value, _load(schema_name))
    assert generated_validator(value) == hand_validator(value)


def _negative_mutations() -> list[tuple[str, str, dict[str, Any]]]:
    """Cases where schema, hand-written, and generated validators must all
    reject. Each entry is (label, contract key, mutation applied to the golden
    payload of that key)."""
    return [
        ("review unknown version", "review", {"schema_version": "openwrite.review.v999"}),
        ("review bad execution enum", "review", {"execution_status": "finished"}),
        ("review bad gate enum", "review", {"gate_status": "ok"}),
        ("review bad delivery enum", "review", {"delivery_status": "maybe"}),
        ("review coverage above range", "review", {"coverage": 1.5}),
        ("review quality above range", "review", {"quality_score": 120}),
        ("review bool is not a number", "review", {"coverage": True}),
        ("review missing schema_version", "review", {"schema_version": ...}),
        ("benchmark bad status", "benchmark", {"status": "done"}),
        ("benchmark candidates not array", "benchmark", {"candidates": "nope"}),
        ("benchmark evaluations null", "benchmark", {"evaluations": None}),
        ("benchmark unknown version", "benchmark", {"schema_version": "openwrite.model-benchmark.v9"}),
        ("benchmark missing context_hash", "benchmark", {"context_hash": ...}),
        ("delivery unknown version", "delivery", {"schemaVersion": "dsh-novel.delivery.manifest.v9"}),
        ("delivery bad recordType", "delivery", {"recordType": "delivery"}),
        ("delivery missing stages", "delivery", {"stages": ...}),
        ("delivery empty stages", "delivery", {"stages": {}}),
    ]


@pytest.mark.parametrize(
    ("label", "key", "mutation"),
    _negative_mutations(),
    ids=[case[0] for case in _negative_mutations()],
)
def test_generated_and_hand_validators_agree_on_negatives(
    label: str, key: str, mutation: dict[str, Any]
) -> None:
    schema_name, hand_validator = SCHEMA_BY_KEY[key]
    generated_validator = GENERATED_BY_KEY[key][1]
    bad = copy.deepcopy(_payload()[key])
    for field, value in mutation.items():
        if value is ...:
            bad.pop(field, None)
        else:
            bad[field] = value
    assert validate_schema(bad, _load(schema_name)), label
    with pytest.raises(ValueError):
        hand_validator(bad)
    with pytest.raises(ValueError):
        generated_validator(bad)


@pytest.mark.parametrize("bad_root", [[], None, "text", 42, True])
def test_generated_and_hand_validators_reject_non_object_roots(bad_root: Any) -> None:
    schema = _load("review-v2-decision.schema.json")
    assert validate_schema(bad_root, schema)
    with pytest.raises(ValueError):
        validate_review_v2(bad_root)
    with pytest.raises(ValueError):
        generated_review_v2(bad_root)


def test_generated_validators_reject_nested_and_credential_negatives() -> None:
    payload = _payload()

    leaked = copy.deepcopy(payload["model_profile"])
    leaked["profiles"][0]["api_key"] = "must-not-appear"
    schema = _load("model-profile-surface-v1.schema.json")
    assert validate_schema(leaked, schema)
    with pytest.raises(ValueError):
        validate_model_profile_surface(leaked)
    with pytest.raises(ValueError):
        generated_model_profile_surface(leaked)

    bad_stage = copy.deepcopy(payload["delivery"])
    bad_stage["stages"]["writing"]["verdict"] = "excellent"
    delivery_schema = _load("delivery-manifest-v2.schema.json")
    assert validate_schema(bad_stage, delivery_schema)
    with pytest.raises(ValueError):
        validate_delivery_v2(bad_stage)
    with pytest.raises(ValueError):
        generated_delivery_v2(bad_stage)


def test_generated_delivery_stage_validator_matches_schema() -> None:
    stage = {
        "schemaVersion": "dsh-novel.delivery.stage.v2",
        "recordType": "delivery-stage",
        "chapterId": "ch_001",
        "stage": "writing",
        "verdict": "pass",
        "status": "committed",
        "evidence": {},
    }
    generated_delivery_stage_v2(stage)
    for mutate in ({"verdict": "excellent"}, {"status": ""}, {"schemaVersion": "v9"}):
        with pytest.raises(ValueError):
            generated_delivery_stage_v2({**stage, **mutate})


def test_generated_review_manifest_validator_matches_hand() -> None:
    base = {
        "schemaVersion": "dsh-novel.review.manifest.v2",
        "recordType": "review",
        "chapterId": "ch_001",
        "verdict": "pass",
    }
    assert generated_review_manifest_v2(base) == validate_review_manifest_v2(base)
    negatives = [
        {"schemaVersion": "dsh-novel.review.manifest.v999"},
        {"recordType": "review-batch"},
        {"chapterId": "chapter-1"},
        {"verdict": "excellent"},
    ]
    for mutate in negatives:
        bad = {**base, **mutate}
        with pytest.raises(ValueError):
            validate_review_manifest_v2(bad)
        with pytest.raises(ValueError):
            generated_review_manifest_v2(bad)
    for key in ("schemaVersion", "recordType", "chapterId", "verdict"):
        bad = {k: v for k, v in base.items() if k != key}
        with pytest.raises(ValueError):
            validate_review_manifest_v2(bad)
        with pytest.raises(ValueError):
            generated_review_manifest_v2(bad)


def test_codegen_output_is_byte_identical_to_committed_artifacts() -> None:
    """Re-running the generator must not change the committed artifacts; a
    schema edit without regeneration fails here."""
    schemas = schema_codegen.load_schemas()
    assert schema_codegen.render_python(schemas) == schema_codegen.PYTHON_TARGET.read_text(
        encoding="utf-8"
    )
    ts_target = schema_codegen.dsh_root() / schema_codegen.TS_RELATIVE_TARGET
    if not ts_target.is_file():
        pytest.skip("dsh-novel checkout not found")
    assert schema_codegen.render_typescript(schemas) == ts_target.read_text(encoding="utf-8")
