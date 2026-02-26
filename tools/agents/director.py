"""Director agent for chapter simulation routing."""

from dataclasses import dataclass
from typing import Dict, List


@dataclass
class DirectorDecision:
    """Decision output produced by Director."""

    objective: str
    chapter_id: str
    required_agents: List[str]
    context_summary: str
    notes: List[str]


class DirectorAgent:
    """Coordinates sub-agents and controls workflow routing."""

    def plan(
        self,
        objective: str,
        context: Dict[str, str],
        chapter_id: str = "",
        use_stylist: bool = False,
    ) -> DirectorDecision:
        required_agents = ["librarian", "lore_checker"]
        if use_stylist:
            required_agents.append("stylist")

        summary = context.get("summary", "")
        notes = [
            "总纲/卷纲默认只读，本轮仅生成草稿",
            "逻辑检查未通过时禁止进入文风润色",
        ]
        if not use_stylist:
            notes.append("已按配置跳过 Stylist（文风单独处理）")

        return DirectorDecision(
            objective=objective,
            chapter_id=chapter_id,
            required_agents=required_agents,
            context_summary=summary[:600],
            notes=notes,
        )
