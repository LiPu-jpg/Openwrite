"""Shared tool executor registry for all novel interaction surfaces."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import yaml

from tools.novel_service import NovelApplicationService, NovelServiceError
from tools.project_lock import ProjectBusyError, ProjectWriteLock
from tools.text_range import (
    normalized_text_spans,
    select_folded_range_anchors,
    select_normalized_text_span,
)

ToolExecutor = Callable[[dict[str, Any]], dict[str, Any]]

DOCUMENT_LONG_OLD_TEXT_CHARS = 240


def _service_error(exc: NovelServiceError) -> dict[str, Any]:
    return {
        "ok": False,
        "blocked": exc.code == "PROJECT_BUSY",
        "code": exc.code,
        "error": str(exc),
    }


def _service_executor(project_root: Path, operation: str) -> ToolExecutor:
    def execute(args: dict[str, Any]) -> dict[str, Any]:
        try:
            service = NovelApplicationService(project_root)
            if operation == "write_chapter":
                return service.write_chapter(args)
            if operation == "review_chapter":
                return service.review_chapter(
                    str(args.get("chapter_id") or "latest"),
                    strict=bool(args.get("strict", False)),
                    dimensions=(
                        args.get("dimensions")
                        if isinstance(args.get("dimensions"), list)
                        else None
                    ),
                )
            raise NovelServiceError(f"未知应用服务操作: {operation}")
        except NovelServiceError as exc:
            return _service_error(exc)

    return execute


def _project(project_root: Path) -> tuple[dict[str, Any], str]:
    path = project_root / "novel_config.yaml"
    if not path.exists():
        raise NovelServiceError("未找到项目配置", code="INVALID_PROJECT")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict) or not data.get("novel_id"):
        raise NovelServiceError("项目配置缺少 novel_id", code="INVALID_PROJECT")
    return data, str(data["novel_id"])


def _application_executor(project_root: Path, operation: str) -> ToolExecutor:
    def execute(args: dict[str, Any]) -> dict[str, Any]:
        try:
            config, novel_id = _project(project_root)
            if operation == "get_status":
                from tools.agent.book_state import BookStateStore
                from tools.novel_workspace import list_chapters
                from tools.truth_manager import TruthFilesManager

                chapters = list_chapters(project_root, novel_id)
                snapshots = TruthFilesManager(project_root, novel_id).list_snapshots()
                current_arc = config.get("current_arc")
                current_chapter = config.get("current_chapter")
                state_store = BookStateStore(project_root, novel_id)
                if state_store.path.exists():
                    state = state_store.load_or_create()
                    current_arc = state.current_arc or current_arc
                    current_chapter = state.current_chapter or current_chapter
                return {
                    "novel_id": novel_id,
                    "current_arc": current_arc,
                    "current_chapter": current_chapter,
                    "chapters_written": len(chapters),
                    "snapshots": len(snapshots),
                }
            if operation == "get_context":
                from tools.context_builder import ContextBuilder

                chapter_id = str(args.get("chapter_id") or "next")
                preview = NovelApplicationService(project_root).context_preview(
                    chapter_id
                )
                packet = cast(dict[str, Any], preview["packet"])
                sections = packet.get("prompt_sections", {})
                try:
                    window_size = max(1, min(20, int(args.get("window_size") or 5)))
                except (TypeError, ValueError):
                    window_size = 5
                generation_context = ContextBuilder(
                    project_root, novel_id
                ).build_generation_context(
                    str(preview["chapter_id"]), window_size=window_size
                )
                return {
                    "chapter_id": preview["chapter_id"],
                    "target_words": preview["target_words"],
                    "chapter_goals": packet.get("chapter_goals", []),
                    "sections": list(sections) if isinstance(sections, dict) else [],
                    "compression": {
                        "message_budget": dict(generation_context.compression),
                        "packet_documents": dict(packet.get("compression", {}) or {}),
                    },
                    "context_packet": packet,
                }
            if operation == "search_project":
                from tools.project_search import ProjectSearchIndex

                novel_root = project_root / "data" / "novels" / novel_id
                return ProjectSearchIndex(novel_root).search(
                    str(args.get("query") or ""),
                    scope=str(args.get("scope") or "all"),
                    limit=int(args.get("limit") or 20),
                )
            if operation == "query_library":
                from tools.library_catalog import query_library

                novel_root = project_root / "data" / "novels" / novel_id
                return query_library(
                    novel_root,
                    scope=str(args.get("scope") or "all"),
                    category=str(args.get("category") or ""),
                    query=str(args.get("query") or ""),
                    limit=int(args.get("limit") or 80),
                )
            if operation == "read_project_document":
                return _read_project_document(project_root, novel_id, args)
            if operation == "edit_project_document":
                return _edit_project_document(project_root, novel_id, args)
            if operation == "list_chapters":
                from tools.novel_workspace import list_chapters

                novel_root = project_root / "data" / "novels" / novel_id
                return {
                    "chapters": [
                        {
                            "number": int(item.chapter_id.split("_")[-1]),
                            "chapter_id": item.chapter_id,
                            "title": item.title,
                            "path": item.path.relative_to(novel_root).as_posix(),
                        }
                        for item in list_chapters(project_root, novel_id)
                    ]
                }
            if operation == "get_truth_files":
                from tools.runtime_state import RuntimeStateManager
                from tools.truth_manager import TruthFilesManager

                truth = TruthFilesManager(project_root, novel_id).load_truth_files()
                state = RuntimeStateManager(project_root, novel_id).load(
                    {
                        "current_state": truth.current_state,
                        "ledger": truth.ledger,
                        "relationships": truth.relationships,
                    }
                )
                return {
                    "schema_version": state.schema_version,
                    "revision": state.revision,
                    "current_state": truth.current_state,
                    "ledger": truth.ledger,
                    "relationships": truth.relationships,
                }
            if operation == "get_character_state":
                from tools.character_state_index import CharacterStateIndex

                return CharacterStateIndex(project_root, novel_id).query(
                    str(args.get("name") or ""),
                    field=str(args.get("field") or ""),
                    lookback=args.get("lookback") or 50,
                )
            if operation == "create_character":
                service = NovelApplicationService(project_root)
                path = service.create_document(
                    kind="character",
                    name=str(args.get("name") or ""),
                    description=str(args.get("description") or ""),
                    content=str(args.get("content") or ""),
                )
                return {
                    "ok": True,
                    "file": str(path),
                    "name": str(args.get("name") or ""),
                    "safe_name": path.stem,
                }
            if operation == "create_outline":
                content = str(args.get("outline_content") or "")
                path = project_root / "data" / "novels" / novel_id / "src" / "outline.md"
                if path.exists():
                    return {
                        "ok": False,
                        "error": "当前大纲已存在，请使用带 revision 和确认流程的增量编辑工具",
                        "code": "OUTLINE_ALREADY_EXISTS",
                    }
                from tools.outline_contract import validate_outline_markdown

                validation_errors = validate_outline_markdown(content, novel_id)
                if validation_errors:
                    return {
                        "ok": False,
                        "error": "大纲不符合 OpenWrite 四级写入契约",
                        "code": "INVALID_OUTLINE_STRUCTURE",
                        "validation_errors": validation_errors,
                    }
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
                return {"ok": True, "file": str(path), "size": len(content)}
            if operation == "get_outline_structure":
                from tools.outline_tree import build_outline_structure

                return build_outline_structure(
                    project_root / "data" / "novels" / novel_id,
                    chapter_id=str(args.get("chapter_id") or ""),
                )
            if operation == "edit_outline_structure":
                from tools.outline_tree import OutlineEditError, mutate_outline_structure
                from tools.outline_tree import build_outline_structure as build_structure

                root = project_root / "data" / "novels" / novel_id
                outline_path = root / "src" / "outline.md"
                if not outline_path.exists():
                    return {"ok": False, "error": "当前没有可编辑的大纲"}
                original = outline_path.read_text(encoding="utf-8")
                try:
                    edit = mutate_outline_structure(
                        root,
                        operation=str(args.get("operation") or ""),
                        revision=str(args.get("revision") or ""),
                        node_id=str(args.get("node_id") or ""),
                        title=str(args.get("title") or ""),
                        summary=str(args.get("summary") or ""),
                        kind=str(args.get("kind") or ""),
                    )
                except OutlineEditError as exc:
                    return {
                        "ok": False,
                        "applied": False,
                        "conflict": exc.code == "conflict",
                        "error": str(exc),
                    }
                revised = str(edit["content"])
                diff = "".join(
                    difflib.unified_diff(
                        original.splitlines(keepends=True),
                        revised.splitlines(keepends=True),
                        fromfile="src/outline.md",
                        tofile="src/outline.md (preview)",
                    )
                )
                if not bool(args.get("confirm")):
                    return {
                        "ok": True,
                        "applied": False,
                        "message": edit["message"],
                        "renumbered": edit.get("renumbered", []),
                        "skipped_renumbering": edit.get("skipped_renumbering", []),
                        "revision": str(args.get("revision") or ""),
                        "diff": diff,
                        "next_action": "使用相同参数并设置 confirm=true",
                    }
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=outline_path.parent,
                    prefix=".outline.",
                    suffix=".tmp",
                    delete=False,
                ) as handle:
                    handle.write(revised)
                    temporary = Path(handle.name)
                temporary.replace(outline_path)
                from tools.git_checkpoint import GitCheckpointManager

                checkpoint_path = outline_path.relative_to(project_root).as_posix()
                checkpoint = GitCheckpointManager(project_root).checkpoint(
                    [checkpoint_path],
                    "outline: incremental tree edit",
                )
                return {
                    "ok": True,
                    "applied": True,
                    "message": edit["message"],
                    "selection_hint": edit["selection_hint"],
                    "renumbered": edit.get("renumbered", []),
                    "skipped_renumbering": edit.get("skipped_renumbering", []),
                    "diff": diff,
                    "checkpoint": checkpoint.to_dict(),
                    "outline": build_structure(root),
                }
            if operation == "update_truth_file":
                from tools.context_schema import normalize_truth_file_key
                from tools.runtime_state import RuntimeStateError, RuntimeStateManager
                from tools.truth_manager import TruthFilesManager

                key = normalize_truth_file_key(str(args.get("file_name") or ""))
                if key not in {"current_state", "ledger", "relationships"}:
                    return {
                        "ok": False,
                        "applied": False,
                        "code": "INVALID_TRUTH_FILE",
                        "error": f"Unknown file: {key}",
                    }
                content = str(args.get("content") or "").strip()
                if not content:
                    return {
                        "ok": False,
                        "applied": False,
                        "code": "EMPTY_RUNTIME_DELTA",
                        "error": "追加事实不能为空",
                    }
                try:
                    source_revision = int(args.get("source_revision"))
                except (TypeError, ValueError):
                    return {
                        "ok": False,
                        "applied": False,
                        "code": "SOURCE_REVISION_REQUIRED",
                        "error": "必须先读取 get_truth_files 返回的 revision",
                    }

                truth_manager = TruthFilesManager(project_root, novel_id)
                truth = truth_manager.load_truth_files()
                state_manager = RuntimeStateManager(project_root, novel_id)
                state = state_manager.load(
                    {
                        "current_state": truth.current_state,
                        "ledger": truth.ledger,
                        "relationships": truth.relationships,
                    }
                )
                chapter_id = str(
                    args.get("chapter_id") or config.get("current_chapter") or "manual"
                ).strip()
                try:
                    updated = state_manager.apply(
                        state,
                        {
                            "schema_version": 1,
                            "chapter_id": chapter_id,
                            "source_revision": source_revision,
                            "operations": [
                                {
                                    "op": "append",
                                    "collection": key,
                                    "value": content,
                                }
                            ],
                        },
                    )
                except (RuntimeStateError, ValueError) as exc:
                    return {
                        "ok": False,
                        "applied": False,
                        "conflict": "版本冲突" in str(exc),
                        "code": "RUNTIME_DELTA_REJECTED",
                        "error": str(exc),
                        "revision": state.revision,
                    }

                revised = state_manager.render(updated)[key]
                original = str(getattr(truth, key, "") or "")
                diff = "".join(
                    difflib.unified_diff(
                        original.splitlines(keepends=True),
                        revised.splitlines(keepends=True),
                        fromfile=f"data/world/{key}.md",
                        tofile=f"data/world/{key}.md (preview)",
                    )
                )
                result = {
                    "ok": True,
                    "applied": bool(args.get("confirm")),
                    "file": key,
                    "chapter_id": chapter_id,
                    "source_revision": state.revision,
                    "revision": updated.revision,
                    "operation": "append",
                    "diff": diff,
                }
                if not bool(args.get("confirm")):
                    result["next_action"] = (
                        "确认后使用相同 file_name/content/chapter_id/source_revision，"
                        "并设置 confirm=true"
                    )
                    return result
                state_manager.save_with_projections(updated)
                result["size"] = len(revised)
                return result
            if operation == "query_world":
                from tools.world_query import get_entity, list_entities

                entity_id = str(args.get("entity_id") or "")
                if entity_id:
                    entity = get_entity(novel_id, entity_id, project_root)
                    if not entity:
                        return {"ok": False, "error": f"实体不存在: {entity_id}"}
                    return {"entity": entity}
                entities = list_entities(
                    novel_id,
                    entity_type=args.get("type"),
                    project_root=project_root,
                )
                return {"entities": entities, "count": len(entities)}
            if operation == "get_world_relations":
                from tools.world_query import get_relations_topology

                graph = get_relations_topology(novel_id, project_root)
                return {
                    "entities": graph["nodes"],
                    "relations": [
                        {
                            "source": edge["source"],
                            "target": edge["target"],
                            "description": edge["label"],
                        }
                        for edge in graph["edges"]
                    ],
                    "total_entities": graph["totals"]["nodes"],
                    "total_relations": graph["totals"]["edges"],
                }
            if operation == "search_relation_targets":
                from tools.world_query import search_relation_targets

                return search_relation_targets(
                    novel_id,
                    str(args.get("query") or ""),
                    project_root=project_root,
                    entity_type=str(args.get("type") or args.get("entity_type") or ""),
                    limit=int(args.get("limit") or 20),
                )
            if operation == "edit_world_relation":
                from tools.world_query import edit_world_relation

                return edit_world_relation(
                    novel_id,
                    str(args.get("source_id") or ""),
                    str(args.get("target_id") or ""),
                    str(args.get("description") or ""),
                    project_root=project_root,
                    action=str(args.get("action") or "upsert"),
                    base_revision=str(args.get("base_revision") or ""),
                    confirm=bool(args.get("confirm")),
                )
            if operation == "edit_world_relations":
                from tools.world_query import edit_world_relations

                return edit_world_relations(
                    novel_id,
                    args.get("relations") if isinstance(args.get("relations"), list) else None,
                    project_root=project_root,
                    confirm=bool(args.get("confirm")),
                    base_revisions=(
                        args.get("base_revisions")
                        if isinstance(args.get("base_revisions"), dict)
                        else {}
                    ),
                    preview_token=str(args.get("preview_token") or ""),
                    preview_tokens=(
                        args.get("preview_tokens")
                        if isinstance(args.get("preview_tokens"), list)
                        else None
                    ),
                )
            if operation in {
                "create_foreshadowing",
                "update_foreshadowing",
                "list_foreshadowing",
                "validate_foreshadowing",
            }:
                return _foreshadowing(project_root, novel_id, operation, args)
            if operation in {
                "get_workflow_status",
                "start_workflow",
                "advance_workflow",
            }:
                return _workflow(project_root, novel_id, operation, args)
            if operation == "validate_truth":
                return _validate_truth(project_root, novel_id, args)
            if operation == "extract_dialogue_fingerprint":
                return _dialogue_fingerprint(project_root, novel_id, args)
            if operation == "validate_post_write":
                return _validate_post_write(project_root, novel_id, args)
            if operation == "chunk_text":
                return _chunk_text(args)
            if operation == "compress_section":
                return _compress_section(project_root, novel_id, args)
            if operation in {
                "get_chapter_run_v2",
                "record_chapter_intervention",
                "update_chapter_intervention",
                "cancel_chapter_run_v2",
            }:
                from tools.chapter_run_v2 import chapter_run_v2_action

                action_by_operation = {
                    "get_chapter_run_v2": str(args.get("action") or "list"),
                    "record_chapter_intervention": "record_intervention",
                    "update_chapter_intervention": "update_intervention",
                    "cancel_chapter_run_v2": "cancel",
                }
                return chapter_run_v2_action(
                    project_root,
                    novel_id,
                    {**args, "action": action_by_operation[operation]},
                )
            if operation == "diagnose_runtime":
                from tools.runtime_diagnostics import RuntimeDiagnosticsService

                return RuntimeDiagnosticsService(
                    project_root, novel_id
                ).run().model_dump(mode="json")
            if operation == "manage_rolling_plan":
                from tools.rolling_planning import rolling_plan_action

                return rolling_plan_action(project_root, novel_id, args)
            if operation == "manage_narrative_forecast":
                from tools.narrative_forecast import narrative_forecast_action

                return narrative_forecast_action(project_root, novel_id, args)
            if operation in {"manage_manuscript_versions", "manage_annotations"}:
                from tools.manuscript_editing import manuscript_editing_action

                if operation == "manage_manuscript_versions":
                    action_map = {
                        "list": "versions",
                        "get": "version",
                        "checkpoint": "checkpoint",
                        "restore": "restore",
                    }
                    default_action = "list"
                else:
                    action_map = {
                        "list": "annotations",
                        "create": "annotate",
                        "resolve": "resolve_annotation",
                    }
                    default_action = "list"
                requested = str(args.get("action") or default_action)
                if requested not in action_map:
                    return {
                        "ok": False,
                        "blocked": False,
                        "code": "INVALID_EDITING_ACTION",
                        "error": "未知正文编辑操作",
                    }
                return manuscript_editing_action(
                    project_root,
                    novel_id,
                    {**args, "action": action_map[requested]},
                )
            from tools.agent.audit_tools import AUDIT_TOOL_NAMES, execute_audit_tool

            if operation in AUDIT_TOOL_NAMES:
                return execute_audit_tool(project_root, novel_id, operation, args)
            raise NovelServiceError(f"未知应用工具: {operation}")
        except NovelServiceError as exc:
            return _service_error(exc)
        except Exception as exc:
            from tools.chapter_run_v2 import ChapterRunV2Error
            from tools.manuscript_editing import ManuscriptEditingError
            from tools.narrative_forecast import NarrativeForecastError
            from tools.rolling_planning import RollingPlanningError

            if isinstance(exc, ChapterRunV2Error):
                return {
                    "ok": False,
                    "blocked": exc.code
                    in {"REVISION_REQUIRED", "STALE_REVISION", "CONFIRMATION_REQUIRED"},
                    "code": exc.code,
                    "error": str(exc),
                }
            if isinstance(exc, RollingPlanningError):
                return {
                    "ok": False,
                    "blocked": exc.code.startswith("STALE_"),
                    "code": exc.code,
                    "error": str(exc),
                }
            if isinstance(exc, NarrativeForecastError):
                return {
                    "ok": False,
                    "blocked": exc.code.startswith("STALE_"),
                    "code": exc.code,
                    "error": str(exc),
                }
            if isinstance(exc, ManuscriptEditingError):
                return {
                    "ok": False,
                    "blocked": exc.code
                    in {"CONFIRMATION_REQUIRED", "STALE_REVISION"},
                    "code": exc.code,
                    "error": str(exc),
                }
            raise

    return execute


def _read_project_document(
    project_root: Path, novel_id: str, args: dict[str, Any]
) -> dict[str, Any]:
    path_result = _resolve_project_document(project_root, novel_id, args)
    if isinstance(path_result, dict):
        return path_result
    path, relative = path_result
    content = path.read_text(encoding="utf-8")
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    revision = content_hash[:16]
    try:
        max_chars = max(1000, min(80000, int(args.get("max_chars") or 24000)))
    except (TypeError, ValueError):
        max_chars = 24000
    truncated = len(content) > max_chars
    return {
        "ok": True,
        "path": relative,
        "revision": revision,
        "source_revision": f"sha256:{content_hash}",
        "content": content[:max_chars],
        "truncated": truncated,
        "size": len(content),
    }


def _edit_project_document(
    project_root: Path, novel_id: str, args: dict[str, Any]
) -> dict[str, Any]:
    action = str(args.get("action") or "").strip().lower()
    confirm = bool(args.get("confirm")) or action in {"apply", "undo"}
    if not action:
        action = "apply" if confirm else "preview"
    if action not in {"preview", "apply", "reject", "retry", "undo"}:
        return {"ok": False, "applied": False, "error": "invalid_document_plan_action"}
    stored_preview_path: Path | None = None
    preview_token = str(args.get("preview_token") or "").strip()
    if action == "reject":
        _record, stored_preview_path, preview_error = _load_document_edit_preview(
            project_root, novel_id, preview_token
        )
        if preview_error or stored_preview_path is None:
            return {
                "ok": False,
                "applied": False,
                "error": "document_preview_invalid",
                "message": preview_error,
            }
        stored_preview_path.unlink(missing_ok=True)
        return {
            "ok": True,
            "applied": False,
            "status": "rejected",
            "preview_token": preview_token,
        }
    if action == "retry":
        stored_preview, stored_preview_path, preview_error = _load_document_edit_preview(
            project_root, novel_id, preview_token
        )
        if preview_error:
            return {
                "ok": False,
                "applied": False,
                "error": "document_preview_invalid",
                "message": preview_error,
            }
        args = {
            "action": "preview",
            "path": stored_preview["path"],
            "edits": stored_preview["edits"],
        }
        confirm = False
    if confirm and preview_token:
        stored_preview, stored_preview_path, preview_error = (
            _load_document_edit_preview(project_root, novel_id, preview_token)
        )
        if preview_error:
            return {
                "ok": False,
                "applied": False,
                "error": "document_preview_invalid",
                "message": preview_error,
            }
        args = {
            **args,
            "path": stored_preview["path"],
            "edits": stored_preview["edits"],
            "revision": stored_preview["revision"],
            "confirmed_result_revision": stored_preview.get("result_revision", ""),
        }

    path_result = _resolve_project_document(project_root, novel_id, args)
    if isinstance(path_result, dict):
        return path_result
    path, relative = path_result
    edits = args.get("edits")
    if not isinstance(edits, list) or not edits:
        return {"ok": False, "error": "edits 不能为空"}
    if len(edits) > 50:
        return {"ok": False, "error": "单次最多编辑 50 个片段"}
    original = path.read_text(encoding="utf-8")
    revision = hashlib.sha256(original.encode("utf-8")).hexdigest()[:16]
    if confirm and str(
        args.get("revision") or args.get("base_revision") or ""
    ).strip() != revision:
        return {
            "ok": False,
            "applied": False,
            "changed": False,
            "path": relative,
            "revision": revision,
            "error": "document_revision_conflict",
            "message": "文件已变化，请重新读取并预览后确认。",
        }
    revised = original
    applied: list[dict[str, Any]] = []
    for index, edit in enumerate(edits):
        if not isinstance(edit, dict):
            return {"ok": False, "error": f"第 {index + 1} 个修改不是对象"}
        start_text = str(edit.get("start_text") or "").strip()
        end_text = str(edit.get("end_text") or "").strip()
        old_text = str(edit.get("old_text") or "")
        new_text = str(edit.get("new_text") or "")
        replace_all = bool(edit.get("replace_all"))
        if start_text or end_text:
            if not start_text or not end_text:
                missing = "start_text" if not start_text else "end_text"
                return {
                    "ok": False,
                    "error": "missing_range_anchor",
                    "message": (
                        f"第 {index + 1} 个修改缺少 {missing}；"
                        "范围替换需要同时提供 start_text 和 end_text。"
                    ),
                    "revision": revision,
                    "details": {
                        "field_path": f"$.edits[{index}].{missing}",
                        "retry_revision": revision,
                    },
                }
            replacement = _replace_document_text_range(
                revised,
                start_text,
                end_text,
                new_text,
            )
            if not replacement["ok"]:
                return {
                    "ok": False,
                    "error": replacement["error"],
                    "message": f"第 {index + 1} 个修改{replacement['message']}",
                    "revision": revision,
                    "details": {
                        "field_paths": [
                            f"$.edits[{index}].start_text",
                            f"$.edits[{index}].end_text",
                        ],
                        "retry_revision": revision,
                        **dict(replacement.get("details") or {}),
                    },
                }
            revised = str(replacement["source"])
            applied.append(
                {
                    "index": index + 1,
                    "mode": "range",
                    "automatic": False,
                    "start_line": replacement["start_line"],
                    "end_line": replacement["end_line"],
                    "replacements": 1,
                    "replace_all": False,
                }
            )
            continue
        if not old_text:
            return {
                "ok": False,
                "error": "missing_edit_selector",
                "message": (
                    f"第 {index + 1} 个修改没有定位信息；"
                    "长范围使用 start_text/end_text，短句使用 old_text。"
                ),
                "revision": revision,
                "details": {
                    "field_paths": [
                        f"$.edits[{index}].start_text",
                        f"$.edits[{index}].end_text",
                        f"$.edits[{index}].old_text",
                    ],
                    "retry_revision": revision,
                },
            }
        occurrences = revised.count(old_text)
        if occurrences == 0:
            normalized_selection = select_normalized_text_span(revised, old_text)
            if normalized_selection["ok"]:
                start = int(normalized_selection["start"])
                end = int(normalized_selection["end"])
                revised = revised[:start] + new_text + revised[end:]
                applied.append(
                    {
                        "index": index + 1,
                        "mode": "normalized_text",
                        "automatic": True,
                        "normalizations": normalized_selection["details"][
                            "normalizations"
                        ],
                        "replacements": 1,
                        "replace_all": False,
                    }
                )
                continue
            if normalized_selection["error"] == "ambiguous_normalized_text":
                return {
                    "ok": False,
                    "error": "ambiguous_old_text",
                    "message": (
                        f"第 {index + 1} 个 old_text 规范化引号与空白后匹配到多处；"
                        "请改用唯一的 start_text/end_text。"
                    ),
                    "revision": revision,
                    "details": {
                        "field_path": f"$.edits[{index}].old_text",
                        "retry_revision": revision,
                        **dict(normalized_selection.get("details") or {}),
                    },
                }
            long_text = len(old_text) >= DOCUMENT_LONG_OLD_TEXT_CHARS
            anchor_selection = (
                select_folded_range_anchors(
                    revised,
                    old_text,
                    min_text_chars=DOCUMENT_LONG_OLD_TEXT_CHARS,
                )
                if long_text
                else None
            )
            if anchor_selection and anchor_selection["ok"]:
                replacement = _replace_document_text_range(
                    revised,
                    str(anchor_selection["start_text"]),
                    str(anchor_selection["end_text"]),
                    new_text,
                )
                if replacement["ok"]:
                    revised = str(replacement["source"])
                    applied.append(
                        {
                            "index": index + 1,
                            "mode": "range",
                            "automatic": True,
                            "anchor_chars": anchor_selection["details"]["anchor_chars"],
                            "start_line": replacement["start_line"],
                            "end_line": replacement["end_line"],
                            "replacements": 1,
                            "replace_all": False,
                        }
                    )
                    continue
            if anchor_selection and (
                anchor_selection["error"] == "ambiguous_text_range"
                or (
                    anchor_selection.get("details", {}).get("start_occurrences") == 1
                    and anchor_selection.get("details", {}).get("end_occurrences") == 1
                )
            ):
                return {
                    "ok": False,
                    "error": anchor_selection["error"],
                    "message": (
                        f"第 {index + 1} 个长 old_text 自动定位失败："
                        f"{anchor_selection['message']}"
                    ),
                    "revision": revision,
                    "details": {
                        "field_path": f"$.edits[{index}].old_text",
                        "retry_revision": revision,
                        **dict(anchor_selection.get("details") or {}),
                    },
                }
            diagnostics = _document_edit_diagnostics(revised, old_text)
            if long_text:
                diagnostics["suggested_old_text"] = ""
                diagnostics["suggested_old_text_truncated"] = False
                diagnostics.update(
                    dict(anchor_selection.get("details") or {})
                    if anchor_selection
                    else {}
                )
            if long_text:
                failure_message = (
                    f"第 {index + 1} 个长 old_text 未匹配；"
                    "请重新读取文件，并改用唯一的 start_text/end_text。"
                )
            elif diagnostics.get("suggested_old_text"):
                failure_message = (
                    f"第 {index + 1} 个 old_text 不存在；"
                    "请使用 details.suggested_old_text 返回的准确原文重试。"
                )
            else:
                failure_message = (
                    f"第 {index + 1} 个 old_text 不存在，请重新读取文件。"
                )
            return {
                "ok": False,
                "error": "old_text_not_found",
                "message": failure_message,
                "revision": revision,
                "details": {
                    "field_path": f"$.edits[{index}].old_text",
                    "retry_revision": revision,
                    **diagnostics,
                },
            }
        if occurrences > 1 and not replace_all:
            return {
                "ok": False,
                "error": "ambiguous_old_text",
                "message": (
                    f"第 {index + 1} 个 old_text 匹配到 {occurrences} 处；"
                    "请改用唯一的 start_text/end_text。"
                ),
                "revision": revision,
            }
        revised = revised.replace(old_text, new_text, -1 if replace_all else 1)
        applied.append(
            {
                "index": index + 1,
                "mode": "text",
                "replacements": occurrences if replace_all else 1,
                "replace_all": replace_all,
            }
        )
    diff = "".join(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            revised.splitlines(keepends=True),
            fromfile=f"a/{relative}",
            tofile=f"b/{relative}",
        )
    )
    payload = {
        "ok": True,
        "applied": False,
        "changed": revised != original,
        "path": relative,
        "revision": revision,
        "edit_count": len(applied),
        "edits": applied,
        "diff": diff,
        "next_action": "用户确认后仅传 preview_token，并设置 confirm=true",
    }
    from tools.mutation_summary import build_mutation_summary, document_entity_kind

    source_revision = "sha256:" + hashlib.sha256(original.encode("utf-8")).hexdigest()
    predicted_revision = "sha256:" + hashlib.sha256(revised.encode("utf-8")).hexdigest()
    confirmed_result_revision = str(args.get("confirmed_result_revision") or "")
    if confirm and confirmed_result_revision and confirmed_result_revision != predicted_revision:
        return {
            "ok": False,
            "applied": False,
            "error": "document_preview_result_mismatch",
            "message": "确认内容与已展示预览不一致，请重新预览。",
        }
    payload["mutation_summary"] = build_mutation_summary(
        operation="document.change_plan",
        entity_kind=document_entity_kind(relative),
        entity_id=path.stem,
        path=relative,
        before=original,
        after=revised,
        source_revision=source_revision,
        result_revision=predicted_revision,
        field_prefix="content",
        flatten=False,
        execution_status="proposed",
    )
    if not confirm:
        if revised != original:
            payload["preview_token"] = _save_document_edit_preview(
                project_root,
                novel_id,
                relative,
                revision,
                edits,
                predicted_revision,
            )
            if stored_preview_path is not None:
                stored_preview_path.unlink(missing_ok=True)
                payload["retried_from"] = preview_token
        return payload
    if revised == original:
        if stored_preview_path is not None:
            stored_preview_path.unlink(missing_ok=True)
        return payload
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(revised)
        temporary = Path(handle.name)
    acceptance: dict[str, Any] | None = None
    acceptance_error: dict[str, Any] | None = None
    is_manuscript = relative.startswith("data/manuscript/") and bool(
        re.fullmatch(r"ch_\d+", path.stem)
    )
    try:
        if is_manuscript:
            from tools.manuscript_acceptance import (
                ManuscriptAcceptanceError,
                ManuscriptAcceptanceService,
            )

            with ProjectWriteLock(
                project_root,
                novel_id,
                operation=f"document_change_plan:{relative}",
            ):
                os.replace(temporary, path)
                try:
                    acceptance = ManuscriptAcceptanceService(
                        project_root, novel_id
                    ).start_acceptance(
                        path.stem,
                        source="agent",
                        expected_previous_revision=source_revision,
                    )
                except ManuscriptAcceptanceError as exc:
                    acceptance_error = {
                        "status": "reconcile_required",
                        "code": exc.code,
                        "message": str(exc),
                    }
        else:
            os.replace(temporary, path)
    except ProjectBusyError as exc:
        temporary.unlink(missing_ok=True)
        return {
            "ok": False,
            "applied": False,
            "blocked": True,
            "error": "PROJECT_BUSY",
            "message": str(exc),
        }
    result_revision = hashlib.sha256(revised.encode("utf-8")).hexdigest()
    undo_preview_token = _save_document_edit_preview(
        project_root,
        novel_id,
        relative,
        result_revision[:16],
        [{"old_text": revised, "new_text": original}],
        source_revision,
    )
    if stored_preview_path is not None:
        stored_preview_path.unlink(missing_ok=True)
    result = {
        **payload,
        "applied": True,
        "status": "applied",
        "revision": result_revision[:16],
        "undo_preview_token": undo_preview_token,
        "mutation_summary": build_mutation_summary(
            operation="document.change_apply" if action != "undo" else "document.change_undo",
            entity_kind=document_entity_kind(relative),
            entity_id=path.stem,
            path=relative,
            before=original,
            after=revised,
            source_revision=source_revision,
            result_revision=f"sha256:{result_revision}",
            field_prefix="content",
            flatten=False,
        ),
    }
    if acceptance is not None:
        result["acceptance"] = {
            "operation_id": str(acceptance.get("operation_id") or ""),
            "status": str(acceptance.get("status") or "pending"),
            "accepted_revision": str(
                acceptance.get("expected_previous_revision") or ""
            ),
            "current_revision": f"sha256:{result_revision}",
            "message": "正文已保存，关联事实待更新",
        }
    elif acceptance_error is not None:
        result["acceptance"] = {
            **acceptance_error,
            "current_revision": f"sha256:{result_revision}",
        }
    return result


def project_document_change_plan(
    project_root: Path, novel_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """Public boundary for preview/apply/reject/retry/undo document plans."""
    return _edit_project_document(project_root, novel_id, payload)


def _replace_document_text_range(
    source: str,
    start_text: str,
    end_text: str,
    new_text: str,
) -> dict[str, Any]:
    start_anchor = str(start_text or "").strip()
    end_anchor = str(end_text or "").strip()
    if not start_anchor or not end_anchor:
        return {
            "ok": False,
            "error": "missing_range_anchor",
            "message": "范围替换需要同时提供 start_text 和 end_text。",
            "details": {},
        }
    start_spans = normalized_text_spans(source, start_anchor)
    end_spans = normalized_text_spans(source, end_anchor)
    if not start_spans or not end_spans:
        missing = []
        if not start_spans:
            missing.append("start_text")
        if not end_spans:
            missing.append("end_text")
        return {
            "ok": False,
            "error": "text_range_not_found",
            "message": f"找不到{'和'.join(missing)}锚点。",
            "details": {
                "missing_anchors": missing,
                "start_occurrences": len(start_spans),
                "end_occurrences": len(end_spans),
            },
        }

    ranges: list[tuple[int, int]] = []
    if start_anchor == end_anchor:
        ranges = list(start_spans)
    else:
        for start, start_end in start_spans:
            for end, end_end in end_spans:
                if end >= start_end:
                    ranges.append((start, end_end))
    if not ranges:
        return {
            "ok": False,
            "error": "text_range_not_found",
            "message": "找到了首尾锚点，但它们的顺序不成立。",
            "details": {
                "start_occurrences": len(start_spans),
                "end_occurrences": len(end_spans),
            },
        }
    if len(ranges) > 1:
        return {
            "ok": False,
            "error": "ambiguous_text_range",
            "message": (
                f"首尾锚点组合成 {len(ranges)} 个可能范围；"
                "请增加锚点文字，直到只定位一处。"
            ),
            "details": {
                "range_count": len(ranges),
                "start_occurrences": len(start_spans),
                "end_occurrences": len(end_spans),
            },
        }

    start, end = ranges[0]
    return {
        "ok": True,
        "source": source[:start] + str(new_text or "") + source[end:],
        "start_line": source.count("\n", 0, start) + 1,
        "end_line": source.count("\n", 0, end) + 1,
    }


def _document_edit_diagnostics(
    source: str,
    submitted: str,
    *,
    max_suggestion_chars: int = 6000,
) -> dict[str, Any]:
    """Return an exact current span only when a fuzzy match is unambiguous."""

    normalized_source, source_positions = _collapse_whitespace_with_positions(source)
    normalized_submitted, _ = _collapse_whitespace_with_positions(submitted.strip())
    suggested = ""
    similarity = 0.0
    if normalized_submitted:
        matches = [
            match.start()
            for match in re.finditer(
                re.escape(normalized_submitted),
                normalized_source,
            )
        ]
        if len(matches) == 1:
            start = source_positions[matches[0]]
            normalized_end = matches[0] + len(normalized_submitted) - 1
            end = source_positions[normalized_end] + 1
            suggested = source[start:end]
            similarity = 1.0

    if not suggested:
        source_lines = source.splitlines(keepends=True)
        submitted_line_count = max(1, len(submitted.splitlines()))
        candidates: list[tuple[float, str]] = []
        for start in range(max(0, len(source_lines) - submitted_line_count + 1)):
            candidate = "".join(source_lines[start : start + submitted_line_count])
            if not submitted.endswith(("\n", "\r")):
                candidate = candidate.rstrip("\r\n")
            score = difflib.SequenceMatcher(
                None,
                " ".join(submitted.split()),
                " ".join(candidate.split()),
            ).ratio()
            candidates.append((score, candidate))
        candidates.sort(key=lambda item: item[0], reverse=True)
        if candidates:
            best_score, best_candidate = candidates[0]
            second_score = candidates[1][0] if len(candidates) > 1 else 0.0
            if best_score >= 0.8 and best_score - second_score >= 0.08:
                suggested = best_candidate
                similarity = best_score

    suggestion_truncated = len(suggested) > max_suggestion_chars
    if suggestion_truncated:
        suggested = ""
    return {
        "suggested_old_text": suggested,
        "suggested_old_text_truncated": suggestion_truncated,
        "similarity": round(similarity, 3),
    }


def _collapse_whitespace_with_positions(value: str) -> tuple[str, list[int]]:
    normalized: list[str] = []
    positions: list[int] = []
    in_whitespace = False
    for index, character in enumerate(value):
        if character.isspace():
            if not in_whitespace:
                normalized.append(" ")
                positions.append(index)
            in_whitespace = True
            continue
        normalized.append(character)
        positions.append(index)
        in_whitespace = False
    return "".join(normalized), positions


def _document_edit_preview_root(project_root: Path, novel_id: str) -> Path:
    return (
        project_root
        / "data"
        / "novels"
        / novel_id
        / "data"
        / "workflows"
        / "document_edit_previews"
    )


def _document_edit_preview_record(
    novel_id: str,
    path: str,
    revision: str,
    edits: list[Any],
    result_revision: str = "",
) -> dict[str, Any]:
    record = {
        "schema_version": 2 if result_revision else 1,
        "novel_id": novel_id,
        "path": path,
        "revision": revision,
        "edits": edits,
    }
    if result_revision:
        record["result_revision"] = result_revision
    return record


def _document_edit_preview_token(record: dict[str, Any]) -> str:
    serialized = json.dumps(
        record,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:24]


def _save_document_edit_preview(
    project_root: Path,
    novel_id: str,
    path: str,
    revision: str,
    edits: list[Any],
    result_revision: str = "",
) -> str:
    record = _document_edit_preview_record(
        novel_id, path, revision, edits, result_revision
    )
    token = _document_edit_preview_token(record)
    preview_root = _document_edit_preview_root(project_root, novel_id)
    preview_root.mkdir(parents=True, exist_ok=True)
    target = preview_root / f"{token}.json"
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=preview_root,
        prefix=f".{token}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(record, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, target)
    return token


def _load_document_edit_preview(
    project_root: Path,
    novel_id: str,
    preview_token: str,
) -> tuple[dict[str, Any], Path | None, str]:
    if not re.fullmatch(r"[a-f0-9]{24}", preview_token):
        return {}, None, "文档预览凭据格式无效，请重新预览。"
    preview_root = _document_edit_preview_root(project_root, novel_id).resolve()
    path = (preview_root / f"{preview_token}.json").resolve()
    if preview_root not in path.parents or not path.is_file():
        return {}, None, "文档预览凭据不存在或已使用，请重新预览。"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, None, "文档预览凭据损坏，请重新预览。"
    if not isinstance(raw, dict):
        return {}, None, "文档预览凭据损坏，请重新预览。"
    edits = raw.get("edits")
    if (
        raw.get("schema_version") not in {1, 2}
        or raw.get("novel_id") != novel_id
        or not isinstance(raw.get("path"), str)
        or not isinstance(raw.get("revision"), str)
        or not isinstance(edits, list)
        or (
            raw.get("schema_version") == 2
            and not re.fullmatch(r"sha256:[0-9a-f]{64}", str(raw.get("result_revision") or ""))
        )
    ):
        return {}, None, "文档预览凭据与当前作品不匹配，请重新预览。"
    record = _document_edit_preview_record(
        novel_id,
        raw["path"],
        raw["revision"],
        edits,
        str(raw.get("result_revision") or ""),
    )
    if _document_edit_preview_token(record) != preview_token:
        return {}, None, "文档预览凭据校验失败，请重新预览。"
    return record, path, ""


def _resolve_project_document(
    project_root: Path, novel_id: str, args: dict[str, Any]
) -> tuple[Path, str] | dict[str, Any]:
    raw_path = str(args.get("path") or args.get("source_path") or "").strip()
    if not raw_path:
        return {"ok": False, "error": "缺少 path"}
    novel_root = (project_root / "data" / "novels" / novel_id).resolve()
    candidate = (novel_root / raw_path).resolve()
    allowed_roots = [
        (novel_root / "src").resolve(),
        (novel_root / "data" / "manuscript").resolve(),
        (novel_root / "data" / "foreshadowing").resolve(),
    ]
    if not any(candidate == root or root in candidate.parents for root in allowed_roots):
        return {
            "ok": False,
            "error": "只能读取或修改小说 src、manuscript、foreshadowing 资产",
        }
    if not candidate.is_file():
        return {"ok": False, "error": f"文件不存在: {raw_path}"}
    try:
        relative = candidate.relative_to(novel_root).as_posix()
    except ValueError:
        return {"ok": False, "error": "文件不在当前小说项目内"}
    return candidate, relative


def _chapter_text(project_root: Path, novel_id: str, chapter_id: str) -> str:
    root = project_root / "data" / "novels" / novel_id / "data" / "manuscript"
    if chapter_id == "latest":
        candidates = sorted(
            root.glob("**/ch_*.md"),
            key=lambda path: int(path.stem.split("_")[-1]),
        )
        if candidates:
            chapter_id = candidates[-1].stem
    for pattern in (f"**/{chapter_id}.md", f"**/{chapter_id}_*.md"):
        matches = sorted(root.glob(pattern))
        if matches:
            return matches[0].read_text(encoding="utf-8")
    return ""


def _validate_truth(
    project_root: Path, novel_id: str, args: dict[str, Any]
) -> dict[str, Any]:
    from tools.state_validator import StateValidator
    from tools.truth_manager import TruthFilesManager

    chapter_id = str(args.get("chapter_id") or "latest")
    truth = TruthFilesManager(project_root, novel_id).load_truth_files()
    issues = StateValidator().validate(
        current_state=truth.current_state,
        content=_chapter_text(project_root, novel_id, chapter_id),
        chapter_number=(
            int(chapter_id.split("_")[-1])
            if chapter_id.startswith("ch_") and chapter_id[3:].isdigit()
            else 1
        ),
    )
    return {
        "chapter_id": chapter_id,
        "issues": [
            {
                "severity": issue.severity,
                "category": issue.category,
                "description": issue.description,
            }
            for issue in issues
        ],
        "issue_count": len(issues),
        "critical_count": sum(issue.severity == "critical" for issue in issues),
    }


def _dialogue_fingerprint(
    project_root: Path, novel_id: str, args: dict[str, Any]
) -> dict[str, Any]:
    from tools.dialogue_fingerprint import DialogueFingerprintExtractor

    chapter_id = str(args.get("chapter_id") or "latest")
    content = _chapter_text(project_root, novel_id, chapter_id)
    if not content:
        return {"ok": False, "error": f"未找到章节: {chapter_id}"}
    names = args.get("character_names")
    fingerprints = DialogueFingerprintExtractor().extract(
        [content], character_names=names if isinstance(names, list) and names else None
    )
    return {
        "chapter_id": chapter_id,
        "fingerprints": [
            {
                "character": item.character_name,
                "avg_sentence_length": item.avg_sentence_length,
                "common_bigrams": item.common_bigrams[:5],
                "question_ratio": item.question_ratio,
                "speech_patterns": item.speech_patterns[:5],
                "summary": item.to_prompt_text(),
            }
            for item in fingerprints
        ],
    }


def _validate_post_write(
    project_root: Path, novel_id: str, args: dict[str, Any]
) -> dict[str, Any]:
    from tools.post_validator import PostWriteValidator

    chapter_id = str(args.get("chapter_id") or "latest")
    content = _chapter_text(project_root, novel_id, chapter_id)
    if not content:
        return {"ok": False, "error": f"未找到章节: {chapter_id}"}
    violations = PostWriteValidator().validate(content)
    return {
        "chapter_id": chapter_id,
        "violations": [
            {
                "severity": item.severity,
                "rule": item.rule,
                "description": item.description,
                "location": item.location,
            }
            for item in violations
        ],
        "error_count": sum(item.severity == "error" for item in violations),
        "warning_count": sum(item.severity == "warning" for item in violations),
        "passed": not violations,
    }


def _chunk_text(args: dict[str, Any]) -> dict[str, Any]:
    from tools.text_chunker import TextChunker

    path = Path(str(args.get("file_path") or ""))
    if not path.exists():
        return {"ok": False, "error": f"文件不存在: {path}"}
    if not path.is_file():
        return {"ok": False, "error": "不支持的路径类型"}
    result = TextChunker(chunk_size=int(args.get("chunk_size") or 30000)).chunk_file(
        path
    )
    chunks = [
        {
            "index": item.index,
            "chapter_range": item.chapter_range,
            "char_count": item.char_count,
        }
        for item in result.chunks
    ]
    return {"file": str(path), "total_chunks": len(chunks), "chunks": chunks}


def _compress_section(
    project_root: Path, novel_id: str, args: dict[str, Any]
) -> dict[str, Any]:
    from tools.progressive_compressor import ProgressiveCompressor

    compressor = ProgressiveCompressor(
        project_root, str(args.get("novel_id") or novel_id)
    )
    arc_id = str(args.get("arc_id") or "arc_001")
    section_id = str(args.get("section_id") or "")
    result = (
        compressor.compress_section(arc_id, section_id)
        if section_id
        else compressor.compress_arc(arc_id)
    )
    compressed = getattr(
        result,
        "compressed_text",
        getattr(result, "merged_summary", ""),
    )
    total_words = getattr(
        result,
        "word_count",
        getattr(result, "total_word_count", 0),
    )
    ratio = (len(compressed) / total_words) if total_words else 0
    payload: dict[str, Any] = {
        "arc_id": arc_id,
        "compressed": str(compressed or "")[:500],
        "compression_ratio": ratio,
    }
    if section_id:
        payload["section_id"] = section_id
    return payload


def _foreshadowing(
    project_root: Path,
    novel_id: str,
    operation: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    from tools.foreshadowing_manager import ForeshadowingDAGManager

    manager = ForeshadowingDAGManager(project_root, novel_id)
    if operation == "create_foreshadowing":
        payload = dict(args)
        payload["action"] = "create"
        result = NovelApplicationService(project_root).manage_foreshadowing(payload)
        return cast(dict[str, Any], result["result"])
    if operation == "update_foreshadowing":
        payload = dict(args)
        payload["action"] = "update"
        result = NovelApplicationService(project_root).manage_foreshadowing(payload)
        return cast(dict[str, Any], result["result"])
    if operation == "validate_foreshadowing":
        valid, errors = manager.validate_dag()
        return {"valid": valid, "errors": errors}
    nodes = manager.get_nodes(
        status=str(args.get("status") or "") or None,
        min_weight=int(args.get("min_weight") or 1),
        layer=str(args.get("layer") or "") or None,
    )
    statistics = manager.get_statistics()
    return {
        "nodes": [node.model_dump() for node in nodes],
        "total": statistics["total"],
        "by_status": statistics["by_status"],
        "by_layer": statistics["by_layer"],
    }


def _workflow(
    project_root: Path,
    novel_id: str,
    operation: str,
    args: dict[str, Any],
) -> dict[str, Any]:
    from tools.workflow_scheduler import WorkflowScheduler

    scheduler = WorkflowScheduler(project_root, novel_id)
    chapter_id = str(args.get("chapter_id") or "")
    if operation == "start_workflow":
        state = scheduler.create_workflow(chapter_id)
        return {
            "chapter_id": state.chapter_id,
            "current_stage": state.current_stage,
            "message": f"工作流已创建: {chapter_id}",
        }
    if operation == "advance_workflow":
        state = scheduler.load_workflow(chapter_id)
        if state is None:
            return {"ok": False, "error": f"未找到工作流: {chapter_id}"}
        stage = str(args.get("stage_name") or "")
        if stage:
            scheduler.start_stage(state, stage)
        else:
            scheduler.complete_stage(
                state,
                state.current_stage,
                message="advanced via agent tool",
            )
        return {
            "chapter_id": state.chapter_id,
            "current_stage": state.current_stage,
            "message": f"已推进到: {state.current_stage}",
        }
    if chapter_id:
        state = scheduler.load_workflow(chapter_id)
        if state is None:
            return {"ok": False, "error": f"未找到工作流: {chapter_id}"}
        return {
            "chapter_id": state.chapter_id,
            "current_stage": state.current_stage,
            "stages": {stage.name: stage.to_dict() for stage in state.stages},
            "is_complete": scheduler.is_complete(state),
        }
    active_states = scheduler.list_active_workflows()
    active = [state.chapter_id for state in active_states]
    complete = [
        path.stem.removeprefix("wf_")
        for path in sorted(scheduler.workflow_dir.glob("wf_*.yaml"))
        if (state := scheduler.load_workflow(path.stem.removeprefix("wf_")))
        and scheduler.is_complete(state)
    ]
    return {"active": active, "complete": complete, "active_count": len(active)}


def build_tool_executors(project_root: Path) -> dict[str, ToolExecutor]:
    """Build the canonical tool registry shared by CLI and both novel agents."""
    project_root = Path(project_root).resolve()
    executors: dict[str, ToolExecutor] = {
        "write_chapter": _service_executor(project_root, "write_chapter"),
        "review_chapter": _service_executor(project_root, "review_chapter"),
    }
    application_operations = {
        "get_status",
        "get_context",
        "search_project",
        "query_library",
        "read_project_document",
        "edit_project_document",
        "list_chapters",
        "create_outline",
        "get_outline_structure",
        "edit_outline_structure",
        "create_character",
        "get_truth_files",
        "get_character_state",
        "update_truth_file",
        "create_foreshadowing",
        "list_foreshadowing",
        "update_foreshadowing",
        "validate_foreshadowing",
        "query_world",
        "get_world_relations",
        "search_relation_targets",
        "edit_world_relation",
        "edit_world_relations",
        "get_workflow_status",
        "start_workflow",
        "advance_workflow",
        "validate_truth",
        "extract_dialogue_fingerprint",
        "validate_post_write",
        "chunk_text",
        "compress_section",
        "inspect_agent_context",
        "list_chapter_runs",
        "get_chapter_run_v2",
        "record_chapter_intervention",
        "update_chapter_intervention",
        "cancel_chapter_run_v2",
        "diagnose_runtime",
        "manage_rolling_plan",
        "manage_narrative_forecast",
        "manage_manuscript_versions",
        "manage_annotations",
        "get_runtime_state",
        "get_chapter_review",
        "get_task_activity",
        "get_goethe_handoff",
    }
    executors.update(
        {
            name: _application_executor(project_root, name)
            for name in application_operations
        }
    )
    return executors
