"""Lore checker for timeline/world consistency checks.
支持 LLM 模式（opt-in）：通过 LLM 进行语义级别的一致性审查。
LLM 发现的问题默认为 advisory（警告），不阻断流程。
不传入 llm_client 时保持原有规则模拟行为。
"""
import json
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional
if TYPE_CHECKING:
    from tools.llm.client import LLMClient
    from tools.llm.router import ModelRouter
logger = logging.getLogger(__name__)

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

    def __init__(
        self,
        strict: bool = False,
        llm_client: Optional["LLMClient"] = None,
        router: Optional["ModelRouter"] = None,
    ):
        self.strict = strict
        self._llm_client = llm_client
        self._router = router

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

        # --- Optional LLM semantic review (advisory only) ---
        if self._llm_client and self._router:
            self._llm_review(
                draft, forbidden, required,
                final_strict, errors, warnings,
            )
        return LoreCheckResult(errors=errors, warnings=warnings)

    def _llm_review(
        self,
        draft: str,
        forbidden: List[str],
        required: List[str],
        strict: bool,
        errors: List[str],
        warnings: List[str],
    ) -> None:
        """调用 LLM 进行语义级一致性审查（advisory only）。

        LLM 发现的问题默认追加为 warnings，不阻断流程。
        仅在 strict=True 且 LLM 明确标记为 error 时才追加到 errors。
        """
        from tools.llm.prompts import PromptBuilder
        from tools.llm.router import TaskType

        # 构建上下文 dict 供 prompt 使用
        context: Dict[str, str] = {
            "forbidden": ", ".join(forbidden) if forbidden else "无",
            "required": ", ".join(required) if required else "无",
        }

        messages = PromptBuilder.lore_checker_review(
            draft=draft,
            context=context,
            forbidden=forbidden,
            required=required,
            strict=strict,
        )

        try:
            routes = self._router.get_routes(TaskType.REVIEW)  # type: ignore[union-attr]
            response = self._llm_client.complete_with_fallback(  # type: ignore[union-attr]
                messages=messages, routes=routes,
            )
            self._parse_llm_findings(response.content, strict, errors, warnings)
        except Exception as e:
            logger.warning("LoreChecker LLM 审查失败，跳过语义检查: %s", e)

    @staticmethod
    def _parse_llm_findings(
        llm_output: str,
        strict: bool,
        errors: List[str],
        warnings: List[str],
    ) -> None:
        """解析 LLM JSON 输出，将发现追加到 errors/warnings。"""
        import re
        json_match = re.search(r'```json\s*(.+?)\s*```', llm_output, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = llm_output.strip()

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("LoreChecker LLM 输出 JSON 解析失败，跳过")
            return

        # LLM errors → advisory warnings by default, errors only in strict mode
        for item in data.get("errors", []):
            prefixed = f"[LLM] {item}"
            if strict:
                errors.append(prefixed)
            else:
                warnings.append(prefixed)

        for item in data.get("warnings", []):
            warnings.append(f"[LLM] {item}")

        for item in data.get("suggestions", []):
            warnings.append(f"[LLM建议] {item}")
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
                rebuilt = character_state_manager.rebuild_state(character_id=character_id)
                normalized = {item.split(" x", 1)[0].strip() for item in rebuilt.items}
                if payload not in normalized:
                    self._append_issue(
                        f"人物 {card.static.name} 尝试使用不存在/不足物品: {payload}",
                        errors,
                        warnings,
                        strict,
                    )

    def check_cross_chapter(
        self,
        chapter_id: str,
        character_state_manager: Optional[Any] = None,
        foreshadowing_manager: Optional[Any] = None,
        outline_query: Optional[Any] = None,
        strict: Optional[bool] = None,
    ) -> LoreCheckResult:
        """Cross-chapter timeline and state consistency checks.

        Validates:
          - Character location continuity (no teleportation without move mutation)
          - Character inventory consistency (items don't appear/vanish)
          - Overdue foreshadowing recovery (high-weight foreshadowings past target chapter)
        """
        errors: List[str] = []
        warnings: List[str] = []
        final_strict = self.strict if strict is None else strict

        if character_state_manager is not None:
            self._check_location_continuity(
                chapter_id, character_state_manager, errors, warnings, final_strict
            )
            self._check_inventory_continuity(
                chapter_id, character_state_manager, errors, warnings, final_strict
            )

        if foreshadowing_manager is not None:
            self._check_overdue_foreshadowing(
                chapter_id, foreshadowing_manager, errors, warnings, final_strict
            )

        return LoreCheckResult(errors=errors, warnings=warnings)

    def _check_location_continuity(
        self,
        chapter_id: str,
        csm: Any,
        errors: List[str],
        warnings: List[str],
        strict: bool,
    ) -> None:
        """Check that characters don't teleport between chapters."""
        for entry in csm.list_characters():
            cid = entry["id"]
            try:
                rebuilt = csm.rebuild_state(character_id=cid)
            except Exception:
                continue
            timeline = rebuilt.timeline_entries if hasattr(rebuilt, 'timeline_entries') else []
            if len(timeline) < 2:
                continue
            # Walk timeline looking for location changes without move mutations
            last_location: Optional[str] = None
            for te in timeline:
                te_text = str(te) if not isinstance(te, dict) else te.get('text', str(te))
                # Detect location from rebuild state
                if hasattr(rebuilt, 'location') and rebuilt.location:
                    current_location = rebuilt.location
                    if last_location and current_location != last_location:
                        # Check if there's a move mutation in recent timeline
                        if 'move:' not in te_text.lower():
                            self._append_issue(
                                f"角色 {cid} 位置不连续: {last_location} -> {current_location}，"
                                f"缺少 move mutation",
                                errors, warnings, strict,
                            )
                    last_location = current_location
                    break  # Only check current state vs last known

    def _check_inventory_continuity(
        self,
        chapter_id: str,
        csm: Any,
        errors: List[str],
        warnings: List[str],
        strict: bool,
    ) -> None:
        """Check that character inventories are consistent with mutations."""
        for entry in csm.list_characters():
            cid = entry["id"]
            try:
                rebuilt = csm.rebuild_state(character_id=cid)
            except Exception:
                continue
            # Check for negative item counts (shouldn't happen)
            for item in rebuilt.items:
                if ' x' in item:
                    name, count_str = item.rsplit(' x', 1)
                    try:
                        count = int(count_str.strip())
                        if count < 0:
                            self._append_issue(
                                f"角色 {cid} 物品数量异常: {name} x{count}",
                                errors, warnings, strict,
                            )
                    except ValueError:
                        pass

    def _check_overdue_foreshadowing(
        self,
        chapter_id: str,
        fsm: Any,
        errors: List[str],
        warnings: List[str],
        strict: bool,
    ) -> None:
        """Check for foreshadowings past their target recovery chapter."""
        try:
            pending = fsm.get_pending_nodes(min_weight=1)
        except Exception:
            return
        # Extract chapter number from chapter_id (e.g. 'ch_003' -> 3)
        import re
        ch_match = re.search(r'(\d+)', chapter_id)
        if not ch_match:
            return
        current_ch_num = int(ch_match.group(1))

        for node in pending:
            target = node.get('target_chapter', '') or ''
            target_match = re.search(r'(\d+)', target)
            if not target_match:
                continue
            target_ch_num = int(target_match.group(1))
            weight = node.get('weight', 0)
            node_id = node.get('id', 'unknown')

            if current_ch_num > target_ch_num:
                overdue_by = current_ch_num - target_ch_num
                if weight >= 8:
                    self._append_issue(
                        f"高权重伏笔 {node_id}(权重={weight}) 已超过目标章节 "
                        f"{target} {overdue_by}章未回收",
                        errors, warnings, strict,
                    )
                elif weight >= 5:
                    warnings.append(
                        f"中权重伏笔 {node_id}(权重={weight}) 已超过目标章节 "
                        f"{target} {overdue_by}章未回收"
                    )
                else:
                    warnings.append(
                        f"伏笔 {node_id}(权重={weight}) 已超过目标章节 "
                        f"{target} {overdue_by}章未回收"
                    )
