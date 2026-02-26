"""Character state manager for mutations, timeline rebuild, and snapshots."""

from __future__ import annotations

import re
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

try:
    from tools.models.character import CharacterCard, CharacterState, CharacterStatic, StateMutation
except ImportError:  # pragma: no cover - supports legacy path injection
    from models.character import CharacterCard, CharacterState, CharacterStatic, StateMutation


class CharacterStateManager:
    """Manage character cards and timeline mutations."""

    def __init__(self, project_dir: Optional[Path] = None, novel_id: str = "my_novel"):
        self.project_dir = project_dir or self._find_project_dir()
        self.novel_id = novel_id
        self.base_dir = self.project_dir / "data" / "novels" / novel_id / "characters"
        self.cards_dir = self.base_dir / "cards"
        self.logs_dir = self.base_dir / "timeline" / "logs"
        self.snapshots_dir = self.base_dir / "timeline" / "snapshots"
        self.index_file = self.base_dir / "index.yaml"
        self._ensure_dirs()

    def _find_project_dir(self) -> Path:
        cwd = Path.cwd()
        for parent in [cwd] + list(cwd.parents):
            if (parent / "tools").exists():
                return parent
        return cwd

    def _ensure_dirs(self) -> None:
        self.cards_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        if not self.index_file.exists():
            self.index_file.write_text("characters: []\n", encoding="utf-8")

    def _load_yaml(self, path: Path, default: Dict) -> Dict:
        if not path.exists():
            return deepcopy(default)
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        return data

    def _save_yaml(self, path: Path, data: Dict) -> None:
        with path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(data, handle, allow_unicode=True, sort_keys=False)

    def _load_index(self) -> Dict[str, List[Dict[str, str]]]:
        return self._load_yaml(self.index_file, {"characters": []})

    def _save_index(self, index_data: Dict[str, List[Dict[str, str]]]) -> None:
        self._save_yaml(self.index_file, index_data)

    def list_characters(self) -> List[Dict[str, str]]:
        """List all registered characters from index."""
        index_data = self._load_index()
        return list(index_data.get("characters", []))

    def _generate_character_id(self) -> str:
        index_data = self._load_index()
        next_no = len(index_data.get("characters", [])) + 1
        return f"char_{next_no:03d}"

    def _card_path(self, character_id: str) -> Path:
        return self.cards_dir / f"{character_id}.yaml"

    def _log_path(self, character_id: str) -> Path:
        return self.logs_dir / f"{character_id}.yaml"

    @staticmethod
    def _chapter_order(chapter_id: str) -> Tuple[int, str]:
        match = re.search(r"(\d+)", chapter_id)
        if not match:
            return (10**9, chapter_id)
        return (int(match.group(1)), chapter_id)

    def create_character(
        self,
        name: str,
        tier: str = "普通配角",
        faction: str = "",
        gender: Optional[str] = None,
        age: Optional[int] = None,
    ) -> CharacterCard:
        index_data = self._load_index()
        for item in index_data.get("characters", []):
            if item.get("name") == name:
                raise ValueError(f"人物已存在: {name}")

        character_id = self._generate_character_id()
        card = CharacterCard(
            static=CharacterStatic(
                id=character_id,
                name=name,
                tier=tier,
                faction=faction,
                gender=gender,
                age=age,
            )
        )
        self._save_yaml(self._card_path(character_id), card.model_dump())

        index_data.setdefault("characters", []).append({"id": character_id, "name": name})
        self._save_index(index_data)
        return card

    def _get_character_id_by_name(self, name: str) -> Optional[str]:
        index_data = self._load_index()
        for item in index_data.get("characters", []):
            if item.get("name") == name:
                return item.get("id")
        return None

    def get_character_card(
        self, *, character_id: Optional[str] = None, name: Optional[str] = None
    ) -> CharacterCard:
        if not character_id and not name:
            raise ValueError("必须提供 character_id 或 name")

        final_id = character_id
        if not final_id and name:
            final_id = self._get_character_id_by_name(name)
        if not final_id:
            raise FileNotFoundError(f"找不到人物: {name or character_id}")

        path = self._card_path(final_id)
        if not path.exists():
            raise FileNotFoundError(f"人物卡不存在: {final_id}")
        data = self._load_yaml(path, {})
        return CharacterCard.model_validate(data)

    def save_character_card(self, card: CharacterCard) -> None:
        self._save_yaml(self._card_path(card.static.id), card.model_dump())

    def _load_mutations(self, character_id: str) -> List[StateMutation]:
        raw = self._load_yaml(self._log_path(character_id), {"mutations": []})
        mutations = [StateMutation.model_validate(item) for item in raw.get("mutations", [])]
        mutations.sort(key=lambda m: self._chapter_order(m.chapter_id))
        return mutations

    def _save_mutations(self, character_id: str, mutations: List[StateMutation]) -> None:
        serialized = [
            mutation.model_dump(
                exclude_none=True,
                exclude_defaults=True,
                exclude={"reason", "before_state", "after_state"},
            )
            for mutation in mutations
        ]
        self._save_yaml(
            self._log_path(character_id),
            {"mutations": serialized},
        )

    def _apply_mutation_action(self, state: CharacterState, mutation_expr: str) -> Dict[str, str]:
        if ":" not in mutation_expr:
            raise ValueError(f"mutation 格式错误: {mutation_expr}")

        action, payload_text = mutation_expr.split(":", 1)
        action = action.strip().lower()
        payload_text = payload_text.strip()
        payload: Dict[str, str] = {"raw": payload_text}

        if action == "acquire":
            count = state.inventory.get(payload_text, 0)
            state.inventory[payload_text] = count + 1
            payload.update({"item": payload_text})
        elif action == "use":
            count = state.inventory.get(payload_text, 0)
            if count <= 0:
                raise ValueError(f"物品不足，无法使用: {payload_text}")
            if count == 1:
                state.inventory.pop(payload_text, None)
            else:
                state.inventory[payload_text] = count - 1
            payload.update({"item": payload_text})
        elif action == "move":
            state.location = payload_text
            payload.update({"location": payload_text})
        elif action == "health":
            state.health = payload_text
            payload.update({"health": payload_text})
        elif action == "realm":
            state.realm = payload_text
            payload.update({"realm": payload_text})
        elif action == "flag":
            if payload_text and payload_text not in state.flags:
                state.flags.append(payload_text)
            payload.update({"flag": payload_text})
        else:
            raise ValueError(f"不支持的 mutation action: {action}")

        payload["action"] = action
        return payload

    @staticmethod
    def _payload_raw_value(action: str, payload: Dict[str, str]) -> str:
        raw = payload.get("raw")
        if raw is not None:
            return str(raw)
        key_by_action = {
            "acquire": "item",
            "use": "item",
            "move": "location",
            "health": "health",
            "realm": "realm",
            "flag": "flag",
        }
        key = key_by_action.get(action, "")
        return str(payload.get(key, ""))

    def _apply_record_action(self, state: CharacterState, mutation: StateMutation) -> None:
        if not mutation.action:
            return
        raw = self._payload_raw_value(mutation.action, mutation.payload)
        self._apply_mutation_action(state, f"{mutation.action}:{raw}")

    def apply_mutation(
        self,
        *,
        character_id: Optional[str] = None,
        name: Optional[str] = None,
        chapter_id: str,
        mutation_expr: Optional[str] = None,
        note: str = "",
        reason: str = "",
    ) -> StateMutation:
        if not mutation_expr and not note.strip() and not reason.strip():
            raise ValueError("至少提供 --change 或 --note/--reason 之一")

        card = self.get_character_card(character_id=character_id, name=name)
        after_state = CharacterState.model_validate(card.current_state.model_dump())
        payload: Dict[str, str] = {}
        action: Optional[str] = None
        if mutation_expr:
            payload = self._apply_mutation_action(after_state, mutation_expr)
            action = payload.get("action")
        timeline_note = note.strip() or reason.strip()

        mutation = StateMutation(
            mutation_id=f"{card.static.id}_{len(self._load_mutations(card.static.id)) + 1:04d}",
            chapter_id=chapter_id,
            action=action,
            payload=payload,
            note=timeline_note,
            reason=timeline_note or None,
        )

        mutations = self._load_mutations(card.static.id)
        mutations.append(mutation)
        mutations.sort(key=lambda item: self._chapter_order(item.chapter_id))
        self._save_mutations(card.static.id, mutations)

        if mutation_expr:
            card.current_state = after_state
            self.save_character_card(card)
        return mutation

    def get_timeline(
        self, *, character_id: Optional[str] = None, name: Optional[str] = None
    ) -> List[StateMutation]:
        card = self.get_character_card(character_id=character_id, name=name)
        return self._load_mutations(card.static.id)

    def rebuild_state(
        self,
        *,
        character_id: Optional[str] = None,
        name: Optional[str] = None,
        until_chapter: Optional[str] = None,
    ) -> CharacterState:
        card = self.get_character_card(character_id=character_id, name=name)
        state = CharacterState.model_validate(card.initial_state.model_dump())
        mutations = self._load_mutations(card.static.id)
        until_order = self._chapter_order(until_chapter) if until_chapter else None

        for mutation in mutations:
            mutation_order = self._chapter_order(mutation.chapter_id)
            if until_order and mutation_order > until_order:
                break
            if mutation.action:
                try:
                    self._apply_record_action(state, mutation)
                    continue
                except ValueError:
                    pass
            if mutation.after_state:
                state = CharacterState.model_validate(mutation.after_state.model_dump())
        return state

    def create_snapshot(
        self,
        *,
        character_id: Optional[str] = None,
        name: Optional[str] = None,
        volume_id: str,
        chapter_range: str = "",
    ) -> Path:
        card = self.get_character_card(character_id=character_id, name=name)
        state = self.rebuild_state(character_id=card.static.id)

        snapshot_file = self.snapshots_dir / f"{card.static.id}_{volume_id}.md"
        content_lines = [
            f"# {card.static.name} - {volume_id} 快照",
            "",
            "## 基本信息",
            f"- 人物ID: {card.static.id}",
            f"- 层级: {card.static.tier}",
            f"- 势力: {card.static.faction or '未设定'}",
            f"- 章节范围: {chapter_range or '未提供'}",
            f"- 生成时间: {datetime.now().isoformat()}",
            "",
            "## 当前状态",
            f"- 健康: {state.health}",
            f"- 境界: {state.realm}",
            f"- 体力: {state.stamina}%",
            f"- 精神: {state.mental_state}",
            f"- 位置: {state.location}",
            "",
            "## 持有物品",
        ]

        if not state.inventory:
            content_lines.append("- 无")
        else:
            for item, count in sorted(state.inventory.items()):
                content_lines.append(f"- {item}: {count}")

        content_lines.extend(["", "## 状态标记"])
        if not state.flags:
            content_lines.append("- 无")
        else:
            for flag in state.flags:
                content_lines.append(f"- {flag}")

        snapshot_file.write_text("\n".join(content_lines) + "\n", encoding="utf-8")

        card.current_snapshot = snapshot_file.name
        self.save_character_card(card)
        return snapshot_file
