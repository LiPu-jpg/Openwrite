"""OpenWrite Web 应用 — FastAPI + Jinja2 本地可视化面板。"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# ── 延迟导入项目模块（避免循环） ──────────────────────────────────

_WEB_DIR = Path(__file__).parent
_TEMPLATES_DIR = _WEB_DIR / "templates"
_STATIC_DIR = _WEB_DIR / "static"


def create_app(
    project_dir: Optional[Path] = None, novel_id: str = "my_novel"
) -> FastAPI:
    """创建 FastAPI 应用实例。"""
    from tools.character_state_manager import CharacterStateManager
    from tools.graph.foreshadowing_dag import ForeshadowingDAGManager
    from tools.models.style import StyleProfile
    from tools.narrative_timeline_manager import NarrativeTimelineManager
    from tools.narrative_renderer import render_html as render_timeline_html
    from tools.queries.character_query import CharacterQuery
    from tools.utils.style_composer import StyleComposer
    from tools.world_conflict_checker import WorldConflictChecker
    from tools.world_graph_manager import WorldGraphManager
    from tools.world_graph_renderer import render_world_graph_html
    from tools.world_rule_engine import WorldRuleEngine

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
            try:
                state = query.get_current_state(c.static.name)
                char_data.append(
                    {
                        "id": c.static.id,
                        "name": c.static.name,
                        "tier": c.static.tier,
                        "faction": c.static.faction,
                        "realm": state["state"].get("realm", ""),
                        "location": state["state"].get("location", ""),
                    }
                )
            except Exception:
                char_data.append(
                    {
                        "id": c.static.id,
                        "name": c.static.name,
                        "tier": c.static.tier,
                        "faction": c.static.faction,
                        "realm": "",
                        "location": "",
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
            nodes_data.append(
                {
                    "id": nid,
                    "content": node.content if hasattr(node, "content") else str(node),
                    "layer": node.layer if hasattr(node, "layer") else "",
                    "weight": node.weight if hasattr(node, "weight") else 0,
                    "status": dag.status.get(nid, "planted"),
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
        # 读取大纲列表
        outline_dir = proj / "data" / "novels" / novel_id / "outline" / "chapters"
        chapters = []
        if outline_dir.exists():
            for f in sorted(outline_dir.glob("*.md")):
                chapters.append({"id": f.stem, "name": f.stem})
        # 读取已有草稿
        ms_dir = proj / "data" / "novels" / novel_id / "manuscript"
        drafts = []
        if ms_dir.exists():
            for f in sorted(ms_dir.glob("*.md")):
                drafts.append({"id": f.stem, "name": f.stem})
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

    @app.get("/api/world/relations")
    async def api_world_relations():
        world = _world_mgr()
        relations = world.list_relations()
        return [
            {
                "source_id": r.source_id,
                "target_id": r.target_id,
                "relation": r.relation,
                "weight": r.weight,
                "note": r.note,
                "chapter_id": r.chapter_id,
            }
            for r in relations
        ]

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
        return [
            {
                "id": c.static.id,
                "name": c.static.name,
                "tier": c.static.tier,
                "faction": c.static.faction,
            }
            for c in all_chars
        ]

    @app.get("/api/characters/{name}")
    async def api_character_detail(name: str):
        query = _char_query()
        try:
            state = query.get_current_state(name)
            timeline = query.get_timeline(name)
            return {"state": state, "timeline": timeline}
        except Exception as e:
            return JSONResponse(status_code=404, content={"error": str(e)})

    @app.get("/api/foreshadowing")
    async def api_foreshadowing():
        fs = _fs_mgr()
        dag = fs._load_dag()
        nodes = []
        for nid, node in dag.nodes.items():
            nodes.append(
                {
                    "id": nid,
                    "content": node.content if hasattr(node, "content") else "",
                    "layer": node.layer if hasattr(node, "layer") else "",
                    "weight": node.weight if hasattr(node, "weight") else 0,
                    "status": dag.status.get(nid, "planted"),
                }
            )
        edges = []
        for edge in dag.edges:
            edges.append({"source": edge.source, "target": edge.target})
        return {"nodes": nodes, "edges": edges, "statistics": fs.get_statistics()}

    @app.get("/api/foreshadowing/statistics")
    async def api_foreshadowing_stats():
        fs = _fs_mgr()
        return fs.get_statistics()

    return app
