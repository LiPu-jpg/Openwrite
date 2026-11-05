"""High-level Goethe planning action adapter."""

from __future__ import annotations

import asyncio
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from ..architect import ArchitectAgent
from ..frontmatter import compose_toml_document
from ..llm import LLMClient, LLMConfig
from ..novel_service import NovelApplicationService, NovelServiceError
from ..story_planning import StoryPlanningStore
from ..truth_manager import TruthFilesManager
from ..utils import generate_id
from .base import AgentContext
from .book_state import BookStage, BookStateError, BookStateStore
from .orchestrator import OpenWriteOrchestrator, OrchestratorResult


class GoethePlanningRuntime:
    """Planning-focused runtime for Goethe actions."""

    def __init__(
        self,
        project_root: Path,
        novel_id: str,
        tool_executors: dict[str, Callable[[dict[str, Any]], Any]] | None = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.novel_id = novel_id
        self.tool_executors = dict(tool_executors or {})
        self.story_planning_store = StoryPlanningStore(self.project_root, novel_id)
        self.truth_manager = TruthFilesManager(self.project_root, novel_id)
        self.book_state_store = BookStateStore(self.project_root, novel_id)
        self.orchestrator = OpenWriteOrchestrator(
            project_root=self.project_root,
            novel_id=novel_id,
            tool_executors=self.tool_executors,
        )
        self.novel_service = NovelApplicationService(self.project_root)
        self._architect: ArchitectAgent | None = None

    def summarize_ideation(self) -> OrchestratorResult:
        return self.orchestrator.summarize_ideation()

    def confirm_ideation_summary(self, text: str) -> OrchestratorResult:
        return self.orchestrator.confirm_ideation_summary(text)

    def generate_outline_draft(self, request_text: str) -> OrchestratorResult:
        return self.orchestrator.generate_outline_draft(request_text)

    def read_outline(
        self,
        *,
        query: str = "",
        start_line: int = 0,
        end_line: int = 0,
    ) -> dict[str, Any]:
        return self.story_planning_store.read_outline_for_edit(
            query=query,
            start_line=start_line,
            end_line=end_line,
        )

    def stage_outline_edits(
        self,
        *,
        base_revision: str,
        edits: list[dict[str, Any]],
        batch_label: str = "",
        final_batch: bool = True,
    ) -> dict[str, Any]:
        payload = self.story_planning_store.stage_outline_edits(
            base_revision=base_revision,
            edits=edits,
            batch_label=batch_label,
            final_batch=final_batch,
        )
        if not payload.get("ok"):
            return payload

        state = self.book_state_store.load_or_create()
        if state.stage in {BookStage.DISCOVERY, BookStage.FOUNDATION}:
            state.stage = BookStage.ROLLING_OUTLINE
        state.pending_confirmation = "outline_scope"
        state.blocking_reason = ""
        state.last_agent_action = "staged_outline_edits"
        self.book_state_store.save(state)
        payload["stage"] = state.stage.value
        return payload

    def confirm_outline_edits(self) -> OrchestratorResult:
        return self.orchestrator.confirm_outline_draft()

    def discard_outline_edits(self) -> dict[str, Any]:
        payload = self.story_planning_store.discard_outline_edit()
        state = self.book_state_store.load_or_create()
        if state.pending_confirmation == "outline_scope":
            state.pending_confirmation = ""
        state.blocking_reason = ""
        state.last_agent_action = "discarded_outline_edits"
        self.book_state_store.save(state)
        payload["stage"] = state.stage.value
        return payload

    def generate_foundation_draft(self, request_text: str) -> dict[str, Any]:
        brief = str(request_text or "").strip()
        title, genre = self._load_title_and_genre()
        confirmed_sections = [
            ("已确认构思摘要", self.story_planning_store.read_ideation_summary(max_chars=2200)),
            (
                "已确认故事背景",
                self.story_planning_store.read_story_document("background", max_chars=3600),
            ),
            (
                "已确认基础设定",
                self.story_planning_store.read_story_document("foundation", max_chars=3600),
            ),
            ("已确认大纲片段", self.story_planning_store.read_outline_source(max_chars=3000)),
        ]
        confirmed_context = "\n\n".join(
            f"### {label}\n{text}" for label, text in confirmed_sections if str(text or "").strip()
        )
        generation_brief = brief
        if confirmed_context:
            generation_brief = (
                f"{brief}\n\n"
                "以下内容是当前项目已经确认的正典资产。草案只能补全或细化，"
                "不得替换题材、世界背景、力量体系、角色身份或组织含义；"
                "若请求与正典冲突，以正典为准。\n\n"
                f"{confirmed_context}"
            ).strip()

        state = self.book_state_store.load_or_create()
        can_promote = state.stage in {BookStage.DISCOVERY, BookStage.FOUNDATION}
        warnings: list[str] = []
        if can_promote:
            foundation = self._get_architect().generate_foundation(
                title=title,
                genre=genre,
                brief=generation_brief,
                include_foreshadowing=True,
            )
            story_bible = foundation.story_bible
            book_rules = foundation.book_rules
            volume_outline = foundation.volume_outline
            current_state = foundation.current_state
            foreshadowing_seed = foundation.foreshadowing_seed
            warnings.extend(foundation.warnings)
        else:
            story_bible = self.story_planning_store.read_story_document("background")
            book_rules = self.story_planning_store.read_story_document("foundation")
            volume_outline = self.story_planning_store.read_outline_source()
            current_state = self.truth_manager.load_truth_files().current_state
            foreshadowing_seed = ""
            warnings.append("mature_project_reused_canonical_foundation")
        if not foreshadowing_seed and self.story_planning_store.foreshadowing_draft_path.is_file():
            foreshadowing_seed = self.story_planning_store.foreshadowing_draft_path.read_text(
                encoding="utf-8"
            )
        try:
            self.story_planning_store.save_foundation_draft(
                background=story_bible,
                foundation=book_rules,
                volume_outline=volume_outline,
                current_state=current_state,
                foreshadowing=foreshadowing_seed,
            )
        except (OSError, ValueError, yaml.YAMLError) as exc:
            return {
                "ok": False,
                "blocked": True,
                "error": "invalid_foundation_draft",
                "message": f"基础设定辅助草案不符合 OpenWrite 结构：{exc}",
                "next_action": "generate_foundation_draft",
            }

        if can_promote:
            state.stage = BookStage.FOUNDATION
            state.pending_confirmation = "foundation"
        elif state.pending_confirmation == "foundation":
            state.pending_confirmation = ""
        state.blocking_reason = ""
        state.last_agent_action = "generated_foundation_draft"
        self.book_state_store.save(state)

        return {
            "ok": True,
            "blocked": False,
            "next_action": "confirm_foundation" if can_promote else "review_foundation_draft",
            "title": title,
            "genre": genre,
            "background_path": str(self.story_planning_store.background_draft_path),
            "foundation_path": str(self.story_planning_store.foundation_draft_path),
            "volume_outline_path": str(self.story_planning_store.volume_outline_draft_path),
            "current_state_path": str(self.story_planning_store.current_state_draft_path),
            "foreshadowing_path": (
                str(self.story_planning_store.foreshadowing_draft_path)
                if self.story_planning_store.foreshadowing_draft_path.is_file()
                else ""
            ),
            "foreshadowing_generated": self.story_planning_store.foreshadowing_draft_path.is_file(),
            "warnings": warnings,
            "story_bible": story_bible,
            "book_rules": book_rules,
            "current_state": current_state,
            "outline_seed": volume_outline,
            "foreshadowing_seed": foreshadowing_seed,
            "message": (
                "基础设定辅助草案已写入 planning；确认前未修改 canonical 资产。"
                if can_promote
                else "基础设定辅助草案已写入 planning；当前写作阶段不会倒退，"
                "如需替换 canonical 基础设定应开启独立修订流程。"
            ),
        }

    def confirm_foundation(self) -> OrchestratorResult:
        return self.orchestrator.confirm_foundation()

    def generate_character_draft(self, request_text: str) -> dict[str, Any]:
        name, role = self._parse_character_request(request_text)
        _, genre = self._load_title_and_genre()
        architect = self._get_architect()
        foundation_text = self.story_planning_store.read_story_document(
            "foundation", max_chars=2000
        )

        character_md = asyncio.run(
            architect.generate_character(
                name=name,
                role=role,
                genre=genre,
                story_bible=foundation_text,
            )
        )
        character_dir = self.story_planning_store.runtime_planning_dir / "characters"
        character_dir.mkdir(parents=True, exist_ok=True)
        character_id = generate_id(name or role or "character", "character")
        draft_path = character_dir / f"{character_id}.md"
        draft_meta = {
            "id": character_id,
            "kind": "character_draft",
            "status": "draft",
            "title": name or role or character_id,
            "name": name or role or character_id,
            "tier": role or "普通配角",
            "summary": f"{name or role or character_id}的待确认角色设定。",
            "tags": [role] if role else [],
            "related": [],
            "source": "goethe",
            "detail_refs": [
                "基本信息",
                "背景",
                "外貌",
                "性格",
                "与主角关系",
                "说话风格",
                "当前戏剧用途",
                "特殊能力",
            ],
        }
        draft_path.write_text(
            compose_toml_document(draft_meta, character_md),
            encoding="utf-8",
        )
        # Strict read: `load_or_create` quarantines a damaged state file and
        # returns a fresh one, which reads as "nothing pending" and would let this
        # guard pass on a corrupted store - the same class of failure K3 guards
        # against, reached by a different route.
        try:
            state = self.book_state_store.load_strict()
        except BookStateError:
            draft_path.unlink(missing_ok=True)
            return {
                "ok": False,
                "blocked": True,
                "error": "BOOK_STATE_UNREADABLE",
                "message": (
                    "书籍状态文件损坏，无法判断是否还有未确认的大纲草案。"
                    "请先修复或删除该文件后重试。"
                ),
                "next_action": "repair_book_state",
            }
        # K3: a pending outline confirmation must not be overwritten. The staged
        # outline draft stays on disk while `pending_confirmation` moves to this
        # character, so the next `confirm_outline_scope()` falls into the
        # "existing outline" branch and promotes the OLD src/outline.md — the
        # author believes the new outline is confirmed and Dante plans against a
        # superseded one. Refuse instead: the author confirms or discards the
        # outline first.
        if state.pending_confirmation == "outline_scope":
            draft_path.unlink(missing_ok=True)
            return {
                "ok": False,
                "blocked": True,
                "error": "OUTLINE_CONFIRMATION_PENDING",
                "message": (
                    "还有一份暂存的大纲草案等待确认。请先确认或丢弃它，再生成角色，"
                    "否则下一步确认会把旧大纲升格。"
                ),
                "next_action": "confirm_outline_scope",
            }
        state.pending_confirmation = f"character:{character_id}"
        state.blocking_reason = ""
        state.last_agent_action = "generated_character_draft"
        self.book_state_store.save(state)

        return {
            "ok": True,
            "blocked": False,
            "next_action": "confirm_character_draft",
            "character_id": character_id,
            "name": name,
            "role": role,
            "genre": genre,
            "draft_path": str(draft_path),
            "content": character_md,
        }

    def confirm_character_draft(self, character_id: str) -> dict[str, Any]:
        clean_id = str(character_id or "").strip()
        if not clean_id or not re.fullmatch(r"[\w\u3400-\u9fff.-]+", clean_id):
            return {
                "ok": False,
                "blocked": True,
                "error": "invalid_character_id",
                "message": "character_id 无效。",
            }
        draft_path = (
            self.story_planning_store.runtime_planning_dir / "characters" / f"{clean_id}.md"
        )
        if not draft_path.is_file():
            return {
                "ok": False,
                "blocked": True,
                "error": "missing_character_draft",
                "message": "未找到待确认角色草案。",
            }

        from ..frontmatter import parse_toml_front_matter, strip_front_matter_padding
        from ..shared_documents import normalize_character_document

        draft = draft_path.read_text(encoding="utf-8")
        meta, body = parse_toml_front_matter(draft)
        clean_body = strip_front_matter_padding(body if meta else draft).strip()
        name = str(meta.get("name") or meta.get("title") or "").strip()
        required_meta = ("id", "name", "tier", "summary", "tags")
        missing_meta = [key for key in required_meta if meta.get(key) in (None, "")]
        required_sections = (
            "基本信息",
            "背景",
            "外貌",
            "性格",
            "与主角关系",
            "说话风格",
            "当前戏剧用途",
        )
        headings = {
            match.group(1).strip()
            for match in re.finditer(r"^##\s+(.+?)\s*$", clean_body, re.MULTILINE)
        }
        missing_sections = [title for title in required_sections if title not in headings]
        if missing_meta or not name or missing_sections:
            return {
                "ok": False,
                "blocked": True,
                "error": "incomplete_character_draft",
                "message": "角色草案结构不完整，不能晋升。",
                "missing_metadata": missing_meta,
                "missing_sections": missing_sections,
            }

        canonical_meta = dict(meta)
        canonical_meta.pop("kind", None)
        canonical_meta["status"] = "active"
        canonical = normalize_character_document(
            compose_toml_document(canonical_meta, clean_body),
            fallback_id=clean_id,
            fallback_name=name,
        )
        try:
            path = self.novel_service.create_document(
                kind="character",
                name=name,
                content=canonical,
            )
        except NovelServiceError as exc:
            return self._service_error("confirm_character_draft", clean_id, exc)

        self.orchestrator._sync_runtime_caches(  # noqa: SLF001
            sync_outline=False,
            sync_characters=True,
        )
        state = self.book_state_store.load_or_create()
        if state.pending_confirmation in {"character", f"character:{clean_id}"}:
            state.pending_confirmation = ""
        state.blocking_reason = ""
        state.last_agent_action = "confirmed_character_draft"
        self.book_state_store.save(state)
        return {
            "ok": True,
            "blocked": False,
            "next_action": "continue_planning",
            "character_id": clean_id,
            "name": name,
            "path": str(path),
            "message": f"角色 {name} 已确认并晋升到 src/characters。",
        }

    def extract_style_source(self, source_id: str, source: str) -> dict[str, Any]:
        return self._run_source_extraction(
            action="extract_style_source",
            source_id=source_id,
            source=source,
            focus="style",
        )

    def extract_setting_source(self, source_id: str, source: str) -> dict[str, Any]:
        return self._run_source_extraction(
            action="extract_setting_source",
            source_id=source_id,
            source=source,
            focus="setting",
        )

    def review_source_pack(self, source_id: str) -> dict[str, Any]:
        try:
            result = self.novel_service.review_source(source_id)
        except NovelServiceError as exc:
            return self._service_error("review_source_pack", source_id, exc)
        review = str(result.get("review_report") or "")
        metadata = result.get("review_metadata") or {}
        promotion_ready = bool(metadata.get("promotion_ready"))
        source_root = self._source_root(source_id)
        return {
            "ok": True,
            "blocked": False,
            "next_action": (
                "promote_source_pack" if promotion_ready else "extract_style_source"
            ),
            "source_id": source_id,
            "source_root": str(source_root),
            "review_report": review,
            "review_metadata": metadata,
            "message": (
                "来源包已通过晋升前检查。"
                if promotion_ready
                else "来源分析可审阅，但旧版晋升资产不完整；请先提取可晋升来源包。"
            ),
        }

    def promote_source_pack(self, source_id: str, target: str = "all") -> dict[str, Any]:
        try:
            result = self.novel_service.promote_source(source_id, target)
        except NovelServiceError as exc:
            return self._service_error("promote_source_pack", source_id, exc)
        source_root = self._source_root(source_id)
        return {
            **result,
            "blocked": False,
            "next_action": "handoff_ready",
            "source_root": str(source_root),
        }

    def list_reference_library(self) -> dict[str, Any]:
        from ..reference_library import ReferenceLibraryService, default_reference_library_root

        service = ReferenceLibraryService(
            default_reference_library_root(),
            project_root=self.project_root,
            novel_id=self.novel_id,
        )
        return {
            "ok": True,
            "references": service.list(),
            "profiles": service.list_profiles(),
            "project_style": service.project_style_surface(),
        }

    def review_reference_source(self, source_id: str) -> dict[str, Any]:
        from ..reference_library import ReferenceLibraryService, default_reference_library_root

        service = ReferenceLibraryService(
            default_reference_library_root(),
            project_root=self.project_root,
            novel_id=self.novel_id,
        )
        try:
            source = service.status(source_id)
        except Exception as exc:
            return {
                "ok": False,
                "blocked": True,
                "error": "reference_source_unavailable",
                "message": str(exc),
            }
        return {
            "ok": True,
            "source": source,
            "project_style": service.project_style_surface(),
        }

    def review_reference_profile(self, profile_id: str) -> dict[str, Any]:
        from ..reference_library import ReferenceLibraryService, default_reference_library_root

        service = ReferenceLibraryService(
            default_reference_library_root(),
            project_root=self.project_root,
            novel_id=self.novel_id,
        )
        try:
            profile = service.profile(profile_id)
        except Exception as exc:
            return {
                "ok": False,
                "blocked": True,
                "error": "reference_profile_unavailable",
                "message": str(exc),
            }
        return {
            "ok": True,
            "profile": profile.model_dump(mode="json"),
            "project_style": service.project_style_surface(),
        }

    def preview_reference_adoption(
        self,
        profile_id: str,
        selections: list[dict[str, Any]],
    ) -> dict[str, Any]:
        from ..reference_library import ReferenceLibraryService, default_reference_library_root

        service = ReferenceLibraryService(
            default_reference_library_root(),
            project_root=self.project_root,
            novel_id=self.novel_id,
        )
        try:
            preview = service.preview_adoption(profile_id, selections)
        except Exception as exc:
            return {
                "ok": False,
                "blocked": True,
                "error": "reference_adoption_preview_failed",
                "message": str(exc),
            }
        return {"ok": True, "preview": preview.model_dump(mode="json")}

    def apply_reference_adoption(self, preview_id: str, *, confirm: bool) -> dict[str, Any]:
        from ..reference_library import ReferenceLibraryService, default_reference_library_root

        if not confirm:
            return {
                "ok": False,
                "blocked": True,
                "error": "confirmation_required",
                "message": "应用参考采纳预览需要用户明确确认。",
            }
        service = ReferenceLibraryService(
            default_reference_library_root(),
            project_root=self.project_root,
            novel_id=self.novel_id,
        )
        try:
            return service.apply_adoption(preview_id, confirm=True)
        except Exception as exc:
            return {
                "ok": False,
                "blocked": True,
                "error": "reference_adoption_apply_failed",
                "message": str(exc),
            }

    def _handoff_asset_revisions(self, readiness: dict[str, Any]) -> dict[str, str]:
        # Content revision for every canonical asset the handoff hands over.
        # `StoryPlanningStore.outline_source_revision()` already exists for exactly
        # this purpose; the handoff simply never recorded it.
        store = self.story_planning_store
        revisions: dict[str, str] = {"outline": store.outline_source_revision()}
        for label, path in (
            ("ideation_summary", store.ideation_summary_path),
            ("background", store.story_src_dir / "background.md"),
            ("foundation", store.story_src_dir / "foundation.md"),
        ):
            try:
                revisions[label] = store._hash_text(path.read_text(encoding="utf-8")) if path.exists() else ""
            except OSError:
                revisions[label] = ""
        for index, path in enumerate(readiness.get("persona_paths") or []):
            target = Path(path)
            try:
                revisions["persona_%d" % index] = store._hash_text(target.read_text(encoding="utf-8")) if target.exists() else ""
            except OSError:
                revisions["persona_%d" % index] = ""
        return revisions

    @staticmethod
    def _now_iso() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()

    def prepare_dante_handoff(self) -> dict[str, Any]:
        readiness = self._evaluate_handoff_readiness()
        if readiness["missing_items"]:
            return {
                "ok": False,
                "blocked": True,
                "error": "missing_handoff_assets",
                "message": "Goethe 资产尚未满足切换到 Dante 的条件。",
                "missing_items": readiness["missing_items"],
                "required_assets": readiness["required_assets"],
                "outline_errors": readiness.get("outline_errors", []),
                "persona_errors": readiness.get("persona_errors", []),
                "next_action": "continue_planning",
            }

        book_state = self.book_state_store.load_or_create()
        book_state.stage = BookStage.CHAPTER_PREFLIGHT
        book_state.pending_confirmation = ""
        book_state.blocking_reason = ""
        book_state.last_agent_action = "goethe_handoff"
        book_state.last_handoff_from = "goethe"
        self.book_state_store.save(book_state)

        manifest = {
            "ready": True,
            "source_agent": "goethe",
            "target_agent": "dante",
            "next_stage": BookStage.CHAPTER_PREFLIGHT.value,
            "required_assets": readiness["required_assets"],
            "missing_items": [],
            "ideation_summary_path": str(self.story_planning_store.ideation_summary_path),
            "background_path": str(self.story_planning_store.story_src_dir / "background.md"),
            "foundation_path": str(self.story_planning_store.story_src_dir / "foundation.md"),
            "outline_path": str(self.story_planning_store.outline_src_path),
            "persona_paths": readiness["persona_paths"],
            "character_paths": readiness["persona_paths"],
            "compatibility_warnings": readiness.get("compatibility_warnings", []),
            "current_arc": book_state.current_arc,
            "current_section": book_state.current_section,
            "current_chapter": book_state.current_chapter,
            # K4: content signatures of the assets this handoff describes. Without
            # them a handoff stays "ready" after src/outline.md is rewritten, and
            # Dante silently plans against a superseded outline.
            "generated_at": self._now_iso(),
            "novel_id": book_state.novel_id,
            "project_root": str(self.project_root),
            "asset_revisions": self._handoff_asset_revisions(readiness),
            "book_state": {
                "novel_id": book_state.novel_id,
                "stage": book_state.stage.value,
                "current_arc": book_state.current_arc,
                "current_section": book_state.current_section,
                "current_chapter": book_state.current_chapter,
                "pending_confirmation": book_state.pending_confirmation,
                "blocking_reason": book_state.blocking_reason,
                "last_agent_action": book_state.last_agent_action,
                "last_handoff_from": book_state.last_handoff_from,
            },
            "summary": self._build_handoff_summary(readiness),
        }
        handoff_md_path, handoff_yaml_path = self.story_planning_store.save_goethe_handoff(manifest)

        return {
            "ok": True,
            "blocked": False,
            "error": "",
            "message": "Goethe 资产已满足切换到 Dante 的条件。",
            "missing_items": [],
            "required_assets": readiness["required_assets"],
            "next_action": "chapter_preflight",
            "handoff_markdown_path": str(handoff_md_path),
            "handoff_yaml_path": str(handoff_yaml_path),
            "book_state": manifest["book_state"],
            "persona_paths": readiness["persona_paths"],
            "compatibility_warnings": readiness.get("compatibility_warnings", []),
        }

    def _get_architect(self) -> ArchitectAgent:
        if self._architect is not None:
            return self._architect
        llm_config = LLMConfig.from_env()
        client = LLMClient(llm_config)
        ctx = AgentContext(client, llm_config.model, str(self.project_root))
        self._architect = ArchitectAgent(ctx)
        return self._architect

    def _load_title_and_genre(self) -> tuple[str, str]:
        config = self._load_config()
        title = str(config.get("title", self.novel_id)).strip() or self.novel_id
        genre = str(config.get("genre", "unspecified")).strip() or "unspecified"
        return title, genre

    def _load_config(self) -> dict[str, Any]:
        config_path = self.project_root / "novel_config.yaml"
        if not config_path.exists():
            fallback = self.project_root / "data" / "novels" / self.novel_id / "novel_config.yaml"
            if not fallback.exists():
                return {}
            config_path = fallback
        try:
            data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _parse_character_request(self, text: str) -> tuple[str, str]:
        raw = str(text or "").strip()
        if not raw:
            return "角色", "人物"

        name = ""
        role = ""
        patterns = [
            (r"角色名[:：]\s*([^，,。;；\n]+)", "name"),
            (r"名字[:：]\s*([^，,。;；\n]+)", "name"),
            (r"角色[:：]\s*([^，,。;；\n]+)", "name"),
        ]
        for pattern, _kind in patterns:
            match = re.search(pattern, raw)
            if match:
                name = match.group(1).strip()
                break

        role_patterns = [
            r"定位[:：]\s*([^，,。;；\n]+)",
            r"身份[:：]\s*([^，,。;；\n]+)",
            r"角色定位[:：]\s*([^，,。;；\n]+)",
            r"角色类型[:：]\s*([^，,。;；\n]+)",
        ]
        for pattern in role_patterns:
            match = re.search(pattern, raw)
            if match:
                role = match.group(1).strip()
                break

        if not name:
            name = raw.split("，", 1)[0].split(",", 1)[0].strip()
        if not role:
            role = "人物"
        return name or "角色", role

    def _run_source_extraction(
        self,
        *,
        action: str,
        source_id: str,
        source: str,
        focus: str,
    ) -> dict[str, Any]:
        source_id = str(source_id or "").strip()
        raw_source = str(source or "").strip()
        if not source_id:
            return self._missing_source_pack(action, source_id)
        if not raw_source:
            return {
                "ok": False,
                "blocked": True,
                "next_action": "provide_source",
                "error": "missing_source",
                "message": "请提供来源文本或文件路径。",
                "source_id": source_id,
            }

        source_file = Path(raw_source).expanduser()
        try:
            is_file = source_file.is_file()
        except OSError:
            is_file = False
        if is_file:
            return self._extract_source_file(
                action=action,
                source_id=source_id,
                source_file=source_file,
                focus=focus,
            )

        if self._looks_like_source_path(raw_source):
            return {
                "ok": False,
                "blocked": True,
                "next_action": "provide_source_file",
                "error": "missing_source_file",
                "message": f"源文件不存在: {source_file}",
                "source_id": source_id,
                "source_file": str(source_file),
            }

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                prefix="openwrite-source-",
                suffix=".txt",
                delete=False,
            ) as handle:
                handle.write(raw_source)
                temporary_path = Path(handle.name)
            return self._extract_source_file(
                action=action,
                source_id=source_id,
                source_file=temporary_path,
                focus=focus,
            )
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _extract_source_file(
        self,
        *,
        action: str,
        source_id: str,
        source_file: Path,
        focus: str,
    ) -> dict[str, Any]:
        try:
            return self.novel_service.extract_source(
                source_id=source_id,
                source_file=source_file,
                focus=focus,
            )
        except NovelServiceError as exc:
            return {
                "action": action,
                "ok": False,
                "blocked": True,
                "error": exc.code,
                "message": str(exc),
                "source_id": source_id,
            }

    @staticmethod
    def _looks_like_source_path(source: str) -> bool:
        if "\n" in source or "\r" in source:
            return False
        candidate = source.strip()
        if candidate.startswith(("/", "~/", "./", "../")):
            return True
        return bool(re.fullmatch(r"[^\s]+\.(?:txt|md|markdown|rst|text)", candidate, re.I))

    def _source_root(self, source_id: str) -> Path:
        return (
            self.project_root / "data" / "novels" / self.novel_id / "data" / "sources" / source_id
        )

    @staticmethod
    def _service_error(
        action: str,
        source_id: str,
        exc: NovelServiceError,
    ) -> dict[str, Any]:
        return {
            "action": action,
            "ok": False,
            "blocked": True,
            "error": exc.code,
            "message": str(exc),
            "source_id": source_id,
        }

    def _evaluate_handoff_readiness(self) -> dict[str, Any]:
        required_assets = ["ideation_summary", "foundation", "outline", "persona"]
        missing_items: list[str] = []

        ideation_ready = (
            self.story_planning_store.ideation_summary_path.exists()
            and self.story_planning_store.ideation_summary_is_current()
        )
        background_doc = self.story_planning_store.load_story_document("background")
        foundation_doc = self.story_planning_store.load_story_document("foundation")
        background_body = str(background_doc.get("body", "")).strip()
        foundation_body = str(foundation_doc.get("body", "")).strip()
        foundation_ready = bool(background_body and foundation_body)
        outline_text = self.story_planning_store.read_outline_source()
        outline_errors = self._outline_readiness_errors(outline_text)
        outline_pending = self.story_planning_store.outline_edit_state_path.exists()
        persona_documents = self.story_planning_store.list_character_documents()
        persona_paths = [item["path"] for item in persona_documents]
        persona_errors = [
            error
            for item in persona_documents
            for error in self._character_readiness_errors(Path(item["path"]))
        ]
        novel_root = self.project_root / "data" / "novels" / self.novel_id
        manuscript_root = novel_root / "data" / "manuscript"
        has_manuscript = manuscript_root.is_dir() and any(
            manuscript_root.rglob("*.md")
        )
        legacy_outline_accepted = bool(
            has_manuscript
            and outline_text.strip()
            and not self.story_planning_store.outline_source_is_placeholder()
        )
        legacy_persona_accepted = bool(has_manuscript and persona_paths)
        outline_ready = not outline_errors or legacy_outline_accepted
        persona_ready = bool(persona_paths) and (
            not persona_errors or legacy_persona_accepted
        )
        compatibility_warnings: list[str] = []
        if outline_errors and legacy_outline_accepted:
            compatibility_warnings.append(
                "项目已有正文，沿用 legacy canonical 大纲；建议后续增量补齐章节字段。"
            )
        if persona_errors and legacy_persona_accepted:
            compatibility_warnings.append(
                "项目已有正文，沿用 legacy canonical 角色卡；建议后续按需补齐结构字段。"
            )

        if not ideation_ready:
            missing_items.append("ideation_summary")
        if not foundation_ready:
            missing_items.append("foundation")
        if not outline_ready:
            missing_items.append("outline")
        elif outline_pending:
            missing_items.append("outline_confirmation")
        if not persona_ready:
            missing_items.append("persona")

        return {
            "required_assets": required_assets,
            "missing_items": missing_items,
            "persona_paths": persona_paths,
            "outline_errors": outline_errors,
            "persona_errors": persona_errors,
            "compatibility_warnings": compatibility_warnings,
        }

    def _outline_readiness_errors(self, outline_text: str) -> list[str]:
        if not outline_text.strip() or self.story_planning_store.outline_source_is_placeholder():
            return ["大纲缺失或仍是占位模板"]
        from ..outline_contract import validate_outline_markdown

        return validate_outline_markdown(outline_text, self.novel_id)

    @staticmethod
    def _character_readiness_errors(path: Path) -> list[str]:
        from ..frontmatter import parse_toml_front_matter, strip_front_matter_padding

        text = path.read_text(encoding="utf-8")
        meta, body = parse_toml_front_matter(text)
        errors: list[str] = []
        missing_meta = [
            key for key in ("id", "name", "tier", "summary", "tags") if meta.get(key) in (None, "")
        ]
        if missing_meta:
            errors.append(f"{path.name} front matter 缺少: {', '.join(missing_meta)}")
        clean_body = strip_front_matter_padding(body if meta else text)
        headings = {
            match.group(1).strip()
            for match in re.finditer(r"^##\s+(.+?)\s*$", clean_body, re.MULTILINE)
        }
        required_groups = (
            ("背景",),
            ("外貌", "外貌特征"),
            ("性格", "性格特点"),
            ("与主角关系", "关系"),
            ("说话风格", "语言风格"),
            ("当前戏剧用途", "戏剧用途"),
        )
        missing_sections = [
            "/".join(group) for group in required_groups if not headings.intersection(group)
        ]
        if missing_sections:
            errors.append(f"{path.name} 正文缺少: {', '.join(missing_sections)}")
        return errors

    def _build_handoff_summary(self, readiness: dict[str, Any]) -> str:
        persona_paths = readiness.get("persona_paths", [])
        summary_lines = [
            "Goethe 已完成到 Dante 的交接准备。",
            "可写资产已收齐：ideation_summary、foundation、outline、persona。",
        ]
        if persona_paths:
            summary_lines.append("主要人物文件: " + "；".join(str(item) for item in persona_paths))
        warnings = readiness.get("compatibility_warnings", [])
        if warnings:
            summary_lines.append("兼容提示: " + "；".join(str(item) for item in warnings))
        return "\n".join(summary_lines)

    def _missing_source_pack(self, action: str, source_id: str) -> dict[str, Any]:
        return {
            "ok": False,
            "blocked": True,
            "next_action": "provide_source_id",
            "error": "missing_source_id",
            "message": "缺少必需参数: source_id",
            "action": action,
            "source_id": source_id,
        }


class GoetheActionAdapter:
    """High-level Goethe planning action adapter."""

    def __init__(self, runtime: GoethePlanningRuntime):
        self.runtime = runtime

    def summarize_ideation(self) -> dict[str, Any]:
        return self._wrap("summarize_ideation", self.runtime.summarize_ideation())

    def confirm_ideation_summary(self, text: str) -> dict[str, Any]:
        return self._wrap(
            "confirm_ideation_summary",
            self.runtime.confirm_ideation_summary(text),
        )

    def generate_foundation_draft(self, request_text: str) -> dict[str, Any]:
        return self._wrap(
            "generate_foundation_draft",
            self.runtime.generate_foundation_draft(request_text),
        )

    def confirm_foundation(self) -> dict[str, Any]:
        return self._wrap(
            "confirm_foundation",
            self.runtime.confirm_foundation(),
        )

    def generate_character_draft(self, request_text: str) -> dict[str, Any]:
        return self._wrap(
            "generate_character_draft",
            self.runtime.generate_character_draft(request_text),
        )

    def confirm_character_draft(self, character_id: str) -> dict[str, Any]:
        if not str(character_id or "").strip():
            return self._missing_required("confirm_character_draft", "character_id")
        return self._wrap(
            "confirm_character_draft",
            self.runtime.confirm_character_draft(character_id),
        )

    def generate_outline_draft(self, request_text: str) -> dict[str, Any]:
        return self._wrap(
            "generate_outline_draft",
            self.runtime.generate_outline_draft(request_text),
        )

    def read_outline(
        self,
        *,
        query: str = "",
        start_line: int = 0,
        end_line: int = 0,
    ) -> dict[str, Any]:
        return self._wrap(
            "read_outline",
            self.runtime.read_outline(
                query=query,
                start_line=start_line,
                end_line=end_line,
            ),
        )

    def stage_outline_edits(
        self,
        *,
        base_revision: str,
        edits: list[dict[str, Any]],
        batch_label: str = "",
        final_batch: bool = True,
    ) -> dict[str, Any]:
        if not str(base_revision or "").strip():
            return self._missing_required("stage_outline_edits", "base_revision")
        if not edits:
            return self._missing_required("stage_outline_edits", "edits")
        return self._wrap(
            "stage_outline_edits",
            self.runtime.stage_outline_edits(
                base_revision=base_revision,
                edits=edits,
                batch_label=batch_label,
                final_batch=final_batch,
            ),
        )

    def confirm_outline_edits(self) -> dict[str, Any]:
        return self._wrap(
            "confirm_outline_edits",
            self.runtime.confirm_outline_edits(),
        )

    def discard_outline_edits(self) -> dict[str, Any]:
        return self._wrap(
            "discard_outline_edits",
            self.runtime.discard_outline_edits(),
        )

    def extract_style_source(self, source_id: str, source: str) -> dict[str, Any]:
        if not str(source_id or "").strip():
            return self._missing_required("extract_style_source", "source_id")
        if not str(source or "").strip():
            return self._missing_required("extract_style_source", "source")
        return self._wrap(
            "extract_style_source",
            self.runtime.extract_style_source(source_id, source),
        )

    def extract_setting_source(self, source_id: str, source: str) -> dict[str, Any]:
        if not str(source_id or "").strip():
            return self._missing_required("extract_setting_source", "source_id")
        if not str(source or "").strip():
            return self._missing_required("extract_setting_source", "source")
        return self._wrap(
            "extract_setting_source",
            self.runtime.extract_setting_source(source_id, source),
        )

    def review_source_pack(self, source_id: str) -> dict[str, Any]:
        if not str(source_id or "").strip():
            return self._missing_required("review_source_pack", "source_id")
        return self._wrap("review_source_pack", self.runtime.review_source_pack(source_id))

    def promote_source_pack(self, source_id: str, target: str = "all") -> dict[str, Any]:
        if not str(source_id or "").strip():
            return self._missing_required("promote_source_pack", "source_id")
        return self._wrap(
            "promote_source_pack",
            self.runtime.promote_source_pack(source_id, target=target or "all"),
        )

    def list_reference_library(self) -> dict[str, Any]:
        return self._wrap("list_reference_library", self.runtime.list_reference_library())

    def review_reference_source(self, source_id: str) -> dict[str, Any]:
        if not str(source_id or "").strip():
            return self._missing_required("review_reference_source", "source_id")
        return self._wrap(
            "review_reference_source",
            self.runtime.review_reference_source(source_id),
        )

    def review_reference_profile(self, profile_id: str) -> dict[str, Any]:
        if not str(profile_id or "").strip():
            return self._missing_required("review_reference_profile", "profile_id")
        return self._wrap(
            "review_reference_profile",
            self.runtime.review_reference_profile(profile_id),
        )

    def preview_reference_adoption(
        self, profile_id: str, selections: list[dict[str, Any]]
    ) -> dict[str, Any]:
        if not str(profile_id or "").strip():
            return self._missing_required("preview_reference_adoption", "profile_id")
        if not selections:
            return self._missing_required("preview_reference_adoption", "selections")
        return self._wrap(
            "preview_reference_adoption",
            self.runtime.preview_reference_adoption(profile_id, selections),
        )

    def apply_reference_adoption(self, preview_id: str, *, confirm: bool) -> dict[str, Any]:
        if not str(preview_id or "").strip():
            return self._missing_required("apply_reference_adoption", "preview_id")
        return self._wrap(
            "apply_reference_adoption",
            self.runtime.apply_reference_adoption(preview_id, confirm=confirm),
        )

    def prepare_dante_handoff(self) -> dict[str, Any]:
        return self._wrap(
            "prepare_dante_handoff",
            self.runtime.prepare_dante_handoff(),
        )

    def _missing_required(self, action: str, field_name: str) -> dict[str, Any]:
        return {
            "action": action,
            "ok": False,
            "blocked": True,
            "error": f"missing_{field_name}",
            "message": f"缺少必需参数: {field_name}",
            field_name: "",
        }

    def _wrap(self, action: str, result: Any) -> dict[str, Any]:
        if isinstance(result, OrchestratorResult):
            return {
                "action": action,
                "ok": not result.blocked,
                "stage": result.stage.value,
                "blocked": result.blocked,
                "next_action": result.next_action,
                "message": result.message,
            }
        if isinstance(result, dict):
            payload = dict(result)
            payload.setdefault("ok", True)
            payload.setdefault("blocked", False)
            payload.setdefault("next_action", "")
            payload["action"] = action
            return payload
        return {
            "action": action,
            "ok": True,
            "blocked": False,
            "next_action": "",
            "result": result,
        }
