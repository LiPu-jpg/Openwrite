"""Dante session state persistence."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

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

DEFAULT_ACTIVE_AGENT = "dante"


@dataclass
class SessionTurn:
    role: str
    content: str


@dataclass
class CompressionMarker:
    compressed_at: str
    dropped_turns: int
    kept_turns: int
    reason: Literal["count", "size"]


@dataclass
class DanteSessionState:
    session_id: str
    active_agent: str = DEFAULT_ACTIVE_AGENT
    conversation_summary: str = ""
    recent_turns: list[SessionTurn] = field(default_factory=list)
    working_memory: dict[str, Any] = field(default_factory=dict)
    open_questions: list[str] = field(default_factory=list)
    recent_files: list[str] = field(default_factory=list)
    last_action: str = ""
    compression_markers: list[CompressionMarker] = field(default_factory=list)
    updated_at: str = ""


# Transcript budget: the rolling YAML is capped at MAX_SESSION_BYTES, so keep the
# append-only JSONL to a small multiple of it rather than letting it grow forever.
MAX_TRANSCRIPT_BYTES = 8 * 1024 * 1024


class SessionStateStore:
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
            self.path = workflow_root / "agent_session.yaml"
        self.transcript_path = self.path.with_suffix(".jsonl")

    def append_turn(self, role: str, content: str) -> None:
        # Archive the full turn; the rolling YAML state remains bounded.
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
        self._rotate_transcript_if_needed()

    def _rotate_transcript_if_needed(self) -> None:
        # Rotate the transcript once it grows past a byte budget. The rolling YAML
        # is carefully bounded (_compress_for_size, _hard_truncate_state), but the
        # JSONL transcript had no cap at all: 500 turns of 4 KB each produced an
        # 18 KB YAML beside a 2 MB JSONL, and the file only ever grew.
        try:
            size = self.transcript_path.stat().st_size
        except OSError:
            return
        if size <= MAX_TRANSCRIPT_BYTES:
            return
        rotated = self.transcript_path.with_name(self.transcript_path.name + ".1")
        try:
            os.replace(self.transcript_path, rotated)
        except OSError:
            logger.warning("Could not rotate session transcript %s", self.transcript_path)
            return
        self._record_rotation_marker(size)

    def _record_rotation_marker(self, previous_size: int) -> None:
        # Leave a marker so a reader can tell the live file starts fresh here.
        try:
            with self.transcript_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({
                    "session_id": self.session_id,
                    "agent": DEFAULT_ACTIVE_AGENT,
                    "role": "system",
                    "content": "transcript rotated; %d bytes moved to %s.1" % (previous_size, self.transcript_path.name),
                    "timestamp": datetime.now().isoformat(),
                    "rotation": True,
                }, ensure_ascii=False) + "\n")
        except OSError:
            logger.warning("Could not record session transcript rotation marker")

    def load_or_create(self) -> DanteSessionState:
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

    def save(self, state: DanteSessionState) -> None:
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
            raise ValueError("session state exceeded MAX_SESSION_BYTES after serialization")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # atomic_write cleans up its temporary file in a finally block, so a
        # failed replace cannot leak one.
        atomic_write(self.path, content)

    def _default_state(self) -> DanteSessionState:
        return DanteSessionState(session_id=self.session_id)

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

    def _stamp_updated_at(self, state: DanteSessionState) -> None:
        state.updated_at = datetime.now().isoformat()

    def _compress_if_needed(self, state: DanteSessionState) -> bool:
        changed = self._compress_by_count(state)
        changed |= self._compress_for_size(state)
        return changed

    def _compress_by_count(self, state: DanteSessionState) -> bool:
        if len(state.recent_turns) <= MAX_RECENT_TURNS:
            return False

        dropped_turns = 0
        while len(state.recent_turns) > MAX_RECENT_TURNS:
            drop_count = len(state.recent_turns) - MAX_RECENT_TURNS
            old_turns = state.recent_turns[:drop_count]
            kept_turns = state.recent_turns[drop_count:]
            summary_block = "\n".join(
                self._render_turn(turn, MAX_TURN_CONTENT_BYTES)
                for turn in old_turns
            )
            state.conversation_summary = self._append_summary(
                state.conversation_summary, summary_block
            )
            state.recent_turns = kept_turns
            dropped_turns += len(old_turns)

        state.compression_markers.append(
            CompressionMarker(
                compressed_at=datetime.now().isoformat(),
                dropped_turns=dropped_turns,
                kept_turns=len(state.recent_turns),
                reason="count",
            )
        )
        self._bound_compression_markers(state)
        return True

    def _compress_for_size(self, state: DanteSessionState) -> bool:
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
                        CompressionMarker(
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
            raise ValueError("session state exceeded MAX_SESSION_BYTES after compression")

        removed_turns = max(0, initial_turn_count - len(state.recent_turns))
        state.compression_markers.append(
            CompressionMarker(
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

    def _estimate_size(self, state: DanteSessionState) -> int:
        return len(self._serialize_state(state).encode("utf-8"))

    def _serialize_state(self, state: DanteSessionState) -> str:
        return yaml.safe_dump(self._to_dict(state), allow_unicode=True, sort_keys=False)

    def _render_turn(self, turn: SessionTurn, content_limit: int | None = None) -> str:
        role = self._stringify_scalar(turn.role) or "unknown"
        content = (
            self._truncate_text(turn.content, content_limit, keep_tail=False)
            if content_limit is not None
            else self._stringify_scalar(turn.content)
        )
        return f"{role}: {content}".rstrip()

    def _compact_text_fields(
        self, state: DanteSessionState, summary_budget: int, turn_budget: int
    ) -> None:
        state.conversation_summary = self._truncate_text(
            state.conversation_summary, summary_budget, keep_tail=True
        )
        state.recent_turns = [
            SessionTurn(
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

    def _compact_metadata_fields(self, state: DanteSessionState) -> None:
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

    def _hard_truncate_state(self, state: DanteSessionState) -> None:
        state.conversation_summary = self._truncate_text(
            state.conversation_summary, 128, keep_tail=True
        )
        if state.recent_turns:
            last_turn = state.recent_turns[-1]
            state.recent_turns = [
                SessionTurn(
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
            truncated = encoded[-limit:]
        else:
            truncated = encoded[:limit]
        return truncated.decode("utf-8", errors="ignore")

    def _to_dict(self, state: DanteSessionState) -> dict[str, Any]:
        data = asdict(state)
        data["session_id"] = self._normalize_identifier_scalar(
            data["session_id"], self.session_id
        )
        data["active_agent"] = self._normalize_structural_scalar(
            data["active_agent"], DEFAULT_ACTIVE_AGENT
        )
        data["conversation_summary"] = self._normalize_scalar(
            data["conversation_summary"], ""
        )
        data["working_memory"] = self._normalize_mapping(data["working_memory"])
        data["open_questions"] = self._sanitize_yaml_value(data["open_questions"])
        data["recent_files"] = self._sanitize_yaml_value(data["recent_files"])
        data["last_action"] = self._normalize_scalar(data["last_action"], "")
        data["compression_markers"] = [
            asdict(marker)
            for marker in self._coerce_marker_list(data["compression_markers"])
        ]
        data["updated_at"] = self._normalize_structural_scalar(
            data["updated_at"], ""
        )
        return data

    def _tighten_serialized_state(self, state: DanteSessionState) -> None:
        while len(state.compression_markers) > 1:
            state.compression_markers.pop(0)
            if self._estimate_size(state) <= MAX_SESSION_BYTES:
                return
        self._hard_truncate_state(state)

    def _from_dict(self, data: dict[str, Any]) -> DanteSessionState:
        return DanteSessionState(
            session_id=self._normalize_identifier_scalar(
                data.get("session_id"), self.session_id
            ),
            active_agent=self._normalize_structural_scalar(
                data.get("active_agent"), DEFAULT_ACTIVE_AGENT
            ),
            conversation_summary=self._normalize_scalar(
                data.get("conversation_summary"), ""
            ),
            recent_turns=self._coerce_turn_list(data.get("recent_turns", [])),
            working_memory=self._normalize_mapping(data.get("working_memory", {})),
            open_questions=self._coerce_string_list(data.get("open_questions", [])),
            recent_files=self._coerce_string_list(data.get("recent_files", [])),
            last_action=self._normalize_scalar(data.get("last_action"), ""),
            compression_markers=self._coerce_marker_list(
                data.get("compression_markers", [])
            ),
            updated_at=self._normalize_structural_scalar(
                data.get("updated_at"), ""
            ),
        )

    def _needs_schema_upgrade(self, data: dict[str, Any]) -> bool:
        required_keys = {
            "session_id",
            "active_agent",
            "conversation_summary",
            "recent_turns",
            "working_memory",
            "open_questions",
            "recent_files",
            "last_action",
            "compression_markers",
            "updated_at",
        }
        return not required_keys.issubset(data.keys())

    def _normalize_mapping(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {"value": self._sanitize_yaml_value(value)}
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            normalized[self._normalize_mapping_key(key, normalized)] = (
                self._normalize_mapping_value(item)
            )
        return normalized

    def _normalize_mapping_value(self, value: Any) -> Any:
        if isinstance(value, dict):
            return self._normalize_mapping(value)
        if isinstance(value, list):
            return [self._normalize_mapping_value(item) for item in value]
        return self._sanitize_yaml_value(value)

    def _coerce_marker_list(self, value: Any) -> list[CompressionMarker]:
        if value is None:
            return []
        if not isinstance(value, list):
            value = [value]
        markers: list[CompressionMarker] = []
        for item in value:
            marker = self._coerce_marker(item)
            if marker is not None:
                markers.append(marker)
        return markers[-MAX_COMPRESSION_MARKERS:]

    def _coerce_marker(self, value: Any) -> CompressionMarker | None:
        if isinstance(value, CompressionMarker):
            compressed_at = value.compressed_at
            dropped_turns = value.dropped_turns
            kept_turns = value.kept_turns
            reason = value.reason
        elif isinstance(value, dict):
            compressed_at = value.get("compressed_at")
            dropped_turns = value.get("dropped_turns", 0)
            kept_turns = value.get("kept_turns", 0)
            reason = value.get("reason")
        else:
            return None

        return CompressionMarker(
            compressed_at=self._truncate_text(
                self._normalize_scalar(compressed_at, ""),
                MAX_STRUCTURAL_TEXT_BYTES,
                keep_tail=False,
            ),
            dropped_turns=self._safe_int(dropped_turns),
            kept_turns=self._safe_int(kept_turns),
            reason=self._normalize_reason(reason),
        )

    def _normalize_state_for_persistence(self, state: DanteSessionState) -> None:
        state.session_id = self._normalize_identifier_scalar(
            state.session_id, self.session_id
        )
        state.active_agent = self._normalize_structural_scalar(
            state.active_agent, DEFAULT_ACTIVE_AGENT
        )
        state.conversation_summary = self._normalize_scalar(
            state.conversation_summary, ""
        )
        state.recent_turns = self._coerce_turn_list(state.recent_turns)
        state.working_memory = self._normalize_mapping(state.working_memory)
        state.open_questions = self._coerce_string_list(state.open_questions)
        state.recent_files = self._coerce_string_list(state.recent_files)
        state.last_action = self._normalize_scalar(state.last_action, "")
        state.updated_at = self._normalize_structural_scalar(state.updated_at, "")
        state.compression_markers = self._coerce_marker_list(state.compression_markers)
        if len(state.working_memory) > MAX_WORKING_MEMORY_KEYS:
            state.working_memory = dict(
                list(state.working_memory.items())[-MAX_WORKING_MEMORY_KEYS:]
            )
        self._bound_compression_markers(state)

    def _coerce_string_list(self, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [self._stringify_scalar(item) for item in value]
        return [self._stringify_scalar(value)]

    def _coerce_turn_list(self, value: Any) -> list[SessionTurn]:
        if value is None:
            return []
        if not isinstance(value, list):
            value = [value]
        turns: list[SessionTurn] = []
        for item in value:
            if isinstance(item, SessionTurn):
                turns.append(
                    SessionTurn(
                        role=self._truncate_text(
                            self._stringify_scalar(item.role),
                            MAX_STRUCTURAL_TEXT_BYTES,
                            keep_tail=False,
                        ),
                        content=self._stringify_scalar(item.content),
                    )
                )
            elif isinstance(item, dict):
                turns.append(
                    SessionTurn(
                        role=self._truncate_text(
                            self._stringify_scalar(item.get("role", "")),
                            MAX_STRUCTURAL_TEXT_BYTES,
                            keep_tail=False,
                        ),
                        content=self._stringify_scalar(item.get("content", "")),
                    )
                )
            else:
                turns.append(
                    SessionTurn(
                        role="unknown",
                        content=self._stringify_scalar(item),
                    )
                )
        return turns

    def _bound_compression_markers(self, state: DanteSessionState) -> None:
        state.compression_markers = self._coerce_marker_list(state.compression_markers)

    def _normalize_reason(self, value: Any) -> Literal["count", "size"]:
        if value == "size":
            return "size"
        return "count"

    def _safe_int(self, value: Any) -> int:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0

    def _compact_mapping(
        self, value: dict[str, Any], budget: int, max_keys: int
    ) -> dict[str, Any]:
        if not isinstance(value, dict):
            value = self._normalize_mapping(value)
        compacted: dict[str, Any] = {}
        for key, item in list(value.items())[-max_keys:]:
            compacted[self._normalize_mapping_key(key, compacted)] = self._compact_value(
                item,
                budget,
            )
        return compacted

    def _compact_string_list(
        self, value: list[str], item_budget: int, max_items: int = 8
    ) -> list[str]:
        return [
            self._truncate_text(item, item_budget, keep_tail=False)
            for item in value[-max_items:]
        ]

    def _compact_value(self, value: Any, budget: int) -> Any:
        if isinstance(value, str):
            return self._truncate_text(value, budget, keep_tail=False)
        if isinstance(value, list):
            return [self._compact_value(item, budget) for item in value[-8:]]
        if isinstance(value, dict):
            return self._compact_mapping(value, budget, 8)
        return value

    def _sanitize_yaml_value(self, value: Any) -> Any:
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, list):
            return [self._sanitize_yaml_value(item) for item in value]
        if isinstance(value, dict):
            return {
                str(key): self._sanitize_yaml_value(item)
                for key, item in value.items()
            }
        return repr(value)

    def _stringify_scalar(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        return str(value)

    def _normalize_mapping_key(self, key: Any, taken: dict[str, Any]) -> str:
        raw = self._stringify_scalar(key) or "key"
        candidate = self._truncate_text(raw, MAX_STRUCTURAL_TEXT_BYTES, keep_tail=False)
        if candidate not in taken:
            return candidate

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

    def _enforce_size_after_marker(self, state: DanteSessionState) -> None:
        while self._estimate_size(state) > MAX_SESSION_BYTES and len(state.compression_markers) > 1:
            state.compression_markers.pop(0)
        if self._estimate_size(state) > MAX_SESSION_BYTES:
            self._hard_truncate_state(state)