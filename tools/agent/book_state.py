"""Book-level orchestrator state persistence."""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from tools.file_ops import atomic_write

logger = logging.getLogger("tools.agent.book_state")


class BookStage(str, Enum):
    DISCOVERY = "discovery"
    FOUNDATION = "foundation"
    ROLLING_OUTLINE = "rolling_outline"
    CHAPTER_PREFLIGHT = "chapter_preflight"
    DRAFTING = "drafting"
    REVIEW_AND_REVISE = "review_and_revise"
    SETTLEMENT = "settlement"
    MILESTONE_REVIEW = "milestone_review"


@dataclass
class BookState:
    novel_id: str
    stage: BookStage = BookStage.DISCOVERY
    current_arc: str = ""
    current_section: str = ""
    current_chapter: str = ""
    pending_confirmation: str = ""
    blocking_reason: str = ""
    last_agent_action: str = ""
    last_handoff_from: str = ""
    # Set when the stored stage value was not a known BookStage: the raw value is
    # preserved in `stage_raw` so the downgrade is visible instead of silent.
    stage_unrecognized: bool = False
    stage_raw: str = ""


class BookStateError(RuntimeError):
    """The persisted book state exists but cannot be read."""


class BookStateStore:
    def __init__(self, project_root: Path, novel_id: str):
        self.project_root = Path(project_root).resolve()
        self.novel_id = novel_id
        self.path = (
            self.project_root
            / "data"
            / "novels"
            / novel_id
            / "data"
            / "workflows"
            / "book_state.yaml"
        )

    def load_strict(self) -> BookState:
        """Read the state, raising when the file exists but cannot be parsed.

        `load_or_create` quarantines a damaged file and returns a fresh state,
        which is right for a writer but wrong for a gate: a caller deciding
        whether an outline scope is still pending would then see "no pending
        confirmation" and proceed.
        """
        if not self.path.exists():
            return BookState(novel_id=self.novel_id)
        try:
            data = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise BookStateError(f"书籍状态无法读取（文件已保留，未覆盖）: {exc}") from exc
        if not data or not isinstance(data, dict):
            raise BookStateError("书籍状态不是有效的映射文档（文件已保留，未覆盖）")
        return self._from_dict(data)

    def load_or_create(self) -> BookState:
        if not self.path.exists():
            state = BookState(novel_id=self.novel_id)
            self.save(state)
            return state

        try:
            data = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            # Move the damaged file aside instead of overwriting it. This store has
            # no transcript to recover from (unlike session_state), so silently
            # writing defaults destroyed current_chapter, pending_confirmation and
            # blocking_reason with no way back.
            self._quarantine(exc)
            state = BookState(novel_id=self.novel_id)
            self.save(state)
            return state

        if not data or not isinstance(data, dict):
            self._quarantine(ValueError("empty or non-mapping document"))
            state = BookState(novel_id=self.novel_id)
            self.save(state)
            return state

        return self._from_dict(data)

    def _quarantine(self, reason: BaseException) -> None:
        """Preserve an unreadable state file next to the fresh one."""
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        target = self.path.with_name(f"{self.path.name}.corrupt-{stamp}")
        try:
            os.replace(self.path, target)
        except OSError:
            logger.warning("Could not quarantine %s: %s", self.path, reason)
            return
        logger.warning("Quarantined unreadable book state %s -> %s (%s)", self.path, target, reason)

    def save(self, state: BookState) -> None:
        # K5(a): a whole-object dump loses a concurrent writer's fields. Two
        # writers that each loaded before the other saved used to clobber each
        # other (A setting current_chapter, B setting last_agent_action, and
        # current_chapter ending up empty). Merge over the on-disk state instead.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        merged = self._merge_with_disk(state)
        content = yaml.safe_dump(
            self._to_dict(merged), allow_unicode=True, sort_keys=False
        )
        # atomic_write cleans up its temporary file in a finally block, so a
        # failed replace cannot leak one into the project data directory.
        atomic_write(self.path, content)

    def _merge_with_disk(self, state: BookState) -> BookState:
        """Overlay this writer's fields onto the freshest on-disk state."""
        if not self.path.is_file():
            return state
        try:
            raw = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError, RecursionError):
            # A malformed on-disk state must not fail the writer's save: fall
            # back to the writer's own state, exactly as the other read failures
            # here do. RecursionError is included because a deeply-nested
            # document overflows the parser's stack, and it is not a YAMLError.
            return state
        if not isinstance(raw, dict):
            return state
        try:
            on_disk = self._from_dict(raw)
        except Exception:
            return state
        for key, value in asdict(state).items():
            if key in self._own_state_fields:
                # These describe what THIS writer is doing right now; an empty
                # value is a real "clear it", never "inherit the other writer's".
                setattr(on_disk, key, value)
                continue
            # An empty value means "this writer did not set it", so keep the
            # on-disk value rather than blanking a concurrent writer's field.
            if value in ("", None, 0, False) and key not in self._identity_fields:
                continue
            setattr(on_disk, key, value)
        on_disk.stage = state.stage
        return on_disk

    # Fields that always describe the project, so an empty value is meaningful.
    _identity_fields = frozenset({'novel_id'})
    # Fields that describe the writer's current intent, so an empty value means
    # "clear it" rather than "inherit the other writer's".
    _own_state_fields = frozenset({'pending_confirmation', 'blocking_reason', 'last_agent_action'})

    def _to_dict(self, state: BookState) -> dict[str, Any]:
        data = asdict(state)
        data["stage"] = state.stage.value
        return data

    def _from_dict(self, data: dict[str, Any]) -> BookState:
        raw_stage = data.get("stage", BookStage.DISCOVERY.value)
        stage_recognized = True
        try:
            stage = (
                BookStage(raw_stage)
                if not isinstance(raw_stage, BookStage)
                else raw_stage
            )
        except (TypeError, ValueError):
            # Keep the raw value visible rather than silently downgrading to
            # DISCOVERY: the process believed it was at discovery while the file
            # still said otherwise, and the next save overwrote the file with
            # discovery — dropping current_chapter and pending_confirmation.
            stage = BookStage.DISCOVERY
            stage_recognized = False
            logger.warning("Unrecognized book stage %r in %s", raw_stage, self.path)
        text = self._text_value
        state = BookState(
            novel_id=text(data.get("novel_id", self.novel_id)) or self.novel_id,
            stage=stage,
            stage_unrecognized=not stage_recognized,
            stage_raw=text(data.get("stage", "")),
            current_arc=text(data.get("current_arc", "")),
            current_section=text(data.get("current_section", "")),
            current_chapter=text(data.get("current_chapter", "")),
            pending_confirmation=text(data.get("pending_confirmation", "")),
            blocking_reason=text(data.get("blocking_reason", "")),
            last_agent_action=text(data.get("last_agent_action", "")),
            last_handoff_from=text(data.get("last_handoff_from", "")),
        )
        return state

    @staticmethod
    def _text_value(value: Any) -> str:
        return "" if value is None else str(value)