"""OpenWrite Web 应用 — FastAPI + Jinja2 本地可视化面板。"""

from __future__ import annotations

import asyncio
import json
import yaml
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

# ── 延迟导入项目模块（避免循环） ──────────────────────────────────

_WEB_DIR = Path(__file__).parent
_TEMPLATES_DIR = _WEB_DIR / "templates"
_STATIC_DIR = _WEB_DIR / "static"

_SIM_TASKS: Dict[str, Dict[str, Any]] = {}

_STATUS_TO_CN = {
    "planted": "埋伏",
    "growing": "待收",
    "pending": "待收",
    "recovered": "已回收",
    "abandoned": "废弃",
}

_STATUS_TO_API = {
    "埋伏": "planted",
    "待收": "growing",
    "已回收": "recovered",
    "废弃": "abandoned",
    "planted": "planted",
    "growing": "growing",
    "pending": "growing",
    "recovered": "recovered",
    "abandoned": "abandoned",
}


class CharacterCreateRequest(BaseModel):
    name: str
    tier: str = "普通配角"
    faction: str = ""


class CharacterMutateRequest(BaseModel):
    chapter: str
    change: Optional[str] = None
    note: str = ""


class WorldEntityRequest(BaseModel):
    id: Optional[str] = None
    name: str
    type: str = "concept"
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    attributes: dict[str, str] = Field(default_factory=dict)


class WorldRelationCreateRequest(BaseModel):
    source: str
    target: str
    relation: str
    weight: int = 1
    note: str = ""


class WorldRelationDeleteRequest(BaseModel):
    source: str
    target: str
    relation: str
    weight: Optional[int] = None
    note: Optional[str] = None


class ForeshadowingCreateRequest(BaseModel):
    id: str
    content: str = ""
    weight: int = 5
    layer: str = "支线"
    target_chapter: Optional[str] = None


class ForeshadowingStatusRequest(BaseModel):
    status: str


class DraftContentRequest(BaseModel):
    content: str


class OutlineMdImportRequest(BaseModel):
    content: str = Field(..., description="Markdown 大纲文本内容")


class OutlineMdExportResponse(BaseModel):
    content: str = Field(..., description="Markdown 大纲文本内容")
    novel_id: str
    title: str

class SimulateChapterRequest(BaseModel):
    chapter_id: str
    objective: str = "推进主线并保持角色一致性"
    style_id: str = ""
    forbidden: list[str] = Field(default_factory=list)
    required: list[str] = Field(default_factory=list)
    use_stylist: bool = False
    strict_lore: bool = False
    max_rewrites: int = 0
    use_style_analysis: bool = False
    use_llm: bool = False


class StyleComposeRequest(BaseModel):
    novel_id: str
    style_id: str


# ── Phase 7C-1 请求模型 ──────────────────────────────────────────

class NovelInitRequest(BaseModel):
    title: str = ""
    core_theme: str = ""
    ending_direction: str = ""
    world_premise: str = ""
    tone: str = ""
    target_word_count: int = 0
    key_turns: list[str] = Field(default_factory=list)
    arc_sketches: list[dict] = Field(default_factory=list)
    character_sketches: list[dict] = Field(default_factory=list)
    world_entities: list[dict] = Field(default_factory=list)


class OutlineArcRequest(BaseModel):
    arc_id: str
    title: str = ""
    order: int = 0
    main_conflict: str = ""
    resolution: str = ""
    key_characters: list[str] = Field(default_factory=list)


class OutlineSectionRequest(BaseModel):
    section_id: str
    arc_id: str = ""
    title: str = ""
    order: int = 0
    plot_summary: str = ""
    key_events: list[str] = Field(default_factory=list)


class OutlineChapterRequest(BaseModel):
    chapter_id: str
    section_id: str = ""
    title: str = ""
    order: int = 0
    goals: list[str] = Field(default_factory=list)
    key_scenes: list[str] = Field(default_factory=list)
    emotion_arc: str = ""
    involved_characters: list[str] = Field(default_factory=list)
    involved_settings: list[str] = Field(default_factory=list)
    foreshadowing_refs: list[str] = Field(default_factory=list)
    target_words: int = 6000


class PipelineV2StartRequest(BaseModel):
    chapter_id: str
    writing_prompt: str = ""
    strict_review: bool = False
    max_rewrites: int = 1
    use_stylist: bool = False


class PipelineApproveRequest(BaseModel):
    approved: bool = True
    user_edits: str = ""


class LLMConfigUpdateRequest(BaseModel):
    enabled: bool = False
    retry_count: int = 2
    retry_delay: float = 1.0
    routes: dict = Field(default_factory=dict)
    default_route: dict = Field(default_factory=dict)


class TextCharacterRequest(BaseModel):
    name: str
    char_type: str = "配角"
    appearance: str = ""
    personality_and_voice: str = ""
    skills_and_abilities: str = ""
    items: str = ""
    attributes: str = ""
    notes: str = ""
    faction: str = ""
    aliases: list[str] = Field(default_factory=list)

def _to_api_status(raw_status: str) -> str:
    return _STATUS_TO_API.get(raw_status, "planted")


def _to_internal_status(raw_status: str) -> str:
    normalized = raw_status.strip().lower()
    if normalized not in _STATUS_TO_CN:
        raise ValueError("status 仅支持 planted/growing/recovered/abandoned")
    return _STATUS_TO_CN[normalized]


def _emit_task_event(task_id: str, *, stage: str, status: str, message: str, progress: int, payload: Optional[dict[str, Any]] = None) -> None:
    task = _SIM_TASKS.get(task_id)
    if task is None:
        return
    event = {
        "event": "progress",
        "task_id": task_id,
        "stage": stage,
        "status": status,
        "message": message,
        "progress": progress,
        "timestamp": datetime.now().isoformat(),
        "payload": payload or {},
    }
    task["stage"] = stage
    task["progress"] = progress
    task["events"].append(event)


def _list_markdown_files(directory: Path) -> list[dict[str, str]]:
    if not directory.exists():
        return []
    return [{"id": item.stem, "name": item.stem} for item in sorted(directory.glob("*.md"))]


def create_app(
    project_dir: Optional[Path] = None, novel_id: str = "my_novel"
) -> FastAPI:
    """创建 FastAPI 应用实例。"""
    from tools.agents.simulator import AgentSimulator
    from tools.character_state_manager import CharacterStateManager
    from tools.graph.foreshadowing_dag import ForeshadowingDAGManager
    from tools.llm.client import LLMClient
    from tools.llm.config import load_llm_config
    from tools.llm.router import ModelRouter
    from tools.models.style import StyleProfile
    from tools.narrative_timeline_manager import NarrativeTimelineManager
    from tools.narrative_renderer import render_html as render_timeline_html
    from tools.queries.character_query import CharacterQuery
    from tools.utils.style_composer import StyleComposer
    from tools.world_conflict_checker import WorldConflictChecker
    from tools.world_graph_manager import WorldGraphManager
    from tools.world_graph_renderer import render_world_graph_html
    from tools.agents.initializer import NovelInitializer
    from tools.agents.pipeline_v2 import PipelineSimulatorV2
    from tools.models.outline import OutlineHierarchy

    proj = project_dir or Path.cwd()

    app = FastAPI(title="OpenWrite", docs_url="/api/docs")
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

    # ── 工具实例 ──────────────────────────────────────────────────

    def _world_mgr() -> WorldGraphManager:
        return WorldGraphManager(project_dir=proj, novel_id=novel_id)

    def _char_mgr() -> CharacterStateManager:
        return CharacterStateManager(project_dir=proj, novel_id=novel_id)

    def _fs_mgr() -> ForeshadowingDAGManager:
        return ForeshadowingDAGManager(project_dir=proj, novel_id=novel_id)

    def _timeline_mgr() -> NarrativeTimelineManager:
        return NarrativeTimelineManager(project_dir=proj, novel_id=novel_id)

    def _char_query() -> CharacterQuery:
        return CharacterQuery(project_dir=proj, novel_id=novel_id)

    def _outline_chapters_dir() -> Path:
        return proj / "data" / "novels" / novel_id / "outline" / "chapters"

    def _manuscript_dir() -> Path:
        return proj / "data" / "novels" / novel_id / "manuscript"

    def _drafts_dir() -> Path:
        path = _manuscript_dir() / "drafts"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _resolve_draft_path(draft_id: str) -> Path:
        preferred = _drafts_dir() / f"{draft_id}.md"
        legacy = _manuscript_dir() / f"{draft_id}.md"
        if preferred.exists():
            return preferred
        if legacy.exists():
            return legacy
        return preferred

    def _collect_recent_tasks() -> list[dict[str, Any]]:
        task_list = []
        for task in _SIM_TASKS.values():
            if task.get("novel_id") == novel_id:
                task_list.append(
                    {
                        "task_id": task["task_id"],
                        "chapter_id": task.get("chapter_id", ""),
                        "status": task.get("status", "queued"),
                        "stage": task.get("stage", "queued"),
                        "progress": task.get("progress", 0),
                        "updated_at": task.get("updated_at", task.get("created_at", "")),
                    }
                )
        task_list.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return task_list[:10]

    async def _run_simulation_task(task_id: str, request_data: SimulateChapterRequest) -> None:
        task = _SIM_TASKS[task_id]
        task["status"] = "running"
        task["updated_at"] = datetime.now().isoformat()

        phase_plan = [
            ("director", 10, "Director planning"),
            ("librarian", 30, "Librarian writing"),
            ("lore_checker", 55, "LoreChecker checking"),
            ("stylist", 75, "Stylist polishing"),
            ("style_analysis", 90, "Style analysis"),
        ]
        phase_index = 0

        _emit_task_event(
            task_id,
            stage="queued",
            status="running",
            message="任务已启动",
            progress=3,
        )

        llm_client = None
        router = None
        if request_data.use_llm:
            llm_cfg = load_llm_config(None)
            if llm_cfg.enabled:
                llm_client = LLMClient(
                    retry_count=llm_cfg.retry_count,
                    retry_delay=llm_cfg.retry_delay,
                )
                router = ModelRouter(llm_cfg)

        simulator = AgentSimulator(
            project_dir=proj,
            novel_id=novel_id,
            style_id=request_data.style_id,
            llm_client=llm_client,
            router=router,
        )

        worker = asyncio.create_task(
            asyncio.to_thread(
                simulator.simulate_chapter,
                chapter_id=request_data.chapter_id,
                objective=request_data.objective,
                forbidden=request_data.forbidden,
                required=request_data.required,
                use_stylist=request_data.use_stylist,
                strict_lore=request_data.strict_lore,
                max_rewrites=request_data.max_rewrites,
                use_style_analysis=request_data.use_style_analysis,
            )
        )

        try:
            while not worker.done():
                if phase_index < len(phase_plan):
                    stage, progress, message = phase_plan[phase_index]
                    _emit_task_event(
                        task_id,
                        stage=stage,
                        status="running",
                        message=message,
                        progress=progress,
                    )
                    phase_index += 1
                task["updated_at"] = datetime.now().isoformat()
                await asyncio.sleep(1.0)

            result = await worker
            task["status"] = "completed"
            task["result"] = {
                "chapter_id": result.chapter_id,
                "passed": result.passed,
                "draft_file": str(result.draft_file),
                "report_file": str(result.report_file),
                "errors": result.errors,
                "warnings": result.warnings,
                "rewrite_attempts": result.rewrite_attempts,
                "style_analysis": result.style_analysis,
            }
            task["updated_at"] = datetime.now().isoformat()
            _emit_task_event(
                task_id,
                stage="completed",
                status="completed",
                message="章节模拟完成",
                progress=100,
                payload=task["result"],
            )
        except Exception as exc:  # pragma: no cover - defensive runtime fallback
            task["status"] = "failed"
            task["error"] = str(exc)
            task["updated_at"] = datetime.now().isoformat()
            _emit_task_event(
                task_id,
                stage="failed",
                status="failed",
                message=f"任务失败: {exc}",
                progress=100,
            )

    # ── 页面路由 ──────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request):
        """仪表盘首页。"""
        world = _world_mgr()
        graph = world._load_graph()
        fs = _fs_mgr()
        dag = fs._load_dag()
        chars = _char_mgr()
        all_chars = chars.list_characters()

        try:
            tl = _timeline_mgr()
            timeline = tl.load()
            thread_count = len(timeline.threads)
            chapter_count = len(timeline.chapters)
        except Exception:
            thread_count = 0
            chapter_count = 0

        stats = {
            "entity_count": len(graph.entities),
            "relation_count": len(graph.relations),
            "character_count": len(all_chars),
            "foreshadowing_count": len(dag.nodes),
            "thread_count": thread_count,
            "chapter_count": chapter_count,
        }
        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "stats": stats,
                "novel_id": novel_id,
                "recent_tasks": _collect_recent_tasks(),
            },
        )

    @app.get("/timeline", response_class=HTMLResponse)
    async def timeline_page(request: Request):
        """叙事时间线页面。"""
        try:
            tl = _timeline_mgr()
            timeline = tl.load()
            timeline_html = render_timeline_html(timeline)
        except Exception:
            timeline_html = (
                "<p>暂无时间线数据，请先运行 <code>timeline build</code></p>"
            )
        return templates.TemplateResponse(
            "timeline.html",
            {
                "request": request,
                "timeline_html": timeline_html,
                "novel_id": novel_id,
            },
        )

    @app.get("/world", response_class=HTMLResponse)
    async def world_page(request: Request):
        """世界观图谱页面。"""
        world = _world_mgr()
        graph = world._load_graph()
        if graph.entities:
            graph_html = render_world_graph_html(graph, title=f"{novel_id} 世界观图谱")
        else:
            graph_html = "<p>暂无世界观数据，请先添加实体</p>"
        return templates.TemplateResponse(
            "world.html",
            {
                "request": request,
                "graph_html": graph_html,
                "novel_id": novel_id,
                "entity_count": len(graph.entities),
                "relation_count": len(graph.relations),
            },
        )

    @app.get("/characters", response_class=HTMLResponse)
    async def characters_page(request: Request):
        """人物档案页面。"""
        chars = _char_mgr()
        all_chars = chars.list_characters()
        query = _char_query()
        char_data = []
        for c in all_chars:
            char_id = c.get("id", "")
            char_name = c.get("name", "")
            try:
                state = query.get_current_state(char_name)
                char_data.append(
                    {
                        "id": char_id,
                        "name": char_name,
                        "tier": c.get("tier", ""),
                        "faction": c.get("faction", ""),
                        "realm": state["state"].get("realm", ""),
                        "location": state["state"].get("location", ""),
                        "statuses": state["state"].get("statuses", []),
                    }
                )
            except Exception:
                char_data.append(
                    {
                        "id": char_id,
                        "name": char_name,
                        "tier": c.get("tier", ""),
                        "faction": c.get("faction", ""),
                        "realm": "",
                        "location": "",
                        "statuses": [],
                    }
                )
        return templates.TemplateResponse(
            "characters.html",
            {
                "request": request,
                "characters": char_data,
                "novel_id": novel_id,
            },
        )

    @app.get("/foreshadowing", response_class=HTMLResponse)
    async def foreshadowing_page(request: Request):
        """伏笔 DAG 页面。"""
        fs = _fs_mgr()
        dag = fs._load_dag()
        nodes_data = []
        for nid, node in dag.nodes.items():
            raw_status = dag.status.get(nid, "planted")
            nodes_data.append(
                {
                    "id": nid,
                    "content": node.content if hasattr(node, "content") else str(node),
                    "layer": node.layer if hasattr(node, "layer") else "",
                    "weight": node.weight if hasattr(node, "weight") else 0,
                    "status": _to_api_status(raw_status),
                }
            )
        edges_data = []
        for edge in dag.edges:
            edges_data.append({"source": edge.source, "target": edge.target})
        stats = fs.get_statistics()
        return templates.TemplateResponse(
            "foreshadowing.html",
            {
                "request": request,
                "nodes": nodes_data,
                "edges": edges_data,
                "stats": stats,
                "novel_id": novel_id,
            },
        )

    @app.get("/style", response_class=HTMLResponse)
    async def style_page(request: Request):
        """风格系统页面。"""
        composer = StyleComposer(proj)
        styles = composer.list_available_styles()
        novels = composer.list_available_novels()
        profile_data = None
        try:
            profile = StyleProfile.from_project(project_root=proj, novel_id=novel_id)
            profile_data = {
                "summary": profile.to_summary(max_chars=2000),
                "banned_count": len(profile.banned_phrases),
                "metrics": {
                    "directness": profile.quality_metrics.directness,
                    "rhythm": profile.quality_metrics.rhythm,
                    "imagery": profile.quality_metrics.imagery,
                    "characterization": profile.quality_metrics.characterization,
                    "ai_artifact_control": profile.quality_metrics.ai_artifact_control,
                },
            }
        except Exception:
            pass
        return templates.TemplateResponse(
            "style.html",
            {
                "request": request,
                "styles": styles,
                "novels": novels,
                "profile": profile_data,
                "novel_id": novel_id,
            },
        )

    @app.get("/editor", response_class=HTMLResponse)
    async def editor_page(request: Request):
        """章节编辑器页面。"""
        chapters = _list_markdown_files(_outline_chapters_dir())
        drafts = _list_markdown_files(_drafts_dir())
        return templates.TemplateResponse(
            "editor.html",
            {
                "request": request,
                "chapters": chapters,
                "drafts": drafts,
                "novel_id": novel_id,
            },
        )

    # ── REST API ──────────────────────────────────────────────────

    @app.get("/api/stats")
    async def api_stats():
        """项目统计 JSON。"""
        world = _world_mgr()
        graph = world._load_graph()
        fs = _fs_mgr()
        dag = fs._load_dag()
        chars = _char_mgr()
        try:
            tl = _timeline_mgr()
            timeline = tl.load()
            thread_count = len(timeline.threads)
            ch_count = len(timeline.chapters)
        except Exception:
            thread_count = 0
            ch_count = 0
        return {
            "novel_id": novel_id,
            "entities": len(graph.entities),
            "relations": len(graph.relations),
            "characters": len(chars.list_characters()),
            "foreshadowing": len(dag.nodes),
            "threads": thread_count,
            "chapters": ch_count,
            "recent_tasks": _collect_recent_tasks(),
        }

    @app.get("/api/world/entities")
    async def api_world_entities():
        world = _world_mgr()
        entities = world.list_entities()
        return [
            {
                "id": e.id,
                "name": e.name,
                "type": e.type,
                "description": e.description,
                "tags": e.tags,
                "attributes": e.attributes,
            }
            for e in entities
        ]

    @app.post("/api/world/entities")
    async def api_world_entities_create(payload: WorldEntityRequest):
        world = _world_mgr()
        entity_id = payload.id or f"entity_{uuid4().hex[:8]}"
        entity = world.upsert_entity(
            entity_id=entity_id,
            name=payload.name,
            entity_type=payload.type,
            description=payload.description,
            tags=payload.tags,
            attributes=payload.attributes,
        )
        return {
            "id": entity.id,
            "name": entity.name,
            "type": entity.type,
            "description": entity.description,
            "tags": entity.tags,
            "attributes": entity.attributes,
        }

    @app.put("/api/world/entities/{entity_id}")
    async def api_world_entities_update(entity_id: str, payload: WorldEntityRequest):
        world = _world_mgr()
        entity = world.upsert_entity(
            entity_id=entity_id,
            name=payload.name,
            entity_type=payload.type,
            description=payload.description,
            tags=payload.tags,
            attributes=payload.attributes,
        )
        return {
            "id": entity.id,
            "name": entity.name,
            "type": entity.type,
            "description": entity.description,
            "tags": entity.tags,
            "attributes": entity.attributes,
        }

    @app.delete("/api/world/entities/{entity_id}")
    async def api_world_entities_delete(entity_id: str):
        world = _world_mgr()
        graph = world._load_graph()
        if entity_id not in graph.entities:
            raise HTTPException(status_code=404, detail="实体不存在")
        graph.entities.pop(entity_id, None)
        graph.relations = [
            rel
            for rel in graph.relations
            if rel.source_id != entity_id and rel.target_id != entity_id
        ]
        world._save_graph(graph)
        return {"ok": True, "deleted": entity_id}

    @app.get("/api/world/relations")
    async def api_world_relations():
        world = _world_mgr()
        relations = world.list_relations()
        return [
            {
                "source": r.source_id,
                "target": r.target_id,
                "relation": r.relation,
                "weight": r.weight,
                "note": r.note,
                "chapter_id": r.chapter_id,
            }
            for r in relations
        ]

    @app.post("/api/world/relations")
    async def api_world_relations_create(payload: WorldRelationCreateRequest):
        world = _world_mgr()
        relation = world.add_relation(
            source_id=payload.source,
            target_id=payload.target,
            relation=payload.relation,
            weight=payload.weight,
            note=payload.note,
        )
        return {
            "source": relation.source_id,
            "target": relation.target_id,
            "relation": relation.relation,
            "weight": relation.weight,
            "note": relation.note,
            "chapter_id": relation.chapter_id,
        }

    @app.delete("/api/world/relations")
    async def api_world_relations_delete(payload: WorldRelationDeleteRequest):
        world = _world_mgr()
        graph = world._load_graph()
        before = len(graph.relations)

        filtered = []
        removed = False
        for rel in graph.relations:
            hit = (
                rel.source_id == payload.source
                and rel.target_id == payload.target
                and rel.relation == payload.relation
            )
            if payload.weight is not None:
                hit = hit and rel.weight == payload.weight
            if payload.note is not None:
                hit = hit and rel.note == payload.note

            if hit and not removed:
                removed = True
                continue
            filtered.append(rel)

        if not removed:
            raise HTTPException(status_code=404, detail="关系不存在")

        graph.relations = filtered
        world._save_graph(graph)
        return {"ok": True, "removed": before - len(graph.relations)}

    @app.get("/api/world/check")
    async def api_world_check():
        world = _world_mgr()
        graph = world._load_graph()
        checker = WorldConflictChecker()
        result = checker.check(graph)
        return {
            "is_valid": result["is_valid"],
            "errors": result["errors"],
            "warnings": result["warnings"],
            "statistics": result["statistics"],
        }

    @app.get("/api/characters")
    async def api_characters():
        chars = _char_mgr()
        all_chars = chars.list_characters()
        return all_chars

    @app.post("/api/characters")
    async def api_characters_create(payload: CharacterCreateRequest):
        chars = _char_mgr()
        card = chars.create_character(
            name=payload.name,
            tier=payload.tier,
            faction=payload.faction,
        )
        return {
            "id": card.static.id,
            "name": card.static.name,
            "tier": card.static.tier,
            "faction": card.static.faction,
        }

    @app.get("/api/characters/{name}")
    async def api_character_detail(name: str):
        query = _char_query()
        try:
            state = query.get_current_state(name)
            timeline = query.get_timeline(name)
            return {"state": state, "timeline": timeline}
        except Exception as exc:
            return JSONResponse(status_code=404, content={"error": str(exc)})

    @app.put("/api/characters/{name}/mutate")
    async def api_character_mutate(name: str, payload: CharacterMutateRequest):
        chars = _char_mgr()
        mutation = chars.apply_mutation(
            name=name,
            chapter_id=payload.chapter,
            mutation_expr=payload.change,
            note=payload.note,
        )
        return mutation.model_dump()

    @app.get("/api/characters/{name}/timeline")
    async def api_character_timeline(name: str):
        query = _char_query()
        timeline = query.get_timeline(name)
        return {"name": name, "timeline": timeline}

    @app.delete("/api/characters/{name}")
    async def api_character_delete(name: str):
        chars = _char_mgr()
        index_data = chars._load_index()
        target = None
        remains = []
        for item in index_data.get("characters", []):
            if item.get("name") == name:
                target = item
            else:
                remains.append(item)
        if target is None:
            raise HTTPException(status_code=404, detail="人物不存在")

        index_data["characters"] = remains
        chars._save_index(index_data)

        char_id = target.get("id", "")
        if char_id:
            for file_path in [
                chars.cards_dir / f"{char_id}.yaml",
                chars.logs_dir / f"{char_id}.yaml",
                chars.profiles_dir / f"{char_id}.md",
                chars.snapshots_dir / f"{char_id}.md",
            ]:
                if file_path.exists():
                    file_path.unlink()

        return {"ok": True, "deleted": name}

    @app.get("/api/foreshadowing")
    async def api_foreshadowing():
        fs = _fs_mgr()
        dag = fs._load_dag()
        nodes = []
        for nid, node in dag.nodes.items():
            raw_status = dag.status.get(nid, "planted")
            nodes.append(
                {
                    "id": nid,
                    "content": node.content if hasattr(node, "content") else "",
                    "layer": node.layer if hasattr(node, "layer") else "",
                    "weight": node.weight if hasattr(node, "weight") else 0,
                    "status": _to_api_status(raw_status),
                    "target_chapter": node.target_chapter if hasattr(node, "target_chapter") else None,
                }
            )
        edges = []
        for edge in dag.edges:
            edges.append({"source": edge.source, "target": edge.target})
        return {"nodes": nodes, "edges": edges, "statistics": fs.get_statistics()}

    @app.post("/api/foreshadowing")
    async def api_foreshadowing_create(payload: ForeshadowingCreateRequest):
        fs = _fs_mgr()
        created = fs.create_node(
            node_id=payload.id,
            content=payload.content,
            weight=payload.weight,
            layer=payload.layer,
            created_at="",
            target_chapter=payload.target_chapter,
        )
        if not created:
            raise HTTPException(status_code=400, detail="伏笔已存在")
        return {"ok": True, "id": payload.id}

    @app.put("/api/foreshadowing/{node_id}/status")
    async def api_foreshadowing_status(node_id: str, payload: ForeshadowingStatusRequest):
        fs = _fs_mgr()
        internal = _to_internal_status(payload.status)
        updated = fs.update_node_status(node_id, internal)
        if not updated:
            raise HTTPException(status_code=404, detail="伏笔不存在")
        return {"ok": True, "id": node_id, "status": _to_api_status(internal)}

    @app.delete("/api/foreshadowing/{node_id}")
    async def api_foreshadowing_delete(node_id: str):
        fs = _fs_mgr()
        dag = fs._load_dag()
        if node_id not in dag.nodes:
            raise HTTPException(status_code=404, detail="伏笔不存在")
        dag.nodes.pop(node_id, None)
        dag.status.pop(node_id, None)
        dag.edges = [
            edge for edge in dag.edges if edge.source != node_id and edge.target != node_id
        ]
        fs._save_dag(dag)
        return {"ok": True, "deleted": node_id}

    @app.get("/api/foreshadowing/statistics")
    async def api_foreshadowing_stats():
        fs = _fs_mgr()
        return fs.get_statistics()

    @app.get("/api/chapters")
    async def api_chapters():
        return _list_markdown_files(_outline_chapters_dir())

    @app.get("/api/chapters/{chapter_id}")
    async def api_chapter_detail(chapter_id: str):
        path = _outline_chapters_dir() / f"{chapter_id}.md"
        if not path.exists():
            raise HTTPException(status_code=404, detail="章节不存在")
        return {
            "id": chapter_id,
            "content": path.read_text(encoding="utf-8"),
            "updated_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
        }

    @app.get("/api/drafts")
    async def api_drafts():
        return _list_markdown_files(_drafts_dir())

    @app.get("/api/drafts/{draft_id}")
    async def api_draft_detail(draft_id: str):
        path = _resolve_draft_path(draft_id)
        if not path.exists():
            raise HTTPException(status_code=404, detail="草稿不存在")
        return {
            "id": draft_id,
            "content": path.read_text(encoding="utf-8"),
            "updated_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(),
        }

    @app.put("/api/drafts/{draft_id}")
    async def api_draft_update(draft_id: str, payload: DraftContentRequest):
        path = _resolve_draft_path(draft_id)
        if not path.exists():
            raise HTTPException(status_code=404, detail="草稿不存在")
        path.write_text(payload.content, encoding="utf-8")
        return {"ok": True, "id": draft_id, "path": str(path)}

    @app.post("/api/drafts/{draft_id}")
    async def api_draft_create(draft_id: str, payload: DraftContentRequest):
        path = _resolve_draft_path(draft_id)
        if path.exists():
            raise HTTPException(status_code=409, detail="草稿已存在")
        path.write_text(payload.content, encoding="utf-8")
        return {"ok": True, "id": draft_id, "path": str(path)}

    @app.post("/api/simulate/chapter")
    async def api_simulate_chapter(payload: SimulateChapterRequest):
        task_id = f"sim_{uuid4().hex}"
        _SIM_TASKS[task_id] = {
            "task_id": task_id,
            "novel_id": novel_id,
            "chapter_id": payload.chapter_id,
            "status": "queued",
            "stage": "queued",
            "progress": 0,
            "events": [],
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "result": None,
            "error": None,
        }
        asyncio.create_task(_run_simulation_task(task_id, payload))
        return {"task_id": task_id, "status": "queued"}

    @app.get("/api/simulate/status/{task_id}")
    async def api_simulate_status(task_id: str):
        task = _SIM_TASKS.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        return {
            "task_id": task["task_id"],
            "chapter_id": task.get("chapter_id", ""),
            "status": task.get("status", "queued"),
            "stage": task.get("stage", "queued"),
            "progress": task.get("progress", 0),
            "created_at": task.get("created_at"),
            "updated_at": task.get("updated_at"),
            "result": task.get("result"),
            "error": task.get("error"),
        }

    @app.get("/api/simulate/stream/{task_id}")
    async def api_simulate_stream(task_id: str):
        if task_id not in _SIM_TASKS:
            raise HTTPException(status_code=404, detail="任务不存在")

        async def event_generator():
            sent_index = 0
            while True:
                task = _SIM_TASKS.get(task_id)
                if task is None:
                    break

                events = task.get("events", [])
                while sent_index < len(events):
                    event = events[sent_index]
                    sent_index += 1
                    yield (
                        f"event: {event.get('event', 'progress')}\n"
                        f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                    )

                if task.get("status") in {"completed", "failed"} and sent_index >= len(events):
                    done_payload = {
                        "event": "end",
                        "task_id": task_id,
                        "status": task.get("status"),
                        "result": task.get("result"),
                        "error": task.get("error"),
                    }
                    yield f"event: end\ndata: {json.dumps(done_payload, ensure_ascii=False)}\n\n"
                    break

                await asyncio.sleep(0.4)

        headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers=headers,
        )

    @app.post("/api/style/compose")
    async def api_style_compose(payload: StyleComposeRequest):
        composer = StyleComposer(proj)
        composed = composer.compose(
            novel_id=payload.novel_id,
            style_id=payload.style_id,
            write_output=True,
        )
        output_path = composer.get_composed_path(payload.novel_id)
        return {
            "ok": True,
            "novel_id": payload.novel_id,
            "style_id": payload.style_id,
            "output": str(output_path),
            "summary": composed.source_summary,
        }

    @app.get("/api/style/profile/{target_novel_id}")
    async def api_style_profile(target_novel_id: str):
        profile = StyleProfile.from_project(project_root=proj, novel_id=target_novel_id)
        return {
            "novel_id": target_novel_id,
            "summary": profile.to_summary(max_chars=3000),
            "metrics": profile.quality_metrics.model_dump(),
            "banned_phrases": [item.model_dump() for item in profile.banned_phrases],
            "positive_features": profile.positive_features.model_dump(),
        }

    @app.get("/api/style/list")
    async def api_style_list():
        composer = StyleComposer(proj)
        return {
            "styles": composer.list_available_styles(),
            "novels": composer.list_available_novels(),
        }


    # ── Phase 7C-1: Pipeline V2 任务存储 ────────────────────────────
    _V2_TASKS: Dict[str, Dict[str, Any]] = {}

    def _initializer() -> NovelInitializer:
        return NovelInitializer(project_dir=proj, novel_id=novel_id)

    def _load_hierarchy() -> Optional[OutlineHierarchy]:
        return _initializer().load_hierarchy()

    # ── Novel Init API ────────────────────────────────────────

    @app.post("/api/novel/init")
    async def api_novel_init(payload: NovelInitRequest):
        init = _initializer()
        result = init.initialize(
            title=payload.title,
            core_theme=payload.core_theme,
            ending_direction=payload.ending_direction,
            world_premise=payload.world_premise,
            tone=payload.tone,
            target_word_count=payload.target_word_count,
            key_turns=payload.key_turns,
            arc_sketches=payload.arc_sketches,
            character_sketches=payload.character_sketches,
            world_entities=payload.world_entities,
        )
        return {
            "success": result.success,
            "novel_id": result.novel_id,
            "master_title": result.master_outline.title if result.master_outline else "",
            "arcs_count": len(result.hierarchy.arcs) if result.hierarchy else 0,
            "characters_count": len(result.characters),
            "world_entities_created": result.world_entities_created,
            "errors": result.errors,
        }

    # ── Outline Markdown Import/Export API ────────────────────
    @app.post("/api/outline/import")
    async def api_outline_import(payload: OutlineMdImportRequest):
        """导入 Markdown 大纲文本，解析为 OutlineHierarchy 并保存。"""
        from tools.parsers.outline_md_parser import parse_outline_md
        try:
            hierarchy = parse_outline_md(payload.content)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"解析失败: {str(e)}")
        # 保存到 hierarchy.yaml
        init = _initializer()
        init.outline_dir.mkdir(parents=True, exist_ok=True)
        with init.hierarchy_file.open("w", encoding="utf-8") as f:
            yaml.safe_dump(hierarchy.model_dump(), f, allow_unicode=True, sort_keys=False)
        return {
            "ok": True,
            "novel_id": hierarchy.master.novel_id,
            "title": hierarchy.master.title,
            "arcs_count": len(hierarchy.arcs),
            "sections_count": len(hierarchy.sections),
            "chapters_count": len(hierarchy.chapters),
        }

    @app.get("/api/outline/export")
    async def api_outline_export():
        """导出当前 OutlineHierarchy 为 Markdown 文本。"""
        from tools.utils.outline_md_serializer import serialize_outline_md
        h = _load_hierarchy()
        if h is None:
            raise HTTPException(status_code=404, detail="大纲不存在，请先初始化或导入")
        content = serialize_outline_md(h)
        return {
            "content": content,
            "novel_id": h.master.novel_id,
            "title": h.master.title,
        }
    # ── Outline Hierarchy API ──────────────────────────────────

    @app.get("/api/outline/hierarchy")
    async def api_outline_hierarchy():
        h = _load_hierarchy()
        if h is None:
            return {"master": None, "arcs": [], "sections": [], "chapters": []}
        return {
            "master": h.master.model_dump(),
            "arcs": [a.model_dump() for a in h.get_all_arcs_ordered()],
            "sections": [s.model_dump() for s in h.sections.values()],
            "chapters": [c.model_dump() for c in h.chapters.values()],
        }

    @app.get("/api/outline/master")
    async def api_outline_master():
        h = _load_hierarchy()
        if h is None:
            raise HTTPException(status_code=404, detail="大纲不存在，请先初始化")
        return h.master.model_dump()

    @app.get("/api/outline/arcs")
    async def api_outline_arcs():
        h = _load_hierarchy()
        if h is None:
            return []
        return [a.model_dump() for a in h.get_all_arcs_ordered()]

    @app.post("/api/outline/arcs")
    async def api_outline_arc_create(payload: OutlineArcRequest):
        init = _initializer()
        h = init.load_hierarchy()
        if h is None:
            raise HTTPException(status_code=404, detail="请先初始化大纲")
        from tools.models.outline import ArcOutline
        arc = ArcOutline(
            arc_id=payload.arc_id,
            novel_id=novel_id,
            title=payload.title,
            order=payload.order,
            main_conflict=payload.main_conflict,
            resolution=payload.resolution,
            key_characters=payload.key_characters,
        )
        h.arcs[payload.arc_id] = arc
        if payload.arc_id not in h.master.arc_ids:
            h.master.arc_ids.append(payload.arc_id)
        init._save_hierarchy(h)
        return arc.model_dump()

    @app.put("/api/outline/arcs/{arc_id}")
    async def api_outline_arc_update(arc_id: str, payload: OutlineArcRequest):
        init = _initializer()
        h = init.load_hierarchy()
        if h is None or arc_id not in h.arcs:
            raise HTTPException(status_code=404, detail="篇纲不存在")
        arc = h.arcs[arc_id]
        arc.title = payload.title or arc.title
        arc.order = payload.order or arc.order
        arc.main_conflict = payload.main_conflict or arc.main_conflict
        arc.resolution = payload.resolution or arc.resolution
        if payload.key_characters:
            arc.key_characters = payload.key_characters
        init._save_hierarchy(h)
        return arc.model_dump()

    @app.delete("/api/outline/arcs/{arc_id}")
    async def api_outline_arc_delete(arc_id: str):
        init = _initializer()
        h = init.load_hierarchy()
        if h is None or arc_id not in h.arcs:
            raise HTTPException(status_code=404, detail="篇纲不存在")
        h.arcs.pop(arc_id)
        h.master.arc_ids = [a for a in h.master.arc_ids if a != arc_id]
        init._save_hierarchy(h)
        return {"ok": True, "deleted": arc_id}

    # ── Section CRUD ─────────────────────────────────────────
    @app.post("/api/outline/sections")
    async def api_outline_section_create(payload: OutlineSectionRequest):
        init = _initializer()
        h = init.load_hierarchy()
        if h is None:
            raise HTTPException(status_code=404, detail="请先初始化大纲")
        from tools.models.outline import SectionOutline
        sec = SectionOutline(
            section_id=payload.section_id,
            arc_id=payload.arc_id,
            title=payload.title,
            order=payload.order,
            plot_summary=payload.plot_summary,
            key_events=payload.key_events,
        )
        h.sections[payload.section_id] = sec
        if payload.arc_id and payload.arc_id in h.arcs:
            arc = h.arcs[payload.arc_id]
            if payload.section_id not in arc.section_ids:
                arc.section_ids.append(payload.section_id)
        init._save_hierarchy(h)
        return sec.model_dump()
    @app.put("/api/outline/sections/{section_id}")
    async def api_outline_section_update(section_id: str, payload: OutlineSectionRequest):
        init = _initializer()
        h = init.load_hierarchy()
        if h is None or section_id not in h.sections:
            raise HTTPException(status_code=404, detail="节纲不存在")
        sec = h.sections[section_id]
        sec.title = payload.title or sec.title
        sec.order = payload.order or sec.order
        sec.plot_summary = payload.plot_summary or sec.plot_summary
        if payload.key_events:
            sec.key_events = payload.key_events
        init._save_hierarchy(h)
        return sec.model_dump()
    @app.delete("/api/outline/sections/{section_id}")
    async def api_outline_section_delete(section_id: str):
        init = _initializer()
        h = init.load_hierarchy()
        if h is None or section_id not in h.sections:
            raise HTTPException(status_code=404, detail="节纲不存在")
        sec = h.sections.pop(section_id)
        if sec.arc_id and sec.arc_id in h.arcs:
            arc = h.arcs[sec.arc_id]
            arc.section_ids = [s for s in arc.section_ids if s != section_id]
        init._save_hierarchy(h)
        return {"ok": True, "deleted": section_id}
    # ── Chapter Outline CRUD ──────────────────────────────────
    @app.post("/api/outline/chapters")
    async def api_outline_chapter_create(payload: OutlineChapterRequest):
        init = _initializer()
        h = init.load_hierarchy()
        if h is None:
            raise HTTPException(status_code=404, detail="请先初始化大纲")
        from tools.models.outline import ChapterOutline as ChOutline
        ch = ChOutline(
            chapter_id=payload.chapter_id,
            section_id=payload.section_id,
            title=payload.title,
            order=payload.order,
            goals=payload.goals,
            key_scenes=payload.key_scenes,
            emotion_arc=payload.emotion_arc,
            involved_characters=payload.involved_characters,
            involved_settings=payload.involved_settings,
            foreshadowing_refs=payload.foreshadowing_refs,
            target_words=payload.target_words,
        )
        h.chapters[payload.chapter_id] = ch
        if payload.section_id and payload.section_id in h.sections:
            sec = h.sections[payload.section_id]
            if payload.chapter_id not in sec.chapter_ids:
                sec.chapter_ids.append(payload.chapter_id)
        init._save_hierarchy(h)
        return ch.model_dump()
    @app.put("/api/outline/chapters/{chapter_id}")
    async def api_outline_chapter_update(chapter_id: str, payload: OutlineChapterRequest):
        init = _initializer()
        h = init.load_hierarchy()
        if h is None or chapter_id not in h.chapters:
            raise HTTPException(status_code=404, detail="章纲不存在")
        ch = h.chapters[chapter_id]
        ch.title = payload.title or ch.title
        ch.order = payload.order or ch.order
        if payload.goals:
            ch.goals = payload.goals
        if payload.key_scenes:
            ch.key_scenes = payload.key_scenes
        ch.emotion_arc = payload.emotion_arc or ch.emotion_arc
        if payload.involved_characters:
            ch.involved_characters = payload.involved_characters
        if payload.involved_settings:
            ch.involved_settings = payload.involved_settings
        if payload.foreshadowing_refs:
            ch.foreshadowing_refs = payload.foreshadowing_refs
        ch.target_words = payload.target_words or ch.target_words
        init._save_hierarchy(h)
        return ch.model_dump()
    @app.delete("/api/outline/chapters/{chapter_id}")
    async def api_outline_chapter_delete(chapter_id: str):
        init = _initializer()
        h = init.load_hierarchy()
        if h is None or chapter_id not in h.chapters:
            raise HTTPException(status_code=404, detail="章纲不存在")
        ch = h.chapters.pop(chapter_id)
        if ch.section_id and ch.section_id in h.sections:
            sec = h.sections[ch.section_id]
            sec.chapter_ids = [c for c in sec.chapter_ids if c != chapter_id]
        init._save_hierarchy(h)
        return {"ok": True, "deleted": chapter_id}

    # ── Pipeline V2 API ─────────────────────────────────────
    @app.post("/api/v2/pipeline/start")
    async def api_v2_pipeline_start(payload: PipelineV2StartRequest):
        init = _initializer()
        h = init.load_hierarchy()
        if h is None:
            raise HTTPException(status_code=404, detail="请先初始化大纲")
        chapter = h.get_chapter(payload.chapter_id)
        if chapter is None:
            raise HTTPException(status_code=404, detail="章纲不存在")
        task_id = f"v2_{uuid4().hex}"
        _V2_TASKS[task_id] = {
            "task_id": task_id, "novel_id": novel_id,
            "chapter_id": payload.chapter_id, "status": "running",
            "stage": "director", "progress": 0, "events": [],
            "result": None, "error": None, "pipeline_result": None,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }
        async def _run_v2(tid: str):
            task = _V2_TASKS[tid]
            try:
                llm_client = None
                router = None
                llm_cfg = load_llm_config(None)
                if llm_cfg.enabled:
                    llm_client = LLMClient(retry_count=llm_cfg.retry_count, retry_delay=llm_cfg.retry_delay)
                    router = ModelRouter(llm_cfg)
                sim = PipelineSimulatorV2(
                    project_dir=proj, novel_id=novel_id,
                    llm_client=llm_client, router=router,
                )
                _emit_task_event(tid, stage="director", status="running", message="组装上下文", progress=10)
                pr = await asyncio.to_thread(
                    sim.run_pipeline, chapter=chapter, hierarchy=h,
                    writing_prompt=payload.writing_prompt,
                    strict_review=payload.strict_review,
                    max_rewrites=payload.max_rewrites,
                    auto_approve=False, use_stylist=payload.use_stylist,
                )
                task["pipeline_result"] = pr
                needs_review = pr.needs_user_review
                task["status"] = "waiting_user" if needs_review else "completed"
                sev = pr.review.severity if pr.review else "none"
                warns = pr.review.warnings if pr.review else []
                errs = pr.review.errors if pr.review else []
                task["result"] = {
                    "chapter_id": pr.chapter_id, "draft_length": len(pr.draft_text),
                    "severity": sev, "warnings": warns, "errors": errs,
                    "needs_user_review": needs_review,
                }
                done_stage = "user_review" if needs_review else "completed"
                done_msg = "等待用户确认" if needs_review else "管线完成"
                done_pct = 90 if needs_review else 100
                _emit_task_event(tid, stage=done_stage, status=task["status"], message=done_msg, progress=done_pct)
            except Exception as exc:
                task["status"] = "failed"
                task["error"] = str(exc)
                _emit_task_event(tid, stage="failed", status="failed", message=str(exc), progress=100)
            task["updated_at"] = datetime.now().isoformat()
        asyncio.create_task(_run_v2(task_id))
        return {"task_id": task_id, "status": "running"}

    @app.get("/api/v2/pipeline/status/{task_id}")
    async def api_v2_pipeline_status(task_id: str):
        task = _V2_TASKS.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        return {
            "task_id": task["task_id"], "status": task["status"],
            "stage": task.get("stage", ""), "progress": task.get("progress", 0),
            "result": task.get("result"), "error": task.get("error"),
        }

    @app.get("/api/v2/pipeline/stream/{task_id}")
    async def api_v2_pipeline_stream(task_id: str):
        if task_id not in _V2_TASKS:
            raise HTTPException(status_code=404, detail="任务不存在")
        async def gen():
            sent = 0
            while True:
                task = _V2_TASKS.get(task_id)
                if task is None:
                    break
                evts = task.get("events", [])
                while sent < len(evts):
                    evt = evts[sent]
                    sent += 1
                    yield f"event: progress\ndata: {json.dumps(evt, ensure_ascii=False)}\n\n"
                st = task.get("status", "")
                if st in {"completed", "failed", "waiting_user"} and sent >= len(evts):
                    end_data = {"event": "end", "task_id": task_id, "status": st, "result": task.get("result"), "error": task.get("error")}
                    yield f"event: end\ndata: {json.dumps(end_data, ensure_ascii=False)}\n\n"
                    break
                await asyncio.sleep(0.4)
        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.post("/api/v2/pipeline/approve/{task_id}")
    async def api_v2_pipeline_approve(task_id: str, payload: PipelineApproveRequest):
        task = _V2_TASKS.get(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        if task["status"] != "waiting_user":
            raise HTTPException(status_code=400, detail="任务不在等待用户确认状态")
        pr = task.get("pipeline_result")
        if not payload.approved:
            task["status"] = "rejected"
            task["updated_at"] = datetime.now().isoformat()
            return {"ok": True, "status": "rejected"}
        # User approved — optionally apply edits then run stylist
        draft = payload.user_edits if payload.user_edits else (pr.draft_text if pr else "")
        if pr and pr.stages and any(s.name == "stylist" for s in pr.stages):
            task["status"] = "completed"
        else:
            # Run stylist if pipeline was configured for it
            task["status"] = "completed"
        task["updated_at"] = datetime.now().isoformat()
        return {"ok": True, "status": "completed", "draft_length": len(draft)}

    # ── LLM Settings API ────────────────────────────────────
    @app.get("/api/settings/llm")
    async def api_settings_llm_get():
        cfg_path = proj / "llm_config.yaml"
        if not cfg_path.exists():
            return {"enabled": False, "retry_count": 2, "retry_delay": 1.0, "routes": {}, "default_route": {}}
        with cfg_path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        return raw

    @app.put("/api/settings/llm")
    async def api_settings_llm_update(payload: LLMConfigUpdateRequest):
        cfg_path = proj / "llm_config.yaml"
        data = {
            "enabled": payload.enabled,
            "retry_count": payload.retry_count,
            "retry_delay": payload.retry_delay,
        }
        if payload.default_route:
            data["default_route"] = payload.default_route
        if payload.routes:
            data["routes"] = payload.routes
        with cfg_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
        return {"ok": True}

    # ── Text Character Profile API ───────────────────────────
    @app.get("/api/v2/characters")
    async def api_v2_characters():
        init = _initializer()
        profiles = init.load_text_characters()
        return [p.model_dump() for p in profiles]

    @app.post("/api/v2/characters")
    async def api_v2_character_create(payload: TextCharacterRequest):
        from tools.models.character import TextCharacterProfile
        char_id = f"char_{payload.name}"
        profile = TextCharacterProfile(
            id=char_id, name=payload.name, char_type=payload.char_type,
            appearance=payload.appearance, personality_and_voice=payload.personality_and_voice,
            skills_and_abilities=payload.skills_and_abilities, items=payload.items,
            attributes=payload.attributes, notes=payload.notes,
            faction=payload.faction, aliases=payload.aliases,
        )
        init = _initializer()
        init.characters_dir.mkdir(parents=True, exist_ok=True)
        path = init.characters_dir / f"{char_id}.yaml"
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(profile.model_dump(), f, allow_unicode=True, sort_keys=False)
        return profile.model_dump()

    @app.delete("/api/v2/characters/{char_id}")
    async def api_v2_character_delete(char_id: str):
        init = _initializer()
        path = init.characters_dir / f"{char_id}.yaml"
        if not path.exists():
            raise HTTPException(status_code=404, detail="人物不存在")
        path.unlink()
        return {"ok": True, "deleted": char_id}

    # ── Settings 页面路由 ─────────────────────────────────────
    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page(request: Request):
        return templates.TemplateResponse("settings.html", {"request": request, "novel_id": novel_id})
    return app
