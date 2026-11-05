"""Canonical runtime-state persistence, validation, delta application and projection."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from models.runtime_state import (
    CharacterRuntimeState,
    ForeshadowingRuntimeReference,
    OpenThreadRuntimeState,
    ProposedEntity,
    RelationshipRuntimeState,
    ResourceRuntimeState,
    RuntimeDeltaOperation,
    RuntimeNote,
    RuntimeState,
    RuntimeStateDelta,
    TimelineRuntimeEvent,
)
from tools.frontmatter import compose_toml_document


class RuntimeStateError(RuntimeError):
    """Raised when a runtime delta cannot be applied safely."""


DOCUMENT_COLLECTIONS = {
    "current_state": "current_state_notes",
    "ledger": "ledger_notes",
    "relationships": "relationship_notes",
}
DICT_MODELS = {
    "characters": CharacterRuntimeState,
    "resources": ResourceRuntimeState,
    "relationship_states": RelationshipRuntimeState,
    "open_threads": OpenThreadRuntimeState,
    "foreshadowing_refs": ForeshadowingRuntimeReference,
    "proposed_entities": ProposedEntity,
}


def legacy_updates_to_delta(
    updates: dict[str, Any], *, chapter_id: str, source_revision: int | None = None
) -> RuntimeStateDelta:
    """Convert legacy whole-document replies into non-destructive appended notes."""
    aliases = {
        "current_state": "current_state",
        "particle_ledger": "ledger",
        "ledger": "ledger",
        "character_matrix": "relationships",
        "relationships": "relationships",
    }
    operations: list[RuntimeDeltaOperation] = []
    for raw_key, raw_value in updates.items():
        collection = aliases.get(str(raw_key))
        text = str(raw_value or "").strip()
        if collection and text:
            # One stable note per (collection, chapter): a re-settle replaces the
            # previous summary instead of appending a second copy of it.
            operations.append(
                RuntimeDeltaOperation(
                    op="append",
                    collection=collection,
                    target=f"legacy_{collection}_{chapter_id}",
                    value=text,
                )
            )
    return RuntimeStateDelta(
        chapter_id=chapter_id,
        source_revision=source_revision,
        operations=operations,
    )


class RuntimeStateManager:
    def __init__(self, project_root: Path, novel_id: str):
        self.project_root = Path(project_root).resolve()
        self.novel_id = str(novel_id)
        self.runtime_root = self.project_root / "data" / "novels" / self.novel_id / "data"
        self.world_dir = self.runtime_root / "world"
        self.state_path = self.world_dir / "runtime_state.json"

    def load(self, legacy_documents: dict[str, str] | None = None) -> RuntimeState:
        if self.state_path.is_file():
            try:
                return RuntimeState.model_validate_json(self.state_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise RuntimeStateError(f"运行态状态文件损坏: {exc}") from exc
        return RuntimeState(
            novel_id=self.novel_id,
            legacy_documents={
                key: str(value or "")
                for key, value in (legacy_documents or {}).items()
                if key in DOCUMENT_COLLECTIONS
            },
        )

    def apply(
        self,
        state: RuntimeState,
        delta: RuntimeStateDelta | dict[str, Any],
        *,
        known_entities: Iterable[str] = (),
    ) -> RuntimeState:
        parsed = (
            delta
            if isinstance(delta, RuntimeStateDelta)
            else RuntimeStateDelta.model_validate(delta)
        )
        if parsed.source_revision is not None and parsed.source_revision != state.revision:
            raise RuntimeStateError(
                f"状态版本冲突: expected {parsed.source_revision}, actual {state.revision}"
            )
        updated = state.model_copy(deep=True)
        known = {str(name).strip() for name in known_entities if str(name).strip()}
        known.update(item.name for item in updated.characters.values())
        for operation in parsed.operations:
            self._apply_operation(updated, operation, parsed.chapter_id, known)
        updated.revision += 1
        updated.source_chapter = parsed.chapter_id
        updated.updated_at = datetime.now(timezone.utc).isoformat()
        return RuntimeState.model_validate(updated.model_dump())

    def save_with_projections(self, state: RuntimeState) -> dict[str, str]:
        rendered = self.render(state)
        documents = {
            self.state_path: json.dumps(state.model_dump(mode="json"), ensure_ascii=False, indent=2)
            + "\n",
            self.world_dir / "current_state.md": self._projection_document(
                "current_state", rendered["current_state"], state
            ),
            self.world_dir / "ledger.md": self._projection_document(
                "ledger", rendered["ledger"], state
            ),
            self.world_dir / "relationships.md": self._projection_document(
                "relationships", rendered["relationships"], state
            ),
        }
        self._atomic_replace_many(documents)
        return rendered

    def render(self, state: RuntimeState) -> dict[str, str]:
        return {
            "current_state": self._render_current_state(state),
            "ledger": self._render_ledger(state),
            "relationships": self._render_relationships(state),
        }

    def _apply_operation(
        self,
        state: RuntimeState,
        operation: RuntimeDeltaOperation,
        chapter_id: str,
        known: set[str],
    ) -> None:
        if operation.collection in DOCUMENT_COLLECTIONS:
            self._apply_note_operation(state, operation, chapter_id)
            return
        if operation.collection == "timeline":
            self._apply_timeline_operation(state, operation, chapter_id)
            return
        state_collection = (
            "relationships"
            if operation.collection == "relationship_states"
            else operation.collection
        )
        collection = getattr(state, state_collection)
        if not isinstance(collection, dict):
            raise RuntimeStateError(f"不支持的状态集合: {operation.collection}")
        target = operation.target.strip() or self._target_from_value(operation.value)
        if operation.op == "remove":
            if target not in collection:
                raise RuntimeStateError(f"状态项不存在: {operation.collection}.{target}")
            del collection[target]
            return
        if operation.op == "resolve":
            item = collection.get(target)
            if item is None or not hasattr(item, "status"):
                raise RuntimeStateError(f"状态项不可结案: {operation.collection}.{target}")
            item.status = "resolved"
            return
        model = DICT_MODELS[operation.collection]
        payload = dict(operation.value) if isinstance(operation.value, dict) else {}
        if not payload:
            raise RuntimeStateError(f"{operation.collection} 需要对象值")
        payload.setdefault("source_chapter", chapter_id)
        if operation.collection == "proposed_entities":
            target = target or str(payload.get("name") or "").strip()
        if operation.collection == "characters":
            name = str(payload.get("name") or target).strip()
            if name not in known:
                self._propose_entity(state, name, "character", chapter_id)
                return
            payload["name"] = name
        if operation.collection == "relationship_states":
            unknown = [
                name
                for name in (
                    str(payload.get("source") or "").strip(),
                    str(payload.get("target") or "").strip(),
                )
                if name and name not in known
            ]
            if unknown:
                for name in unknown:
                    self._propose_entity(state, name, "character", chapter_id)
                return
        try:
            collection[target] = model.model_validate(payload)
        except ValueError as exc:
            raise RuntimeStateError(f"无效状态项 {operation.collection}.{target}: {exc}") from exc

    @staticmethod
    def _apply_note_operation(
        state: RuntimeState, operation: RuntimeDeltaOperation, chapter_id: str
    ) -> None:
        notes: list[RuntimeNote] = getattr(state, DOCUMENT_COLLECTIONS[operation.collection])
        if operation.op == "append":
            text = str(operation.value or "").strip()
            if not text:
                raise RuntimeStateError("状态增量正文不能为空")
            target = operation.target.strip()
            if not target:
                notes.append(
                    RuntimeNote(
                        id=f"note_{uuid4().hex[:12]}",
                        text=text,
                        source_chapter=chapter_id,
                    )
                )
                return
            # A chapter has one current summary per collection. Supersede older
            # active notes for the same chapter (including notes written before
            # stable ids existed) so repeated settlement cannot accumulate them.
            for note in notes:
                if note.source_chapter == chapter_id and note.id != target and note.status == "active":
                    note.status = "resolved"
            existing = next((note for note in notes if note.id == target), None)
            if existing is not None:
                existing.text = text
                existing.source_chapter = chapter_id
                existing.status = "active"
                return
            notes.append(RuntimeNote(id=target, text=text, source_chapter=chapter_id))
            return
        index = next((i for i, note in enumerate(notes) if note.id == operation.target), -1)
        if index < 0:
            raise RuntimeStateError(f"状态注记不存在: {operation.target}")
        if operation.op == "remove":
            notes.pop(index)
        elif operation.op == "resolve":
            notes[index].status = "resolved"
        elif operation.op == "set":
            notes[index].text = str(operation.value or "").strip()
        else:
            raise RuntimeStateError(f"注记集合不支持操作: {operation.op}")

    @staticmethod
    def _apply_timeline_operation(
        state: RuntimeState, operation: RuntimeDeltaOperation, chapter_id: str
    ) -> None:
        if operation.op == "append":
            payload = dict(operation.value) if isinstance(operation.value, dict) else {}
            payload.setdefault("id", operation.target or f"event_{uuid4().hex[:12]}")
            payload.setdefault("chapter_id", chapter_id)
            state.timeline.append(TimelineRuntimeEvent.model_validate(payload))
            return
        index = next(
            (i for i, event in enumerate(state.timeline) if event.id == operation.target),
            -1,
        )
        if index < 0:
            raise RuntimeStateError(f"时间线事件不存在: {operation.target}")
        if operation.op == "remove":
            state.timeline.pop(index)
            return
        raise RuntimeStateError(f"时间线不支持操作: {operation.op}")

    @staticmethod
    def _target_from_value(value: Any) -> str:
        if not isinstance(value, dict):
            return ""
        for key in ("id", "name", "title"):
            target = str(value.get(key) or "").strip()
            if target:
                return target
        source = str(value.get("source") or "").strip()
        target = str(value.get("target") or "").strip()
        return f"{source}->{target}" if source and target else ""

    @staticmethod
    def _propose_entity(state: RuntimeState, name: str, entity_type: str, chapter_id: str) -> None:
        clean = name.strip()
        if not clean:
            raise RuntimeStateError("新实体名称不能为空")
        state.proposed_entities.setdefault(
            clean,
            ProposedEntity(
                name=clean,
                entity_type=entity_type,
                reason="章节结算引用了未登记实体，等待作者确认",
                source_chapter=chapter_id,
            ),
        )

    @staticmethod
    def _latest_active_notes(notes: Iterable[RuntimeNote]) -> list[RuntimeNote]:
        """Keep one active note per chapter; older duplicates stay as audit rows."""
        latest: dict[str, RuntimeNote] = {}
        passthrough: list[RuntimeNote] = []
        for note in notes:
            if note.status != "active":
                continue
            chapter = note.source_chapter.strip()
            if not chapter:
                passthrough.append(note)
            else:
                latest[chapter] = note
        return passthrough + list(latest.values())

    def _render_current_state(self, state: RuntimeState) -> str:
        parts = [state.legacy_documents.get("current_state", "").strip()]
        active_notes = self._latest_active_notes(state.current_state_notes)
        if active_notes:
            parts.append("## 后续章节状态增量\n\n" + self._render_notes(active_notes))
        if state.characters:
            lines = ["## 结构化角色状态"]
            for item in state.characters.values():
                detail = "；".join(
                    part
                    for part in (
                        item.state,
                        f"位置：{item.location}" if item.location else "",
                    )
                    if part
                )
                lines.append(f"- {item.name}：{detail or '状态已登记'}")
            parts.append("\n".join(lines))
        if state.open_threads:
            lines = ["## 未决事项（结构化）"]
            lines.extend(
                f"- {item.title}：{item.detail}".rstrip("：")
                for item in state.open_threads.values()
                if item.status == "open"
            )
            parts.append("\n".join(lines))
        return self._join_parts(parts)

    def _render_ledger(self, state: RuntimeState) -> str:
        parts = [state.legacy_documents.get("ledger", "").strip()]
        active_notes = self._latest_active_notes(state.ledger_notes)
        if active_notes:
            parts.append("## 后续章节账本增量\n\n" + self._render_notes(active_notes))
        if state.resources:
            lines = ["## 结构化资源"]
            for item in state.resources.values():
                quantity = f"，数量：{item.quantity}" if item.quantity is not None else ""
                owner = f"，持有者：{item.owner}" if item.owner else ""
                lines.append(f"- {item.name}：{item.status}{owner}{quantity}")
            parts.append("\n".join(lines))
        return self._join_parts(parts)

    def _render_relationships(self, state: RuntimeState) -> str:
        parts = [state.legacy_documents.get("relationships", "").strip()]
        active_notes = self._latest_active_notes(state.relationship_notes)
        if active_notes:
            parts.append("## 后续章节关系增量\n\n" + self._render_notes(active_notes))
        if state.relationships:
            lines = ["## 结构化关系", "", "| 关系 | 当前状态 | 未决张力 |", "|---|---|---|"]
            lines.extend(
                f"| {item.source} -> {item.target} | {item.status} | {item.tension} |"
                for item in state.relationships.values()
            )
            parts.append("\n".join(lines))
        if state.proposed_entities:
            lines = ["## 待确认实体"]
            lines.extend(
                f"- {item.name}（{item.entity_type}）：{item.reason}"
                for item in state.proposed_entities.values()
            )
            parts.append("\n".join(lines))
        return self._join_parts(parts)

    @staticmethod
    def _projection_document(key: str, body: str, state: RuntimeState) -> str:
        return compose_toml_document(
            {
                "id": key,
                "type": "runtime_truth",
                "schema_version": state.schema_version,
                "state_revision": state.revision,
                "source_chapter": state.source_chapter,
                "summary": f"由 runtime_state.json 第 {state.revision} 版生成",
                "detail_refs": ["runtime_state.json"],
            },
            body,
        )

    @staticmethod
    def _render_notes(notes: list[RuntimeNote]) -> str:
        return "\n\n".join(
            f"### {note.source_chapter or '未知章节'}\n\n{note.text}" for note in notes
        )

    @staticmethod
    def _join_parts(parts: list[str]) -> str:
        body = "\n\n".join(part for part in parts if part.strip()).strip()
        return body

    @staticmethod
    def _atomic_replace_many(documents: dict[Path, str]) -> None:
        temporary: dict[Path, Path] = {}
        previous = {
            path: path.read_bytes() if path.is_file() else None for path in documents
        }
        replaced: list[Path] = []
        try:
            for path, content in documents.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=path.parent,
                    prefix=f".{path.name}.",
                    suffix=".tmp",
                    delete=False,
                ) as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                    temporary[path] = Path(handle.name)
            for path in documents:
                temporary[path].replace(path)
                replaced.append(path)
        except Exception:
            for path in temporary.values():
                path.unlink(missing_ok=True)
            for path in reversed(replaced):
                old_content = previous[path]
                if old_content is None:
                    path.unlink(missing_ok=True)
                    continue
                with tempfile.NamedTemporaryFile(
                    mode="wb",
                    dir=path.parent,
                    prefix=f".{path.name}.rollback.",
                    suffix=".tmp",
                    delete=False,
                ) as handle:
                    handle.write(old_content)
                    handle.flush()
                    os.fsync(handle.fileno())
                    rollback = Path(handle.name)
                rollback.replace(path)
            raise
