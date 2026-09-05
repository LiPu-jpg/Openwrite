"""Truthful, bounded entity changes returned by OpenWrite write surfaces."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

SCHEMA_VERSION = "openwrite.mutation-summary.v1"
MAX_INLINE_VALUE_CHARS = 4000
MAX_PREVIEW_CHARS = 480

_MISSING = object()


def fingerprint_value(value: Any) -> str:
    rendered = _render(value)
    return "sha256:" + hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def document_entity_kind(path: str) -> str:
    clean = str(path or "").replace("\\", "/").strip("/")
    if clean.startswith("data/manuscript/"):
        return "manuscript"
    if clean == "src/outline.md":
        return "outline"
    if clean.startswith("src/characters/"):
        return "character"
    if clean.startswith(("src/world/", "data/world/")):
        return "world"
    if clean.startswith("data/foreshadowing/"):
        return "foreshadowing"
    if clean.startswith("src/story/"):
        return "canon"
    return "document"


def build_mutation_summary(
    *,
    operation: str,
    entity_kind: str,
    entity_id: str,
    path: str,
    before: Any = _MISSING,
    after: Any = _MISSING,
    source_revision: str = "",
    result_revision: str = "",
    field_prefix: str = "",
    flatten: bool = True,
    execution_status: str = "committed",
) -> dict[str, Any]:
    """Build a committed mutation envelope without inventing unchanged fields.

    Small values are returned exactly. Large values carry an explicit preview,
    length and hash so clients cannot mistake a clipped excerpt for the value.
    """
    items: list[dict[str, Any]] = []
    if (
        flatten
        and isinstance(before, Mapping)
        and isinstance(after, Mapping)
    ):
        fields = sorted(set(before) | set(after))
        for field in fields:
            old = before.get(field, _MISSING)
            new = after.get(field, _MISSING)
            if _equal(old, new):
                continue
            items.extend(
                _field_items(
                    entity_kind=entity_kind,
                    entity_id=entity_id,
                    path=path,
                    field=_join_field(field_prefix, str(field)),
                    before=old,
                    after=new,
                    source_revision=source_revision,
                    result_revision=result_revision,
                    execution_status=execution_status,
                )
            )
    elif not _equal(before, after):
        items.extend(
            _field_items(
                entity_kind=entity_kind,
                entity_id=entity_id,
                path=path,
                field=field_prefix or "value",
                before=before,
                after=after,
                source_revision=source_revision,
                result_revision=result_revision,
                execution_status=execution_status,
            )
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "operation": str(operation or "update"),
        "execution_status": execution_status,
        "source_revision": source_revision or None,
        "result_revision": result_revision or None,
        "items": items,
    }


def merge_mutation_summaries(
    operation: str,
    summaries: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    items = [
        dict(item)
        for summary in summaries
        for item in summary.get("items", [])
        if isinstance(item, Mapping)
    ]
    source_revisions = {
        str(item.get("source_revision") or "") for item in items
    }
    result_revisions = {
        str(item.get("result_revision") or "") for item in items
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "operation": str(operation or "update"),
        "execution_status": "committed",
        "source_revision": (
            next(iter(source_revisions)) if len(source_revisions) == 1 else None
        ),
        "result_revision": (
            next(iter(result_revisions)) if len(result_revisions) == 1 else None
        ),
        "items": items,
    }


def _field_items(
    *,
    entity_kind: str,
    entity_id: str,
    path: str,
    field: str,
    before: Any,
    after: Any,
    source_revision: str,
    result_revision: str,
    execution_status: str,
) -> list[dict[str, Any]]:
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        nested: list[dict[str, Any]] = []
        for key in sorted(set(before) | set(after)):
            old = before.get(key, _MISSING)
            new = after.get(key, _MISSING)
            if _equal(old, new):
                continue
            nested.extend(
                _field_items(
                    entity_kind=entity_kind,
                    entity_id=entity_id,
                    path=path,
                    field=_join_field(field, str(key)),
                    before=old,
                    after=new,
                    source_revision=source_revision,
                    result_revision=result_revision,
                    execution_status=execution_status,
                )
            )
        return nested
    return [
        {
            "change_id": f"{entity_kind}:{entity_id}:{field}",
            "entity_kind": str(entity_kind or "document"),
            "entity_id": str(entity_id or path),
            "path": str(path or ""),
            "field": field,
            "before": _value_envelope(before),
            "after": _value_envelope(after),
            "source_revision": source_revision or None,
            "result_revision": result_revision or None,
            "execution_status": execution_status,
        }
    ]


def _value_envelope(value: Any) -> dict[str, Any]:
    if value is _MISSING:
        return {
            "kind": "missing",
            "value": None,
            "preview": "",
            "truncated": False,
            "units": 0,
            "sha256": None,
        }
    rendered = _render(value)
    exact = len(rendered) <= MAX_INLINE_VALUE_CHARS
    return {
        "kind": _kind(value),
        "value": value if exact else None,
        "preview": rendered[:MAX_PREVIEW_CHARS],
        "truncated": not exact,
        "units": len(rendered),
        "sha256": fingerprint_value(value),
    }


def _kind(value: Any) -> str:
    if isinstance(value, str):
        return "text"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if value is None:
        return "null"
    if isinstance(value, list):
        return "list"
    if isinstance(value, Mapping):
        return "object"
    return "text"


def _render(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return str(value)


def _equal(left: Any, right: Any) -> bool:
    if left is _MISSING or right is _MISSING:
        return left is right
    return left == right


def _join_field(prefix: str, field: str) -> str:
    return f"{prefix}.{field}" if prefix else field


MISSING_VALUE = _MISSING
