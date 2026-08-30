"""Generate schema-derived contract types and validators from ``contracts/*.schema.json``.

The six JSON Schemas under ``contracts/`` are the machine-readable source of
truth for the OpenWrite boundary contracts. This generator renders:

- ``tools/contracts_generated.py`` — TypedDict types plus ``validate_*``
  functions. Validation is schema-derived (the canonical schemas are embedded
  and interpreted through the shared subset validator ``tools.schema_lint``);
  failures raise ``ValueError``, which the Studio boundary surfaces as
  ``CONTRACT_INVALID``.
- the TypeScript mirror ``contracts-generated.ts`` in the dsh-novel bridge
  package (types plus validators throwing ``CONTRACT_INVALID: ...`` errors).

Both artifacts embed the same canonical schema text and the same validation
subset (type/const/enum/required/properties/items/minProperties/minimum/
maximum/pattern/minLength/disallowed/additionalProperties), so Python and
TypeScript verdicts are identical by construction.

Usage::

    .venv/bin/python tools/schema_codegen.py           # regenerate both artifacts
    .venv/bin/python tools/schema_codegen.py --check   # fail if artifacts are stale
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

OPENWRITE_ROOT = Path(__file__).resolve().parents[1]
CONTRACTS_DIR = OPENWRITE_ROOT / "contracts"
PYTHON_TARGET = OPENWRITE_ROOT / "tools" / "contracts_generated.py"
TS_RELATIVE_TARGET = Path("packages") / "openwrite-bridge" / "src" / "contracts-generated.ts"

# key, schema file, python validator, TypeScript validator, human label
CONTRACTS: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "review_v2_decision",
        "review-v2-decision.schema.json",
        "validate_review_v2",
        "validateReviewV2Decision",
        "review_v2",
    ),
    (
        "review_manifest_v2",
        "review-manifest-v2.schema.json",
        "validate_review_manifest_v2",
        "validateReviewManifestV2",
        "review manifest",
    ),
    (
        "delivery_manifest_v2",
        "delivery-manifest-v2.schema.json",
        "validate_delivery_v2",
        "validateDeliveryManifestV2",
        "delivery manifest",
    ),
    (
        "delivery_stage_v2",
        "delivery-stage-v2.schema.json",
        "validate_delivery_stage_v2",
        "validateDeliveryStageV2",
        "delivery stage",
    ),
    (
        "model_benchmark_v1",
        "model-benchmark-v1.schema.json",
        "validate_benchmark_v1",
        "validateModelBenchmarkV1",
        "benchmark",
    ),
    (
        "model_profile_surface_v1",
        "model-profile-surface-v1.schema.json",
        "validate_model_profile_surface",
        "validateModelProfileSurfaceV1",
        "model profile surface",
    ),
)


def dsh_root() -> Path:
    """Locate the sibling dsh-novel repository (override with DSH_NOVEL_ROOT)."""
    return Path(os.environ.get("DSH_NOVEL_ROOT") or Path.home() / "dsh-novel")


def load_schemas() -> dict[str, dict[str, Any]]:
    schemas: dict[str, dict[str, Any]] = {}
    for key, filename, *_ in CONTRACTS:
        schemas[key] = json.loads((CONTRACTS_DIR / filename).read_text(encoding="utf-8"))
    return schemas


def _pascal(name: str) -> str:
    parts = re.split(r"[_\-]+", name)
    return "".join(
        part.upper() if re.fullmatch(r"v\d+", part) else part[:1].upper() + part[1:]
        for part in parts
        if part
    )


def _collection_item_hint(hint: str) -> str:
    return hint[:-1] if hint.endswith("s") else f"{hint}Item"


def _py_literal(values: list[Any]) -> str:
    return "Literal[" + ", ".join(json.dumps(v, ensure_ascii=False) for v in values) + "]"


class _PyTypeRenderer:
    """Render TypedDict classes from schemas, nested classes first."""

    def __init__(self) -> None:
        self.classes: list[str] = []
        self.seen: set[str] = set()

    def annotation(self, schema: Mapping[str, Any], hint: str) -> str:
        if "const" in schema:
            return _py_literal([schema["const"]])
        if "enum" in schema:
            return _py_literal(list(schema["enum"]))
        raw = schema.get("type")
        if isinstance(raw, str):
            names = [raw]
        elif isinstance(raw, list):
            names = [str(item) for item in raw]
        else:
            names = []
        nullable = "null" in names
        names = [name for name in names if name != "null"]
        base = self._base(names[0] if names else "", schema, hint)
        return f"{base} | None" if nullable else base

    def _base(self, name: str, schema: Mapping[str, Any], hint: str) -> str:
        if name == "string":
            return "str"
        if name == "number":
            return "float"
        if name == "integer":
            return "int"
        if name == "boolean":
            return "bool"
        if name == "array":
            items = schema.get("items")
            if isinstance(items, Mapping):
                item_hint = _collection_item_hint(hint)
                return f"list[{self.annotation(items, item_hint)}]"
            return "list[Any]"
        if name == "object" or "properties" in schema:
            if "properties" in schema:
                return self._typed_dict(hint, schema)
            extra = schema.get("additionalProperties")
            if isinstance(extra, Mapping):
                value_hint = _collection_item_hint(hint)
                return f"dict[str, {self.annotation(extra, value_hint)}]"
            return "dict[str, Any]"
        return "Any"

    def _typed_dict(self, name: str, schema: Mapping[str, Any]) -> str:
        if name in self.seen:
            return name
        self.seen.add(name)
        properties = schema.get("properties", {})
        required = list(schema.get("required", []))
        required_lines: list[str] = []
        optional_lines: list[str] = []
        for prop, sub in properties.items():
            annotation = self.annotation(sub, name + _pascal(prop))
            target = required_lines if prop in required else optional_lines
            target.extend(_py_property_lines(prop, annotation))
        title = str(schema.get("title") or name)
        lines: list[str] = []
        if required_lines:
            lines.append(f"class _{name}Required(TypedDict):")
            lines.append(f'    """Required keys of {name}."""')
            lines.append("")
            lines.extend(required_lines)
            lines.append("")
            lines.append("")
            lines.append(f"class {name}(_{name}Required, total=False):")
        else:
            lines.append(f"class {name}(TypedDict, total=False):")
        lines.append(f'    """{title}."""')
        if optional_lines:
            lines.append("")
        lines.extend(optional_lines)
        self.classes.append("\n".join(lines))
        return name


def _py_property_lines(prop: str, annotation: str) -> list[str]:
    line = f"    {prop}: {annotation}"
    if len(line) <= 96 or not annotation.startswith("Literal["):
        return [line]
    items = annotation[len("Literal[") : -1].split(", ")
    out = [f"    {prop}: Literal["]
    out.extend(f"        {item}," for item in items)
    out.append("    ]")
    return out


class _TsTypeRenderer:
    """Render TypeScript interfaces from schemas, nested interfaces first."""

    def __init__(self) -> None:
        self.interfaces: list[str] = []
        self.seen: set[str] = set()

    def annotation(self, schema: Mapping[str, Any], hint: str) -> str:
        if "const" in schema:
            return json.dumps(schema["const"], ensure_ascii=False)
        if "enum" in schema:
            return " | ".join(json.dumps(v, ensure_ascii=False) for v in schema["enum"])
        raw = schema.get("type")
        if isinstance(raw, str):
            names = [raw]
        elif isinstance(raw, list):
            names = [str(item) for item in raw]
        else:
            names = []
        nullable = "null" in names
        names = [name for name in names if name != "null"]
        base = self._base(names[0] if names else "", schema, hint)
        return f"{base} | null" if nullable else base

    def _base(self, name: str, schema: Mapping[str, Any], hint: str) -> str:
        if name == "string":
            return "string"
        if name in ("number", "integer"):
            return "number"
        if name == "boolean":
            return "boolean"
        if name == "array":
            items = schema.get("items")
            if isinstance(items, Mapping):
                item_hint = _collection_item_hint(hint)
                return f"{self.annotation(items, item_hint)}[]"
            return "unknown[]"
        if name == "object" or "properties" in schema:
            if "properties" in schema:
                return self._interface(hint, schema)
            extra = schema.get("additionalProperties")
            if isinstance(extra, Mapping):
                value_hint = _collection_item_hint(hint)
                return f"Record<string, {self.annotation(extra, value_hint)}>"
            return "Record<string, unknown>"
        return "unknown"

    def _interface(self, name: str, schema: Mapping[str, Any]) -> str:
        if name in self.seen:
            return name
        self.seen.add(name)
        properties = schema.get("properties", {})
        required = set(schema.get("required", []))
        title = str(schema.get("title") or name)
        lines = [f"/** {title}. Extra keys are allowed (additionalProperties). */"]
        lines.append(f"export interface {name} {{")
        for prop, sub in properties.items():
            annotation = self.annotation(sub, name + _pascal(prop))
            marker = "" if prop in required else "?"
            name_part = prop if prop.isidentifier() else json.dumps(prop)
            lines.append(f"  {name_part}{marker}: {annotation}")
        if schema.get("additionalProperties") is True:
            lines.append("  [key: string]: unknown")
        lines.append("}")
        self.interfaces.append("\n".join(lines))
        return name


def _canonical_embed(schemas: dict[str, Any]) -> str:
    ordered = {key: schemas[key] for key, *_ in CONTRACTS}
    return json.dumps(ordered, ensure_ascii=False, sort_keys=True, indent=2)


def _source_lines(schemas: dict[str, Any], comment: str) -> list[str]:
    lines = []
    for key, filename, *_ in CONTRACTS:
        raw = (CONTRACTS_DIR / filename).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()[:12]
        schema_id = schemas[key].get("$id", "?")
        lines.append(f"{comment}   {filename} sha256:{digest} $id: {schema_id}")
    return lines


_TS_VALIDATOR_TEMPLATE = """
type SchemaMap = Record<string, unknown>

function typeOk(value: unknown, name: string): boolean {
  switch (name) {
    case 'object': return value !== null && typeof value === 'object' && !Array.isArray(value)
    case 'array': return Array.isArray(value)
    case 'null': return value === null
    case 'integer': return Number.isInteger(value)
    case 'number': return typeof value === 'number' && !Number.isNaN(value)
    default: return typeof value === name
  }
}

/** Minimal JSON Schema subset validator mirroring OpenWrite
 * `tools/schema_lint.py` and `scripts/schema-lint.mjs`. */
export function validateSchema(value: unknown, schema: SchemaMap, path = '$'): string[] {
  const errors: string[] = []
  const fail = (message: string) => errors.push(`${path}: ${message}`)

  const rawType = schema['type']
  if (rawType !== undefined) {
    const names = Array.isArray(rawType) ? rawType.map(String) : [String(rawType)]
    if (!names.some(name => typeOk(value, name))) {
      const got = value === null ? 'null' : Array.isArray(value) ? 'array' : typeof value
      fail(`expected type ${names.join('/')}, got ${got}`)
      return errors
    }
  }

  if (schema['const'] !== undefined && value !== schema['const']) {
    fail(`expected const ${JSON.stringify(schema['const'])}, got ${JSON.stringify(value)}`)
  }

  const enumValues = schema['enum']
  if (Array.isArray(enumValues) && !enumValues.includes(value)) {
    fail(`${JSON.stringify(value)} not in enum ${JSON.stringify(enumValues)}`)
  }

  if (value !== null && typeof value === 'object' && !Array.isArray(value)) {
    const record = value as Record<string, unknown>
    for (const key of (schema['required'] as string[] | undefined) ?? []) {
      if (!(key in record)) fail(`missing required property '${key}'`)
    }
    for (const key of (schema['disallowed'] as string[] | undefined) ?? []) {
      if (key in record) fail(`forbidden credential-like property '${key}' must not appear`)
    }
    const properties = (schema['properties'] as Record<string, SchemaMap> | undefined) ?? {}
    const additional = schema['additionalProperties']
    for (const [key, sub] of Object.entries(record)) {
      if (key in properties) {
        errors.push(...validateSchema(sub, properties[key] as SchemaMap, `${path}.${key}`))
      } else if (additional === false) {
        fail(`unexpected property '${key}'`)
      } else if (additional !== undefined && typeof additional === 'object') {
        errors.push(...validateSchema(sub, additional as SchemaMap, `${path}.${key}`))
      }
    }
    const minProperties = schema['minProperties']
    if (typeof minProperties === 'number' && Object.keys(record).length < minProperties) {
      fail(`expected at least ${minProperties} properties, got ${Object.keys(record).length}`)
    }
  }

  const items = schema['items']
  if (Array.isArray(value) && items !== undefined && typeof items === 'object') {
    value.forEach((item, index) => {
      errors.push(...validateSchema(item, items as SchemaMap, `${path}[${index}]`))
    })
  }

  if (typeof value === 'number' && !Number.isNaN(value)) {
    const minimum = schema['minimum']
    if (typeof minimum === 'number' && value < minimum) {
      fail(`${value} is less than minimum ${minimum}`)
    }
    const maximum = schema['maximum']
    if (typeof maximum === 'number' && value > maximum) {
      fail(`${value} is greater than maximum ${maximum}`)
    }
  }

  if (typeof value === 'string') {
    const minLength = schema['minLength']
    if (typeof minLength === 'number' && value.length < minLength) {
      fail(`string shorter than minLength ${minLength}`)
    }
    const pattern = schema['pattern']
    if (typeof pattern === 'string' && new RegExp(pattern).test(value) === false) {
      fail(`'${value}' does not match pattern '${pattern}'`)
    }
  }

  return errors
}

const SCHEMAS: Record<string, SchemaMap> = __SCHEMAS__

function validateContract(value: unknown, key: string, label: string): Record<string, unknown> {
  const errors = validateSchema(value, SCHEMAS[key] as SchemaMap)
  if (errors.length > 0) {
    throw new Error(`CONTRACT_INVALID: ${label} violates ${key}: ${errors.join('; ')}`)
  }
  return value as Record<string, unknown>
}
"""


def render_python(schemas: dict[str, Any] | None = None) -> str:
    schemas = schemas or load_schemas()
    renderer = _PyTypeRenderer()
    type_names = {key: _pascal(key) for key, *_ in CONTRACTS}
    for key, *_ in CONTRACTS:
        renderer._typed_dict(type_names[key], schemas[key])

    header = [
        "# generated by tools/schema_codegen.py, do not edit",
        "# sources:",
        *_source_lines(schemas, "#"),
        "",
        '"""Schema-derived contract types and validators (see tools/schema_codegen.py).',
        "",
        "Validation failures raise ValueError; the Studio boundary translates them",
        'into StudioError(code="CONTRACT_INVALID").',
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "import json",
        "from typing import Any, Literal, TypedDict, cast",
        "",
        "from tools.schema_lint import validate_schema",
        "",
        'SCHEMAS: dict[str, Any] = json.loads(r"""',
        _canonical_embed(schemas),
        '""")',
        "",
        "",
        "",
    ]
    body = "\n\n\n".join(renderer.classes)
    validators = [
        "",
        "",
        "",
        "def _validate(value: Any, key: str, label: str) -> dict[str, Any]:",
        "    errors = validate_schema(value, SCHEMAS[key])",
        "    if errors:",
        '        raise ValueError(f"{label} violates {key} contract: '
        + "{"
        + "'; '.join(errors)}"
        + '")',
        "    return dict(value)",
    ]
    for key, _filename, py_name, _ts_name, label in CONTRACTS:
        type_name = type_names[key]
        schema_file = dict((k, f) for k, f, *_ in CONTRACTS)[key]
        validators.extend(
            [
                "",
                "",
                f"def {py_name}(value: Any) -> {type_name}:",
                f'    """Validate against {schema_file} (schema-derived)."""',
                f'    result = _validate(value, "{key}", "{label}")',
                f"    return cast({type_name}, result)",
            ]
        )
    return "\n".join(header) + body + "\n".join(validators) + "\n"


def render_typescript(schemas: dict[str, Any] | None = None) -> str:
    schemas = schemas or load_schemas()
    renderer = _TsTypeRenderer()
    for key, *_ in CONTRACTS:
        renderer._interface(_pascal(key), schemas[key])

    header = [
        "// generated by tools/schema_codegen.py (OpenWrite), do not edit",
        "// sources:",
        *_source_lines(schemas, "//"),
        "",
    ]
    validators: list[str] = []
    for key, _filename, _py_name, ts_name, label in CONTRACTS:
        type_name = _pascal(key)
        validators.extend(
            [
                "",
                f"/** Validate `value` against the {key} schema; throw on failure. */",
                f"export function {ts_name}(value: unknown): {type_name} {{",
                f"  return validateContract(value, '{key}', '{label}') as {type_name}",
                "}",
            ]
        )
    validator = _TS_VALIDATOR_TEMPLATE.replace("__SCHEMAS__", _canonical_embed(schemas))
    return (
        "\n".join(header)
        + "\n\n".join(renderer.interfaces)
        + "\n"
        + validator
        + "\n".join(validators)
        + "\n"
    )


def targets() -> dict[Path, str]:
    return {
        PYTHON_TARGET: render_python(),
        dsh_root() / TS_RELATIVE_TARGET: render_typescript(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if a generated artifact differs from the current render",
    )
    args = parser.parse_args(argv)
    rendered = targets()
    stale = False
    for path, content in rendered.items():
        current = path.read_text(encoding="utf-8") if path.is_file() else None
        if args.check:
            if current != content:
                print(f"STALE: {path}", file=sys.stderr)
                stale = True
            else:
                print(f"current: {path}")
        else:
            if current != content:
                path.write_text(content, encoding="utf-8")
                print(f"wrote: {path}")
            else:
                print(f"unchanged: {path}")
    return 1 if stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
