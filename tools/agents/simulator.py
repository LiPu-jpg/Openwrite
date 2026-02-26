"""Agent workflow simulator (Director -> Librarian -> LoreChecker)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import yaml

try:
    from tools.agents.director import DirectorAgent
    from tools.agents.librarian import LibrarianAgent
    from tools.agents.lore_checker import LoreCheckerAgent
    from tools.agents.stylist import StylistAgent
    from tools.character_state_manager import CharacterStateManager
    from tools.graph.foreshadowing_dag import ForeshadowingDAGManager
    from tools.queries.outline_query import OutlineQuery
    from tools.world_graph_manager import WorldGraphManager
except ImportError:  # pragma: no cover - supports legacy path injection
    from agents.director import DirectorAgent
    from agents.librarian import LibrarianAgent
    from agents.lore_checker import LoreCheckerAgent
    from agents.stylist import StylistAgent
    from character_state_manager import CharacterStateManager
    from graph.foreshadowing_dag import ForeshadowingDAGManager
    from queries.outline_query import OutlineQuery
    from world_graph_manager import WorldGraphManager


@dataclass
class SimulationResult:
    """Output of a simulated chapter workflow."""

    chapter_id: str
    passed: bool
    draft_file: Path
    report_file: Path
    errors: List[str]
    warnings: List[str]


class AgentSimulator:
    """Runs a local multi-agent simulation pipeline."""

    def __init__(self, project_dir: Path, novel_id: str):
        self.project_dir = project_dir
        self.novel_id = novel_id
        self.base_dir = self.project_dir / "data" / "novels" / novel_id
        self.drafts_dir = self.base_dir / "manuscript" / "drafts"
        self.sim_logs_dir = self.project_dir / "logs" / "simulations"
        self.manager = CharacterStateManager(project_dir=project_dir, novel_id=novel_id)
        self.outline_query = OutlineQuery(project_dir=project_dir, novel_id=novel_id)
        self.foreshadowing_manager = ForeshadowingDAGManager(
            project_dir=project_dir, novel_id=novel_id
        )
        self.world_manager = WorldGraphManager(project_dir=project_dir, novel_id=novel_id)

        self.director = DirectorAgent()
        self.librarian = LibrarianAgent()
        self.lore_checker = LoreCheckerAgent()
        self.stylist = StylistAgent()

        self.drafts_dir.mkdir(parents=True, exist_ok=True)
        self.sim_logs_dir.mkdir(parents=True, exist_ok=True)

    def _outline_context(self, chapter_id: str) -> str:
        chapter_data = self.outline_query.get_chapter(chapter_id)
        if not chapter_data:
            return "未找到章节大纲文件，使用默认推进策略"
        content = chapter_data.get("raw_content", "").strip()
        compact = " ".join(content.split())
        return compact[:240] if compact else "章节大纲为空"

    def _chapter_annotations(self, chapter_id: str) -> Dict[str, List[Dict[str, str]]]:
        chapter_data = self.outline_query.get_chapter(chapter_id) or {}
        annotations = chapter_data.get("annotations", {})
        return {
            "foreshadowings": annotations.get("foreshadowings", []),
            "recovers": annotations.get("recovers", []),
            "characters": annotations.get("characters", []),
            "scenes": annotations.get("scenes", []),
        }

    def _scene_context(self, chapter_annotations: Dict[str, List[Dict[str, str]]]) -> str:
        scenes = chapter_annotations.get("scenes", [])
        if not scenes:
            return "未标注场景张力/情绪"

        tensions: List[int] = []
        emotions: List[str] = []
        for scene in scenes:
            attrs = scene.get("attributes", {})
            tension_raw = attrs.get("tension")
            if tension_raw is not None:
                try:
                    tensions.append(int(str(tension_raw)))
                except ValueError:
                    pass
            emotion = str(attrs.get("emotion", "")).strip()
            if emotion:
                emotions.append(emotion)

        tension_desc = (
            f"张力范围={min(tensions)}-{max(tensions)}" if tensions else "张力未标注"
        )
        emotion_desc = (
            f"情绪标签={','.join(sorted(set(emotions)))}" if emotions else "情绪未标注"
        )
        return f"场景数={len(scenes)}, {tension_desc}, {emotion_desc}"

    def _pending_foreshadowing_context(self, limit: int = 8) -> str:
        pending = self.foreshadowing_manager.get_pending_nodes(min_weight=1)
        if pending:
            pending.sort(key=lambda item: int(item.get("weight", 0)), reverse=True)
            lines = []
            for item in pending[:limit]:
                node_id = item.get("id", "")
                weight = item.get("weight", 0)
                layer = item.get("layer", "")
                target = item.get("target_chapter") or "未指定"
                lines.append(
                    f"{node_id}(权重={weight}, 层级={layer}, 目标={target})"
                )
            return "; ".join(lines)

        pending_from_outline = self.outline_query.get_pending_foreshadowings()
        if pending_from_outline:
            lines = []
            for entry in pending_from_outline[:limit]:
                fs = entry.get("foreshadowing", {})
                attrs = fs.get("attributes", {})
                node_id = attrs.get("id", "unknown")
                weight = attrs.get("weight", "0")
                layer = attrs.get("layer", "未标注")
                chapter_id = entry.get("chapter_id", "")
                lines.append(
                    f"{node_id}(权重={weight}, 层级={layer}, 创建章节={chapter_id})"
                )
            return "; ".join(lines)

        return "暂无待回收伏笔"

    def _characters_context(self, limit: int = 5) -> str:
        entries = self.manager.list_characters()
        if not entries:
            return "暂无人物档案"

        lines: List[str] = []
        for item in entries[:limit]:
            card = self.manager.get_character_card(character_id=item["id"])
            summary = self.manager.rebuild_state(character_id=item["id"])
            inventory_count = len(summary.items)
            profile_excerpt = self.manager.get_profile_excerpt(
                character_id=item["id"], max_chars=80
            )
            profile_part = f", 设定={profile_excerpt}" if profile_excerpt else ""
            lines.append(
                f"{card.static.name}(境界={summary.realm}, 位置={summary.location}, "
                f"物品数={inventory_count}{profile_part})"
            )
        return "; ".join(lines)

    def _world_context(self) -> str:
        return self.world_manager.summary(max_entities=6, max_relations=8)

    def _build_context(
        self,
        chapter_id: str,
        objective: str,
        chapter_annotations: Dict[str, List[Dict[str, str]]],
    ) -> Dict[str, str]:
        outline_summary = self._outline_context(chapter_id)
        character_summary = self._characters_context()
        foreshadowing_summary = self._pending_foreshadowing_context()
        scene_summary = self._scene_context(chapter_annotations)
        world_summary = self._world_context()
        summary = (
            f"目标:{objective}; 章节:{chapter_id}; 大纲:{outline_summary}; "
            f"人物:{character_summary}; 待回收伏笔:{foreshadowing_summary}; "
            f"场景标记:{scene_summary}; 世界观:{world_summary}"
        )
        return {
            "summary": summary,
            "seed": objective,
            "outline": outline_summary,
            "characters": character_summary,
            "foreshadowing": foreshadowing_summary,
            "scenes": scene_summary,
            "world": world_summary,
        }

    def simulate_chapter(
        self,
        chapter_id: str,
        objective: str,
        forbidden: Optional[List[str]] = None,
        required: Optional[List[str]] = None,
        use_stylist: bool = False,
        strict_lore: bool = False,
    ) -> SimulationResult:
        forbidden = forbidden or []
        required = required or []
        chapter_annotations = self._chapter_annotations(chapter_id)
        context = self._build_context(chapter_id, objective, chapter_annotations)

        decision = self.director.plan(
            objective=objective,
            context=context,
            chapter_id=chapter_id,
            use_stylist=use_stylist,
        )

        librarian_output = self.librarian.generate_chapter(
            chapter_id=chapter_id,
            objective=objective,
            context=context,
        )
        draft_text = librarian_output.draft

        lore_result = self.lore_checker.check_draft(
            draft=draft_text,
            forbidden=forbidden,
            required=required,
            chapter_annotations=chapter_annotations,
            character_state_manager=self.manager,
            strict=strict_lore,
        )

        style_edits: List[str] = []
        if lore_result.passed and use_stylist:
            style_result = self.stylist.polish(draft_text, banned_phrases=[])
            draft_text = style_result.text + "\n"
            style_edits = style_result.edits

        draft_file = self.drafts_dir / f"{chapter_id}_draft.md"
        draft_file.write_text(draft_text, encoding="utf-8")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = self.sim_logs_dir / f"{timestamp}_{chapter_id}.yaml"
        report_data = {
            "timestamp": datetime.now().isoformat(),
            "novel_id": self.novel_id,
            "chapter_id": chapter_id,
            "objective": objective,
            "decision": asdict(decision),
            "librarian": {
                "beat_count": len(librarian_output.beat_list),
                "beats": librarian_output.beat_list,
            },
            "lore_checker": {
                "strict": strict_lore,
                "passed": lore_result.passed,
                "errors": lore_result.errors,
                "warnings": lore_result.warnings,
            },
            "style": {
                "enabled": use_stylist,
                "edits": style_edits,
            },
            "context": context,
            "chapter_annotations": chapter_annotations,
            "artifacts": {
                "draft_file": str(draft_file),
            },
        }
        with report_file.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(report_data, handle, allow_unicode=True, sort_keys=False)

        return SimulationResult(
            chapter_id=chapter_id,
            passed=lore_result.passed,
            draft_file=draft_file,
            report_file=report_file,
            errors=lore_result.errors,
            warnings=lore_result.warnings,
        )
