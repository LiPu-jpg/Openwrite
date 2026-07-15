"""Shared tool executor registry for all novel interaction surfaces."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import yaml

from tools.novel_service import NovelApplicationService, NovelServiceError

ToolExecutor = Callable[[dict[str, Any]], dict[str, Any]]


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
                    str(args.get("chapter_id") or "latest")
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
                chapter_id = str(args.get("chapter_id") or "next")
                preview = NovelApplicationService(project_root).context_preview(
                    chapter_id
                )
                packet = cast(dict[str, Any], preview["packet"])
                sections = packet.get("prompt_sections", {})
                return {
                    "chapter_id": preview["chapter_id"],
                    "target_words": preview["target_words"],
                    "chapter_goals": packet.get("chapter_goals", []),
                    "sections": list(sections) if isinstance(sections, dict) else [],
                    "context_packet": packet,
                }
            if operation == "list_chapters":
                from tools.novel_workspace import list_chapters

                return {
                    "chapters": [
                        {
                            "number": int(item.chapter_id.split("_")[-1]),
                            "chapter_id": item.chapter_id,
                            "title": item.title,
                        }
                        for item in list_chapters(project_root, novel_id)
                    ]
                }
            if operation == "get_truth_files":
                from tools.truth_manager import TruthFilesManager

                truth = TruthFilesManager(project_root, novel_id).load_truth_files()
                return {
                    "current_state": truth.current_state[:500],
                    "ledger": truth.ledger[:500],
                    "relationships": truth.relationships[:500],
                }
            if operation == "create_character":
                service = NovelApplicationService(project_root)
                path = service.create_document(
                    kind="character",
                    name=str(args.get("name") or ""),
                    description=str(args.get("description") or ""),
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
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
                return {"file": str(path), "size": len(content)}
            if operation == "update_truth_file":
                from tools.context_schema import normalize_truth_file_key
                from tools.truth_manager import TruthFilesManager

                key = normalize_truth_file_key(str(args.get("file_name") or ""))
                if key not in {"current_state", "ledger", "relationships"}:
                    return {"ok": False, "error": f"Unknown file: {key}"}
                manager = TruthFilesManager(project_root, novel_id)
                truth = manager.load_truth_files()
                content = str(args.get("content") or "")
                setattr(truth, key, content)
                manager.save_truth_files(truth)
                return {"file": key, "size": len(content)}
            if operation == "query_world":
                from tools.world_query import get_entity, list_entities

                entity_id = str(args.get("entity_id") or "")
                if entity_id:
                    entity = get_entity(novel_id, entity_id, project_root)
                    if not entity:
                        return {"ok": False, "error": f"实体不存在: {entity_id}"}
                    return {
                        "entity": {
                            "id": entity["id"],
                            "name": entity["name"],
                            "type": entity["type"],
                            "subtype": entity["subtype"],
                            "status": entity["status"],
                            "description": str(entity["description"] or "")[:200],
                            "rules": list(entity["rules"] or [])[:5],
                            "relations": list(entity["relations"] or [])[:10],
                        }
                    }
                entities = list_entities(
                    novel_id,
                    entity_type=args.get("type"),
                    project_root=project_root,
                )
                return {"entities": entities, "count": len(entities)}
            if operation == "get_world_relations":
                from tools.world_query import get_relations_graph

                graph = get_relations_graph(novel_id, project_root)
                return {
                    "entities": graph["entities"],
                    "relations": graph["relations"][:50],
                    "total_entities": len(graph["entities"]),
                    "total_relations": len(graph["relations"]),
                }
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
            raise NovelServiceError(f"未知应用工具: {operation}")
        except NovelServiceError as exc:
            return _service_error(exc)

    return execute


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
    payload: dict[str, Any] = {
        "arc_id": arc_id,
        "compressed": str(result.compressed_text or "")[:500],
        "compression_ratio": result.compression_ratio,
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
    nodes = manager.get_pending_nodes(
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
        scheduler.advance_to(state, stage) if stage else scheduler.advance(state)
        scheduler.save_workflow(state)
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
            "stages": {stage.name: stage.to_dict() for stage in state.stage_records},
            "is_complete": scheduler.is_complete(state),
        }
    active = scheduler.list_active()
    complete = scheduler.list_complete()
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
        "list_chapters",
        "create_outline",
        "create_character",
        "get_truth_files",
        "update_truth_file",
        "create_foreshadowing",
        "list_foreshadowing",
        "update_foreshadowing",
        "validate_foreshadowing",
        "query_world",
        "get_world_relations",
        "get_workflow_status",
        "start_workflow",
        "advance_workflow",
        "validate_truth",
        "extract_dialogue_fingerprint",
        "validate_post_write",
        "chunk_text",
        "compress_section",
    }
    executors.update(
        {
            name: _application_executor(project_root, name)
            for name in application_operations
        }
    )
    return executors
