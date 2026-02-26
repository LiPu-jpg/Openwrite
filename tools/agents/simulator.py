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
except ImportError:  # pragma: no cover - supports legacy path injection
    from agents.director import DirectorAgent
    from agents.librarian import LibrarianAgent
    from agents.lore_checker import LoreCheckerAgent
    from agents.stylist import StylistAgent
    from character_state_manager import CharacterStateManager
    from graph.foreshadowing_dag import ForeshadowingDAGManager
    from queries.outline_query import OutlineQuery


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
            state = card.current_state
            inventory_count = sum(state.inventory.values()) if state.inventory else 0
            lines.append(
                f"{card.static.name}(境界={state.realm}, 位置={state.location}, 物品数={inventory_count})"
            )
        return "; ".join(lines)

    def _build_context(self, chapter_id: str, objective: str) -> Dict[str, str]:
        outline_summary = self._outline_context(chapter_id)
        character_summary = self._characters_context()
        foreshadowing_summary = self._pending_foreshadowing_context()
        summary = (
            f"目标:{objective}; 章节:{chapter_id}; 大纲:{outline_summary}; "
            f"人物:{character_summary}; 待回收伏笔:{foreshadowing_summary}"
        )
        return {
            "summary": summary,
            "seed": objective,
            "outline": outline_summary,
            "characters": character_summary,
            "foreshadowing": foreshadowing_summary,
        }

    def simulate_chapter(
        self,
        chapter_id: str,
        objective: str,
        forbidden: Optional[List[str]] = None,
        required: Optional[List[str]] = None,
        use_stylist: bool = False,
    ) -> SimulationResult:
        forbidden = forbidden or []
        required = required or []
        context = self._build_context(chapter_id, objective)

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
                "passed": lore_result.passed,
                "errors": lore_result.errors,
                "warnings": lore_result.warnings,
            },
            "style": {
                "enabled": use_stylist,
                "edits": style_edits,
            },
            "context": context,
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
