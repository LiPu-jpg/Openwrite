"""Minimal JSON Schema subset validator shared by contract parity tests.

Supported keywords (the subset used by `contracts/*.schema.json`): type,
const, enum, required, properties, items, minProperties, minimum, maximum,
pattern, minLength, disallowed (custom: keys that must not exist), and
additionalProperties: false.

This is deliberately tiny: it validates what the canonical contracts need so
Python and the TypeScript smoke test can mirror each other exactly. Full JSON
Schema codegen remains future work (see GOAL.md).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_TYPES: dict[str, tuple[type, ...]] = {
    "object": (dict,),
    "array": (list,),
    "string": (str,),
    "number": (int, float),
    "integer": (int,),
    "boolean": (bool,),
    "null": (type(None),),
}


def _type_ok(value: Any, name: str) -> bool:
    expected = _TYPES.get(name)
    if expected is None:
        return False
    if not isinstance(value, expected):
        return False
    # bool is a subclass of int; keep number/integer checks strict.
    if name in ("integer", "number") and isinstance(value, bool):
        return False
    return True


def validate_schema(value: Any, schema: Mapping[str, Any], *, path: str = "$") -> list[str]:
    """Return a list of human-readable errors; empty list means valid."""
    errors: list[str] = []

    def fail(message: str) -> None:
        errors.append(f"{path}: {message}")

    expected_types = schema.get("type")
    if expected_types is not None:
        names = [expected_types] if isinstance(expected_types, str) else list(expected_types)
        if not any(_type_ok(value, name) for name in names):
            fail(f"expected type {'/'.join(names)}, got {type(value).__name__}")
            return errors

    if "const" in schema and value != schema["const"]:
        fail(f"expected const {schema['const']!r}, got {value!r}")

    if "enum" in schema and value not in schema["enum"]:
        fail(f"{value!r} not in enum {schema['enum']!r}")

    if isinstance(value, Mapping):
        for key in schema.get("required", []):
            if key not in value:
                fail(f"missing required property {key!r}")
        for key in schema.get("disallowed", []):
            if key in value:
                fail(f"forbidden credential-like property {key!r} must not appear")
        properties = schema.get("properties", {})
        for key, sub_value in value.items():
            if key in properties:
                errors.extend(
                    validate_schema(sub_value, properties[key], path=f"{path}.{key}")
                )
            elif schema.get("additionalProperties") is False:
                fail(f"unexpected property {key!r}")
            elif isinstance(schema.get("additionalProperties"), Mapping):
                errors.extend(
                    validate_schema(
                        sub_value,
                        schema["additionalProperties"],
                        path=f"{path}.{key}",
                    )
                )
        min_props = schema.get("minProperties")
        if min_props is not None and len(value) < min_props:
            fail(f"expected at least {min_props} properties, got {len(value)}")

    if isinstance(value, list):
        item_schema = schema.get("items")
        if item_schema is not None:
            for index, item in enumerate(value):
                errors.extend(
                    validate_schema(item, item_schema, path=f"{path}[{index}]")
                )

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        if minimum is not None and value < minimum:
            fail(f"{value} is less than minimum {minimum}")
        maximum = schema.get("maximum")
        if maximum is not None and value > maximum:
            fail(f"{value} is greater than maximum {maximum}")

    if isinstance(value, str):
        min_length = schema.get("minLength")
        if min_length is not None and len(value) < min_length:
            fail(f"string shorter than minLength {min_length}")
        pattern = schema.get("pattern")
        if pattern is not None and re.search(pattern, value) is None:
            fail(f"{value!r} does not match pattern {pattern!r}")

    return errors


def validate_or_raise(value: Any, schema: Mapping[str, Any]) -> None:
    """Raise a single ValueError aggregating all schema errors."""
    errors = validate_schema(value, schema)
    if errors:
        raise ValueError("; ".join(errors))
