"""Canonical long-form chapter writing and review pipeline."""

from __future__ import annotations

import asyncio
import os
import tempfile
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import yaml

from tools.context_schema import normalize_context_payload
from tools.style_synthesizer import render_style_manifest_summary


def _load_config(project_root: Path) -> dict[str, Any]:
    path = project_root / "novel_config.yaml"
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def _chapter_number(chapter_id: str) -> int:
    try:
        return int(chapter_id.rsplit("_", 1)[-1])
    except (TypeError, ValueError):
        return 0


def _chapter_path(project_root: Path, novel_id: str, chapter_id: str) -> Path:
    config = _load_config(project_root)
    arc_id = str(config.get("current_arc") or "arc_001")
    return (
        project_root
        / "data"
        / "novels"
        / novel_id
        / "data"
        / "manuscript"
        / arc_id
        / f"{chapter_id}.md"
    )


def _load_chapter(project_root: Path, novel_id: str, chapter_id: str) -> str | None:
    expected = _chapter_path(project_root, novel_id, chapter_id)
    if expected.is_file():
        return expected.read_text(encoding="utf-8")
    root = project_root / "data" / "novels" / novel_id / "data" / "manuscript"
    for pattern in (f"**/{chapter_id}.md", f"**/{chapter_id}_*.md"):
        matches = sorted(root.glob(pattern))
        if matches:
            return matches[0].read_text(encoding="utf-8")
    return None


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(path)


def _save_chapter(
    project_root: Path,
    novel_id: str,
    chapter_id: str,
    title: str,
    content: str,
) -> Path:
    path = _chapter_path(project_root, novel_id, chapter_id)
    _atomic_write(path, f"# {title}\n\n{content}".encode())
    return path


def load_chapter(
    project_root: Path,
    novel_id: str,
    chapter_id: str,
) -> str | None:
    """Load a committed chapter from the canonical manuscript layout."""
    return _load_chapter(Path(project_root).resolve(), novel_id, chapter_id)


def save_chapter(
    project_root: Path,
    novel_id: str,
    chapter_id: str,
    title: str,
    content: str,
) -> Path:
    """Atomically save a chapter in the canonical manuscript layout."""
    return _save_chapter(
        Path(project_root).resolve(), novel_id, chapter_id, title, content
    )


def _restore(path: Path, previous: bytes | None) -> None:
    if previous is None:
        path.unlink(missing_ok=True)
    else:
        _atomic_write(path, previous)


def _style_profile(documents: Any, max_chars: int) -> str:
    if not isinstance(documents, dict):
        return ""
    labels = (
        ("summary", "风格摘要", 600),
        ("prompt_section", "风格指南", 800),
        ("work.manifest", "风格合成清单", 1200),
        ("work.composed", "作品合成风格", 1200),
        ("work.fingerprint", "作品风格指纹", 800),
        ("craft.dialogue_craft", "对话技法", 700),
        ("craft.scene_craft", "场景技法", 700),
        ("craft.rhythm_craft", "节奏技法", 700),
        ("craft.humanization", "去模板化约束", 700),
        ("craft.ai_patterns", "AI痕迹规避", 700),
        ("source.summary", "提取风格摘要", 700),
        ("source.voice", "提取叙述声音", 700),
        ("source.language", "提取语言习惯", 700),
        ("source.rhythm", "提取节奏", 700),
        ("source.dialogue", "提取对话", 700),
        ("source.consistency", "提取一致性", 700),
    )
    parts: list[str] = []
    used: set[str] = set()
    for key, label, limit in labels:
        raw = documents.get(key, "")
        value = (
            render_style_manifest_summary(raw)
            if key == "work.manifest"
            else str(raw).strip()
        )
        if value:
            used.add(key)
            parts.append(f"## {label}\n{value[:limit]}")
    for key in sorted(documents):
        value = str(documents.get(key) or "").strip()
        if key not in used and value:
            parts.append(f"## {key}\n{value[:600]}")
    return "\n\n".join(parts)[:max_chars]


def _packet_payload(packet: Any) -> dict[str, Any]:
    if isinstance(packet, dict):
        payload = dict(packet)
    elif is_dataclass(packet):
        payload = asdict(cast(Any, packet))
    else:
        payload = {
            key: getattr(packet, key)
            for key in (
                "author_intent",
                "creative_focus",
                "story_background",
                "previous_chapter_content",
                "style_documents",
                "character_documents",
                "concept_documents",
                "prompt_sections",
                "foundation",
                "target_words",
            )
            if getattr(packet, key, None) not in (None, "")
        }
    if hasattr(packet, "to_markdown"):
        payload["outline"] = str(packet.to_markdown())
    return payload


def _render_outline(sections: Any) -> str:
    if not isinstance(sections, dict):
        return ""
    parts = []
    for key in ("大纲窗口", "当前章节", "戏剧位置", "本章目标", "上文"):
        value = str(sections.get(key) or "").strip()
        if value:
            parts.append(f"## {key}\n{value}")
    return "\n\n".join(parts)


def _characters(documents: Any) -> list[dict[str, str]]:
    if isinstance(documents, dict):
        return [
            {"name": str(name), "description": str(content)[:1200]}
            for name, content in documents.items()
            if str(content).strip()
        ]
    if not isinstance(documents, list):
        return []
    characters: list[dict[str, str]] = []
    for index, content in enumerate(documents, start=1):
        text = str(content or "").strip()
        if not text:
            continue
        heading = next(
            (
                line.lstrip("#").strip()
                for line in text.splitlines()
                if line.strip().startswith("#")
            ),
            f"角色{index}",
        )
        characters.append({"name": heading, "description": text[:1200]})
    return characters


def build_writer_payload(
    *,
    context: Any,
    truth: Any,
    packet: dict[str, Any],
    guidance: str,
    target_words: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "target_words": target_words or getattr(context, "target_words", 0),
        "author_intent": getattr(context, "author_intent", ""),
        "creative_focus": getattr(context, "creative_focus", ""),
        "chapter_goals": getattr(context, "chapter_goals", []),
        "dramatic_context": getattr(context, "dramatic_context", {}),
        "current_state": getattr(context, "current_state", ""),
        "foreshadowing_summary": getattr(context, "foreshadowing_summary", ""),
        "ledger": getattr(context, "ledger", ""),
        "relationships": getattr(truth, "relationships", ""),
        "recent_chapters": getattr(context, "recent_text", ""),
        "chapter_summaries": getattr(context, "chapter_summaries", ""),
    }
    if packet:
        sections = packet.get("prompt_sections", {})
        concepts = packet.get("concept_documents", {})
        styles = packet.get("style_documents", {})
        if not isinstance(sections, dict):
            sections = {}
        if not isinstance(concepts, dict):
            concepts = {}
        payload["author_intent"] = str(
            packet.get("author_intent")
            or sections.get("作者意图")
            or payload["author_intent"]
        )
        payload["creative_focus"] = str(
            packet.get("creative_focus")
            or sections.get("创作罗盘（当前最高优先级）")
            or payload["creative_focus"]
        )
        payload["chapter_summaries"] = str(
            sections.get("历史章节记忆") or payload["chapter_summaries"]
        )
        outline = str(packet.get("outline") or "").strip() or _render_outline(sections)
        if outline:
            payload["outline"] = outline
        style = _style_profile(styles, 4000)
        if style:
            payload["style_profile"] = style
        active = _characters(packet.get("character_documents", {}))
        if active:
            payload["active_characters"] = active
        for key in ("current_state", "ledger", "relationships"):
            payload[key] = str(concepts.get(key) or payload.get(key) or "")
        payload["foreshadowing_summary"] = str(
            concepts.get("pending_hooks") or payload["foreshadowing_summary"]
        )
        payload["recent_chapters"] = str(packet.get("previous_chapter_content") or "")
        extra = []
        for label, value in (
            ("故事背景", packet.get("story_background")),
            ("基础设定", packet.get("foundation")),
            ("世界规则", concepts.get("world_rules")),
            ("额外要求", guidance),
        ):
            text = str(value or "").strip()
            if text:
                extra.append(f"## {label}\n{text}")
        if extra:
            payload["external_context"] = "\n\n".join(extra)
    elif guidance:
        payload["external_context"] = guidance
    return cast(
        dict[str, Any],
        normalize_context_payload(payload, include_aliases=False),
    )


def build_review_payload(packet: dict[str, Any]) -> dict[str, Any]:
    concepts = packet.get("concept_documents", {})
    sections = packet.get("prompt_sections", {})
    if not isinstance(concepts, dict):
        concepts = {}
    if not isinstance(sections, dict):
        sections = {}
    characters = packet.get("character_documents", {})
    character_text = (
        "\n\n".join(str(item) for item in characters.values())
        if isinstance(characters, dict)
        else ""
    )
    payload: dict[str, Any] = {
        "target_words": int(packet.get("target_words") or 0),
        "character_profiles": character_text[:4000],
        "current_state": str(concepts.get("current_state") or ""),
        "relationships": str(concepts.get("relationships") or ""),
        "author_intent": str(
            packet.get("author_intent") or sections.get("作者意图") or ""
        ),
        "creative_focus": str(
            packet.get("creative_focus")
            or sections.get("创作罗盘（当前最高优先级）")
            or ""
        ),
    }
    outline = _render_outline(sections)
    if outline:
        payload["outline"] = outline[:4000]
    style = _style_profile(packet.get("style_documents", {}), 2500)
    if style:
        payload["style_profile"] = style[:2000]
    previous = str(packet.get("previous_chapter_content") or "").strip()
    if previous:
        payload["recent_chapters"] = previous[:2000]
    return {key: value for key, value in payload.items() if value}


def _collect_truth_updates(state_updates: Any) -> dict[str, str]:
    if not isinstance(state_updates, dict):
        return {}
    aliases = {
        "current_state": "current_state",
        "particle_ledger": "ledger",
        "ledger": "ledger",
        "character_matrix": "relationships",
        "relationships": "relationships",
    }
    return {
        aliases[key]: value
        for key, value in state_updates.items()
        if key in aliases and isinstance(value, str) and value.strip()
    }


def _sync_book_state(
    project_root: Path,
    novel_id: str,
    chapter_id: str,
    review_passed: bool | None,
) -> None:
    from tools.agent.book_state import BookStage, BookStateStore

    store = BookStateStore(project_root, novel_id)
    state = store.load_or_create()
    if _chapter_number(chapter_id) >= _chapter_number(state.current_chapter):
        state.current_chapter = chapter_id
    if review_passed is None:
        state.stage = BookStage.REVIEW_AND_REVISE
        state.blocking_reason = "review_not_run"
        state.last_agent_action = "write_pending_review"
    elif review_passed:
        state.stage = BookStage.CHAPTER_PREFLIGHT
        state.blocking_reason = ""
        state.last_agent_action = "review_review_passed"
    else:
        state.stage = BookStage.REVIEW_AND_REVISE
        state.blocking_reason = "review_revision_requested"
        state.last_agent_action = "review_review_failed"
    store.save(state)


def execute_write_chapter(project_root: Path, args: dict[str, Any]) -> dict[str, Any]:
    from tools.agent import AgentContext, WriterAgent
    from tools.chapter_memory import ChapterMemoryStore
    from tools.context_builder import ContextBuilder
    from tools.llm import LLMClient, LLMConfig
    from tools.project_lock import ProjectBusyError, ProjectWriteLock
    from tools.truth_manager import TruthFilesManager
    from tools.workflow_scheduler import WorkflowScheduler

    project_root = Path(project_root).resolve()
    config = _load_config(project_root)
    if not config:
        return {"ok": False, "error": "未找到项目配置", "code": "INVALID_PROJECT"}
    novel_id = str(config.get("novel_id") or "")
    chapter_id = str(args.get("chapter_id") or "ch_001")
    packet = args.get("context_packet")
    packet = packet if isinstance(packet, dict) else {}
    target_words = int(args.get("target_words") or 0)
    scheduler = WorkflowScheduler(project_root, novel_id)
    workflow = scheduler.load_or_create(chapter_id)
    active_stage = ""
    try:
        with ProjectWriteLock(project_root, novel_id, operation=f"write:{chapter_id}"):
            active_stage = "context_assembly"
            scheduler.start_stage(workflow, active_stage)
            context = ContextBuilder(project_root, novel_id).build_generation_context(
                chapter_id
            )
            truth_manager = TruthFilesManager(project_root, novel_id)
            truth = truth_manager.load_truth_files()
            scheduler.complete_stage(
                workflow,
                active_stage,
                message="canonical context assembled",
                data={"chapter_id": chapter_id},
            )
            active_stage = "writing"
            scheduler.start_stage(workflow, active_stage)
            llm_config = LLMConfig.from_env()
            writer = WriterAgent(
                AgentContext(LLMClient(llm_config), llm_config.model, str(project_root))
            )
            writer_payload = build_writer_payload(
                context=context,
                truth=truth,
                packet=packet,
                guidance=str(args.get("guidance") or "").strip(),
                target_words=target_words,
            )
            result = asyncio.run(
                writer.write_chapter(
                    context=writer_payload,
                    chapter_number=_chapter_number(chapter_id) or 1,
                    temperature=float(args.get("temperature") or 0.7),
                    target_words=writer_payload.get("target_words") or None,
                )
            )
            snapshot = truth_manager.create_snapshot(max(_chapter_number(chapter_id) - 1, 0))
            memory = ChapterMemoryStore(project_root, novel_id)
            draft_path = _chapter_path(project_root, novel_id, chapter_id)
            memory_path = memory.path_for(chapter_id)
            previous_draft = draft_path.read_bytes() if draft_path.is_file() else None
            previous_memory = memory_path.read_bytes() if memory_path.is_file() else None
            try:
                _save_chapter(
                    project_root, novel_id, chapter_id, result.title, result.content
                )
                updates = _collect_truth_updates(getattr(result, "state_updates", {}))
                if updates:
                    truth_manager.update_truth_files(
                        truth_manager.load_truth_files(), updates
                    )
                memory.save(
                    chapter_id=chapter_id,
                    title=result.title,
                    summary=str(getattr(result, "chapter_summary", "") or ""),
                    word_count=int(getattr(result, "word_count", 0) or 0),
                    observations=str(getattr(result, "observations", "") or ""),
                    token_usage=dict(getattr(result, "token_usage", {}) or {}),
                )
                scheduler.complete_stage(
                    workflow,
                    active_stage,
                    message="chapter committed",
                    data={"draft_path": str(draft_path)},
                )
                _sync_book_state(project_root, novel_id, chapter_id, None)
                active_stage = ""
            except Exception:
                truth_manager.restore_snapshot(snapshot)
                _restore(draft_path, previous_draft)
                _restore(memory_path, previous_memory)
                raise
            return {
                "ok": True,
                "chapter_id": chapter_id,
                "title": result.title,
                "word_count": result.word_count,
                "draft_path": str(draft_path),
                "truth_updates": updates,
            }
    except ProjectBusyError as exc:
        return {
            "ok": False,
            "chapter_id": chapter_id,
            "error": str(exc),
            "code": "PROJECT_BUSY",
        }
    except Exception as exc:
        if active_stage:
            scheduler.fail_stage(workflow, active_stage, str(exc))
        return {"ok": False, "chapter_id": chapter_id, "error": str(exc)}


def execute_review_chapter(project_root: Path, args: dict[str, Any]) -> dict[str, Any]:
    from tools.agent import AgentContext, ReviewerAgent
    from tools.chapter_assembler import ChapterAssemblerV2
    from tools.llm import LLMClient, LLMConfig
    from tools.project_lock import ProjectBusyError, ProjectWriteLock
    from tools.review_store import ReviewStore
    from tools.truth_manager import TruthFilesManager
    from tools.workflow_scheduler import WorkflowScheduler

    project_root = Path(project_root).resolve()
    config = _load_config(project_root)
    if not config:
        return {"ok": False, "error": "未找到项目配置", "code": "INVALID_PROJECT"}
    novel_id = str(config.get("novel_id") or "")
    chapter_id = str(args.get("chapter_id") or "ch_001")
    scheduler = WorkflowScheduler(project_root, novel_id)
    workflow = scheduler.load_or_create(chapter_id)
    try:
        with ProjectWriteLock(project_root, novel_id, operation=f"review:{chapter_id}"):
            content = _load_chapter(project_root, novel_id, chapter_id)
            if not content:
                return {
                    "ok": False,
                    "error": f"未找到章节: {chapter_id}",
                    "code": "NOT_FOUND",
                }
            scheduler.start_stage(workflow, "review")
            llm_config = LLMConfig.from_env()
            reviewer = ReviewerAgent(
                AgentContext(LLMClient(llm_config), llm_config.model, str(project_root))
            )
            packet = ChapterAssemblerV2(
                project_root=project_root,
                novel_id=novel_id,
                style_id=str(config.get("style_id") or novel_id),
            ).assemble(chapter_id)
            review_context = build_review_payload(_packet_payload(packet))
            prewrite = TruthFilesManager(project_root, novel_id).load_snapshot_before(
                _chapter_number(chapter_id)
            )
            if prewrite is not None:
                review_context["current_state"] = prewrite.current_state
                review_context["relationships"] = prewrite.relationships
            result = asyncio.run(reviewer.review(content=content, context=review_context))
            issues: list[dict[str, Any]] = [
                {
                    "severity": str(getattr(issue, "severity", "warning")),
                    "category": str(getattr(issue, "category", "未知")),
                    "description": str(getattr(issue, "description", "")),
                    "suggestion": str(getattr(issue, "suggestion", "")),
                    "dimension": getattr(issue, "dimension", None),
                }
                for issue in result.issues
            ]
            payload = {
                "ok": True,
                "chapter_id": chapter_id,
                "passed": bool(result.passed),
                "score": result.score,
                "issues": len(issues),
                "summary": str(getattr(result, "summary", "") or ""),
                "issue_details": issues,
            }
            ReviewStore(project_root, novel_id).save(chapter_id, payload)
            scheduler.complete_stage(
                workflow,
                "review",
                message="chapter reviewed",
                data={
                    "passed": bool(result.passed),
                    "errors": [
                        item["description"]
                        for item in issues
                        if item["severity"].lower() == "critical"
                    ],
                    "warnings": [
                        item["description"]
                        for item in issues
                        if item["severity"].lower() != "critical"
                    ],
                },
            )
            _sync_book_state(project_root, novel_id, chapter_id, bool(result.passed))
            return payload
    except ProjectBusyError as exc:
        return {
            "ok": False,
            "chapter_id": chapter_id,
            "error": str(exc),
            "code": "PROJECT_BUSY",
        }
    except Exception as exc:
        scheduler.fail_stage(workflow, "review", str(exc))
        return {"ok": False, "chapter_id": chapter_id, "error": str(exc)}


def execute_multi_agent_chapter(
    project_root: Path,
    args: dict[str, Any],
) -> dict[str, Any]:
    """Run the director/writer/reviewer chapter flow behind the same lock boundary."""
    from tools.agent import AgentContext, MultiAgentDirector
    from tools.llm import LLMClient, LLMConfig
    from tools.project_lock import ProjectBusyError, ProjectWriteLock
    from tools.review_store import ReviewStore
    from tools.workflow_scheduler import WorkflowScheduler

    project_root = Path(project_root).resolve()
    config = _load_config(project_root)
    if not config:
        return {"ok": False, "error": "未找到项目配置", "code": "INVALID_PROJECT"}
    novel_id = str(config.get("novel_id") or "")
    chapter_id = str(args.get("chapter_id") or "ch_001")
    scheduler = WorkflowScheduler(project_root, novel_id)
    workflow = scheduler.load_or_create(chapter_id)
    active_stage = ""
    try:
        with ProjectWriteLock(
            project_root,
            novel_id,
            operation=f"multi-write:{chapter_id}",
        ):
            llm_config = LLMConfig.from_env()
            director = MultiAgentDirector(
                AgentContext(
                    LLMClient(llm_config), llm_config.model, str(project_root)
                ),
                novel_id=novel_id,
                style_id=str(config.get("style_id") or novel_id),
            )
            active_stage = "context_assembly"
            scheduler.start_stage(workflow, active_stage)
            packet_markdown = ""
            packet_path = ""
            if bool(args.get("show_packet")):
                packet = director.assemble_packet(chapter_id)
                packet_markdown = packet.to_markdown()
                output_dir = (
                    Path(str(args["packet_output_dir"]))
                    if args.get("packet_output_dir")
                    else project_root
                    / "data"
                    / "novels"
                    / novel_id
                    / "data"
                    / "test_outputs"
                    / "multi_write"
                )
                output_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                target = output_dir / f"{chapter_id}_packet_{stamp}.md"
                target.write_text(packet_markdown, encoding="utf-8")
                packet_path = str(target)
            scheduler.complete_stage(
                workflow,
                active_stage,
                message=(
                    "packet assembled for multi-write"
                    if packet_markdown
                    else "packet assembly delegated to multi-write director"
                ),
                data={"chapter_id": chapter_id},
            )
            active_stage = "writing"
            scheduler.start_stage(workflow, active_stage)
            result = asyncio.run(
                director.run(
                    chapter_id=chapter_id,
                    temperature=float(args.get("temperature") or 0.7),
                    run_review=not bool(args.get("no_review")),
                )
            )
            if not result.draft:
                raise RuntimeError("未生成草稿")
            draft_path = _save_chapter(
                project_root,
                novel_id,
                chapter_id,
                result.draft.title,
                result.draft.content,
            )
            scheduler.complete_stage(
                workflow,
                active_stage,
                message="chapter written via multi-write",
                data={"draft_path": str(draft_path)},
            )
            active_stage = ""
            review_payload: dict[str, Any] | None = None
            if result.review:
                issues: list[dict[str, Any]] = [
                    {
                        "severity": str(getattr(issue, "severity", "warning")),
                        "category": str(getattr(issue, "category", "未知")),
                        "description": str(getattr(issue, "description", "")),
                        "suggestion": str(getattr(issue, "suggestion", "")),
                        "dimension": getattr(issue, "dimension", None),
                    }
                    for issue in result.review.issues
                ]
                review_payload = {
                    "ok": True,
                    "chapter_id": chapter_id,
                    "passed": bool(result.review.passed),
                    "score": result.review.score,
                    "issues": len(issues),
                    "summary": str(getattr(result.review, "summary", "") or ""),
                    "issue_details": issues,
                }
                ReviewStore(project_root, novel_id).save(chapter_id, review_payload)
                scheduler.start_stage(workflow, "review")
                scheduler.complete_stage(
                    workflow,
                    "review",
                    message="chapter reviewed via multi-write",
                    data={
                        "passed": bool(result.review.passed),
                        "errors": [
                            item["description"]
                            for item in issues
                            if item["severity"].lower() == "critical"
                        ],
                        "warnings": [
                            item["description"]
                            for item in issues
                            if item["severity"].lower() != "critical"
                        ],
                    },
                )
            _sync_book_state(
                project_root,
                novel_id,
                chapter_id,
                bool(result.review.passed) if result.review else None,
            )
            return {
                "ok": True,
                "chapter_id": chapter_id,
                "title": result.draft.title,
                "draft_path": str(draft_path),
                "review": review_payload,
                "applied_state_updates": dict(result.applied_state_updates or {}),
                "new_concepts": list(result.new_concepts or []),
                "packet_markdown": packet_markdown,
                "packet_path": packet_path,
            }
    except ProjectBusyError as exc:
        return {
            "ok": False,
            "chapter_id": chapter_id,
            "error": str(exc),
            "code": "PROJECT_BUSY",
        }
    except Exception as exc:
        if active_stage:
            scheduler.fail_stage(workflow, active_stage, str(exc))
        return {"ok": False, "chapter_id": chapter_id, "error": str(exc)}
