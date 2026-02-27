"""Pipeline simulator v2 -- Director/Writer/Reviewer/Stylist + human-in-loop.

Phase 7 architecture redesign. New simplified 3+1 agent pipeline:
  1. Director (context assembly + user interaction)
  2. Writer (chapter generation with rich context)
  3. Reviewer (read-only consistency check, only severe errors trigger rewrite)
  4. User reviews & edits
  5. Stylist (final polish after user confirmation)

Old AgentSimulator preserved for backward compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import yaml

if TYPE_CHECKING:
    from tools.llm.client import LLMClient
    from tools.llm.router import ModelRouter

try:
    from tools.agents.librarian import LibrarianAgent
    from tools.agents.lore_checker import LoreCheckerAgent
    from tools.agents.stylist import StylistAgent
    from tools.character_state_manager import CharacterStateManager
    from tools.graph.foreshadowing_dag import ForeshadowingDAGManager
    from tools.models.character import TextCharacterProfile
    from tools.models.context_package import (
        GenerationContext,
        ReviewContext,
        ReviewResult,
        StylistContext,
    )
    from tools.models.outline import (
        ChapterOutline,
        OutlineHierarchy,
    )
    from tools.queries.outline_query import OutlineQuery
    from tools.utils.progressive_compressor import ProgressiveCompressor
    from tools.world_graph_manager import WorldGraphManager
except ImportError:  # pragma: no cover
    from agents.librarian import LibrarianAgent
    from agents.lore_checker import LoreCheckerAgent
    from agents.stylist import StylistAgent
    from character_state_manager import CharacterStateManager
    from graph.foreshadowing_dag import ForeshadowingDAGManager
    from models.character import TextCharacterProfile
    from models.context_package import (
        GenerationContext,
        ReviewContext,
        ReviewResult,
        StylistContext,
    )
    from models.outline import (
        ChapterOutline,
        OutlineHierarchy,
    )
    from queries.outline_query import OutlineQuery
    from utils.progressive_compressor import ProgressiveCompressor
    from world_graph_manager import WorldGraphManager


@dataclass
class PipelineStage:
    """Single stage result in the pipeline."""

    name: str
    status: str = "pending"  # pending/running/completed/failed
    message: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""


@dataclass
class PipelineResult:
    """Full pipeline execution result."""

    novel_id: str
    chapter_id: str
    draft_text: str = ""
    polished_text: str = ""
    review: Optional[ReviewResult] = None
    stages: List[PipelineStage] = field(default_factory=list)
    needs_user_review: bool = False
    user_approved: bool = False
    generation_context: Optional[GenerationContext] = None

    @property
    def passed(self) -> bool:
        return self.review is not None and self.review.passed

    @property
    def has_severe_errors(self) -> bool:
        return self.review is not None and self.review.severity == "severe"


class PipelineSimulatorV2:
    """New simplified pipeline: Director -> Writer -> Reviewer -> User -> Stylist."""

    def __init__(
        self,
        project_dir: Path,
        novel_id: str,
        style_id: str = "",
        llm_client: Optional["LLMClient"] = None,
        router: Optional["ModelRouter"] = None,
    ):
        self.project_dir = project_dir
        self.novel_id = novel_id
        self.style_id = style_id
        self._llm_client = llm_client
        self._router = router

        self.base_dir = project_dir / "data" / "novels" / novel_id
        self.drafts_dir = self.base_dir / "manuscript" / "drafts"
        self.logs_dir = project_dir / "logs" / "pipeline_v2"
        self.drafts_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        # Managers
        self.char_mgr = CharacterStateManager(
            project_dir=project_dir, novel_id=novel_id
        )
        self.outline_query = OutlineQuery(project_dir=project_dir, novel_id=novel_id)
        self.fs_mgr = ForeshadowingDAGManager(
            project_dir=project_dir, novel_id=novel_id
        )
        self.world_mgr = WorldGraphManager(project_dir=project_dir, novel_id=novel_id)
        self.compressor = ProgressiveCompressor(
            project_dir=project_dir, novel_id=novel_id
        )

        # Agents (reuse existing implementations)
        self.writer = LibrarianAgent(llm_client=llm_client, router=router)
        self.reviewer = LoreCheckerAgent(llm_client=llm_client, router=router)
        self.stylist = StylistAgent(
            project_root=project_dir,
            novel_id=novel_id,
            llm_client=llm_client,
            router=router,
        )

    # -- Stage 1: Director (context assembly) --

    def assemble_context(
        self,
        chapter: ChapterOutline,
        hierarchy: OutlineHierarchy,
        writing_prompt: str = "",
    ) -> GenerationContext:
        """Stage 1: Director assembles rich GenerationContext."""
        # Gather manuscript text for recent_text extraction
        manuscript_text = self._load_manuscript_up_to(chapter.chapter_id)

        # Gather character profiles (non-cannon-fodder only)
        characters = self._gather_characters(chapter.involved_characters)

        # Gather foreshadowing context
        foreshadowing_text = self._gather_foreshadowing(chapter.foreshadowing_refs)

        # Gather setting context
        setting_text = self._gather_settings(chapter.involved_settings)

        # Gather style guide
        style_guide = self._load_style_guide()

        return self.compressor.build_generation_context(
            chapter=chapter,
            hierarchy=hierarchy,
            manuscript_text=manuscript_text,
            characters=characters,
            foreshadowing_text=foreshadowing_text,
            setting_text=setting_text,
            style_guide=style_guide,
            writing_prompt=writing_prompt,
        )

    # -- Stage 2: Writer (chapter generation) --

    def generate_chapter(
        self,
        context: GenerationContext,
    ) -> str:
        """Stage 2: Writer generates chapter draft from rich context."""
        # Build context dict for existing LibrarianAgent interface
        ctx_dict = context.to_prompt_sections()
        flat_context: Dict[str, str] = {}
        for key, value in ctx_dict.items():
            flat_context[key] = value

        output = self.writer.generate_chapter(
            chapter_id=context.chapter_id,
            objective="\n".join(context.chapter_goals)
            if context.chapter_goals
            else "continue",
            context=flat_context,
        )
        return output.draft

    # -- Stage 3: Reviewer (consistency check, read-only) --

    def review_draft(
        self,
        draft_text: str,
        context: GenerationContext,
        strict: bool = False,
    ) -> ReviewResult:
        """Stage 3: Reviewer checks consistency. Read-only.

        Only severe errors trigger rewrite.
        Mild issues are shown to user for confirmation.
        """
        # Use existing LoreChecker
        lore_result = self.reviewer.check_draft(
            draft=draft_text,
            forbidden=[],
            required=[],
            chapter_annotations={},
            character_state_manager=self.char_mgr,
            strict=strict,
        )

        # Cross-chapter check
        cross_check = self.reviewer.check_cross_chapter(
            chapter_id=context.chapter_id,
            character_state_manager=self.char_mgr,
            foreshadowing_manager=self.fs_mgr,
            strict=strict,
        )

        all_errors = lore_result.errors + cross_check.errors
        all_warnings = lore_result.warnings + cross_check.warnings

        # Classify severity
        if all_errors:
            severity = "severe"
            passed = False
        elif all_warnings:
            severity = "mild"
            passed = True  # mild issues don't block, user decides
        else:
            severity = "none"
            passed = True

        return ReviewResult(
            passed=passed,
            severity=severity,
            errors=all_errors,
            warnings=all_warnings,
            suggestions=[],
        )

    # -- Stage 4: User review (handled externally via API) --

    # -- Stage 5: Stylist (final polish) --

    def polish_draft(
        self,
        draft_text: str,
        context: GenerationContext,
    ) -> str:
        """Stage 5: Stylist polishes the draft after user confirmation."""
        result = self.stylist.polish(
            draft_text,
            banned_phrases=[],
            novel_id=self.novel_id,
        )
        return result.text

    # -- Full pipeline (non-interactive, for testing/CLI) --

    def run_pipeline(
        self,
        chapter: ChapterOutline,
        hierarchy: OutlineHierarchy,
        writing_prompt: str = "",
        strict_review: bool = False,
        max_rewrites: int = 1,
        auto_approve: bool = False,
        use_stylist: bool = False,
    ) -> PipelineResult:
        """Run the full pipeline end-to-end.

        For web UI, use individual stage methods instead.
        """
        stages: List[PipelineStage] = []
        result = PipelineResult(
            novel_id=self.novel_id,
            chapter_id=chapter.chapter_id,
        )

        # Stage 1: Assemble context
        stage1 = PipelineStage(
            name="director", status="running", timestamp=datetime.now().isoformat()
        )
        context = self.assemble_context(chapter, hierarchy, writing_prompt)
        result.generation_context = context
        stage1.status = "completed"
        stage1.message = f"context assembled, ~{context.estimate_token_count()} tokens"
        stages.append(stage1)

        # Stage 2: Generate
        stage2 = PipelineStage(
            name="writer", status="running", timestamp=datetime.now().isoformat()
        )
        draft_text = self.generate_chapter(context)
        result.draft_text = draft_text
        stage2.status = "completed"
        stage2.message = f"draft generated, {len(draft_text)} chars"
        stages.append(stage2)

        # Stage 3: Review (with rewrite loop for severe errors)
        rewrite_count = 0
        while True:
            stage3 = PipelineStage(
                name=f"reviewer{'_retry' + str(rewrite_count) if rewrite_count else ''}",
                status="running",
                timestamp=datetime.now().isoformat(),
            )
            review = self.review_draft(draft_text, context, strict=strict_review)
            result.review = review
            stage3.data = {
                "severity": review.severity,
                "errors": review.errors,
                "warnings": review.warnings,
            }

            if review.severity != "severe" or rewrite_count >= max_rewrites:
                stage3.status = "completed"
                stage3.message = f"review done: {review.severity}"
                stages.append(stage3)
                break

            # Severe error -> rewrite
            stage3.status = "completed"
            stage3.message = (
                f"severe errors found, rewriting (attempt {rewrite_count + 1})"
            )
            stages.append(stage3)

            rewrite_count += 1
            ctx_dict = context.to_prompt_sections()
            rewritten = self.writer.rewrite_chapter(
                chapter_id=context.chapter_id,
                objective="\n".join(context.chapter_goals)
                if context.chapter_goals
                else "continue",
                context=ctx_dict,
                previous_draft=draft_text,
                forbidden=[],
                required=[],
                errors=review.errors,
                warnings=review.warnings,
                attempt=rewrite_count,
            )
            if rewritten.draft == draft_text:
                break
            draft_text = rewritten.draft
            result.draft_text = draft_text

        # Stage 4: User review
        if review.severity == "mild" and not auto_approve:
            result.needs_user_review = True
            stage4 = PipelineStage(
                name="user_review",
                status="waiting",
                message="mild issues found, awaiting user confirmation",
                timestamp=datetime.now().isoformat(),
                data={"warnings": review.warnings},
            )
            stages.append(stage4)
        else:
            result.user_approved = True

        # Stage 5: Stylist (only if approved and requested)
        if use_stylist and (auto_approve or result.user_approved):
            stage5 = PipelineStage(
                name="stylist", status="running", timestamp=datetime.now().isoformat()
            )
            polished = self.polish_draft(draft_text, context)
            result.polished_text = polished
            stage5.status = "completed"
            stage5.message = f"polished, {len(polished)} chars"
            stages.append(stage5)

        result.stages = stages

        # Save draft
        final_text = result.polished_text or result.draft_text
        draft_file = self.drafts_dir / f"{chapter.chapter_id}_draft.md"
        draft_file.write_text(final_text, encoding="utf-8")

        # Save pipeline log
        self._save_log(result)

        return result

    # -- Internal helpers --

    def _load_manuscript_up_to(self, chapter_id: str) -> str:
        """Load all manuscript text up to (not including) the given chapter."""
        drafts = sorted(self.drafts_dir.glob("*_draft.md"))
        parts: List[str] = []
        for draft_path in drafts:
            if chapter_id in draft_path.stem:
                break
            parts.append(draft_path.read_text(encoding="utf-8"))
        return "\n\n".join(parts)

    def _gather_characters(
        self, character_ids: List[str]
    ) -> List[TextCharacterProfile]:
        """Load TextCharacterProfile for non-cannon-fodder characters."""
        profiles: List[TextCharacterProfile] = []
        for char_id in character_ids:
            try:
                card = self.char_mgr.get_character_card(character_id=char_id)
                if card.static.tier in ("主角", "重要配角", "配角"):
                    profiles.append(TextCharacterProfile.from_legacy_card(card))
            except (FileNotFoundError, ValueError):
                continue
        return profiles

    def _gather_foreshadowing(self, refs: List[str]) -> str:
        """Gather foreshadowing context for given refs."""
        if not refs:
            # Fall back to pending foreshadowings
            pending = self.fs_mgr.get_pending_nodes(min_weight=1)
            if not pending:
                return ""
            lines = []
            for item in pending[:8]:
                nid = item.get("id", "")
                weight = item.get("weight", 0)
                layer = item.get("layer", "")
                lines.append(f"{nid}(weight={weight}, layer={layer})")
            return "; ".join(lines)

        lines = []
        for ref_id in refs:
            nodes = self.fs_mgr.get_pending_nodes(min_weight=1)
            for node in nodes:
                if node.get("id") == ref_id:
                    lines.append(
                        f"{ref_id}(weight={node.get('weight', 0)}, "
                        f"layer={node.get('layer', '')})"
                    )
                    break
        return "; ".join(lines) if lines else ""

    def _gather_settings(self, setting_refs: List[str]) -> str:
        """Gather world/setting context."""
        if not setting_refs:
            return self.world_mgr.summary(max_entities=6, max_relations=8)
        # If specific settings referenced, try to find them
        parts: List[str] = []
        for ref in setting_refs:
            entities = self.world_mgr.list_entities()
            for e in entities:
                if ref in e.name or ref == e.id:
                    parts.append(f"{e.name}: {e.description}")
                    break
        return (
            "; ".join(parts)
            if parts
            else self.world_mgr.summary(max_entities=6, max_relations=8)
        )

    def _load_style_guide(self) -> str:
        """Load composed style document if available."""
        composed_dir = self.project_dir / "composed"
        composed_file = composed_dir / f"{self.novel_id}_composed.md"
        if composed_file.exists():
            text = composed_file.read_text(encoding="utf-8")
            return text[:2000]  # cap style guide length
        return ""

    def _save_log(self, result: PipelineResult) -> None:
        """Save pipeline execution log."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = self.logs_dir / f"{timestamp}_{result.chapter_id}.yaml"
        log_data = {
            "timestamp": datetime.now().isoformat(),
            "novel_id": result.novel_id,
            "chapter_id": result.chapter_id,
            "draft_length": len(result.draft_text),
            "polished_length": len(result.polished_text),
            "review": result.review.model_dump() if result.review else None,
            "needs_user_review": result.needs_user_review,
            "user_approved": result.user_approved,
            "stages": [
                {
                    "name": s.name,
                    "status": s.status,
                    "message": s.message,
                    "timestamp": s.timestamp,
                }
                for s in result.stages
            ],
        }
        with log_file.open("w", encoding="utf-8") as f:
            yaml.safe_dump(log_data, f, allow_unicode=True, sort_keys=False)
