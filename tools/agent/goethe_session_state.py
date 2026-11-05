"""Goethe session state persistence."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, cast

import yaml

from .session_limits import (
    MAX_COMPRESSION_MARKERS,
    MAX_RECENT_TURNS,
    MAX_SESSION_BYTES,
    MAX_STRUCTURAL_TEXT_BYTES,
    MAX_SUMMARY_BYTES,
    MAX_TURN_CONTENT_BYTES,
    MAX_WORKING_MEMORY_KEYS,
)
from tools.file_ops import atomic_write

DEFAULT_ACTIVE_AGENT = "goethe"


@dataclass
class GoetheSessionTurn:
    role: str
    content: str


@dataclass
class GoetheCompressionMarker:
    compressed_at: str
    dropped_turns: int
    kept_turns: int
    reason: Literal["count", "size"]


@dataclass
class GoetheSessionState:
    session_id: str
    active_agent: str = DEFAULT_ACTIVE_AGENT
    conversation_summary: str = ""
    recent_turns: list[GoetheSessionTurn] = field(default_factory=list)
    working_memory: dict[str, Any] = field(default_factory=dict)
    open_questions: list[str] = field(default_factory=list)
    recent_files: list[str] = field(default_factory=list)
    last_action: str = ""
    compression_markers: list[GoetheCompressionMarker] = field(default_factory=list)
    updated_at: str = ""


class GoetheSessionStateStore:
    def __init__(
        self,
        project_root: Path,
        novel_id: str,
        session_id: str | None = None,
    ):
        self.project_root = Path(project_root).resolve()
        self.novel_id = novel_id
        self.session_id = (
            self._normalize_identifier_scalar(session_id, self.novel_id)
            if str(session_id or "").strip()
            else self.novel_id
        )
        workflow_root = (
            self.project_root / "data" / "novels" / novel_id / "data" / "workflows"
        )
        if str(session_id or "").strip():
            session_stem = self._session_file_stem(self.session_id)
            self.path = workflow_root / "sessions" / DEFAULT_ACTIVE_AGENT / f"{session_stem}.yaml"
        else:
            self.path = workflow_root / "goethe_session.yaml"
        self.transcript_path = self.path.with_suffix(".jsonl")

    def append_turn(self, role: str, content: str) -> None:
        """Archive the full turn; the rolling YAML state remains bounded."""
        record = {
            "session_id": self.session_id,
            "agent": DEFAULT_ACTIVE_AGENT,
            "role": str(role),
            "content": str(content),
            "timestamp": datetime.now().isoformat(),
        }
        self.transcript_path.parent.mkdir(parents=True, exist_ok=True)
        with self.transcript_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def load_or_create(self) -> GoetheSessionState:
        if not self.path.exists():
            state = self._default_state()
            self.save(state)
            return state

        try:
            data = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        except (yaml.YAMLError, UnicodeDecodeError, RecursionError):
            # RecursionError is included because a deeply-nested document
            # overflows the parser's stack; without it every session start would
            # fail on the same damaged file instead of rebuilding.
            state = self._default_state()
            self.save(state)
            return state

        if not data or not isinstance(data, dict):
            state = self._default_state()
            self.save(state)
            return state

        state = self._from_dict(data)
        needs_repair = self._needs_schema_upgrade(data) or data != self._to_dict(state)
        if needs_repair or self._compress_if_needed(state):
            self.save(state)
        return state

    def save(self, state: GoetheSessionState) -> None:
        self._normalize_state_for_persistence(state)
        self._stamp_updated_at(state)
        self._compress_if_needed(state)
        self._normalize_state_for_persistence(state)
        content = self._serialize_state(state)
        if len(content.encode("utf-8")) > MAX_SESSION_BYTES:
            self._tighten_serialized_state(state)
            self._normalize_state_for_persistence(state)
            content = self._serialize_state(state)
        if len(content.encode("utf-8")) > MAX_SESSION_BYTES:
            raise ValueError("goethe session state exceeded MAX_SESSION_BYTES after serialization")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # atomic_write cleans up its temporary file in a finally block, so a
        # failed replace cannot leak one.
        atomic_write(self.path, content)

    def _default_state(self) -> GoetheSessionState:
        return GoetheSessionState(session_id=self.session_id)

    @staticmethod
    def _session_file_stem(session_id: str) -> str:
        raw = str(session_id or "").strip()
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw).strip(".-")
        if not safe:
            safe = "session"
        if len(safe.encode("utf-8")) <= 80:
            return safe
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
        return f"{safe[:56].rstrip('.-')}-{digest}"

    def _stamp_updated_at(self, state: GoetheSessionState) -> None:
        state.updated_at = datetime.now().isoformat()

    def _compress_if_needed(self, state: GoetheSessionState) -> bool:
        changed = self._compress_by_count(state)
        changed |= self._compress_for_size(state)
        return changed

    def _compress_by_count(self, state: GoetheSessionState) -> bool:
        if len(state.recent_turns) <= MAX_RECENT_TURNS:
            return False

        dropped_turns = 0
        while len(state.recent_turns) > MAX_RECENT_TURNS:
            drop_count = len(state.recent_turns) - MAX_RECENT_TURNS
            old_turns = state.recent_turns[:drop_count]
            kept_turns = state.recent_turns[drop_count:]
            summary_block = "\n".join(
                self._render_turn(turn, MAX_TURN_CONTENT_BYTES) for turn in old_turns
            )
            state.conversation_summary = self._append_summary(
                state.conversation_summary, summary_block
            )
            state.recent_turns = kept_turns
            dropped_turns += len(old_turns)

        state.compression_markers.append(
            GoetheCompressionMarker(
                compressed_at=datetime.now().isoformat(),
                dropped_turns=dropped_turns,
                kept_turns=len(state.recent_turns),
                reason="count",
            )
        )
        self._bound_compression_markers(state)
        return True

    def _compress_for_size(self, state: GoetheSessionState) -> bool:
        if self._estimate_size(state) <= MAX_SESSION_BYTES:
            return False

        initial_turn_count = len(state.recent_turns)
        if state.recent_turns:
            moved_turns = 0
            while len(state.recent_turns) > 1 and self._estimate_size(state) > MAX_SESSION_BYTES:
                old_turn = state.recent_turns.pop(0)
                state.conversation_summary = self._append_summary(
                    state.conversation_summary,
                    self._render_turn(old_turn, MAX_TURN_CONTENT_BYTES),
                )
                moved_turns += 1
            if moved_turns:
                self._bound_compression_markers(state)
                if self._estimate_size(state) <= MAX_SESSION_BYTES:
                    removed_turns = max(0, initial_turn_count - len(state.recent_turns))
                    state.compression_markers.append(
                        GoetheCompressionMarker(
                            compressed_at=datetime.now().isoformat(),
                            dropped_turns=removed_turns,
                            kept_turns=len(state.recent_turns),
                            reason="size",
                        )
                    )
                    self._bound_compression_markers(state)
                    self._enforce_size_after_marker(state)
                    return True

        summary_budget = MAX_SUMMARY_BYTES
        turn_budget = MAX_TURN_CONTENT_BYTES

        while self._estimate_size(state) > MAX_SESSION_BYTES:
            self._compact_text_fields(state, summary_budget, turn_budget)
            if self._estimate_size(state) <= MAX_SESSION_BYTES:
                break

            if summary_budget > 64:
                summary_budget = max(64, summary_budget // 2)
            if turn_budget > 32:
                turn_budget = max(32, turn_budget // 2)

            if summary_budget == 64 and turn_budget == 32:
                break

        if self._estimate_size(state) > MAX_SESSION_BYTES:
            self._compact_metadata_fields(state)

        if self._estimate_size(state) > MAX_SESSION_BYTES:
            self._hard_truncate_state(state)

        if self._estimate_size(state) > MAX_SESSION_BYTES:
            raise ValueError("goethe session state exceeded MAX_SESSION_BYTES after compression")

        removed_turns = max(0, initial_turn_count - len(state.recent_turns))
        state.compression_markers.append(
            GoetheCompressionMarker(
                compressed_at=datetime.now().isoformat(),
                dropped_turns=removed_turns,
                kept_turns=len(state.recent_turns),
                reason="size",
            )
        )
        self._bound_compression_markers(state)
        self._enforce_size_after_marker(state)
        return True

    def _append_summary(self, existing: str, addition: str) -> str:
        if not addition:
            return existing
        if not existing:
            return addition
        return f"{existing}\n{addition}"

    def _estimate_size(self, state: GoetheSessionState) -> int:
        return len(self._serialize_state(state).encode("utf-8"))

    def _serialize_state(self, state: GoetheSessionState) -> str:
        return yaml.safe_dump(self._to_dict(state), allow_unicode=True, sort_keys=False)

    def _render_turn(self, turn: GoetheSessionTurn, content_limit: int | None = None) -> str:
        role = self._stringify_scalar(turn.role) or "unknown"
        content = (
            self._truncate_text(turn.content, content_limit, keep_tail=False)
            if content_limit is not None
            else self._stringify_scalar(turn.content)
        )
        return f"{role}: {content}".rstrip()

    def _compact_text_fields(
        self, state: GoetheSessionState, summary_budget: int, turn_budget: int
    ) -> None:
        state.conversation_summary = self._truncate_text(
            state.conversation_summary, summary_budget, keep_tail=True
        )
        state.recent_turns = [
            GoetheSessionTurn(
                role=turn.role,
                content=self._truncate_text(turn.content, turn_budget, keep_tail=False),
            )
            for turn in state.recent_turns
        ]
        state.working_memory = self._compact_mapping(
            state.working_memory, turn_budget, MAX_WORKING_MEMORY_KEYS
        )
        state.open_questions = self._compact_string_list(state.open_questions, turn_budget)
        state.recent_files = self._compact_string_list(state.recent_files, turn_budget)
        state.last_action = self._truncate_text(state.last_action, turn_budget, keep_tail=False)

    def _compact_metadata_fields(self, state: GoetheSessionState) -> None:
        working_budget = MAX_WORKING_MEMORY_KEYS
        list_item_budget = 8
        while True:
            state.working_memory = self._compact_mapping(
                state.working_memory, 32, working_budget
            )
            state.open_questions = self._compact_string_list(
                state.open_questions, list_item_budget
            )
            state.recent_files = self._compact_string_list(
                state.recent_files, list_item_budget
            )
            state.last_action = self._truncate_text(
                state.last_action, 32, keep_tail=False
            )
            if self._estimate_size(state) <= MAX_SESSION_BYTES or working_budget <= 1:
                break
            working_budget = max(1, working_budget // 2)
            list_item_budget = max(1, list_item_budget // 2)
        self._bound_compression_markers(state)

    def _hard_truncate_state(self, state: GoetheSessionState) -> None:
        state.conversation_summary = self._truncate_text(
            state.conversation_summary, 128, keep_tail=True
        )
        if state.recent_turns:
            last_turn = state.recent_turns[-1]
            state.recent_turns = [
                GoetheSessionTurn(
                    role=last_turn.role,
                    content=self._truncate_text(last_turn.content, 128, keep_tail=False),
                )
            ]
        else:
            state.recent_turns = []
        state.working_memory = self._compact_mapping(state.working_memory, 64, 32)
        state.open_questions = self._compact_string_list(state.open_questions, 64)
        state.recent_files = self._compact_string_list(state.recent_files, 64)
        state.last_action = self._truncate_text(state.last_action, 64, keep_tail=False)
        state.compression_markers = self._coerce_marker_list(state.compression_markers)[-1:]
        if self._estimate_size(state) > MAX_SESSION_BYTES:
            state.compression_markers = []

    def _truncate_text(
        self, text: str, limit: int, *, keep_tail: bool
    ) -> str:
        text = self._stringify_scalar(text)
        if limit <= 0 or not text:
            return ""

        encoded = text.encode("utf-8")
        if len(encoded) <= limit:
            return text

        if keep_tail:
            tail = encoded[-limit:].decode("utf-8", errors="ignore")
            if tail:
                return tail

        return encoded[:limit].decode("utf-8", errors="ignore")

    def _compact_mapping(
        self, mapping: dict[str, Any], value_limit: int, key_limit: int
    ) -> dict[str, Any]:
        if not mapping:
            return {}

        items = list(mapping.items())[:key_limit]
        compacted: dict[str, Any] = {}
        for key, value in items:
            compacted[self._normalize_mapping_key(key, compacted)] = self._compact_value(
                value, value_limit
            )
        return compacted

    def _compact_value(self, value: Any, value_limit: int) -> Any:
        if isinstance(value, str):
            return self._truncate_text(value, value_limit, keep_tail=False)
        if isinstance(value, list):
            return [self._compact_value(item, value_limit) for item in value[:8]]
        if isinstance(value, dict):
            return self._compact_mapping(value, value_limit, MAX_WORKING_MEMORY_KEYS)
        return value

    def _compact_string_list(self, items: list[Any], value_limit: int) -> list[str]:
        compacted: list[str] = []
        for item in items[:MAX_WORKING_MEMORY_KEYS]:
            text = self._stringify_scalar(item)
            if text:
                compacted.append(self._truncate_text(text, value_limit, keep_tail=False))
        return compacted

    def _bound_compression_markers(self, state: GoetheSessionState) -> None:
        state.compression_markers = self._coerce_marker_list(state.compression_markers)[
            -MAX_COMPRESSION_MARKERS:
        ]

    def _enforce_size_after_marker(self, state: GoetheSessionState) -> None:
        if self._estimate_size(state) > MAX_SESSION_BYTES:
            state.compression_markers = self._coerce_marker_list(state.compression_markers)[
                -1:
            ]

    def _tighten_serialized_state(self, state: GoetheSessionState) -> None:
        while len(state.compression_markers) > 1:
            state.compression_markers.pop(0)
            if self._estimate_size(state) <= MAX_SESSION_BYTES:
                return
        self._hard_truncate_state(state)

    def _needs_schema_upgrade(self, data: dict[str, Any]) -> bool:
        return any(key not in data for key in ("active_agent", "compression_markers"))

    def _normalize_state_for_persistence(self, state: GoetheSessionState) -> None:
        state.session_id = self._normalize_identifier_scalar(state.session_id, self.session_id)
        state.active_agent = self._normalize_structural_scalar(
            state.active_agent, DEFAULT_ACTIVE_AGENT
        )
        state.conversation_summary = self._normalize_scalar(state.conversation_summary, "")
        state.recent_turns = self._coerce_turn_list(state.recent_turns)
        state.working_memory = self._normalize_mapping(state.working_memory)
        state.open_questions = self._coerce_string_list(state.open_questions)
        state.recent_files = self._coerce_string_list(state.recent_files)
        state.last_action = self._normalize_scalar(state.last_action, "")
        state.compression_markers = self._coerce_marker_list(state.compression_markers)
        if len(state.working_memory) > MAX_WORKING_MEMORY_KEYS:
            state.working_memory = dict(
                list(state.working_memory.items())[:MAX_WORKING_MEMORY_KEYS]
            )

    def _to_dict(self, state: GoetheSessionState) -> dict[str, Any]:
        return asdict(state)

    def _from_dict(self, data: dict[str, Any]) -> GoetheSessionState:
        recent_turns = self._coerce_turn_list(data.get("recent_turns", []))
        compression_markers = self._coerce_marker_list(data.get("compression_markers", []))
        return GoetheSessionState(
            session_id=self._normalize_identifier_scalar(
                data.get("session_id"), self.session_id
            ),
            active_agent=self._normalize_structural_scalar(
                data.get("active_agent"), DEFAULT_ACTIVE_AGENT
            ),
            conversation_summary=self._normalize_scalar(
                data.get("conversation_summary"), ""
            ),
            recent_turns=recent_turns,
            working_memory=self._normalize_mapping(data.get("working_memory", {})),
            open_questions=self._coerce_string_list(data.get("open_questions", [])),
            recent_files=self._coerce_string_list(data.get("recent_files", [])),
            last_action=self._normalize_scalar(data.get("last_action"), ""),
            compression_markers=compression_markers,
            updated_at=self._normalize_structural_scalar(data.get("updated_at"), ""),
        )

    def _coerce_marker_list(self, markers: list[Any]) -> list[GoetheCompressionMarker]:
        coerced: list[GoetheCompressionMarker] = []
        for marker in markers or []:
            if isinstance(marker, GoetheCompressionMarker):
                coerced.append(marker)
                continue
            if not isinstance(marker, dict):
                continue
            reason = self._stringify_scalar(marker.get("reason", "count"))
            if reason not in {"count", "size"}:
                reason = "count"
            coerced.append(
                GoetheCompressionMarker(
                    compressed_at=self._stringify_scalar(marker.get("compressed_at", "")),
                    dropped_turns=self._safe_int(marker.get("dropped_turns", 0)),
                    kept_turns=self._safe_int(marker.get("kept_turns", 0)),
                    reason=cast(Literal["count", "size"], reason),
                )
            )
        return coerced

    def _normalize_mapping_key(self, key: Any, taken: dict[str, Any]) -> str:
        raw = self._stringify_scalar(key) or "key"
        candidate = self._truncate_text(raw, MAX_STRUCTURAL_TEXT_BYTES, keep_tail=False)
        if candidate not in taken:
            return candidate or "key"

        attempt = 0
        while True:
            digest = hashlib.sha1(f"{raw}:{attempt}".encode()).hexdigest()[:10]
            suffix = f"~{digest}"
            limit = MAX_STRUCTURAL_TEXT_BYTES - len(suffix.encode("utf-8"))
            prefix = self._truncate_text(raw, max(limit, 0), keep_tail=False)
            candidate = f"{prefix}{suffix}" if prefix else suffix[-MAX_STRUCTURAL_TEXT_BYTES:]
            if candidate not in taken:
                return candidate
            attempt += 1

    def _safe_int(self, value: Any) -> int:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0

    def _stringify_scalar(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        return str(value)

    def _normalize_scalar(self, value: Any, default: str) -> str:
        if value is None:
            return default
        if isinstance(value, str):
            if value == "":
                return default
            return value
        return str(value)

    def _normalize_structural_scalar(self, value: Any, default: str) -> str:
        return self._truncate_text(
            self._normalize_scalar(value, default),
            MAX_STRUCTURAL_TEXT_BYTES,
            keep_tail=False,
        )

    def _normalize_identifier_scalar(self, value: Any, default: str) -> str:
        normalized = self._normalize_scalar(value, default)
        if len(normalized.encode("utf-8")) <= MAX_STRUCTURAL_TEXT_BYTES:
            return normalized

        digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:10]
        suffix = f"~{digest}"
        budget = MAX_STRUCTURAL_TEXT_BYTES - len(suffix.encode("utf-8"))
        prefix = self._truncate_text(normalized, max(budget, 0), keep_tail=False)
        return f"{prefix}{suffix}" if prefix else suffix[-MAX_STRUCTURAL_TEXT_BYTES:]

    def _coerce_string_list(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [self._stringify_scalar(item) for item in value]
        return [self._stringify_scalar(value)]

    def _coerce_turn_list(self, value: Any) -> list[GoetheSessionTurn]:
        if value is None:
            return []
        if not isinstance(value, list):
            value = [value]
        turns: list[GoetheSessionTurn] = []
        for item in value:
            if isinstance(item, GoetheSessionTurn):
                turns.append(
                    GoetheSessionTurn(
                        role=self._truncate_text(
                            self._normalize_scalar(item.role, ""),
                            MAX_STRUCTURAL_TEXT_BYTES,
                            keep_tail=False,
                        ),
                        content=self._normalize_scalar(item.content, ""),
                    )
                )
            elif isinstance(item, dict):
                turns.append(
                    GoetheSessionTurn(
                        role=self._truncate_text(
                            self._normalize_scalar(item.get("role", ""), ""),
                            MAX_STRUCTURAL_TEXT_BYTES,
                            keep_tail=False,
                        ),
                        content=self._normalize_scalar(item.get("content", ""), ""),
                    )
                )
            else:
                turns.append(
                    GoetheSessionTurn(
                        role="unknown",
                        content=self._stringify_scalar(item),
                    )
                )
        return turns

    def _normalize_mapping(self, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            items = value.items()
        else:
            try:
                items = dict(value).items()
            except (TypeError, ValueError):
                return {}

        normalized: dict[str, Any] = {}
        for key, item in items:
            normalized[self._normalize_mapping_key(key, normalized)] = item
        return normalized