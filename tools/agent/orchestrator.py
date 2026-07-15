"""Deterministic book-level orchestrator for ``openwrite agent``."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

from ..context_builder import ContextBuilder
from ..frontmatter import parse_toml_front_matter
from ..source_sync import run_sync
from ..style_synthesizer import render_style_manifest_summary
from ..story_planning import StoryPlanningStore
from ..utils import parse_chapter_id
from ..workflow_scheduler import WorkflowScheduler
from .toolkits import ORCHESTRATOR_TOOLKIT, WRITING_TOOLKIT
from .book_state import BookStage, BookState, BookStateStore


@dataclass(frozen=True)
class OrchestratorResult:
    message: str
    stage: BookStage
    blocked: bool
    next_action: str


@dataclass(frozen=True)
class WriteRequest:
    chapter_id: str
    guidance: str = ""
    target_words: int = 0


@dataclass(frozen=True)
class ReviewRequest:
    chapter_id: str
    guidance: str = ""


class OpenWriteOrchestrator:
    """Book-level deterministic orchestrator."""

    def __init__(
        self,
        project_root: Path,
        novel_id: str,
        state_store: Optional[BookStateStore] = None,
        planning_store: Optional[StoryPlanningStore] = None,
        tool_executors: Optional[dict[str, Callable[[dict[str, Any]], dict[str, Any]]]] = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.novel_id = novel_id
        self.state_store = state_store or BookStateStore(self.project_root, novel_id)
        self.story_planning_store = planning_store or StoryPlanningStore(
            self.project_root, novel_id
        )
        self.tool_executors = dict(tool_executors or {})
        self.state = BookState(novel_id=novel_id)

    @classmethod
    def for_testing(
        cls,
        project_root: Path,
        novel_id: str,
        state_store: Optional[BookStateStore] = None,
        planning_store: Optional[StoryPlanningStore] = None,
        tool_executors: Optional[dict[str, Callable[[dict[str, Any]], dict[str, Any]]]] = None,
    ) -> "OpenWriteOrchestrator":
        return cls(
            project_root=project_root,
            novel_id=novel_id,
            state_store=state_store,
            planning_store=planning_store,
            tool_executors=tool_executors,
        )

    def build_chapter_packet(self, chapter_id: str) -> dict[str, Any]:
        builder = ContextBuilder(self.project_root, self.novel_id)
        context = builder.build_generation_context(chapter_id)
        prompt_sections = context.to_prompt_sections()

        packet = {
            "novel_id": self.novel_id,
            "chapter_id": chapter_id,
            "author_intent": getattr(context, "author_intent", ""),
            "creative_focus": getattr(context, "creative_focus", ""),
            "story_background": self.story_planning_store.read_story_document(
                "background", max_chars=2000
            ),
            "foundation": self.story_planning_store.read_story_document(
                "foundation", max_chars=2000
            ),
            "previous_chapter_content": self._read_previous_chapter_content(chapter_id),
            "style_documents": self._build_style_documents(context, prompt_sections),
            "character_documents": self._build_character_documents(context),
            "concept_documents": self._build_concept_documents(context, prompt_sections),
            "prompt_sections": prompt_sections,
        }

        self._write_context_packet_snapshot(chapter_id, packet)
        return packet

    def run_preflight(self, chapter_id: str) -> dict[str, Any]:
        self.state = self.state_store.load_or_create()

        if self.state.stage != BookStage.CHAPTER_PREFLIGHT:
            return self._preflight_result(
                chapter_id=chapter_id,
                ok=False,
                reason="outline_not_confirmed",
                missing_items=["outline_scope"],
            )

        context = ContextBuilder(self.project_root, self.novel_id).build_generation_context(
            chapter_id
        )
        if not context.current_chapter:
            return self._preflight_result(
                chapter_id=chapter_id,
                ok=False,
                reason="missing_chapter_scope",
                missing_items=[chapter_id],
            )

        previous_chapter_id = self._previous_chapter_id(chapter_id)
        previous_chapter_content = ""
        missing_items: list[str] = []
        if previous_chapter_id:
            previous_chapter_content = self._read_previous_chapter_content(chapter_id)
            if not previous_chapter_content:
                missing_items.append(previous_chapter_id)

        if chapter_id != "ch_001" and not previous_chapter_content:
            return self._preflight_result(
                chapter_id=chapter_id,
                ok=False,
                reason="missing_previous_chapter",
                missing_items=missing_items or [previous_chapter_id],
            )

        packet = self.build_chapter_packet(chapter_id)
        return {
            "ok": True,
            "chapter_id": chapter_id,
            "reason": "",
            "missing_items": [],
            "packet": packet,
        }

    def summarize_ideation(self) -> OrchestratorResult:
        self.state = self.state_store.load_or_create()
        return self._ensure_ideation_summary_confirmation(blocked=False)

    def confirm_ideation_summary(self, text: str = "这个汇总可以") -> OrchestratorResult:
        self.state = self.state_store.load_or_create()
        return self._handle_ideation_summary_confirmation(text)

    def generate_outline_draft(self, request_text: str) -> OrchestratorResult:
        self.state = self.state_store.load_or_create()
        return self._handle_outline_generation(request_text)

    def run_chapter_preflight(self, chapter_id: str) -> dict[str, Any]:
        return self.run_preflight(chapter_id)

    def review_chapter(self, chapter_id: str, guidance: str = "") -> dict[str, Any]:
        self.state = self.state_store.load_or_create()
        try:
            executor = self._get_orchestrator_executor("review_chapter")
            result = self._normalize_review_result(
                executor(
                    {
                        "chapter_id": chapter_id,
                        "guidance": guidance,
                    }
                )
            )
            if result.get("error") or not result.get("ok", True):
                raise RuntimeError(result.get("error", "review_failed"))
        except Exception as exc:
            self.state.blocking_reason = "review_failed"
            self.state.last_agent_action = "reviewed_chapter_failed"
            self.state_store.save(self.state)
            return {
                "ok": False,
                "chapter_id": chapter_id,
                "reason": str(exc) or exc.__class__.__name__,
                "passed": False,
            }

        self.state.blocking_reason = ""
        self.state.last_agent_action = "reviewed_chapter"
        self.state_store.save(self.state)
        normalized = dict(result)
        normalized.setdefault("chapter_id", chapter_id)
        return normalized

    def delegate_writing(
        self,
        chapter_id: str,
        preflight_result: Optional[dict[str, Any]] = None,
        guidance: str = "",
        target_words: int = 0,
    ) -> dict[str, Any]:
        self.state = self.state_store.load_or_create()
        packet_result = preflight_result or self.run_preflight(chapter_id)
        if not packet_result.get("ok"):
            return {
                "ok": False,
                "chapter_id": chapter_id,
                "reason": packet_result.get("reason", "preflight_failed"),
                "missing_items": packet_result.get("missing_items", []),
                "next_stage": self.state.stage.value,
                "next_action": "preflight_failed",
            }

        packet = packet_result["packet"]
        scheduler = WorkflowScheduler(self.project_root, self.novel_id)
        workflow = scheduler.load_or_create(chapter_id)
        active_stage = "writing"
        try:
            scheduler.start_stage(workflow, "context_assembly")
            scheduler.complete_stage(
                workflow,
                "context_assembly",
                message="chapter packet assembled",
                data={"chapter_id": chapter_id},
            )
            scheduler.start_stage(workflow, "writing")

            executor = self._get_writing_executor("write_chapter")
            raw_result = executor(
                {
                    "chapter_id": chapter_id,
                    "packet": packet,
                    "context_packet": packet,
                    "prompt_sections": packet["prompt_sections"],
                    "guidance": guidance,
                    "target_words": target_words,
                }
            )
            result = self._normalize_write_result(raw_result)
            if result.get("error") or not result.get("ok"):
                raise RuntimeError(result.get("error", "write_chapter_failed"))

            draft_path = self._sanitize_draft_path(result.get("draft_path", ""))
            scheduler.complete_stage(
                workflow,
                "writing",
                message="chapter written",
                data={"draft_path": draft_path},
            )

            review_result = None
            review_executor = self._get_optional_orchestrator_executor("review_chapter")
            if review_executor is not None:
                active_stage = "review"
                scheduler.start_stage(workflow, "review")
                raw_review = review_executor({"chapter_id": chapter_id, "guidance": guidance})
                review_result = self._normalize_review_result(raw_review)
                if review_result.get("error") or not review_result.get("ok", True):
                    raise RuntimeError(review_result.get("error", "review_chapter_failed"))
                scheduler.complete_stage(
                    workflow,
                    "review",
                    message="chapter reviewed",
                    data={"passed": bool(review_result.get("passed", False))},
                )

            self.state.current_chapter = chapter_id
            if review_result is None:
                self.state.stage = BookStage.REVIEW_AND_REVISE
                self.state.blocking_reason = "review_not_run"
                self.state.last_agent_action = "delegated_writing_pending_review"
                next_stage = BookStage.REVIEW_AND_REVISE.value
                next_action = "manual_review"
            elif review_result.get("passed", False):
                self.state.stage = BookStage.CHAPTER_PREFLIGHT
                self.state.blocking_reason = ""
                self.state.last_agent_action = "delegated_writing_review_passed"
                next_stage = BookStage.CHAPTER_PREFLIGHT.value
                next_action = "ready_for_next_chapter"
            else:
                self.state.stage = BookStage.REVIEW_AND_REVISE
                self.state.blocking_reason = "review_revision_requested"
                self.state.last_agent_action = "delegated_writing_review_failed"
                next_stage = BookStage.REVIEW_AND_REVISE.value
                next_action = "review_and_revise"
            self.state_store.save(self.state)

            return {
                "ok": True,
                "chapter_id": chapter_id,
                "reason": "",
                "next_stage": next_stage,
                "next_action": next_action,
                "workflow_stage": scheduler.load_workflow(chapter_id).current_stage,
                "review": review_result,
            }
        except Exception as exc:
            error = str(exc) or exc.__class__.__name__
            try:
                scheduler.fail_stage(workflow, active_stage, error)
            except Exception:
                self._persist_failed_workflow(
                    scheduler=scheduler,
                    workflow=workflow,
                    stage_name=active_stage,
                    error=error,
                )
            self.state.blocking_reason = f"{active_stage}_failed"
            if active_stage == "review":
                self.state.stage = BookStage.REVIEW_AND_REVISE
                self.state.last_agent_action = "delegated_review_failed"
            else:
                self.state.last_agent_action = "delegated_writing_failed"
            self.state_store.save(self.state)
            return {
                "ok": False,
                "chapter_id": chapter_id,
                "reason": error,
                "next_stage": self.state.stage.value,
                "next_action": "writing_failed",
            }

    def handle_user_message(self, text: str) -> OrchestratorResult:
        self.state = self.state_store.load_or_create()

        if self._is_status_request(text):
            return self._handle_status_request()

        if self._is_negated_chapter_request(text):
            return self._ignored_result()

        if self._is_negated_foundation_confirmation(text):
            return self._ignored_result()

        if self._is_negated_outline_confirmation(text):
            return self._ignored_result()

        write_request = self._extract_write_request(text)
        if write_request:
            return self._handle_chapter_request(write_request)

        review_request = self._extract_review_request(text)
        if review_request:
            return self._handle_review_request(review_request)

        if self._looks_like_foundation_confirmation(text):
            return self._handle_foundation_confirmation()

        if self._looks_like_outline_confirmation(text):
            return self._handle_outline_confirmation()

        if self._looks_like_ideation_summary_request(text):
            return self._handle_ideation_summary_request(blocked=False)

        if self._looks_like_ideation_summary_confirmation(text):
            return self._handle_ideation_summary_confirmation(text)

        if self._looks_like_outline_generation_request(text):
            return self._handle_outline_generation(text)

        if self._looks_like_character_creation_request(text):
            return self._handle_character_creation(text)

        return self._handle_discovery(text)

    def run_cli(self, instruction: str, quiet: bool = False, max_turns: int = 20) -> int:
        """Run a deterministic CLI interaction."""
        _ = max_turns

        if self._is_status_request(instruction):
            result = self._handle_status_request()
        else:
            result = self.handle_user_message(instruction)
        if not quiet:
            print(result.message)

        write_request = self._extract_write_request(instruction)
        if write_request and result.next_action == "chapter_preflight" and not result.blocked:
            preflight = self.run_preflight(write_request.chapter_id)
            if not quiet:
                print(self._format_cli_preflight_message(write_request.chapter_id, preflight))
            if not preflight.get("ok"):
                return 1

            delegate = self.delegate_writing(
                write_request.chapter_id,
                preflight_result=preflight,
                guidance=write_request.guidance,
                target_words=write_request.target_words,
            )
            if not quiet:
                print(self._format_cli_delegate_message(write_request.chapter_id, delegate))
            return 0 if delegate.get("ok") else 1

        return 0 if not result.blocked else 1

    def _handle_discovery(self, text: str) -> OrchestratorResult:
        self.story_planning_store.append_ideation(text)
        self.state.last_agent_action = "recorded_ideation"
        self.state.blocking_reason = ""
        self.state_store.save(self.state)
        return OrchestratorResult(
            message="收到。请继续补充更多背景或基础设定，我会先整理立项信息。",
            stage=self.state.stage,
            blocked=False,
            next_action="request_more_background",
        )

    def _handle_ideation_summary_request(self, *, blocked: bool) -> OrchestratorResult:
        return self._ensure_ideation_summary_confirmation(blocked=blocked)

    def _handle_ideation_summary_confirmation(self, text: str) -> OrchestratorResult:
        if self.state.pending_confirmation != "ideation_summary":
            return self._stage_blocked_result(
                "当前没有待确认的想法汇总，我先保持现状。",
                next_action="ignore",
            )

        self.state.pending_confirmation = ""
        self.state.blocking_reason = ""
        self.state.last_agent_action = "confirmed_ideation_summary"
        if self.state.stage == BookStage.DISCOVERY:
            self.state.stage = BookStage.FOUNDATION
        self.state_store.save(self.state)

        if self._looks_like_outline_generation_request(text):
            return self._handle_outline_generation(text)

        return OrchestratorResult(
            message="已确认当前想法汇总。下一步可以继续补基础设定，或让我开始整理大纲。",
            stage=self.state.stage,
            blocked=False,
            next_action="ready_for_outline_generation",
        )

    def _ignored_result(self) -> OrchestratorResult:
        return OrchestratorResult(
            message="收到。当前指令是否定表达，我先不推进流程。",
            stage=self.state.stage,
            blocked=True,
            next_action="ignore",
        )

    def _is_status_request(self, text: str) -> bool:
        normalized = re.sub(r"\s+", "", text).lower()
        if normalized in {"查看项目状态", "查看状态", "查看当前状态", "status"}:
            return True
        return (
            ("状态" in text or "进度" in text)
            and any(token in text for token in ("查看", "当前", "项目", "现在", "目前"))
        )

    def _handle_status_request(self) -> OrchestratorResult:
        state = self._snapshot_state()
        current_chapter = state.current_chapter or "未指定"
        return OrchestratorResult(
            message=f"当前状态: {state.stage.value}，当前章节: {current_chapter}",
            stage=state.stage,
            blocked=False,
            next_action="report_status",
        )

    def _snapshot_state(self) -> BookState:
        if self.state_store.path.exists():
            try:
                return self.state_store.load_or_create()
            except Exception:
                pass
        return BookState(novel_id=self.novel_id)

    def _format_cli_preflight_message(self, chapter_id: str, result: dict[str, Any]) -> str:
        if result.get("ok"):
            return f"章节预检通过: {chapter_id}"

        reason = result.get("reason", "preflight_failed")
        missing_items = result.get("missing_items", [])
        if missing_items:
            missing_text = ", ".join(str(item) for item in missing_items)
            return f"章节预检失败: {chapter_id} ({reason}; missing: {missing_text})"
        return f"章节预检失败: {chapter_id} ({reason})"

    def _format_cli_delegate_message(self, chapter_id: str, result: dict[str, Any]) -> str:
        if result.get("ok"):
            review = result.get("review") or {}
            if review:
                if review.get("passed", False):
                    return f"章节已完成并通过审查: {chapter_id}"
                score = review.get("score")
                if score is not None:
                    return f"章节已生成但审查未通过: {chapter_id} (score={score})"
                return f"章节已生成但审查未通过: {chapter_id}"
            return f"章节已委派: {chapter_id}"

        reason = result.get("reason", "writing_failed")
        return f"章节委派失败: {chapter_id} ({reason})"

    def _handle_foundation_confirmation(self) -> OrchestratorResult:
        if self.state.stage not in {BookStage.DISCOVERY, BookStage.FOUNDATION}:
            return self._stage_blocked_result(
                "当前不在基础设定确认阶段，我先不推进基础设定升格。",
                next_action="ignore",
            )
        if not self.story_planning_store.promote_foundation():
            self.state.blocking_reason = "missing_foundation_drafts"
            self.state.last_agent_action = "blocked_foundation_promotion_missing_drafts"
            self.state_store.save(self.state)
            return OrchestratorResult(
                message="基础设定文档缺失。请先准备 src/story/background.md 与 src/story/foundation.md。",
                stage=self.state.stage,
                blocked=True,
                next_action="prepare_foundation_documents",
            )

        self.state.stage = BookStage.ROLLING_OUTLINE
        self.state.pending_confirmation = "outline_scope"
        self.state.blocking_reason = ""
        self.state.last_agent_action = "requested_outline_confirmation"
        self.state_store.save(self.state)
        return OrchestratorResult(
            message="基础设定已确认并升格。请确认可写的大纲范围后再进入章节编写。",
            stage=self.state.stage,
            blocked=False,
            next_action="request_outline_confirmation",
        )

    def _handle_outline_confirmation(self) -> OrchestratorResult:
        if self.state.stage != BookStage.ROLLING_OUTLINE:
            return self._stage_blocked_result(
                "当前不在大纲确认阶段，我先不推进章节写作。",
                next_action="ignore",
            )
        if self.state.pending_confirmation != "outline_scope":
            return self._stage_blocked_result(
                "当前没有待确认的大纲范围，我先保持现状。",
                next_action="ignore",
            )
        if not self.story_planning_store.promote_outline(confirmed=True):
            self.state.blocking_reason = "missing_outline_draft"
            self.state.last_agent_action = "blocked_outline_promotion_missing_draft"
            self.state_store.save(self.state)
            return OrchestratorResult(
                message="大纲文档缺失。请先准备 src/outline.md。",
                stage=self.state.stage,
                blocked=True,
                next_action="prepare_outline_document",
            )

        self._sync_runtime_caches(sync_outline=True, sync_characters=False)
        self.state.stage = BookStage.CHAPTER_PREFLIGHT
        self.state.pending_confirmation = ""
        self.state.blocking_reason = ""
        self.state.last_agent_action = "promoted_outline"
        self.state_store.save(self.state)
        return OrchestratorResult(
            message="大纲范围已确认。下一步进入章节预检。",
            stage=self.state.stage,
            blocked=False,
            next_action="chapter_preflight",
        )

    def _handle_outline_generation(self, text: str) -> OrchestratorResult:
        if self.state.stage == BookStage.DISCOVERY:
            return self._ensure_ideation_summary_confirmation(blocked=True)

        if self.state.pending_confirmation == "ideation_summary" or (
            self._read_text(self.story_planning_store.ideation_path).strip()
            and not self.story_planning_store.ideation_summary_is_current()
        ):
            return self._ensure_ideation_summary_confirmation(blocked=True)

        try:
            outline = self._generate_outline_draft(text)
        except Exception as exc:
            return self._stage_blocked_result(
                f"大纲草案生成失败: {exc}",
                next_action="generate_outline_failed",
            )

        self.story_planning_store.save_outline_draft(outline)
        if self.state.stage in {
            BookStage.DISCOVERY,
            BookStage.FOUNDATION,
            BookStage.ROLLING_OUTLINE,
        }:
            self.state.stage = BookStage.ROLLING_OUTLINE
            self.state.pending_confirmation = "outline_scope"
            next_action = "request_outline_confirmation"
            message = "已生成大纲草案。请确认可写范围后再进入章节编写。"
        else:
            next_action = "review_outline_draft"
            message = "已生成新的大纲草案，但我没有切换当前流程状态。"
        self.state.blocking_reason = ""
        self.state.last_agent_action = "generated_outline_draft"
        self.state_store.save(self.state)
        return OrchestratorResult(
            message=message,
            stage=self.state.stage,
            blocked=False,
            next_action=next_action,
        )

    def _handle_character_creation(self, text: str) -> OrchestratorResult:
        try:
            content = self._generate_character_document(text)
            name = self._extract_generated_character_name(content)
            executor = self._get_orchestrator_executor("create_character")
            result = executor({"name": name, "content": content})
            if result.get("error"):
                raise RuntimeError(result["error"])
            self._sync_runtime_caches(sync_outline=False, sync_characters=True)
        except Exception as exc:
            return self._stage_blocked_result(
                f"角色创建失败: {exc}",
                next_action="create_character_failed",
            )

        self.state.blocking_reason = ""
        self.state.last_agent_action = "created_character"
        self.state_store.save(self.state)
        return OrchestratorResult(
            message=f"已创建角色 {name}，并同步角色卡缓存。",
            stage=self.state.stage,
            blocked=False,
            next_action="character_created",
        )

    def _handle_review_request(self, request: ReviewRequest) -> OrchestratorResult:
        try:
            executor = self._get_orchestrator_executor("review_chapter")
            result = self._normalize_review_result(
                executor(
                    {
                        "chapter_id": request.chapter_id,
                        "guidance": request.guidance,
                    }
                )
            )
            if result.get("error") or not result.get("ok", True):
                raise RuntimeError(result.get("error", "review_failed"))
        except Exception as exc:
            return self._stage_blocked_result(
                f"章节审查失败: {exc}",
                next_action="review_failed",
            )

        score = result.get("score")
        if score is not None:
            summary = (
                f"已审查 {request.chapter_id}，结果: "
                f"{'通过' if result.get('passed', False) else '未通过'}，得分 {score}。"
            )
        else:
            summary = (
                f"已审查 {request.chapter_id}，结果: "
                f"{'通过' if result.get('passed', False) else '未通过'}。"
            )
        self.state.blocking_reason = ""
        self.state.last_agent_action = "reviewed_chapter"
        self.state_store.save(self.state)
        return OrchestratorResult(
            message=summary,
            stage=self.state.stage,
            blocked=False,
            next_action="review_completed",
        )

    def _handle_chapter_request(self, request: WriteRequest) -> OrchestratorResult:
        if self.state.stage != BookStage.CHAPTER_PREFLIGHT:
            self.state.blocking_reason = "outline_not_confirmed"
            self.state.last_agent_action = "blocked_chapter_request_before_outline_confirmation"
            self.state_store.save(self.state)
            return OrchestratorResult(
                message="还不能写章节。请先确认大纲范围。",
                stage=self.state.stage,
                blocked=True,
                next_action="request_outline_confirmation",
            )

        self.state.current_chapter = request.chapter_id
        self.state.blocking_reason = ""
        self.state.last_agent_action = "recorded_current_chapter"
        self.state_store.save(self.state)
        message = f"已记录当前章节 {request.chapter_id}，下一步进入章节预检。"
        if request.guidance:
            message = f"已记录当前章节 {request.chapter_id} 和额外写作要求，下一步进入章节预检。"
        return OrchestratorResult(
            message=message,
            stage=self.state.stage,
            blocked=False,
            next_action="chapter_preflight",
        )

    def _extract_write_request(self, text: str) -> Optional[WriteRequest]:
        match = re.search(
            r"(?:开始写|写一下|写出|帮我写|请写|我要写|写)\s*"
            r"(?P<chapter>ch\s*_\s*\d{3}|第\s*[零一二三四五六七八九十百千万\d]+\s*章)",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            chapter_id = parse_chapter_id(re.sub(r"\s+", "", match.group("chapter")))
            if chapter_id:
                guidance = text[match.end() :].strip()
                guidance = re.sub(r"^[，,;；。:\s]+", "", guidance)
                target_words = self._extract_target_words(guidance)
                return WriteRequest(
                    chapter_id=chapter_id,
                    guidance=guidance,
                    target_words=target_words,
                )
        return None

    def _extract_chapter_request(self, text: str) -> Optional[str]:
        request = self._extract_write_request(text)
        return request.chapter_id if request else None

    def _extract_review_request(self, text: str) -> Optional[ReviewRequest]:
        match = re.search(
            r"(?:审查|复检|review)\s*"
            r"(?P<chapter>latest|最新章节|ch\s*_\s*\d{3}|第\s*[零一二三四五六七八九十百千万\d]+\s*章)",
            text,
            flags=re.IGNORECASE,
        )
        if not match:
            return None

        raw_chapter = re.sub(r"\s+", "", match.group("chapter"))
        if raw_chapter in {"latest", "最新章节"}:
            chapter_id = "latest"
        else:
            chapter_id = parse_chapter_id(raw_chapter)
        if not chapter_id:
            return None

        guidance = text[match.end() :].strip()
        guidance = re.sub(r"^[，,;；。:\s]+", "", guidance)
        return ReviewRequest(chapter_id=chapter_id, guidance=guidance)

    def _is_negated_chapter_request(self, text: str) -> bool:
        compact = re.sub(r"\s+", "", text)
        chapter = r"(?:第[零一二三四五六七八九十百千万\d]+章|ch_\d{3})"
        write = r"(?:写|开始写|帮我写|请写|我要写)"
        negation = r"(?:不要|别|先别|先不要)"
        return bool(
            re.search(fr"{negation}.{{0,6}}{write}.{{0,12}}{chapter}", compact)
            or re.search(fr"{write}.{{0,12}}{chapter}.{{0,6}}{negation}", compact)
            or re.search(fr"{chapter}.{{0,12}}{negation}.{{0,6}}{write}", compact)
        )

    def _looks_like_foundation_confirmation(self, text: str) -> bool:
        lowered = text.lower()
        foundation_terms = ("基础设定", "foundation", "背景")
        ready_terms = ("准备好了", "已准备好", "ready", "可以开始", "开始", "start")
        outline_terms = ("outline", "大纲", "提纲")
        return (
            any(term in lowered for term in ("基础设定准备好了", "基础设定好了", "foundation ready"))
            or (
                any(term in text for term in foundation_terms)
                and any(term in lowered for term in ready_terms)
                and any(term in lowered for term in outline_terms)
            )
            or ("开始 outline" in lowered)
            or ("开始提纲" in text)
            or ("开始大纲" in text)
        )

    def _is_negated_foundation_confirmation(self, text: str) -> bool:
        compact = re.sub(r"\s+", "", text.lower())
        return bool(
            re.search(
                r"(?:不要|别|先别|先不要|先不).{0,6}(?:开始|启动).{0,12}(?:outline|大纲|提纲)",
                compact,
            )
        )

    def _looks_like_outline_confirmation(self, text: str) -> bool:
        lowered = text.lower()
        if any(term in text for term in ("吗", "？", "?")):
            return False
        positive_patterns = (
            r"(?:大纲|范围|提纲).*(?:确认|确认好了|确认通过|可写|可以直接写|开始写|进入章节)",
            r"(?:确认|确定|同意).*(?:大纲|范围|提纲)",
            r"outline.*(?:confirm|confirmed|ready|go ahead)",
        )
        return any(re.search(pattern, lowered, flags=re.IGNORECASE) for pattern in positive_patterns)

    def _is_negated_outline_confirmation(self, text: str) -> bool:
        compact = re.sub(r"\s+", "", text.lower())
        outline = r"(?:大纲|范围|提纲|outline)"
        negation = r"(?:不要|别|先别|先不要|先不|不确认|不同意|不认可|不接受)"
        return bool(
            re.search(fr"{negation}.{{0,12}}{outline}", compact)
            or re.search(fr"{outline}.{{0,12}}{negation}", compact)
        )

    def _looks_like_outline_generation_request(self, text: str) -> bool:
        if any(token in text for token in ("确认", "确认好了", "确认通过", "可写")):
            return False
        if not any(token in text for token in ("大纲", "提纲", "四级大纲", "章节规划")):
            return False
        return any(token in text for token in ("生成", "创建", "设计", "规划", "整理", "来一份"))

    def _looks_like_ideation_summary_request(self, text: str) -> bool:
        if not any(token in text for token in ("汇总", "总结", "整理")):
            return False
        lowered = text.lower()
        return any(token in lowered for token in ("想法", "灵感", "设定", "idea", "脑洞", "思路"))

    def _looks_like_ideation_summary_confirmation(self, text: str) -> bool:
        if self.state.pending_confirmation != "ideation_summary":
            return False
        lowered = text.lower()
        return (
            any(token in lowered for token in ("汇总", "总结", "想法", "idea", "灵感"))
            and any(
                token in lowered
                for token in ("确认", "可以", "没问题", "同意", "行", "ok", "okay", "继续")
            )
        )

    def _looks_like_character_creation_request(self, text: str) -> bool:
        if "角色" not in text:
            return False
        return any(token in text for token in ("创建", "生成", "设计", "补一个", "增加一个", "来个"))

    def _extract_target_words(self, text: str) -> int:
        match = re.search(r"(?:字数|约|控制在)\s*(\d{3,5})", text)
        if not match:
            return 0
        try:
            return int(match.group(1))
        except ValueError:
            return 0

    def _get_orchestrator_executor(self, tool_name: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
        if tool_name not in ORCHESTRATOR_TOOLKIT:
            raise KeyError(f"Tool {tool_name} is not part of ORCHESTRATOR_TOOLKIT")
        if tool_name not in self.tool_executors:
            raise KeyError(f"Missing executor for {tool_name}")
        return self.tool_executors[tool_name]

    def _get_optional_orchestrator_executor(
        self, tool_name: str
    ) -> Optional[Callable[[dict[str, Any]], dict[str, Any]]]:
        if tool_name not in ORCHESTRATOR_TOOLKIT:
            return None
        return self.tool_executors.get(tool_name)

    def _get_writing_executor(self, tool_name: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
        if tool_name not in WRITING_TOOLKIT:
            raise KeyError(f"Tool {tool_name} is not part of WRITING_TOOLKIT")
        if tool_name not in self.tool_executors:
            raise KeyError(f"Missing executor for {tool_name}")
        return self.tool_executors[tool_name]

    def _stage_blocked_result(self, message: str, next_action: str) -> OrchestratorResult:
        return OrchestratorResult(
            message=message,
            stage=self.state.stage,
            blocked=True,
            next_action=next_action,
        )

    def _build_style_documents(
        self, context: Any, prompt_sections: dict[str, str]
    ) -> dict[str, str]:
        summary = ""
        if getattr(context, "style_profile", None) and hasattr(
            context.style_profile, "to_summary"
        ):
            summary = context.style_profile.to_summary(max_chars=1200)
        docs = {
            "summary": summary,
            "prompt_section": prompt_sections.get("风格指南", ""),
        }
        runtime_style_root = (
            self.project_root / "data" / "novels" / self.novel_id / "data" / "style"
        )
        composed_path = runtime_style_root / "composed.md"
        manifest_path = runtime_style_root / "manifest.toml"
        fingerprint_path = runtime_style_root / "fingerprint.yaml"
        if composed_path.exists():
            docs["work.composed"] = self._read_text(composed_path)
        if manifest_path.exists():
            docs["work.manifest"] = render_style_manifest_summary(self._read_text(manifest_path))
        if fingerprint_path.exists():
            docs["work.fingerprint"] = self._read_text(fingerprint_path)

        craft_root = self.project_root / "craft"
        for name in (
            "dialogue_craft.md",
            "scene_craft.md",
            "rhythm_craft.md",
            "humanization.yaml",
            "ai_patterns.yaml",
        ):
            path = craft_root / name
            if path.exists():
                docs[f"craft.{path.stem}"] = self._read_text(path)
        return docs

    def _build_character_documents(self, context: Any) -> list[str]:
        documents: list[str] = []
        for character in getattr(context, "active_characters", []):
            if hasattr(character, "to_context_text"):
                documents.append(character.to_context_text(max_chars=800))
            else:
                documents.append(str(character))
        return documents

    def _build_concept_documents(
        self, context: Any, prompt_sections: dict[str, str]
    ) -> dict[str, str]:
        return {
            "world_rules": prompt_sections.get("世界观", ""),
            "chapter_goals": prompt_sections.get("本章目标", ""),
            "current_state": getattr(context, "current_state", ""),
            "pending_hooks": getattr(context, "pending_hooks", ""),
            "ledger": getattr(context, "ledger", ""),
            "relationships": getattr(context, "relationships", ""),
            "chapter_summaries": getattr(context, "chapter_summaries", ""),
        }

    def _write_context_packet_snapshot(self, chapter_id: str, packet: dict[str, Any]) -> None:
        snapshot_dir = (
            self.project_root
            / "data"
            / "novels"
            / self.novel_id
            / "data"
            / "test_outputs"
            / "context_packets"
        )
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = snapshot_dir / f"{chapter_id}.yaml"
        snapshot_path.write_text(
            yaml.safe_dump(packet, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    def _read_text(self, path: Path) -> str:
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def _previous_chapter_id(self, chapter_id: str) -> str:
        match = re.search(r"(\d+)$", chapter_id)
        if not match:
            return ""
        chapter_num = int(match.group(1))
        if chapter_num <= 1:
            return ""
        return f"ch_{chapter_num - 1:03d}"

    def _read_previous_chapter_content(self, chapter_id: str) -> str:
        previous_chapter_id = self._previous_chapter_id(chapter_id)
        if not previous_chapter_id:
            return ""

        manuscript_dir = (
            self.project_root / "data" / "novels" / self.novel_id / "data" / "manuscript"
        )
        if not manuscript_dir.exists():
            return ""

        patterns = [
            f"{previous_chapter_id}.md",
            f"{previous_chapter_id}_*.md",
            f"chapter_{previous_chapter_id.split('_')[-1]}.md",
        ]
        for pattern in patterns:
            matches = sorted(manuscript_dir.rglob(pattern))
            if matches:
                return self._read_text(matches[0])
        return ""

    def _preflight_result(
        self,
        chapter_id: str,
        ok: bool,
        reason: str,
        missing_items: list[str],
    ) -> dict[str, Any]:
        return {
            "ok": ok,
            "chapter_id": chapter_id,
            "reason": reason,
            "missing_items": missing_items,
            "packet": None,
        }

    def _normalize_write_result(self, result: Any) -> dict[str, Any]:
        if not isinstance(result, dict):
            raise TypeError("write_chapter returned invalid response")
        return result

    def _normalize_review_result(self, result: Any) -> dict[str, Any]:
        if not isinstance(result, dict):
            raise TypeError("review_chapter returned invalid response")
        normalized = dict(result)
        normalized.setdefault("ok", "error" not in normalized)
        normalized.setdefault("passed", bool(normalized.get("ok")))
        return normalized

    def _generate_outline_draft(self, request_text: str) -> str:
        story_title = self._current_story_title()
        context = self._build_story_context()
        system_prompt = """你是 OpenWrite 的小说规划师。

请输出一份可直接落盘的四级 Markdown 大纲草案，只输出 Markdown，不要解释，不要代码围栏。

格式要求：
- `# 作品名`
- 总纲标题下先给 1-2 段故事简介，说明主角、核心冲突和整本书的大方向
- `## 第X篇：篇标题`
- `### 第X节：节标题`
- `#### 第X章：章标题`
- 每篇至少包含：
  > 篇弧线:
  > 篇情感:
- 每节至少包含：
  > 节结构:
  > 节情感:
  > 节张力:
- 每章至少包含：
  > 内容焦点:
  > 预估字数:
  > 出场角色:

约束：
- 输出 2-3 篇，每篇 2-3 节，每节 2-3 章
- 采用滚动大纲思路，优先保证前半段可写
- 保持中文网文风格，信息具体，不写空泛套话"""
        user_prompt = (
            f"项目名：{story_title}\n"
            f"用户请求：{request_text}\n\n"
            f"已有设定：\n{context}"
        )
        return self._strip_code_fences(
            self._chat_text(system_prompt, user_prompt, temperature=0.6, max_tokens=6000)
        )

    def _generate_ideation_summary(self) -> str:
        ideation = self._read_text(self.story_planning_store.ideation_path).strip()
        if not ideation:
            raise RuntimeError("缺少可汇总的 ideation 内容")
        story_title = self._current_story_title()
        system_prompt = """你是 OpenWrite 的立项整理助手。

请把用户目前的零散想法整理成一份可确认的 Markdown 汇总，只输出 Markdown，不要解释，不要代码围栏。

结构要求：
- `# 当前想法汇总`
- `## 核心方向`
- `## 稳定共识`
- `## 待确认点`
- `## 开放问题`
- `## 下一步建议`

约束：
- 只根据已有想法归纳，不要硬造细节
- 语言要清楚，便于作者确认
- 如果信息不足，要明确写在“待确认点”或“开放问题”里"""
        user_prompt = f"项目名：{story_title}\n\n当前灵感记录：\n{ideation}"
        return self._strip_code_fences(
            self._chat_text(system_prompt, user_prompt, temperature=0.4, max_tokens=3000)
        )

    def _generate_character_document(self, request_text: str) -> str:
        story_title = self._current_story_title()
        context = self._build_story_context()
        system_prompt = """你是 OpenWrite 的角色设计师。

请输出一个可直接保存到 `src/characters/*.md` 的角色文档，只输出 Markdown，不要解释，不要代码围栏。

格式要求：
- 使用 TOML front matter
- front matter 至少包含：id, name, tier, summary, tags
- 正文至少包含：
  # 角色名
  ## 背景
  ## 外貌
  ## 性格
  ## 与主角关系
  ## 说话风格
  ## 当前戏剧用途

约束：
- 如果用户没有提供名字，请自行起一个贴合题材的中文名
- 内容要和已有世界观、主角气质、冲突方向相容
- 如果用户提到关系约束，必须写进正文和 related 关系里"""
        user_prompt = (
            f"项目名：{story_title}\n"
            f"角色需求：{request_text}\n\n"
            f"已有设定：\n{context}"
        )
        return self._strip_code_fences(
            self._chat_text(system_prompt, user_prompt, temperature=0.7, max_tokens=4000)
        )

    def _chat_text(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float,
        max_tokens: int,
    ) -> str:
        from ..llm import LLMClient, LLMConfig, Message

        config = LLMConfig.from_env()
        client = LLMClient(config)
        response = client.chat(
            messages=[
                Message("system", system_prompt),
                Message("user", user_prompt),
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        content = response.content.strip()
        if not content:
            raise RuntimeError("LLM returned empty content")
        return content

    def _build_story_context(self) -> str:
        parts: list[str] = []
        background = self.story_planning_store.read_story_document("background", max_chars=1800)
        foundation = self.story_planning_store.read_story_document("foundation", max_chars=1800)
        ideation_summary = self.story_planning_store.read_ideation_summary(max_chars=1800)
        ideation = self._read_text(self.story_planning_store.ideation_path)[:1200]
        if background:
            parts.append(f"## 背景\n{background}")
        if foundation:
            parts.append(f"## 基础设定\n{foundation}")
        if ideation_summary and self.story_planning_store.ideation_summary_is_current():
            parts.append(f"## 当前想法汇总\n{ideation_summary}")
        elif ideation:
            parts.append(f"## 灵感记录\n{ideation}")
        return "\n\n".join(parts).strip() or "暂无现成设定，请根据用户请求自行补足。"

    def _ensure_ideation_summary_confirmation(self, *, blocked: bool) -> OrchestratorResult:
        ideation = self._read_text(self.story_planning_store.ideation_path).strip()
        if not ideation:
            return OrchestratorResult(
                message="当前还没有可整理的想法记录。请先继续补充灵感和设定方向。",
                stage=self.state.stage,
                blocked=True,
                next_action="request_more_background",
            )

        if (
            self.state.pending_confirmation == "ideation_summary"
            and self.story_planning_store.ideation_summary_is_current()
        ):
            return OrchestratorResult(
                message="当前想法汇总已整理完成。请先确认这版汇总，再继续生成或修改大纲。",
                stage=self.state.stage,
                blocked=True if blocked else False,
                next_action="confirm_ideation_summary",
            )

        if not self.story_planning_store.ideation_summary_is_current():
            summary = self._generate_ideation_summary()
            self.story_planning_store.save_ideation_summary(summary)

        self.state.pending_confirmation = "ideation_summary"
        self.state.blocking_reason = ""
        self.state.last_agent_action = "generated_ideation_summary"
        self.state_store.save(self.state)
        return OrchestratorResult(
            message="已整理当前想法汇总。请先确认这版汇总，再继续生成或修改大纲。",
            stage=self.state.stage,
            blocked=blocked,
            next_action="confirm_ideation_summary",
        )

    def _current_story_title(self) -> str:
        outline_text = self._read_text(self.story_planning_store.outline_src_path)
        match = re.search(r"^#\s+(.+)$", outline_text, re.MULTILINE)
        if match:
            return match.group(1).strip()
        return self.novel_id

    def _strip_code_fences(self, text: str) -> str:
        stripped = text.strip()
        fenced = re.match(r"^```(?:markdown|md|toml)?\s*\n(?P<body>.*)\n```$", stripped, re.DOTALL)
        if fenced:
            return fenced.group("body").strip()
        return stripped

    def _extract_generated_character_name(self, content: str) -> str:
        meta, body = parse_toml_front_matter(content)
        meta_name = str(meta.get("name", "")).strip()
        if meta_name:
            return meta_name
        heading = re.search(r"^#\s+(.+)$", body or content, re.MULTILINE)
        if heading:
            return heading.group(1).strip()
        raise RuntimeError("generated character content missing name")

    def _sync_runtime_caches(self, *, sync_outline: bool, sync_characters: bool) -> None:
        run_sync(
            self.project_root,
            self.novel_id,
            sync_outline=sync_outline,
            sync_characters=sync_characters,
        )

    def _persist_failed_workflow(
        self,
        scheduler: WorkflowScheduler,
        workflow: Any,
        stage_name: str,
        error: str,
    ) -> None:
        stage = None
        for candidate in getattr(workflow, "stages", []):
            if getattr(candidate, "name", "") == stage_name:
                stage = candidate
                break

        if stage is not None:
            stage.status = "failed"
            stage.completed_at = datetime.now().isoformat()
            stage.message = error

        workflow.error = f"{stage_name}: {error}"
        workflow.updated_at = datetime.now().isoformat()

        path = scheduler.workflow_dir / f"wf_{workflow.chapter_id}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(
                workflow.to_dict(),
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )

    def _sanitize_draft_path(self, draft_path: Any) -> str:
        if not draft_path:
            return ""

        try:
            candidate = Path(str(draft_path))
            if not candidate.is_absolute():
                candidate = (self.project_root / candidate).resolve()
            else:
                candidate = candidate.resolve()

            if self._is_within_project(candidate):
                return str(candidate)
        except Exception:
            return ""
        return ""

    def _is_within_project(self, path: Path) -> bool:
        try:
            path.relative_to(self.project_root)
            return True
        except ValueError:
            return False


__all__ = ["OpenWriteOrchestrator", "OrchestratorResult"]
