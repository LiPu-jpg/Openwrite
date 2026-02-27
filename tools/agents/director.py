"""Director agent — orchestrates sub-agents and compresses context.

The Director is the 'brain' of the simulation pipeline:
  1. Analyzes the chapter objective and available context
  2. Compresses context to fit within token budgets
  3. Routes sub-agents based on chapter needs
  4. Provides style-aware instructions when stylist is enabled

支持 LLM 模式（opt-in）：通过 llm_client + router 接入真实 LLM 进行路由决策。
不传入 llm_client 时保持原有规则模拟行为。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from tools.llm.client import LLMClient
    from tools.llm.router import ModelRouter

logger = logging.getLogger(__name__)


@dataclass
class DirectorDecision:
    """Decision output produced by Director."""

    objective: str
    chapter_id: str
    required_agents: List[str]
    context_summary: str
    notes: List[str]
    compressed_context: Dict[str, str] = field(default_factory=dict)
    style_instructions: str = ""
    suggested_strict_lore: bool = False
    priority_elements: List[str] = field(default_factory=list)


class DirectorAgent:
    """Coordinates sub-agents and controls workflow routing.

    Args:
        llm_client: 可选 LLM 客户端，传入时启用 LLM 路由决策
        router: 可选模型路由器，与 llm_client 配合使用
    """

    # Context budget: max chars per section for compressed context
    BUDGET_OUTLINE: int = 300
    BUDGET_CHARACTERS: int = 400
    BUDGET_FORESHADOWING: int = 250
    BUDGET_WORLD: int = 200
    BUDGET_SCENES: int = 150
    BUDGET_STYLE: int = 300

    def __init__(
        self,
        llm_client: Optional["LLMClient"] = None,
        router: Optional["ModelRouter"] = None,
    ):
        self._llm_client = llm_client
        self._router = router
    def plan(
        self,
        objective: str,
        context: Dict[str, str],
        chapter_id: str = "",
        use_stylist: bool = False,
        style_summary: Optional[str] = None,
    ) -> DirectorDecision:
        """Analyze context and produce a routing decision.

        当 llm_client 存在时，使用 LLM 进行路由决策；
        否则使用规则引擎（原有行为）。

        Args:
            objective: The chapter's writing goal.
            context: Raw context dict from simulator (outline, characters, etc.)
            chapter_id: Current chapter identifier.
            use_stylist: Whether the stylist agent should be included.
            style_summary: Optional composed style summary text.
        """
        # --- Context compression (always rule-based) ---
        compressed = self._compress_context(context)

        # --- LLM branch ---
        if self._llm_client and self._router:
            return self._plan_with_llm(
                objective, context, chapter_id, use_stylist,
                style_summary, compressed,
            )

        # --- Rule-based branch (original behavior) ---
        return self._plan_rule_based(
            objective, context, chapter_id, use_stylist,
            style_summary, compressed,
        )

    def _plan_rule_based(
        self,
        objective: str,
        context: Dict[str, str],
        chapter_id: str,
        use_stylist: bool,
        style_summary: Optional[str],
        compressed: Dict[str, str],
    ) -> DirectorDecision:
        """规则引擎路由决策（原有行为）。"""
        required_agents = ["librarian", "lore_checker"]
        notes: List[str] = []
        priority_elements: List[str] = []



        # --- Analyze objective for routing hints ---
        suggested_strict = self._should_strict_lore(objective, context)
        if suggested_strict:
            notes.append("检测到高风险章节内容，建议启用严格逻辑检查")

        # --- Detect priority elements from objective ---
        priority_elements = self._extract_priority_elements(objective, context)
        if priority_elements:
            notes.append(f"本章重点要素: {', '.join(priority_elements)}")

        # --- Stylist routing ---
        style_instructions = ""
        if use_stylist:
            required_agents.append("stylist")
            style_instructions = self._build_style_instructions(style_summary)
            notes.append("文风处理已启用，Stylist 将在逻辑检查通过后执行")
        else:
            notes.append("已按配置跳过 Stylist（文风单独处理）")

        # --- Foreshadowing awareness ---
        foreshadowing_text = context.get("foreshadowing", "")
        if foreshadowing_text and "暂无" not in foreshadowing_text:
            pending_count = foreshadowing_text.count(";") + 1
            notes.append(f"有{pending_count}条待回收伏笔，Librarian 应考虑自然融入")

        # --- Standard rules ---
        notes.append("总纲/卷纲默认只读，本轮仅生成草稿")
        notes.append("逻辑检查未通过时禁止进入文风润色")

        # Build full compressed summary
        summary_parts = [f"目标:{objective}", f"章节:{chapter_id}"]
        for key in ["outline", "characters", "foreshadowing", "scenes", "world"]:
            if key in compressed and compressed[key]:
                summary_parts.append(f"{key}:{compressed[key]}")
        full_summary = "; ".join(summary_parts)

        return DirectorDecision(
            objective=objective,
            chapter_id=chapter_id,
            required_agents=required_agents,
            context_summary=full_summary[:800],
            notes=notes,
            compressed_context=compressed,
            style_instructions=style_instructions,
            suggested_strict_lore=suggested_strict,
            priority_elements=priority_elements,
        )

    def _compress_context(self, context: Dict[str, str]) -> Dict[str, str]:
        """Compress each context section using the ContextCompressor."""
        try:
            from tools.utils.context_compressor import ContextCompressor
        except ImportError:
            from utils.context_compressor import ContextCompressor
        total_budget = (
            self.BUDGET_OUTLINE + self.BUDGET_CHARACTERS + self.BUDGET_FORESHADOWING
            + self.BUDGET_WORLD + self.BUDGET_SCENES + self.BUDGET_STYLE
        )
        compressor = ContextCompressor(budget=total_budget)
        # Only compress the main content sections
        compressible = {
            k: v for k, v in context.items()
            if k in ("outline", "characters", "foreshadowing", "world",
                     "scenes", "cross_chapter", "seed", "summary")
            and v
        }
        if not compressible:
            return {}
        result = compressor.compress(compressible)
        return result.sections

    def _truncate_smart(self, text: str, max_chars: int) -> str:
        """Truncate text intelligently — prefer cutting at sentence boundaries."""
        if len(text) <= max_chars:
            return text

        # Try to cut at a Chinese sentence boundary
        truncated = text[:max_chars]
        # Find last sentence-ending punctuation
        for marker in ["。", "；", "!", "？", "\n"]:
            last_pos = truncated.rfind(marker)
            if last_pos > max_chars * 0.6:
                return truncated[: last_pos + 1]

        # Fall back to hard truncation
        return truncated + "…"

    def _should_strict_lore(self, objective: str, context: Dict[str, str]) -> bool:
        """Heuristic: should this chapter use strict lore checking?"""
        high_risk_keywords = [
            "战斗",
            "死亡",
            "死斗",
            "决斗",
            "突破",
            "晋级",
            "关键",
            "转折",
            "高潮",
            "揭秘",
            "真相",
            "伏笔回收",
            "回收",
            "时间线",
        ]
        combined = objective + " " + context.get("outline", "")
        return any(kw in combined for kw in high_risk_keywords)

    def _extract_priority_elements(
        self, objective: str, context: Dict[str, str]
    ) -> List[str]:
        """Extract key elements that this chapter must address."""
        elements: List[str] = []

        # Check for foreshadowing targets
        foreshadowing = context.get("foreshadowing", "")
        if foreshadowing and "暂无" not in foreshadowing:
            # Extract node IDs from foreshadowing context
            ids = re.findall(r"(\w+)\(权重=(\d+)", foreshadowing)
            high_weight = [nid for nid, w in ids if int(w) >= 7]
            if high_weight:
                elements.append(f"高权重伏笔: {', '.join(high_weight[:3])}")

        # Check for character mentions in objective
        characters = context.get("characters", "")
        if characters and "暂无" not in characters:
            # Extract character names
            names = re.findall(r"(\S+?)\(境界=", characters)
            if names:
                elements.append(f"涉及角色: {', '.join(names[:4])}")

        # Check for scene requirements
        scenes = context.get("scenes", "")
        if scenes and "未标注" not in scenes:
            elements.append(f"场景要求: {scenes}")

        return elements

    def _build_style_instructions(self, style_summary: Optional[str]) -> str:
        """Build style instructions for the Stylist agent."""
        if not style_summary:
            return "使用默认风格规则进行润色（无特定风格文档加载）"

        # Extract key style points from the composed document
        instructions: List[str] = [
            "风格润色指令：",
            "1. 检查并移除AI痕迹（禁用表达清单）",
            "2. 验证叙述者-角色声音融合度",
            "3. 检查段落节奏（短段60%/中段30%/长段10%）",
            "4. 确保吐槽密度符合风格要求",
            "5. 验证现代感用语自然融入",
        ]

        # Add style-specific notes if available
        if "风格DNA" in style_summary or "风格指纹" in style_summary:
            instructions.append("6. 已加载作品风格指纹，按风格DNA维度评分")

        return "\n".join(instructions)

    def _plan_with_llm(
        self,
        objective: str,
        context: Dict[str, str],
        chapter_id: str,
        use_stylist: bool,
        style_summary: Optional[str],
        compressed: Dict[str, str],
    ) -> DirectorDecision:
        """LLM 路由决策 — 调用 LLM 分析章节目标并生成决策。"""
        assert self._llm_client is not None
        assert self._router is not None

        from tools.llm.prompts import PromptBuilder
        from tools.llm.router import TaskType

        # 构建压缩摘要
        summary_parts = [f"目标:{objective}", f"章节:{chapter_id}"]
        for key in ["outline", "characters", "foreshadowing", "scenes", "world"]:
            if key in compressed and compressed[key]:
                summary_parts.append(f"{key}:{compressed[key]}")
        full_summary = "; ".join(summary_parts)

        messages = PromptBuilder.director_plan(
            objective=objective,
            chapter_id=chapter_id,
            context_summary=full_summary[:2000],
            style_summary=style_summary,
        )

        try:
            routes = self._router.get_routes(TaskType.REASONING)
            response = self._llm_client.complete_with_fallback(
                messages=messages, routes=routes,
            )
            return self._parse_llm_decision(
                response.content, objective, chapter_id,
                use_stylist, compressed, full_summary,
            )
        except Exception as e:
            logger.warning("Director LLM 调用失败，回退到规则引擎: %s", e)
            return self._plan_rule_based(
                objective, context, chapter_id, use_stylist,
                style_summary, compressed,
            )

    def _parse_llm_decision(
        self,
        llm_output: str,
        objective: str,
        chapter_id: str,
        use_stylist: bool,
        compressed: Dict[str, str],
        full_summary: str,
    ) -> DirectorDecision:
        """解析 LLM JSON 输出为 DirectorDecision。"""
        # 提取 JSON 块
        json_match = re.search(r'```json\s*(.+?)\s*```', llm_output, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # 尝试直接解析
            json_str = llm_output.strip()

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning("Director LLM 输出 JSON 解析失败，使用默认值")
            data = {}

        required_agents = ["librarian", "lore_checker"]
        if use_stylist:
            required_agents.append("stylist")

        notes = data.get("notes", [])
        if data.get("generation_instructions"):
            notes.append(f"LLM 创作指令: {data['generation_instructions']}")

        return DirectorDecision(
            objective=objective,
            chapter_id=chapter_id,
            required_agents=required_agents,
            context_summary=full_summary[:800],
            notes=notes,
            compressed_context=compressed,
            style_instructions=data.get("style_instructions", ""),
            suggested_strict_lore=data.get("strict_lore", False),
            priority_elements=data.get("priority_elements", []),
        )
