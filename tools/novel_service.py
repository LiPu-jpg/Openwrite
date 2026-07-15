"""Unified application service for creator-facing novel operations.

CLI, Studio and long-session agents should enter novel workflows through this
surface.  Legacy CLI executors remain implementation adapters for now, while
input normalization, canonical packet assembly and result semantics live here.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from pathlib import Path
from threading import Lock
from typing import Any, cast

import yaml


class NovelServiceError(RuntimeError):
    def __init__(self, message: str, *, code: str = "OPERATION_FAILED"):
        super().__init__(message)
        self.code = code


class NovelApplicationService:
    """One application boundary shared by CLI, Studio and agents."""

    @classmethod
    def initialize(
        cls,
        project_root: Path,
        novel_id: str,
        title: str = "",
    ) -> NovelApplicationService:
        from tools.init_project import init_project

        try:
            init_project(Path(project_root), novel_id, title)
        except Exception as exc:
            raise NovelServiceError(f"初始化失败: {exc}", code="INVALID_INPUT") from exc
        return cls(Path(project_root))

    def __init__(
        self,
        project_root: Path,
        *,
        writer_executor: Callable[[Path, dict[str, Any]], dict[str, Any]] | None = None,
        review_executor: Callable[[Path, dict[str, Any]], dict[str, Any]] | None = None,
        source_executor: Callable[[Path, dict[str, Any]], dict[str, Any]] | None = None,
        task_lock: Lock | None = None,
    ):
        self.project_root = Path(project_root).resolve()
        self.config_path = self.project_root / "novel_config.yaml"
        self.config = self._load_config()
        self.novel_id = str(self.config.get("novel_id") or "")
        if not self.novel_id:
            raise NovelServiceError("novel_config.yaml 缺少 novel_id", code="INVALID_PROJECT")
        self.novel_root = self.project_root / "data" / "novels" / self.novel_id
        self._writer_executor = writer_executor
        self._review_executor = review_executor
        self._source_executor = source_executor
        self._task_lock = task_lock or Lock()

    def refresh(self) -> None:
        self.config = self._load_config()
        self.novel_id = str(self.config.get("novel_id") or self.novel_id)
        self.novel_root = self.project_root / "data" / "novels" / self.novel_id

    def sync_status(self) -> dict[str, Any]:
        from tools.source_sync import collect_sync_status

        return cast(
            dict[str, Any],
            collect_sync_status(self.project_root, self.novel_id),
        )

    def sync(self) -> dict[str, Any]:
        from tools.source_sync import run_sync

        before = self.sync_status()
        run_sync(self.project_root, self.novel_id)
        return {"before": before, "after": self.sync_status()}

    def workspace_snapshot(self) -> dict[str, Any]:
        snapshot: dict[str, Any] = self.workspace_state().to_dict()
        return snapshot

    def workspace_state(self) -> Any:
        from tools.novel_workspace import build_workspace_snapshot

        self.refresh()
        return build_workspace_snapshot(self.project_root, self.config)

    def focus_snapshot(self) -> dict[str, Any]:
        from tools.novel_workspace import load_creative_focus

        return asdict(load_creative_focus(self.project_root, self.novel_id))

    def render_focus(self) -> str:
        from tools.novel_workspace import load_creative_focus, render_creative_focus

        rendered: str = render_creative_focus(
            load_creative_focus(self.project_root, self.novel_id)
        )
        return rendered

    def update_focus(
        self,
        *,
        goal: str,
        must_keep: list[str] | None = None,
        must_avoid: list[str] | None = None,
        notes: list[str] | None = None,
    ) -> Path:
        from tools.novel_workspace import save_creative_focus

        clean_goal = str(goal or "").strip()
        if not clean_goal:
            raise NovelServiceError("当前阶段目标不能为空", code="INVALID_INPUT")
        path: Path = save_creative_focus(
            self.project_root,
            self.novel_id,
            goal=clean_goal,
            must_keep=must_keep or [],
            must_avoid=must_avoid or [],
            notes=notes or [],
        )
        return path

    def clear_focus(self) -> Path:
        from tools.novel_workspace import (
            CreativeFocus,
            current_focus_path,
            render_creative_focus,
        )

        path: Path = current_focus_path(self.project_root, self.novel_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_creative_focus(CreativeFocus()), encoding="utf-8")
        return path

    def import_book(
        self,
        source: Path,
        *,
        arc_id: str | None = None,
        start_number: int | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        from tools.novel_workspace import import_manuscript, update_project_progress

        target_arc = str(arc_id or self.config.get("current_arc") or "arc_001")
        if not re.fullmatch(r"arc_\d+", target_arc):
            raise NovelServiceError("篇 ID 必须形如 arc_001", code="INVALID_INPUT")
        try:
            imported = import_manuscript(
                self.project_root,
                self.novel_id,
                Path(source),
                arc_id=target_arc,
                start_number=start_number,
                force=force,
            )
        except FileExistsError as exc:
            raise NovelServiceError(str(exc), code="CONFLICT") from exc
        except (OSError, ValueError) as exc:
            raise NovelServiceError(str(exc), code="INVALID_INPUT") from exc
        next_number = self._chapter_number(imported[-1].chapter_id) + 1
        next_chapter = f"ch_{next_number:03d}"
        update_project_progress(
            self.project_root,
            current_chapter=next_chapter,
            current_arc=target_arc,
        )
        self.refresh()
        return {
            "arc_id": target_arc,
            "next_chapter": next_chapter,
            "writing_units": sum(item.writing_units for item in imported),
            "imported": [
                {
                    "chapter_id": item.chapter_id,
                    "title": item.title,
                    "writing_units": item.writing_units,
                }
                for item in imported
            ],
        }

    def export_book(
        self,
        output: Path,
        *,
        format_name: str = "md",
        title: str = "",
    ) -> Path:
        from tools.novel_workspace import export_manuscript

        try:
            path: Path = export_manuscript(
                self.project_root,
                self.novel_id,
                Path(output),
                format_name=format_name,
                title=title or str(self.config.get("title") or ""),
            )
            return path
        except (OSError, ValueError) as exc:
            raise NovelServiceError(str(exc), code="INVALID_INPUT") from exc

    def market_radar(
        self,
        *,
        platforms: list[str] | None = None,
        top_n: int = 5,
    ) -> dict[str, Any]:
        """Run novel-market research behind the application boundary."""
        from tools.agent import AgentContext
        from tools.llm import LLMClient, LLMConfig
        from tools.radar import RadarAgent

        if top_n < 1 or top_n > 50:
            raise NovelServiceError(
                "推荐数量必须在 1 到 50 之间", code="INVALID_INPUT"
            )
        try:
            llm_config = LLMConfig.from_env()
            agent = RadarAgent(
                AgentContext(
                    LLMClient(llm_config),
                    llm_config.model,
                    str(self.project_root),
                )
            )
            result = asyncio.run(
                agent.scan_market(platforms=platforms, top_n=top_n)
            )
        except Exception as exc:
            raise NovelServiceError(f"市场分析失败: {exc}") from exc
        return {
            "recommendations": [
                {
                    "confidence": float(item.confidence),
                    "platform": str(item.platform),
                    "genre": str(item.genre),
                    "concept": str(item.concept),
                    "reasoning": str(item.reasoning),
                    "benchmarks": list(item.benchmarks or []),
                }
                for item in result.platform_recommendations
            ],
            "trends": list(result.trends or []),
        }

    def create_document(
        self, *, kind: str, name: str, description: str = ""
    ) -> Path:
        from tools.shared_documents import (
            normalize_character_document,
            normalize_world_entity_document,
        )

        if kind not in {"character", "world"}:
            raise NovelServiceError("仅支持创建人物或世界设定文档", code="INVALID_INPUT")
        clean_name = str(name or "").strip()
        if (
            not clean_name
            or len(clean_name) > 80
            or any(char in clean_name for char in "/\\\x00")
        ):
            raise NovelServiceError(
                "名称不能为空、不能超过 80 字或包含路径分隔符",
                code="INVALID_INPUT",
            )
        safe_name = re.sub(r"[^\w\u3400-\u9fff.-]+", "_", clean_name).strip("._")
        if not safe_name:
            raise NovelServiceError("名称无效", code="INVALID_INPUT")
        if kind == "character":
            path = self.novel_root / "src" / "characters" / f"{safe_name}.md"
            content = normalize_character_document(
                "",
                fallback_id=safe_name,
                fallback_name=clean_name,
                fallback_description=description,
            )
        else:
            path = self.novel_root / "src" / "world" / "entities" / f"{safe_name}.md"
            content = normalize_world_entity_document(
                "",
                fallback_id=safe_name,
                fallback_name=clean_name,
                fallback_summary=description,
            )
        if path.exists():
            raise NovelServiceError("同名文档已存在", code="CONFLICT")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def context_preview(self, chapter_id: str = "next") -> dict[str, Any]:
        target = self.resolve_chapter_id(chapter_id)
        packet = self.assemble_packet(target)
        return {
            "chapter_id": target,
            "target_words": int(packet.get("target_words") or 0),
            "characters": list((packet.get("character_documents") or {}).keys()),
            "markdown": str(packet.get("outline") or ""),
            "packet": packet,
        }

    def assemble_packet(self, chapter_id: str) -> dict[str, Any]:
        from tools.chapter_assembler import ChapterAssemblerV2

        style_id = str(self.config.get("style_id") or self.novel_id)
        packet = ChapterAssemblerV2(
            project_root=self.project_root,
            novel_id=self.novel_id,
            style_id=style_id,
        ).assemble(chapter_id)
        if is_dataclass(packet):
            payload = asdict(cast(Any, packet))
        elif isinstance(packet, dict):
            payload = dict(packet)
        else:
            payload = {}
            for key in (
                "novel_id",
                "chapter_id",
                "target_words",
                "author_intent",
                "creative_focus",
                "story_background",
                "previous_chapter_content",
                "current_state",
                "ledger",
                "relationships",
                "style_documents",
                "character_documents",
                "concept_documents",
                "prompt_sections",
                "foundation",
            ):
                value = getattr(packet, key, None)
                if value not in (None, ""):
                    payload[key] = value
        if hasattr(packet, "to_markdown"):
            payload["outline"] = str(packet.to_markdown())
        return payload

    def write_chapter(self, payload: dict[str, Any]) -> dict[str, Any]:
        chapter_id = self.resolve_chapter_id(str(payload.get("chapter_id") or "next"))
        args = dict(payload)
        args["chapter_id"] = chapter_id
        args.setdefault("context_packet", self.assemble_packet(chapter_id))
        args["guidance"] = str(args.get("guidance") or "").strip()
        args["target_words"] = self._positive_int(args.get("target_words"))
        args["temperature"] = float(args.get("temperature") or 0.7)
        executor = self._writer_executor or self._default_writer_executor
        if not self._task_lock.acquire(blocking=False):
            raise NovelServiceError("已有写作或审稿任务正在运行", code="PROJECT_BUSY")
        try:
            result = executor(self.project_root, args)
        finally:
            self._task_lock.release()
        self._ensure_ok(result, fallback="写作失败")
        if self._writer_executor is not None:
            self._record_write_lifecycle(chapter_id, result)
        return result

    def review_chapter(self, chapter_id: str) -> dict[str, Any]:
        target = self.resolve_chapter_id(chapter_id, latest=True)
        executor = self._review_executor or self._default_review_executor
        if not self._task_lock.acquire(blocking=False):
            raise NovelServiceError("已有写作或审稿任务正在运行", code="PROJECT_BUSY")
        try:
            if self._review_executor is None:
                result = executor(self.project_root, {"chapter_id": target})
            else:
                from tools.project_lock import ProjectBusyError, ProjectWriteLock

                try:
                    with ProjectWriteLock(
                        self.project_root,
                        self.novel_id,
                        operation=f"review:{target}",
                    ):
                        result = executor(self.project_root, {"chapter_id": target})
                except ProjectBusyError as exc:
                    raise NovelServiceError(str(exc), code="PROJECT_BUSY") from exc
        finally:
            self._task_lock.release()
        self._ensure_ok(result, fallback="审稿失败")
        if self._review_executor is not None:
            from tools.review_store import ReviewStore

            ReviewStore(self.project_root, self.novel_id).save(target, result)
            self._record_review_lifecycle(target, result)
        return result

    def multi_write(self, payload: dict[str, Any]) -> dict[str, Any]:
        from tools.chapter_pipeline import execute_multi_agent_chapter

        args = dict(payload)
        args["chapter_id"] = self.resolve_chapter_id(
            str(args.get("chapter_id") or "next")
        )
        if not self._task_lock.acquire(blocking=False):
            raise NovelServiceError(
                "已有写作或审稿任务正在运行", code="PROJECT_BUSY"
            )
        try:
            result = execute_multi_agent_chapter(self.project_root, args)
        finally:
            self._task_lock.release()
        self._ensure_ok(result, fallback="多 Agent 写作失败")
        return result

    def continuity(self) -> dict[str, Any]:
        from tools.foreshadowing_manager import ForeshadowingDAGManager
        from tools.truth_manager import TruthFilesManager
        from tools.workflow_scheduler import WorkflowScheduler

        truth = TruthFilesManager(self.project_root, self.novel_id).load_truth_files()
        manager = ForeshadowingDAGManager(self.project_root, self.novel_id)
        pending = manager.get_pending_nodes(min_weight=1)
        valid, validation_errors = manager.validate_dag()
        workflows = []
        for workflow in WorkflowScheduler(
            self.project_root, self.novel_id
        ).list_active_workflows():
            workflows.append(
                {
                    "chapter_id": workflow.chapter_id,
                    "current_stage": workflow.current_stage,
                    "error": workflow.error,
                    "stages": [
                        {
                            "name": stage.name,
                            "status": stage.status,
                            "message": stage.message,
                        }
                        for stage in workflow.stages
                    ],
                }
            )
        return {
            "truth": {
                "current_state": truth.current_state,
                "ledger": truth.ledger,
                "relationships": truth.relationships,
            },
            "foreshadowing": {
                "nodes": [node.model_dump() for node in pending],
                **manager.get_statistics(),
            },
            "foreshadowing_validation": {
                "valid": valid,
                "errors": validation_errors,
            },
            "workflows": workflows,
        }

    def manage_foreshadowing(self, payload: dict[str, Any]) -> dict[str, Any]:
        from tools.foreshadowing_manager import ForeshadowingDAGManager

        manager = ForeshadowingDAGManager(self.project_root, self.novel_id)
        action = str(payload.get("action") or "create")
        node_id = str(payload.get("node_id") or "").strip()
        if not node_id:
            raise NovelServiceError("伏笔 ID 不能为空", code="INVALID_INPUT")
        if action == "create":
            created = manager.create_node(
                node_id=node_id,
                content=str(payload.get("content") or "").strip(),
                weight=self._positive_int(payload.get("weight")) or 5,
                layer=str(payload.get("layer") or "支线"),
                created_at=str(payload.get("created_at") or ""),
                target_chapter=str(payload.get("target_chapter") or "") or None,
            )
            if not created:
                raise NovelServiceError(f"伏笔节点已存在: {node_id}", code="CONFLICT")
            result = {"node_id": node_id, "status": "created"}
        elif action == "update":
            status = str(payload.get("status") or "").strip()
            if not manager.update_node_status(node_id, status):
                raise NovelServiceError(f"伏笔节点不存在: {node_id}", code="NOT_FOUND")
            result = {"node_id": node_id, "status": status}
        else:
            raise NovelServiceError("未知伏笔操作", code="INVALID_INPUT")
        return {"result": result, "continuity": self.continuity()}

    def extract_source(
        self,
        *,
        source_id: str,
        source_file: Path,
        focus: str = "style",
        chunk_size: int = 30000,
    ) -> dict[str, Any]:
        source_id = self._validate_source_id(source_id)
        source_file = Path(source_file)
        if focus not in {"style", "setting"}:
            raise NovelServiceError("提取类型必须是 style 或 setting", code="INVALID_INPUT")
        if not source_file.is_file():
            raise NovelServiceError(f"来源文本不存在: {source_file}", code="NOT_FOUND")
        if chunk_size <= 0:
            raise NovelServiceError("分块字数必须大于 0", code="INVALID_INPUT")
        executor = self._source_executor or self._default_source_executor
        payload = {
            "source_id": source_id,
            "source_file": str(source_file),
            "focus": focus,
            "chunk_size": chunk_size,
            "content": source_file.read_text(encoding="utf-8"),
        }
        try:
            result = executor(self.project_root, payload)
        except NovelServiceError:
            raise
        except Exception as exc:
            raise NovelServiceError(f"来源提取失败: {exc}") from exc
        self._ensure_ok(result, fallback="来源提取失败")
        return result

    def review_source(self, source_id: str) -> dict[str, Any]:
        from tools.source_pack import SourcePackService

        source_id = self._validate_source_id(source_id)
        self._require_source_pack(source_id)
        try:
            report = SourcePackService(
                self.project_root, self.novel_id
            ).render_review(source_id)
        except Exception as exc:
            raise NovelServiceError(f"来源审阅失败: {exc}") from exc
        return {
            "ok": True,
            "source_id": source_id,
            "review_report": report,
        }

    def promote_source(self, source_id: str, target: str = "all") -> dict[str, Any]:
        from tools.source_pack import SourcePackService

        source_id = self._validate_source_id(source_id)
        if target not in {"style", "setting", "world", "all"}:
            raise NovelServiceError("晋升目标无效", code="INVALID_INPUT")
        self._require_source_pack(source_id)
        try:
            promoted = SourcePackService(
                self.project_root, self.novel_id
            ).promote(source_id, target)
        except Exception as exc:
            raise NovelServiceError(f"来源晋升失败: {exc}") from exc
        self.refresh()
        return {
            "ok": True,
            "source_id": source_id,
            "target": target,
            "promoted": promoted,
        }

    def synthesize_style(self, source_id: str) -> dict[str, Any]:
        from tools.style_synthesizer import synthesize_style_document

        source_id = self._validate_source_id(source_id)
        try:
            result = cast(
                dict[str, Any],
                synthesize_style_document(
                    self.project_root,
                    self.novel_id,
                    source_id,
                ),
            )
        except Exception as exc:
            raise NovelServiceError(f"风格合成失败: {exc}") from exc
        return {**result, "ok": True, "source_id": source_id}

    def resolve_chapter_id(self, chapter_id: str, *, latest: bool = False) -> str:
        value = str(chapter_id or "").strip()
        manuscript_root = self.novel_root / "data" / "manuscript"
        chapter_ids = {
            path.stem
            for path in manuscript_root.glob("**/ch_*.md")
            if re.fullmatch(r"ch_\d+", path.stem)
        }
        if value == "next":
            number = max((self._chapter_number(item) for item in chapter_ids), default=0) + 1
            value = f"ch_{number:03d}"
        elif value == "latest" or (latest and not value):
            value = max(chapter_ids, key=self._chapter_number) if chapter_ids else "ch_001"
        if not re.fullmatch(r"ch_\d+", value):
            raise NovelServiceError("章节 ID 必须形如 ch_001", code="INVALID_INPUT")
        return value

    def _load_config(self) -> dict[str, Any]:
        if not self.config_path.exists():
            raise NovelServiceError("未找到 novel_config.yaml", code="INVALID_PROJECT")
        try:
            data = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise NovelServiceError(f"项目配置无法读取: {exc}", code="INVALID_PROJECT") from exc
        return data if isinstance(data, dict) else {}

    def _validate_source_id(self, source_id: str) -> str:
        value = str(source_id or "").strip()
        if not value or not re.fullmatch(r"[\w.-]{1,64}", value) or ".." in value:
            raise NovelServiceError(
                "来源 ID 只能包含字母、数字、中文、点、横线或下划线",
                code="INVALID_INPUT",
            )
        return value

    def _require_source_pack(self, source_id: str) -> Path:
        source_root = self.novel_root / "data" / "sources" / source_id
        if not source_root.is_dir():
            raise NovelServiceError("来源包不存在", code="NOT_FOUND")
        return source_root

    @staticmethod
    def _positive_int(value: Any) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return 0
        return parsed if parsed > 0 else 0

    @staticmethod
    def _chapter_number(chapter_id: str) -> int:
        match = re.search(r"(\d+)", chapter_id)
        return int(match.group(1)) if match else 0

    @staticmethod
    def _ensure_ok(result: dict[str, Any], *, fallback: str) -> None:
        if result.get("ok"):
            return
        raise NovelServiceError(
            str(result.get("error") or fallback),
            code=str(result.get("code") or "OPERATION_FAILED"),
        )

    @staticmethod
    def _default_writer_executor(root: Path, args: dict[str, Any]) -> dict[str, Any]:
        from tools.chapter_pipeline import execute_write_chapter

        result: dict[str, Any] = execute_write_chapter(root, args)
        return result

    @staticmethod
    def _default_review_executor(root: Path, args: dict[str, Any]) -> dict[str, Any]:
        from tools.chapter_pipeline import execute_review_chapter

        result: dict[str, Any] = execute_review_chapter(root, args)
        return result

    @staticmethod
    def _default_source_executor(
        root: Path, args: dict[str, Any]
    ) -> dict[str, Any]:
        from tools.source_pack import SourcePackService

        config = yaml.safe_load((root / "novel_config.yaml").read_text(encoding="utf-8")) or {}
        result: dict[str, Any] = SourcePackService(
            root, str(config.get("novel_id") or "")
        ).extract(
            str(args["source_id"]),
            Path(str(args["source_file"])),
            focus=str(args.get("focus") or "style"),
            chunk_size=int(args.get("chunk_size") or 30000),
        )
        return result

    def _record_write_lifecycle(
        self, chapter_id: str, result: dict[str, Any]
    ) -> None:
        from tools.workflow_scheduler import WorkflowScheduler

        scheduler = WorkflowScheduler(self.project_root, self.novel_id)
        workflow = scheduler.load_or_create(chapter_id)
        statuses = {stage.name: stage.status for stage in workflow.stages}
        if statuses.get("context_assembly") != "completed":
            scheduler.start_stage(workflow, "context_assembly")
            scheduler.complete_stage(
                workflow,
                "context_assembly",
                message="canonical context assembled",
                data={"chapter_id": chapter_id},
            )
        if statuses.get("writing") != "completed":
            scheduler.start_stage(workflow, "writing")
            scheduler.complete_stage(
                workflow,
                "writing",
                message="chapter committed",
                data={"draft_path": str(result.get("draft_path") or "")},
            )
        self._sync_book_state(
            chapter_id,
            review_passed=None,
            action_prefix="application_write",
        )

    def _record_review_lifecycle(
        self, chapter_id: str, result: dict[str, Any]
    ) -> None:
        from tools.workflow_scheduler import WorkflowScheduler

        scheduler = WorkflowScheduler(self.project_root, self.novel_id)
        workflow = scheduler.load_or_create(chapter_id)
        errors: list[str] = []
        warnings: list[str] = []
        for issue in result.get("issue_details", []):
            if not isinstance(issue, dict):
                continue
            description = str(issue.get("description") or "").strip()
            if not description:
                continue
            if str(issue.get("severity") or "").lower() == "critical":
                errors.append(description)
            else:
                warnings.append(description)
        scheduler.start_stage(workflow, "review")
        scheduler.complete_stage(
            workflow,
            "review",
            message="chapter reviewed via application service",
            data={
                "passed": bool(result.get("passed")),
                "errors": errors,
                "warnings": warnings,
            },
        )
        self._sync_book_state(
            chapter_id,
            review_passed=bool(result.get("passed")),
            action_prefix="application_review",
        )

    def _sync_book_state(
        self,
        chapter_id: str,
        *,
        review_passed: bool | None,
        action_prefix: str,
    ) -> None:
        from tools.agent.book_state import BookStage, BookStateStore

        store = BookStateStore(self.project_root, self.novel_id)
        state = store.load_or_create()
        if self._chapter_number(chapter_id) >= self._chapter_number(
            state.current_chapter
        ):
            state.current_chapter = chapter_id
        if review_passed is None:
            state.stage = BookStage.REVIEW_AND_REVISE
            state.blocking_reason = "review_not_run"
            state.last_agent_action = f"{action_prefix}_pending_review"
        elif review_passed:
            state.stage = BookStage.CHAPTER_PREFLIGHT
            state.blocking_reason = ""
            state.last_agent_action = f"{action_prefix}_review_passed"
        else:
            state.stage = BookStage.REVIEW_AND_REVISE
            state.blocking_reason = "review_revision_requested"
            state.last_agent_action = f"{action_prefix}_review_failed"
        store.save(state)
