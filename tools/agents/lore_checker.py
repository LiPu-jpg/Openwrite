"""Lore checker for timeline/world consistency checks."""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class LoreCheckResult:
    """Consistency check result."""

    errors: List[str]
    warnings: List[str]

    @property
    def passed(self) -> bool:
        return len(self.errors) == 0


class LoreCheckerAgent:
    """Performs lightweight rule checks on generated draft text."""

    SUPPORTED_MUTATIONS = {"acquire", "use", "move", "health", "realm", "flag"}

    def __init__(self, strict: bool = False):
        self.strict = strict

    @staticmethod
    def _append_issue(
        message: str, errors: List[str], warnings: List[str], strict: bool
    ) -> None:
        if strict:
            errors.append(message)
            return
        warnings.append(message)

    def check(
        self, draft: str, constraints: Dict[str, str], strict: Optional[bool] = None
    ) -> LoreCheckResult:
        forbidden_raw = constraints.get("forbidden", "")
        required_raw = constraints.get("required", "")

        forbidden = [item.strip() for item in forbidden_raw.split("|") if item.strip()]
        required = [item.strip() for item in required_raw.split("|") if item.strip()]
        return self.check_draft(
            draft,
            forbidden=forbidden,
            required=required,
            strict=strict,
        )

    def check_draft(
        self,
        draft: str,
        forbidden: List[str],
        required: List[str],
        chapter_annotations: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        character_state_manager: Optional[Any] = None,
        strict: Optional[bool] = None,
    ) -> LoreCheckResult:
        errors: List[str] = []
        warnings: List[str] = []
        final_strict = self.strict if strict is None else strict

        for token in forbidden:
            if token in draft:
                errors.append(f"检测到禁用设定: {token}")

        for token in required:
            if token not in draft:
                warnings.append(f"未显式出现必备要素: {token}")

        if chapter_annotations:
            self._check_scene_rules(
                chapter_annotations,
                errors,
                warnings,
                strict=final_strict,
            )
            if character_state_manager is not None:
                self._check_character_mutations(
                    chapter_annotations,
                    character_state_manager,
                    errors,
                    warnings,
                    strict=final_strict,
                )

        return LoreCheckResult(errors=errors, warnings=warnings)

    def _check_scene_rules(
        self,
        chapter_annotations: Dict[str, List[Dict[str, Any]]],
        errors: List[str],
        warnings: List[str],
        strict: bool,
    ) -> None:
        scenes = chapter_annotations.get("scenes", [])
        if not scenes:
            return

        tensions: List[int] = []
        emotions: List[str] = []
        for scene in scenes:
            attrs = scene.get("attributes", {})
            tension_raw = attrs.get("tension")
            if tension_raw is not None:
                try:
                    tension = int(str(tension_raw))
                except ValueError:
                    self._append_issue(
                        f"场景 tension 非数字: {tension_raw}",
                        errors,
                        warnings,
                        strict,
                    )
                else:
                    if tension < 1 or tension > 10:
                        self._append_issue(
                            f"场景 tension 超出范围(1-10): {tension}",
                            errors,
                            warnings,
                            strict,
                        )
                    tensions.append(tension)
            emotion = str(attrs.get("emotion", "")).strip()
            if emotion:
                emotions.append(emotion)

        if tensions and all(value < 3 for value in tensions):
            warnings.append("本章场景张力均低于3，可能过于平淡")
        if tensions and all(value > 8 for value in tensions):
            warnings.append("本章场景张力均高于8，可能造成疲劳")
        if len(emotions) >= 3 and len(set(emotions)) == 1:
            warnings.append(f"本章情绪标签单一: {emotions[0]}")

    def _check_character_mutations(
        self,
        chapter_annotations: Dict[str, List[Dict[str, Any]]],
        character_state_manager: Any,
        errors: List[str],
        warnings: List[str],
        strict: bool,
    ) -> None:
        characters = chapter_annotations.get("characters", [])
        for annotation in characters:
            attrs = annotation.get("attributes", {})
            mutation = str(attrs.get("mutation", "")).strip()
            if not mutation:
                continue

            character_id = str(attrs.get("id") or attrs.get("ref") or "").strip()
            if not character_id:
                self._append_issue(
                    f"人物 mutation 缺少 id/ref: {mutation}",
                    errors,
                    warnings,
                    strict,
                )
                continue

            if ":" not in mutation:
                self._append_issue(
                    f"人物 mutation 格式错误: {mutation}",
                    errors,
                    warnings,
                    strict,
                )
                continue
            action, payload = [part.strip() for part in mutation.split(":", 1)]
            action = action.lower()
            if action not in self.SUPPORTED_MUTATIONS:
                self._append_issue(
                    f"人物 mutation action 不支持: {action}",
                    errors,
                    warnings,
                    strict,
                )
                continue

            try:
                card = character_state_manager.get_character_card(character_id=character_id)
            except FileNotFoundError:
                warnings.append(f"人物标记引用不存在角色: {character_id}")
                continue

            if action == "use":
                count = card.current_state.inventory.get(payload, 0)
                if count <= 0:
                    self._append_issue(
                        f"人物 {card.static.name} 尝试使用不存在/不足物品: {payload}",
                        errors,
                        warnings,
                        strict,
                    )
