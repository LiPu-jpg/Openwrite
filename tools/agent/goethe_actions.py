"""High-level Goethe planning action adapter."""

from __future__ import annotations

import asyncio
import re
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
from .book_state import BookStage, BookStateStore
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

    def generate_outline_draft(self, request_text: str) -> OrchestratorResult:
        return self.orchestrator.generate_outline_draft(request_text)

    def generate_foundation_draft(self, request_text: str) -> dict[str, Any]:
        brief = str(request_text or "").strip()
        title, genre = self._load_title_and_genre()
        architect = self._get_architect()

        foundation = architect.generate_foundation(
            title=title,
            genre=genre,
            brief=brief,
        )
        self.story_planning_store.save_foundation_draft(
            background=foundation.story_bible,
            foundation=foundation.book_rules,
        )
        truth = self.truth_manager.load_truth_files()
        truth.current_state = foundation.current_state
        self.truth_manager.save_truth_files(truth)

        foreshadowing_path = (
            self.story_planning_store.runtime_planning_dir
            / "foreshadowing_draft.md"
        )
        foreshadowing_path.write_text(foundation.foreshadowing_seed, encoding="utf-8")

        return {
            "ok": True,
            "blocked": False,
            "next_action": "confirm_foundation",
            "title": title,
            "genre": genre,
            "background_path": str(self.story_planning_store.background_draft_path),
            "foundation_path": str(self.story_planning_store.foundation_draft_path),
            "current_state_path": str(self.truth_manager.world_dir / "current_state.md"),
            "foreshadowing_path": str(foreshadowing_path),
            "story_bible": foundation.story_bible,
            "book_rules": foundation.book_rules,
            "current_state": foundation.current_state,
            "outline_seed": foundation.volume_outline,
            "foreshadowing_seed": foundation.foreshadowing_seed,
        }

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
            "source": "goethe",
            "detail_refs": ["background", "relationship", "voice", "special_notes"],
        }
        draft_path.write_text(
            compose_toml_document(draft_meta, character_md),
            encoding="utf-8",
        )

        return {
            "ok": True,
            "blocked": False,
            "next_action": "revise_character",
            "character_id": character_id,
            "name": name,
            "role": role,
            "genre": genre,
            "draft_path": str(draft_path),
            "content": character_md,
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
            review = self.novel_service.review_source(source_id)["review_report"]
        except NovelServiceError as exc:
            return self._service_error("review_source_pack", source_id, exc)
        source_root = self._source_root(source_id)
        return {
            "ok": True,
            "blocked": False,
            "next_action": "promote_source_pack",
            "source_id": source_id,
            "source_root": str(source_root),
            "review_report": review,
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
            "current_arc": book_state.current_arc,
            "current_section": book_state.current_section,
            "current_chapter": book_state.current_chapter,
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
        handoff_md_path, handoff_yaml_path = self.story_planning_store.save_goethe_handoff(
            manifest
        )

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
        genre = str(config.get("genre", "xuanhuan")).strip() or "xuanhuan"
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
            (r"角色名[:：]\s*([^，,。;\n]+)", "name"),
            (r"名字[:：]\s*([^，,。;\n]+)", "name"),
            (r"角色[:：]\s*([^，,。;\n]+)", "name"),
        ]
        for pattern, _kind in patterns:
            match = re.search(pattern, raw)
            if match:
                name = match.group(1).strip()
                break

        role_patterns = [
            r"定位[:：]\s*([^，,。;\n]+)",
            r"身份[:：]\s*([^，,。;\n]+)",
            r"角色定位[:：]\s*([^，,。;\n]+)",
            r"角色类型[:：]\s*([^，,。;\n]+)",
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
        source_file = Path(str(source or "").strip())
        if not source_id:
            return self._missing_source_pack(action, source_id)
        if not source_file.exists():
            return {
                "ok": False,
                "blocked": True,
                "next_action": "provide_source_file",
                "error": "missing_source_file",
                "message": f"源文件不存在: {source_file}",
                "source_id": source_id,
                "source_file": str(source_file),
            }
        try:
            return self.novel_service.extract_source(
                source_id=source_id,
                source_file=source_file,
                focus=focus,
            )
        except NovelServiceError as exc:
            return {
                "ok": False,
                "blocked": True,
                "error": exc.code,
                "message": str(exc),
                "source_id": source_id,
            }

    def _source_root(self, source_id: str) -> Path:
        return (
            self.project_root
            / "data"
            / "novels"
            / self.novel_id
            / "data"
            / "sources"
            / source_id
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
        outline_text = self.story_planning_store.read_outline_draft()
        outline_ready = bool(outline_text.strip())
        persona_paths = [
            item["path"]
            for item in self.story_planning_store.list_character_documents()
        ]
        persona_ready = bool(persona_paths)

        if not ideation_ready:
            missing_items.append("ideation_summary")
        if not foundation_ready:
            missing_items.append("foundation")
        if not outline_ready:
            missing_items.append("outline")
        if not persona_ready:
            missing_items.append("persona")

        return {
            "required_assets": required_assets,
            "missing_items": missing_items,
            "persona_paths": persona_paths,
        }

    def _build_handoff_summary(self, readiness: dict[str, Any]) -> str:
        persona_paths = readiness.get("persona_paths", [])
        summary_lines = [
            "Goethe 已完成到 Dante 的交接准备。",
            "可写资产已收齐：ideation_summary、foundation、outline、persona。",
        ]
        if persona_paths:
            summary_lines.append("主要人物文件: " + "；".join(str(item) for item in persona_paths))
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

    def generate_foundation_draft(self, request_text: str) -> dict[str, Any]:
        return self._wrap(
            "generate_foundation_draft",
            self.runtime.generate_foundation_draft(request_text),
        )

    def generate_character_draft(self, request_text: str) -> dict[str, Any]:
        return self._wrap(
            "generate_character_draft",
            self.runtime.generate_character_draft(request_text),
        )

    def generate_outline_draft(self, request_text: str) -> dict[str, Any]:
        return self._wrap(
            "generate_outline_draft",
            self.runtime.generate_outline_draft(request_text),
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
