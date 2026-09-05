"""Redacted, bounded operation traces for author-visible Studio mutations.

The trace deliberately stores digests and provenance instead of raw prompts,
model output, manuscript text, tool credentials, or chain-of-thought.  Files
live with the novel so an author can inspect and remove them with the project.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

TRACE_SCHEMA = "openwrite.operation-trace.v1"
TRACE_MAX_RECORDS = 100
TRACE_MAX_AGE_DAYS = 30

_SENSITIVE_KEY = re.compile(
    r"(?:api[_-]?key|authorization|bearer|credential|password|secret|token)$",
    re.IGNORECASE,
)
_CONTENT_KEY = re.compile(
    r"(?:content|text|prompt|guidance|replacement|before|after|excerpt|quote)",
    re.IGNORECASE,
)
_SAFE_EXACT_KEYS = {
    "action",
    "chapter",
    "chapter_id",
    "entity_id",
    "id",
    "kind",
    "operation",
    "path",
    "proposal_id",
    "revision",
    "source_revision",
    "result_revision",
    "target_words",
}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _scrub_credentials(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "<credential-omitted>" if _SENSITIVE_KEY.search(str(key)) else _scrub_credentials(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_scrub_credentials(item) for item in value]
    return value


def _digest(value: Any) -> dict[str, Any]:
    scrubbed = _scrub_credentials(value)
    rendered = scrubbed if isinstance(scrubbed, str) else _canonical_json(scrubbed)
    encoded = rendered.encode("utf-8")
    return {
        "storage": "digest_only",
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "utf8_bytes": len(encoded),
        "rendered_units": len(rendered),
        "raw_stored": False,
    }


def summarize_arguments(payload: dict[str, Any]) -> dict[str, Any]:
    """Describe tool/API arguments without retaining author text or secrets."""

    values: dict[str, Any] = {}
    sensitive_fields: list[str] = []
    content_fields: list[str] = []
    for key in sorted(str(item) for item in payload):
        value = payload.get(key)
        if _SENSITIVE_KEY.search(key):
            sensitive_fields.append(key)
            values[key] = {"storage": "omitted", "present": value not in (None, "")}
        elif _CONTENT_KEY.search(key) or isinstance(value, (dict, list)):
            content_fields.append(key)
            values[key] = _digest(value)
        elif key in _SAFE_EXACT_KEYS and isinstance(value, (str, int, float, bool, type(None))):
            values[key] = {"storage": "exact", "value": value}
        else:
            values[key] = _digest(value)
    return {
        "fields": sorted(values),
        "values": values,
        "sensitive_fields": sensitive_fields,
        "content_fields": content_fields,
    }


def _tool_arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {"arguments": str(value or "")}
    return parsed if isinstance(parsed, dict) else {"arguments": parsed}


def summarize_context_packet(packet: dict[str, Any]) -> dict[str, Any]:
    """Keep packet provenance, budget and source revisions without source text."""

    manifest = packet.get("context_manifest")
    manifest = manifest if isinstance(manifest, dict) else {}
    sources: list[dict[str, Any]] = []
    for item in manifest.get("items", []):
        if not isinstance(item, dict):
            continue
        for source in item.get("sources", []):
            if not isinstance(source, dict):
                continue
            sources.append(
                {
                    "path": str(source.get("path") or ""),
                    "exists": bool(source.get("exists")),
                    "revision": str(source.get("revision") or ""),
                }
            )
    unique_sources = list({(item["path"], item["revision"]): item for item in sources}.values())
    return {
        "chapter_id": str(packet.get("chapter_id") or ""),
        "packet_revision": str(manifest.get("packet_revision") or manifest.get("revision") or ""),
        "source_revision": str(manifest.get("source_revision") or ""),
        "strategy": str(manifest.get("strategy") or ""),
        "measurement": manifest.get("measurement") if isinstance(manifest.get("measurement"), dict) else {},
        "estimated_tokens": manifest.get("estimated_tokens"),
        "request_budget": manifest.get("request_budget") if isinstance(manifest.get("request_budget"), dict) else {},
        "compression": manifest.get("compression") if isinstance(manifest.get("compression"), dict) else {},
        "freshness": manifest.get("freshness") if isinstance(manifest.get("freshness"), dict) else {},
        "sources": unique_sources,
        "raw_context_stored": False,
    }


def _redacted_mutation_summary(summary: Any) -> dict[str, Any]:
    source = summary if isinstance(summary, dict) else {}
    items: list[dict[str, Any]] = []
    for raw in source.get("items", []):
        if not isinstance(raw, dict):
            continue
        item = {
            key: raw.get(key)
            for key in (
                "change_id",
                "entity_kind",
                "entity_id",
                "path",
                "field",
                "source_revision",
                "result_revision",
                "execution_status",
            )
        }
        for side in ("before", "after"):
            value = raw.get(side)
            value = value if isinstance(value, dict) else {}
            item[side] = {
                "kind": value.get("kind"),
                "sha256": value.get("sha256"),
                "units": value.get("units"),
                "truncated": value.get("truncated"),
                "raw_stored": False,
            }
        items.append(item)
    return {
        "schema_version": source.get("schema_version"),
        "operation": source.get("operation"),
        "execution_status": source.get("execution_status"),
        "source_revision": source.get("source_revision"),
        "result_revision": source.get("result_revision"),
        "items": items,
        "raw_values_stored": False,
    }


class OperationTraceCollector:
    """Request-local collector populated by OpenWrite's LLM adapter."""

    def __init__(self) -> None:
        self.model_calls: list[dict[str, Any]] = []

    def record_model_exchange(
        self,
        *,
        messages: list[Any],
        response: Any | None,
        operation: str = "",
        context_plan: dict[str, Any] | None = None,
        error: Exception | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> None:
        message_material = [
            {
                "role": str(getattr(message, "role", "")),
                "content": str(getattr(message, "content", "")),
            }
            for message in messages
        ]
        entry: dict[str, Any] = {
            "sequence": len(self.model_calls) + 1,
            "operation": str(operation or ""),
            "prompt": {
                **_digest(message_material),
                "message_roles": [item["role"] for item in message_material],
                "scope": "messages_before_provider_context_planning",
            },
            "context_plan": dict(context_plan or {}),
            "tools": [str(item.get("function", {}).get("name") or "") for item in (tools or []) if isinstance(item, dict)],
            "status": "failed" if error is not None else "completed",
            "chain_of_thought": {"storage": "omitted", "raw_stored": False},
        }
        if response is not None:
            content = str(getattr(response, "content", "") or "")
            entry["response"] = {
                **_digest(content),
                "model": str(getattr(response, "model", "") or ""),
                "provider": str(getattr(response, "provider", "") or ""),
                "finish_reason": str(getattr(response, "finish_reason", "") or ""),
                "usage": dict(getattr(response, "usage", {}) or {}),
            }
            tool_calls = getattr(response, "tool_calls", []) or []
            entry["tool_calls"] = [
                {
                    "id": str(call.get("id") or ""),
                    "name": str(call.get("name") or ""),
                    "arguments": summarize_arguments(_tool_arguments(call.get("arguments"))),
                }
                for call in tool_calls
                if isinstance(call, dict)
            ]
        if error is not None:
            entry["error"] = {"type": type(error).__name__, "message": "omitted"}
        self.model_calls.append(entry)


_ACTIVE_COLLECTOR: ContextVar[OperationTraceCollector | None] = ContextVar(
    "openwrite_operation_trace_collector", default=None
)


@contextmanager
def capture_operation_trace() -> Iterator[OperationTraceCollector]:
    collector = OperationTraceCollector()
    token = _ACTIVE_COLLECTOR.set(collector)
    try:
        yield collector
    finally:
        _ACTIVE_COLLECTOR.reset(token)


def active_operation_trace() -> OperationTraceCollector | None:
    return _ACTIVE_COLLECTOR.get()


class OperationTraceStore:
    """One-file-per-trace store with age and count retention enforcement."""

    def __init__(self, novel_root: Path) -> None:
        self.root = Path(novel_root) / "data" / "traces"

    def record(
        self,
        *,
        route: str,
        request_id: str,
        payload: dict[str, Any],
        response: dict[str, Any],
        request_context: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        model_calls: list[dict[str, Any]] | None = None,
        status: str = "completed",
        error_code: str = "",
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        trace_id = f"trace_{now.strftime('%Y%m%dT%H%M%S%fZ')}_{uuid.uuid4().hex[:8]}"
        relative_path = f"data/traces/{trace_id}.json"
        record = {
            "schema_version": TRACE_SCHEMA,
            "trace_id": trace_id,
            "created_at": now.isoformat(),
            "status": status,
            "error_code": error_code,
            "request": {
                "request_id": request_id,
                "route": route,
                **dict(request_context or {}),
                "arguments": summarize_arguments(payload),
            },
            "context": dict(context or {}),
            "model_calls": list(model_calls or []),
            "domain_change": _redacted_mutation_summary(response.get("mutation_summary")),
            "privacy": {
                "raw_prompt_stored": False,
                "raw_context_stored": False,
                "raw_model_response_stored": False,
                "raw_chain_of_thought_stored": False,
                "raw_credentials_stored": False,
                "raw_mutation_values_stored": False,
            },
            "retention": {
                "scope": "novel_project",
                "max_age_days": TRACE_MAX_AGE_DAYS,
                "max_records": TRACE_MAX_RECORDS,
            },
        }
        self.root.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=".trace-", suffix=".json", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(record, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.root / f"{trace_id}.json")
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
        self.prune(now=now)
        return {
            "schema_version": TRACE_SCHEMA,
            "trace_id": trace_id,
            "path": relative_path,
            "status": status,
            "model_call_count": len(model_calls or []),
            "privacy": record["privacy"],
            "retention": record["retention"],
        }

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        self.prune()
        records: list[dict[str, Any]] = []
        for path in sorted(self.root.glob("trace_*.json"), reverse=True)[: max(1, min(limit, TRACE_MAX_RECORDS))]:
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(value, dict) and value.get("schema_version") == TRACE_SCHEMA:
                records.append(value)
        return records

    def prune(self, *, now: datetime | None = None) -> None:
        if not self.root.exists():
            return
        current = now or datetime.now(timezone.utc)
        cutoff = current - timedelta(days=TRACE_MAX_AGE_DAYS)
        kept: list[tuple[datetime, Path]] = []
        for path in self.root.glob("trace_*.json"):
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                created = datetime.fromisoformat(str(value.get("created_at") or ""))
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if created < cutoff:
                path.unlink(missing_ok=True)
            else:
                kept.append((created, path))
        for _created, path in sorted(kept, reverse=True)[TRACE_MAX_RECORDS:]:
            path.unlink(missing_ok=True)
