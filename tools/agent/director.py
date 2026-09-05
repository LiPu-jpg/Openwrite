"""多 Agent 编排器。

将写作流程拆分为多个职责 Agent，默认串行编排：
1) context_engineer 组装上下文
2) writer 产出初稿
3) continuity_reviewer 审查
4) state_settler 结算
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from .base import AgentContext
from .writer import WriterAgent, WritingResult
from .reviewer import ReviewerAgent, ReviewResult
from ..chapter_assembler import ChapterAssemblerV2, ChapterAssemblyPacket, ROLE_SYSTEM_PROMPTS
from ..context_schema import normalize_truth_file_key
from ..truth_manager import TruthFilesManager
from ..agent_policy import get_default_agent_specs


@dataclass
class MultiAgentResult:
    packet: ChapterAssemblyPacket
    draft: Optional[WritingResult] = None
    review: Optional[ReviewResult] = None
    system_prompts: Dict[str, str] = field(default_factory=dict)
    applied_state_updates: Dict[str, str] = field(default_factory=dict)
    new_concepts: List[str] = field(default_factory=list)


class MultiAgentDirector:
    """写作多 Agent 总控。"""

    def __init__(self, ctx: AgentContext, novel_id: str, style_id: str = ""):
        self.ctx = ctx
        self.novel_id = novel_id
        self.style_id = style_id
        self.agent_specs = get_default_agent_specs()
        self.assembler = ChapterAssemblerV2(
            project_root=Path(ctx.project_root),
            novel_id=novel_id,
            style_id=style_id,
        )
        self.writer = WriterAgent(ctx)
        self.reviewer = ReviewerAgent(ctx)
        self.truth_manager = TruthFilesManager(Path(ctx.project_root), novel_id)

    def assemble_packet(self, chapter_id: str) -> ChapterAssemblyPacket:
        return self.assembler.assemble(chapter_id)

    async def run(
        self,
        chapter_id: str,
        temperature: float = 0.7,
        run_review: bool = True,
        settle_state: bool = True,
        *,
        guidance: str = "",
        target_words: int | None = None,
        dimensions: list[int] | None = None,
        strict: bool = False,
    ) -> MultiAgentResult:
        self._assert_permission("context_engineer", "packet:build")
        packet = self.assemble_packet(chapter_id)
        from ..chapter_pipeline import build_review_payload, build_writer_payload
        from ..context_builder import ContextBuilder

        generation_context = ContextBuilder(
            Path(self.ctx.project_root), self.novel_id
        ).build_generation_context(chapter_id)
        truth = self.truth_manager.load_truth_files()
        writing_context = build_writer_payload(
            context=generation_context,
            truth=truth,
            packet=asdict(packet),
            guidance=guidance,
            target_words=int(
                target_words
                or packet.target_words
                or generation_context.target_words
                or 6000
            ),
        )

        chapter_number = self._parse_chapter_index(chapter_id)
        effective_target = int(writing_context.get("target_words") or 6000)
        self._assert_permission("writer", "manuscript:draft")
        draft = await self.writer.write_chapter(
            context=writing_context,
            chapter_number=chapter_number,
            temperature=temperature,
            target_words=effective_target,
        )

        review = None
        if run_review:
            self._assert_permission("continuity_reviewer", "review:report")
            review_context = build_review_payload(
                asdict(packet),
                context=generation_context,
            )
            review_context["target_words"] = effective_target
            review = await self.reviewer.review(
                content=draft.content,
                context=review_context,
                dimensions=dimensions,
                strict=strict,
            )

        known_entities = [
            str(item.get("name") or "").strip()
            for item in writing_context.get("active_characters", [])
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        ]
        applied_updates = (
            self._apply_state_settlement(
                draft.state_delta,
                draft.state_updates,
                chapter_id=chapter_id,
                known_entities=known_entities,
            )
            if settle_state
            else {}
        )
        new_concepts = self._collect_proposed_concepts(draft.state_delta)

        return MultiAgentResult(
            packet=packet,
            draft=draft,
            review=review,
            system_prompts=dict(ROLE_SYSTEM_PROMPTS),
            applied_state_updates=applied_updates,
            new_concepts=new_concepts,
        )

    def _apply_state_settlement(
        self,
        state_delta: dict,
        updates: Dict[str, str],
        *,
        chapter_id: str,
        known_entities: List[str],
    ) -> Dict[str, str]:
        if not updates:
            if not state_delta:
                return {}
        self._assert_permission("state_settler", "runtime:delta")

        writable: Dict[str, str] = {}
        file_map = {
            "current_state": "current_state",
            "ledger": "ledger",
            "relationships": "relationships",
        }

        for key, value in updates.items():
            if not isinstance(value, str) or not value.strip():
                continue
            canonical = normalize_truth_file_key(key)
            attr = file_map.get(canonical)
            if attr:
                writable[attr] = value

        from ..chapter_pipeline import apply_runtime_delta_with_fallback

        apply_runtime_delta_with_fallback(
            self.truth_manager,
            state_delta,
            writable,
            chapter_id=chapter_id,
            known_entities=known_entities,
        )
        return writable

    def _apply_state_updates(
        self,
        updates: Dict[str, str],
        *,
        chapter_id: str = "ch_000",
    ) -> Dict[str, str]:
        """Compatibility wrapper that persists legacy updates additively."""

        return self._apply_state_settlement(
            {},
            updates,
            chapter_id=chapter_id,
            known_entities=[],
        )

    @staticmethod
    def _collect_proposed_concepts(state_delta: dict) -> List[str]:
        names: List[str] = []
        operations = (
            state_delta.get("operations", [])
            if isinstance(state_delta, dict)
            else []
        )
        for operation in operations:
            if not isinstance(operation, dict) or operation.get("collection") != "proposed_entities":
                continue
            value = operation.get("value")
            if isinstance(value, dict):
                name = str(value.get("name") or operation.get("target") or "").strip()
                if name and name not in names:
                    names.append(name)
        return names

    def _assert_permission(self, agent_name: str, action: str) -> None:
        spec = self.agent_specs.get(agent_name)
        if not spec:
            raise PermissionError(f"Unknown agent: {agent_name}")
        if action in spec.forbidden:
            raise PermissionError(f"Agent '{agent_name}' forbidden action: {action}")
        if action in spec.can_write:
            return
        if action in spec.can_read:
            return
        # 支持前缀匹配，如 src:* / world:*
        for rule in spec.can_read + spec.can_write:
            if rule.endswith(":*"):
                prefix = rule[:-1]
                if action.startswith(prefix):
                    return
        raise PermissionError(f"Agent '{agent_name}' no permission for action: {action}")

    def _extract_dramatic_context(self, packet: ChapterAssemblyPacket) -> str:
        if not packet.current_arc_sections:
            return ""
        lines = []
        for sec in packet.current_arc_sections:
            lines.append(f"{sec.title}：{sec.summary[:180]}")
        return "\n".join(lines)

    def _parse_chapter_index(self, chapter_id: str) -> int:
        import re

        m = re.search(r"(\d+)", chapter_id)
        return int(m.group(1)) if m else 1
