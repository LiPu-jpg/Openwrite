import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import tools.agent.tool_layers as tool_layers_module
import tools.cli as cli_module
from tools.agent.tool_runtime import build_tool_executors
from tools.agent.toolkits import (
    DANTE_ACTION_TOOLKIT,
    DANTE_DIRECT_TOOLKIT,
    GOETHE_DIRECT_TOOLKIT,
    ORCHESTRATOR_TOOLKIT,
    WRITING_TOOLKIT,
)


def test_build_tool_executors_contains_existing_openwrite_tools(tmp_path: Path):
    executors = build_tool_executors(project_root=tmp_path)
    assert ORCHESTRATOR_TOOLKIT.issubset(executors.keys())
    assert WRITING_TOOLKIT.issubset(executors.keys())


def test_agent_manuscript_change_enters_acceptance_protocol(tmp_path: Path):
    from tools.init_project import init_project
    from tools.manuscript_acceptance import ManuscriptAcceptanceService

    init_project(tmp_path, "demo")
    chapter = (
        tmp_path
        / "data"
        / "novels"
        / "demo"
        / "data"
        / "manuscript"
        / "arc_001"
        / "ch_001.md"
    )
    chapter.write_text("# 第一章\n\n旧句。\n", encoding="utf-8")
    executor = build_tool_executors(tmp_path)["edit_project_document"]

    preview = executor(
        {
            "path": "data/manuscript/arc_001/ch_001.md",
            "edits": [{"old_text": "旧句。", "new_text": "新句。"}],
        }
    )
    applied = executor({"preview_token": preview["preview_token"], "confirm": True})

    assert applied["ok"] is True
    assert applied["acceptance"]["status"] == "pending"
    assert applied["acceptance"]["current_revision"].startswith("sha256:")
    surface = ManuscriptAcceptanceService(tmp_path, "demo").inspect()
    assert surface["status"] == "pending"
    assert surface["latest_operation_id"] == applied["acceptance"]["operation_id"]


def test_build_tool_executors_owns_registry_outside_cli(monkeypatch, tmp_path: Path):
    from tools.init_project import init_project
    from tools.novel_service import NovelApplicationService

    init_project(tmp_path, "demo")
    monkeypatch.setattr(
        cli_module,
        "build_cli_tool_executors",
        lambda root: (_ for _ in ()).throw(
            AssertionError("agent registry must not call the CLI factory")
        ),
    )
    monkeypatch.setattr(
        NovelApplicationService,
        "write_chapter",
        lambda self, args: {"ok": True, "chapter_id": args["chapter_id"]},
    )

    executors = build_tool_executors(project_root=tmp_path)
    assert executors["write_chapter"]({"chapter_id": "ch_001"}) == {
        "ok": True,
        "chapter_id": "ch_001",
    }


def test_agent_direct_tools_do_not_call_cli_private_functions(monkeypatch, tmp_path: Path):
    from tools.init_project import init_project

    init_project(tmp_path, "demo")

    def forbidden(*args, **kwargs):
        raise AssertionError("direct agent tools must not call CLI private functions")

    for name in (
        "_exec_get_status",
        "_exec_get_context",
        "_exec_list_chapters",
        "_exec_get_truth_files",
        "_exec_query_world",
        "_exec_get_world_relations",
    ):
        monkeypatch.setattr(cli_module, name, forbidden)

    executors = build_tool_executors(tmp_path)
    assert executors["get_status"]({})["novel_id"] == "demo"
    context = executors["get_context"]({"chapter_id": "ch_001"})
    assert context["chapter_id"] == "ch_001"
    assert (
        context["compression"]["message_budget"]["strategy"]
        == "staircase-proportional-v3"
    )
    assert (
        context["compression"]["packet_documents"]["strategy"]
        == "staircase-proportional-v3"
    )
    assert executors["list_chapters"]({}) == {"chapters": []}
    assert "current_state" in executors["get_truth_files"]({})
    library = executors["query_library"]({"scope": "core"})
    assert library["scope"] == "core"
    assert all(item["scope"] == "core" for item in library["items"])
    assert executors["query_world"]({})["count"] >= 0
    assert "relations" in executors["get_world_relations"]({})
    outline = executors["get_outline_structure"]({})
    assert outline["path"] == "src/outline.md"
    assert "recommendation" in outline
    edit_args = {
        "operation": "rename",
        "revision": outline["revision"],
        "node_id": "volume_001",
        "title": "第一卷：增量编辑",
    }
    preview = executors["edit_outline_structure"](edit_args)
    assert preview["ok"] is True
    assert preview["applied"] is False
    assert "+# 第一卷：增量编辑" in preview["diff"]
    edited = executors["edit_outline_structure"](
        {
            **edit_args,
            "confirm": True,
        }
    )
    assert edited["ok"] is True
    assert edited["applied"] is True
    assert edited["outline"]["roots"][0]["title"] == "第一卷：增量编辑"
    outline_path = tmp_path / "data" / "novels" / "demo" / "src" / "outline.md"
    outline = edited["outline"]
    summary_args = {
        "operation": "update_summary",
        "revision": outline["revision"],
        "node_id": "section_001",
        "summary": "这一节由 Agent 直接修改节点内容。",
    }
    preview = executors["edit_outline_structure"](summary_args)
    assert preview["ok"] is True
    assert preview["applied"] is False
    assert "+这一节由 Agent 直接修改节点内容。" in preview["diff"]
    edited_summary = executors["edit_outline_structure"](
        {
            **summary_args,
            "confirm": True,
        }
    )
    assert edited_summary["applied"] is True
    assert "这一节由 Agent 直接修改节点内容。" in outline_path.read_text(encoding="utf-8")

    outline_path.write_text(
        "# 第一卷\n## 第一幕\n### 第一节\n"
        "#### 第14章：删除\n#### 第15章：补位\n#### 第16章：继续\n",
        encoding="utf-8",
    )
    outline = executors["get_outline_structure"]({})
    delete_args = {
        "operation": "delete",
        "revision": outline["revision"],
        "node_id": "ch_014",
    }
    preview = executors["edit_outline_structure"](delete_args)
    assert preview["applied"] is False
    assert [(item["old_id"], item["new_id"]) for item in preview["renumbered"]] == [
        ("ch_015", "ch_014"),
        ("ch_016", "ch_015"),
    ]
    assert "-#### 第14章：删除" in preview["diff"]
    assert "+#### 第14章：补位" in preview["diff"]
    assert "第14章：删除" in outline_path.read_text(encoding="utf-8")
    applied = executors["edit_outline_structure"]({**delete_args, "confirm": True})
    assert applied["applied"] is True
    assert "第14章：补位" in outline_path.read_text(encoding="utf-8")

    relation_source = (
        tmp_path / "data" / "novels" / "demo" / "src" / "characters" / "source.md"
    )
    relation_target = relation_source.with_name("target.md")
    relation_source.parent.mkdir(parents=True, exist_ok=True)
    relation_source.write_text("# 源人物\n", encoding="utf-8")
    relation_target.write_text("# 目标人物\n", encoding="utf-8")
    original = relation_source.read_text(encoding="utf-8")
    preview = executors["edit_world_relation"](
        {"source_id": "source", "target_id": "target", "description": "盟友"}
    )
    assert preview["ok"] is True
    assert preview["applied"] is False
    assert "[[related]]" in preview["diff"]
    assert relation_source.read_text(encoding="utf-8") == original


def test_relation_preview_tokens_survive_turns_and_replace_regenerated_arguments():
    from tools.agent.confirmation import (
        RELATION_PREVIEW_TOKENS_KEY,
        remember_relation_previews,
    )

    memory: dict[str, object] = {}
    persisted: list[dict[str, object]] = []
    instruction = {"text": "批量预览这些关系"}
    calls: list[dict] = []
    preview_tokens = iter(("a" * 24, "b" * 24))

    def executor(args: dict) -> dict:
        calls.append(args)
        if args.get("confirm"):
            return {"ok": True, "applied": True}
        return {"ok": True, "applied": False, "preview_token": next(preview_tokens)}

    wrapped = remember_relation_previews(
        {"edit_world_relations": executor},
        working_memory=lambda: memory,
        persist=lambda: persisted.append(dict(memory)),
        instruction=lambda: instruction["text"],
    )["edit_world_relations"]

    wrapped({"relations": [{"source_id": "hero", "target_id": "city"}]})
    wrapped({"relations": [{"source_id": "hero", "target_id": "ability"}]})
    assert memory[RELATION_PREVIEW_TOKENS_KEY] == ["a" * 24, "b" * 24]

    instruction["text"] = "确认应用"
    result = wrapped(
        {
            "relations": [{"source_id": "模型重新生成的错字", "target_id": "city"}],
            "confirm": True,
        }
    )

    assert result["applied"] is True
    assert calls[-1] == {"confirm": True, "preview_tokens": ["a" * 24, "b" * 24]}
    assert RELATION_PREVIEW_TOKENS_KEY not in memory
    assert len(persisted) == 3


def test_document_preview_tokens_survive_turns_and_follow_document_paths():
    from tools.agent.confirmation import (
        DOCUMENT_PREVIEWS_KEY,
        remember_document_edit_previews,
    )

    memory: dict[str, object] = {}
    persisted: list[dict[str, object]] = []
    instruction = {"text": "修改两份设定"}
    calls: list[dict] = []
    preview_tokens = iter(("a" * 24, "b" * 24))

    def executor(args):
        calls.append(args)
        if args.get("confirm"):
            return {"ok": True, "applied": True}
        return {
            "ok": True,
            "applied": False,
            "path": args["path"],
            "preview_token": next(preview_tokens),
        }

    wrapped = remember_document_edit_previews(
        {"edit_project_document": executor},
        working_memory=lambda: memory,
        persist=lambda: persisted.append(dict(memory)),
        instruction=lambda: instruction["text"],
    )["edit_project_document"]

    wrapped({"path": "src/foundation.md", "edits": [{"old_text": "a"}]})
    wrapped({"path": "src/world/rules.md", "edits": [{"old_text": "b"}]})
    assert memory[DOCUMENT_PREVIEWS_KEY] == [
        {"path": "src/foundation.md", "preview_token": "a" * 24},
        {"path": "src/world/rules.md", "preview_token": "b" * 24},
    ]

    instruction["text"] = "确认应用两份文档修改"
    first = wrapped(
        {
            "path": "src/world/rules.md",
            "edits": [{"old_text": "模型重新生成的内容"}],
            "confirm": True,
        }
    )
    assert calls[-1] == {"confirm": True, "preview_token": "b" * 24}
    assert first["pending_document_previews"] == 1

    wrapped({"confirm": True})
    assert calls[-1] == {"confirm": True, "preview_token": "a" * 24}
    assert DOCUMENT_PREVIEWS_KEY not in memory
    assert len(persisted) == 4


def test_truth_tools_return_complete_documents_and_use_revisioned_append_preview(
    tmp_path: Path,
):
    from tools.init_project import init_project
    from tools.truth_manager import TruthFiles, TruthFilesManager

    init_project(tmp_path, "demo")
    long_state = "既有事实。" + "甲" * 900
    manager = TruthFilesManager(tmp_path, "demo")
    manager.save_truth_files(
        TruthFiles(
            current_state=long_state,
            ledger="旧账本。",
            relationships="旧关系。",
        )
    )
    executors = build_tool_executors(tmp_path)

    snapshot = executors["get_truth_files"]({})
    assert snapshot["schema_version"] == 1
    assert snapshot["revision"] == 0
    assert snapshot["current_state"] == long_state

    args = {
        "file_name": "current_state",
        "content": "本章新增事实。",
        "chapter_id": "ch_007",
        "source_revision": snapshot["revision"],
    }
    preview = executors["update_truth_file"](args)
    assert preview["ok"] is True
    assert preview["applied"] is False
    assert preview["operation"] == "append"
    assert "+本章新增事实。" in preview["diff"]
    assert manager.load_truth_files().current_state == long_state
    assert not (manager.world_dir / "runtime_state.json").exists()

    applied = executors["update_truth_file"]({**args, "confirm": True})
    assert applied["ok"] is True
    assert applied["applied"] is True
    assert applied["revision"] == 1
    updated = manager.load_truth_files().current_state
    assert long_state in updated
    assert "本章新增事实。" in updated

    conflict = executors["update_truth_file"]({**args, "confirm": True})
    assert conflict["ok"] is False
    assert conflict["conflict"] is True


def test_world_read_tools_do_not_silently_truncate_details_or_relations(
    monkeypatch,
    tmp_path: Path,
):
    import tools.world_query as world_query
    from tools.init_project import init_project

    init_project(tmp_path, "demo")
    description = "完整描述" * 100
    rules = [f"规则{i}" for i in range(12)]
    relations = [{"target": f"entity_{i}", "description": "关联"} for i in range(18)]
    entity = {
        "id": "entity_0",
        "name": "完整实体",
        "type": "地点",
        "subtype": "遗迹",
        "status": "active",
        "description": description,
        "rules": rules,
        "features": ["特征"],
        "relations": relations,
        "tags": [],
        "detail_refs": [],
        "extra_sections": {"历史": "完整段落"},
        "file": "entity_0.md",
    }
    edges = [
        {"source": "entity_0", "target": f"entity_{i}", "label": f"关系{i}"}
        for i in range(75)
    ]
    monkeypatch.setattr(world_query, "get_entity", lambda *args, **kwargs: entity)
    monkeypatch.setattr(
        world_query,
        "get_relations_topology",
        lambda *args, **kwargs: {
            "nodes": [{"id": "entity_0"}],
            "edges": edges,
            "totals": {"nodes": 1, "edges": len(edges)},
        },
    )
    executors = build_tool_executors(tmp_path)

    detail = executors["query_world"]({"entity_id": "entity_0"})["entity"]
    graph = executors["get_world_relations"]({})

    assert detail["description"] == description
    assert detail["rules"] == rules
    assert detail["relations"] == relations
    assert len(graph["relations"]) == 75


def test_orchestrator_toolkit_excludes_write_tools():
    assert "get_status" in ORCHESTRATOR_TOOLKIT
    assert "write_chapter" not in ORCHESTRATOR_TOOLKIT
    assert "review_chapter" in ORCHESTRATOR_TOOLKIT
    assert "create_character" in ORCHESTRATOR_TOOLKIT


def test_writing_toolkit_stays_small():
    assert WRITING_TOOLKIT == {
        "write_chapter",
        "get_context",
        "list_chapters",
        "get_truth_files",
        "get_character_state",
    }


def test_dante_direct_toolkit_exposes_only_light_tools():
    assert DANTE_DIRECT_TOOLKIT == {
        "get_status",
        "get_context",
        "query_library",
        "search_project",
        "read_project_document",
        "edit_project_document",
        "list_chapters",
        "get_truth_files",
        "get_character_state",
        "create_character",
        "query_world",
        "get_world_relations",
        "search_relation_targets",
        "edit_world_relation",
        "edit_world_relations",
        "get_outline_structure",
        "edit_outline_structure",
        "inspect_agent_context",
        "list_chapter_runs",
        "get_chapter_run_v2",
        "record_chapter_intervention",
        "update_chapter_intervention",
        "cancel_chapter_run_v2",
        "diagnose_runtime",
        "manage_rolling_plan",
        "manage_manuscript_versions",
        "manage_annotations",
        "get_runtime_state",
        "get_chapter_review",
        "get_task_activity",
        "get_goethe_handoff",
    }
    assert "write_chapter" not in DANTE_DIRECT_TOOLKIT
    assert "review_chapter" not in DANTE_DIRECT_TOOLKIT


def test_shared_agent_audit_tools_are_read_only_and_redacted(tmp_path: Path):
    from tools.chapter_pipeline import save_chapter
    from tools.chapter_run_store import ChapterRunStore
    from tools.init_project import init_project
    from tools.review_store import ReviewStore
    from tools.story_planning import StoryPlanningStore
    from tools.task_store import TaskStore
    from tools.truth_manager import TruthFiles, TruthFilesManager

    init_project(tmp_path, "demo", "审计工具", template="demo_short")
    truth_manager = TruthFilesManager(tmp_path, "demo")
    truth_manager.save_truth_files(
        TruthFiles(
            current_state="旧钟仍停在午夜。",
            ledger="铜钥匙：主角持有。",
            relationships="主角 -> 守钟人：怀疑。",
        )
    )
    state = truth_manager.load_runtime_state()
    truth_manager.apply_runtime_delta(
        {
            "chapter_id": "ch_001",
            "source_revision": state.revision,
            "operations": [
                {"op": "append", "collection": "current_state", "value": "钟声重新响起。"}
            ],
        }
    )
    save_chapter(tmp_path, "demo", "ch_001", "钟差", "雨落在钟楼上。")

    run_store = ChapterRunStore(tmp_path, "demo")
    run = run_store.create(
        "ch_001",
        requested_target_words=800,
        outline_target_words=1200,
        effective_target_words=800,
        provider="openai",
        model="flash",
        context_payload={"chapter_id": "ch_001"},
        baseline_state_revision=0,
    )
    run_store.complete_write(run, draft_content="雨落在钟楼上。", usage={"total_tokens": 12})
    ReviewStore(tmp_path, "demo").save(
        "ch_001",
        {"passed": True, "score": 95, "issue_details": []},
    )
    task_store = TaskStore(tmp_path, "demo")
    task = task_store.create(
        "write",
        {"api_key": "sk-temporary-audit-secret", "chapter_id": "ch_001"},
        chapter_id="ch_001",
    )
    StoryPlanningStore(tmp_path, "demo").save_goethe_handoff(
        {"ready": True, "summary": "资产齐备，可以开始第一章。"}
    )

    tools = build_tool_executors(tmp_path)
    context = tools["inspect_agent_context"](
        {"chapter_id": "ch_001", "agent": "writer"}
    )
    assert context["ok"] is True
    assert context["messages"]
    assert all("content" not in message for message in context["messages"])
    assert "agent_payload" not in context

    runs = tools["list_chapter_runs"]({"chapter_id": "ch_001"})
    assert runs["runs"][0]["run_id"] == run.run_id
    assert runs["runs"][0]["stages"]["write"]["usage"]["total_tokens"] == 12

    runtime = tools["get_runtime_state"]({})["runtime_state"]
    assert runtime["revision"] == 1
    assert "legacy_documents" not in runtime
    assert runtime["legacy_document_manifest"]["current_state"]["characters"] > 0

    review = tools["get_chapter_review"]({"chapter_id": "ch_001"})
    assert review["ok"] is True
    assert review["stale"] is False
    assert review["review"]["score"] == 95

    task_activity = tools["get_task_activity"]({"task_id": task["task_id"]})
    assert task_activity["ok"] is True
    assert task_activity["events"][0]["event"] == "task_created"
    assert "temporary-audit-secret" not in str(task_activity)

    handoff = tools["get_goethe_handoff"]({})
    assert handoff["ok"] is True
    assert handoff["manifest"]["ready"] is True
    assert "资产齐备" in handoff["markdown"]


def test_chapter_review_audit_marks_changed_manuscript_stale(tmp_path: Path):
    from tools.chapter_pipeline import save_chapter
    from tools.init_project import init_project
    from tools.review_store import ReviewStore

    init_project(tmp_path, "demo", "过期审稿", template="demo_short")
    save_chapter(tmp_path, "demo", "ch_001", "旧稿", "第一版正文。")
    ReviewStore(tmp_path, "demo").save(
        "ch_001", {"passed": True, "score": 100, "issue_details": []}
    )
    save_chapter(tmp_path, "demo", "ch_001", "新稿", "第二版正文已经变化。")

    result = build_tool_executors(tmp_path)["get_chapter_review"](
        {"chapter_id": "ch_001"}
    )

    assert result["ok"] is True
    assert result["stale"] is True


def test_runtime_state_audit_does_not_migrate_or_write_legacy_project(tmp_path: Path):
    from tools.init_project import init_project
    from tools.truth_manager import TruthFiles, TruthFilesManager

    init_project(tmp_path, "demo", "只读运行态", template="demo_short")
    manager = TruthFilesManager(tmp_path, "demo")
    manager.save_truth_files(TruthFiles(current_state="只存在于旧 Markdown。"))
    runtime_path = manager.world_dir / "runtime_state.json"
    assert not runtime_path.exists()

    before = {
        path.relative_to(tmp_path).as_posix()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    result = build_tool_executors(tmp_path)["get_runtime_state"]({})
    after = {
        path.relative_to(tmp_path).as_posix()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    assert result["ok"] is True
    assert result["runtime_state"]["revision"] == 0
    assert before == after
    assert not runtime_path.exists()


def test_goethe_and_dante_can_persist_persona_documents(tmp_path: Path):
    from tools.init_project import init_project

    init_project(tmp_path, "demo")
    goethe_layers = tool_layers_module.build_goethe_tool_layers(tmp_path)
    dante_layers = tool_layers_module.build_dante_tool_layers(tmp_path)

    assert "create_character" in GOETHE_DIRECT_TOOLKIT
    assert "create_character" in DANTE_DIRECT_TOOLKIT
    goethe_result = goethe_layers["direct_tool_executors"]["create_character"](
        {"name": "苔青", "description": "负责保存城市失落时间的钟楼管理员。"}
    )
    dante_result = dante_layers["direct_tool_executors"]["create_character"](
        {"name": "季砚", "description": "追踪匿名信来源的年轻记者。"}
    )

    assert goethe_result["ok"] is True
    assert dante_result["ok"] is True
    characters = tmp_path / "data" / "novels" / "demo" / "src" / "characters"
    assert (characters / "苔青.md").exists()
    assert (characters / "季砚.md").exists()


def test_agent_direct_tools_can_read_edit_and_link_project_documents(
    tmp_path: Path,
):
    from tools.init_project import init_project

    init_project(tmp_path, "demo")
    novel_root = tmp_path / "data" / "novels" / "demo"
    characters = novel_root / "src" / "characters"
    entities = novel_root / "src" / "world" / "entities"
    characters.mkdir(parents=True, exist_ok=True)
    entities.mkdir(parents=True, exist_ok=True)
    hero = characters / "hero.md"
    hero.write_text(
        """+++
id = "hero"
name = "沈烛"
role = "主角"
summary = "旧动机：只想远离归墟。"
+++

# 沈烛

旧动机：只想远离归墟。
""",
        encoding="utf-8",
    )
    (entities / "birth_city.md").write_text(
        """+++
id = "birth_city"
name = "幽都转轮府"
type = "地点"
summary = "沈烛的出身地点。"
+++

# 幽都转轮府
""",
        encoding="utf-8",
    )
    (entities / "echo_ability.md").write_text(
        """+++
id = "echo_ability"
name = "折界回响"
type = "能力"
summary = "沈烛在回响中逐渐掌握的感知能力。"
+++

# 折界回响
""",
        encoding="utf-8",
    )
    executors = build_tool_executors(tmp_path)

    read = executors["read_project_document"]({"path": "src/characters/hero.md"})
    assert read["ok"] is True
    assert read["revision"]
    assert "旧动机" in read["content"]

    mismatch = executors["edit_project_document"](
        {
            "path": "src/characters/hero.md",
            "edits": [
                {
                    "old_text": 'role: "主角"',
                    "new_text": 'role = "核心主角"',
                }
            ],
        }
    )
    assert mismatch["error"] == "old_text_not_found"
    assert mismatch["details"]["field_path"] == "$.edits[0].old_text"
    assert mismatch["details"]["suggested_old_text"] == 'role = "主角"'
    assert mismatch["details"]["retry_revision"] == read["revision"]

    edit_args = {
        "path": "src/characters/hero.md",
        "edits": [
            {
                "old_text": "旧动机：只想远离归墟。",
                "new_text": "新动机：查清幽都转轮府与回响异动的关联。",
                "replace_all": True,
            }
        ],
    }
    preview = executors["edit_project_document"](edit_args)
    assert preview["ok"] is True
    assert preview["applied"] is False
    assert preview["preview_token"]
    assert preview["mutation_summary"]["execution_status"] == "proposed"
    assert preview["mutation_summary"]["items"][0]["before"]["value"] is not None
    assert "+新动机：查清幽都转轮府与回响异动的关联。" in preview["diff"]
    assert "旧动机：只想远离归墟。" in hero.read_text(encoding="utf-8")

    applied = executors["edit_project_document"](
        {"preview_token": preview["preview_token"], "confirm": True}
    )
    assert applied["ok"] is True
    assert applied["applied"] is True
    assert applied["mutation_summary"]["execution_status"] == "committed"
    assert applied["mutation_summary"]["source_revision"].startswith("sha256:")
    assert applied["mutation_summary"]["result_revision"].startswith("sha256:")
    assert applied["undo_preview_token"]
    assert "新动机：查清幽都转轮府与回响异动的关联。" in hero.read_text(
        encoding="utf-8"
    )
    reused = executors["edit_project_document"](
        {"preview_token": preview["preview_token"], "confirm": True}
    )
    assert reused["error"] == "document_preview_invalid"

    undone = executors["edit_project_document"](
        {"action": "undo", "preview_token": applied["undo_preview_token"]}
    )
    assert undone["ok"] is True
    assert undone["applied"] is True
    assert undone["mutation_summary"]["operation"] == "document.change_undo"
    assert "旧动机：只想远离归墟。" in hero.read_text(encoding="utf-8")

    stale_preview = executors["edit_project_document"](
        {
            "path": "src/characters/hero.md",
            "edits": [
                {
                    "old_text": 'role = "主角"',
                    "new_text": 'role = "核心主角"',
                }
            ],
        }
    )
    hero.write_text(hero.read_text(encoding="utf-8") + "\n外部变更。\n", encoding="utf-8")
    stale = executors["edit_project_document"](
        {"preview_token": stale_preview["preview_token"], "confirm": True}
    )
    assert stale["error"] == "document_revision_conflict"
    assert 'role = "主角"' in hero.read_text(encoding="utf-8")

    retried = executors["edit_project_document"](
        {"action": "retry", "preview_token": stale_preview["preview_token"]}
    )
    assert retried["ok"] is True
    assert retried["applied"] is False
    assert retried["preview_token"] != stale_preview["preview_token"]
    assert retried["retried_from"] == stale_preview["preview_token"]
    rejected = executors["edit_project_document"](
        {"action": "reject", "preview_token": retried["preview_token"]}
    )
    assert rejected["status"] == "rejected"
    rejected_apply = executors["edit_project_document"](
        {"action": "apply", "preview_token": retried["preview_token"]}
    )
    assert rejected_apply["error"] == "document_preview_invalid"

    quote_document = novel_root / "src" / "world" / "quote_rules.md"
    quote_document.write_text(
        '守门人说：“门后的名字不能写错。”\n下一条规则保持不变。\n',
        encoding="utf-8",
    )
    normalized_preview = executors["edit_project_document"](
        {
            "path": "src/world/quote_rules.md",
            "edits": [
                {
                    "old_text": '守门人说：  "门后的名字不能写错。"',
                    "new_text": "守门人要求逐字核对门后的名字。",
                }
            ],
        }
    )
    assert normalized_preview["ok"] is True
    assert normalized_preview["edits"][0]["mode"] == "normalized_text"
    assert normalized_preview["edits"][0]["automatic"] is True
    assert "+守门人要求逐字核对门后的名字。" in normalized_preview["diff"]

    ambiguous_quotes = novel_root / "src" / "world" / "ambiguous_quotes.md"
    ambiguous_quotes.write_text(
        '“这句话足够长且出现两次。”\n“这句话足够长且出现两次。”\n',
        encoding="utf-8",
    )
    ambiguous_normalized = executors["edit_project_document"](
        {
            "path": "src/world/ambiguous_quotes.md",
            "edits": [
                {
                    "old_text": '"这句话足够长且出现两次。"',
                    "new_text": "不应自动写入",
                }
            ],
        }
    )
    assert ambiguous_normalized["error"] == "ambiguous_old_text"
    assert ambiguous_normalized["details"]["normalized_occurrences"] == 2
    assert "不应自动写入" not in ambiguous_quotes.read_text(encoding="utf-8")

    range_document = novel_root / "src" / "world" / "range_rules.md"
    range_document.write_text(
        "# 范围规则\n\n"
        "【范围起点】锚点后的旧内容。\n"
        "这是无需复制的长篇中间内容。\n"
        "【范围终点】旧内容到此结束。\n\n"
        "## 保留章节\n不得被范围替换。\n",
        encoding="utf-8",
    )
    range_preview = executors["edit_project_document"](
        {
            "path": "src/world/range_rules.md",
            "edits": [
                {
                    "start_text": "【范围起点】",
                    "end_text": "【范围终点】旧内容到此结束。",
                    "new_text": "【新范围】\n只写替换后的完整内容。",
                }
            ],
        }
    )
    assert range_preview["ok"] is True
    assert range_preview["edits"][0]["mode"] == "range"
    assert range_preview["edits"][0]["automatic"] is False
    assert "无需复制的长篇中间内容" in range_document.read_text(encoding="utf-8")
    range_applied = executors["edit_project_document"](
        {"preview_token": range_preview["preview_token"], "confirm": True}
    )
    assert range_applied["applied"] is True
    range_content = range_document.read_text(encoding="utf-8")
    assert "【新范围】" in range_content
    assert "不得被范围替换" in range_content

    automatic_document = novel_root / "src" / "world" / "automatic_range.md"
    start_anchor = "START-UNIQUE"
    end_anchor = "END-UNIQUE12"
    start_line = start_anchor + "真" * 110
    end_line = "实" * 110 + end_anchor
    automatic_document.write_text(
        f"{start_line}\n文件中的真实中间内容。\n{end_line}\n",
        encoding="utf-8",
    )
    inaccurate_long_text = (
        f"{start_anchor}{'错' * 110}\n"
        f"模型记错的中间内容，并且这一段足够长。{'错' * 80}\n"
        f"{'误' * 110}{end_anchor}"
    )
    automatic_preview = executors["edit_project_document"](
        {
            "path": "src/world/automatic_range.md",
            "edits": [
                {
                    "old_text": inaccurate_long_text,
                    "new_text": "自动首尾锚点替换成功。",
                }
            ],
        }
    )
    assert automatic_preview["ok"] is True
    assert automatic_preview["edits"][0]["mode"] == "range"
    assert automatic_preview["edits"][0]["automatic"] is True
    assert automatic_preview["edits"][0]["anchor_chars"] == 12

    folded_ambiguous_document = (
        novel_root / "src" / "world" / "folded_ambiguous_range.md"
    )
    repeated_start = "S" * 48
    unique_end = "E" * 48
    folded_ambiguous_document.write_text(
        f"{repeated_start}{'甲' * 60}\n"
        f"{repeated_start}{'乙' * 60}\n"
        f"{'丙' * 60}{unique_end}\n",
        encoding="utf-8",
    )
    folded_ambiguous = executors["edit_project_document"](
        {
            "path": "src/world/folded_ambiguous_range.md",
            "edits": [
                {
                    "old_text": (
                        f"{repeated_start}{'错' * 60}\n"
                        f"{'模型错误内容' * 20}\n"
                        f"{'丙' * 60}{unique_end}"
                    ),
                    "new_text": "不应自动写入",
                }
            ],
        }
    )
    assert folded_ambiguous["error"] == "ambiguous_text_range"
    assert folded_ambiguous["details"]["anchor_chars"] == 48
    assert "不应自动写入" not in folded_ambiguous_document.read_text(encoding="utf-8")

    ambiguous_document = novel_root / "src" / "world" / "ambiguous_range.md"
    ambiguous_document.write_text(
        "共同起点\n第一段\n共同终点\n共同起点\n第二段\n共同终点\n",
        encoding="utf-8",
    )
    ambiguous = executors["edit_project_document"](
        {
            "path": "src/world/ambiguous_range.md",
            "edits": [
                {
                    "start_text": "共同起点",
                    "end_text": "共同终点",
                    "new_text": "不应写入",
                }
            ],
        }
    )
    assert ambiguous["error"] == "ambiguous_text_range"
    assert "不应写入" not in ambiguous_document.read_text(encoding="utf-8")

    candidates = executors["search_relation_targets"](
        {"query": "沈烛 出身 能力", "limit": 10}
    )
    candidate_ids = {candidate["id"] for candidate in candidates["candidates"]}
    assert {"hero", "birth_city", "echo_ability"}.issubset(candidate_ids)

    relations = [
        {
            "source_id": "hero",
            "target_id": "birth_city",
            "description": "出身地点",
        },
        {
            "source_id": "hero",
            "target_id": "echo_ability",
            "description": "能力设定",
        },
    ]
    relation_preview = executors["edit_world_relations"]({"relations": relations})
    assert relation_preview["ok"] is True
    assert relation_preview["applied"] is False
    assert 'target = "birth_city"' in relation_preview["diff"]
    assert 'target = "echo_ability"' in relation_preview["diff"]

    relation_applied = executors["edit_world_relations"](
        {
            "preview_token": relation_preview["preview_token"],
            "confirm": True,
        }
    )
    assert relation_applied["ok"] is True
    assert relation_applied["applied"] is True
    updated = hero.read_text(encoding="utf-8")
    assert 'target = "birth_city"' in updated
    assert 'target = "echo_ability"' in updated


def test_list_chapters_returns_canonical_path_for_document_reads(tmp_path: Path):
    from tools.init_project import init_project

    init_project(tmp_path, "demo")
    chapter = (
        tmp_path
        / "data"
        / "novels"
        / "demo"
        / "data"
        / "manuscript"
        / "arc_001"
        / "ch_007.md"
    )
    chapter.parent.mkdir(parents=True, exist_ok=True)
    chapter.write_text("# 第七章：回声归来\n\n钟声越过空城。\n", encoding="utf-8")

    executors = build_tool_executors(tmp_path)
    listed = executors["list_chapters"]({})

    assert listed == {
        "chapters": [
            {
                "number": 7,
                "chapter_id": "ch_007",
                "title": "第七章：回声归来",
                "path": "data/manuscript/arc_001/ch_007.md",
            }
        ]
    }
    read = executors["read_project_document"](
        {"path": listed["chapters"][0]["path"]}
    )
    assert read["ok"] is True
    assert read["path"] == "data/manuscript/arc_001/ch_007.md"
    assert "钟声越过空城" in read["content"]


def test_agent_runtime_workflow_and_arc_compression_tools_use_current_apis(
    tmp_path: Path,
):
    from tools.init_project import init_project

    init_project(tmp_path, "demo")
    executors = build_tool_executors(tmp_path)

    compressed = executors["compress_section"]({"arc_id": "arc_001"})
    assert compressed["arc_id"] == "arc_001"
    assert "compressed" in compressed
    assert "compression_ratio" in compressed

    started = executors["start_workflow"]({"chapter_id": "ch_099"})
    assert started["chapter_id"] == "ch_099"
    assert started["current_stage"] == "context_assembly"

    advanced = executors["advance_workflow"]({"chapter_id": "ch_099"})
    assert advanced["chapter_id"] == "ch_099"
    assert advanced["current_stage"] == "writing"

    status = executors["get_workflow_status"]({"chapter_id": "ch_099"})
    assert status["stages"]["context_assembly"]["status"] == "completed"
    assert status["is_complete"] is False

    listed = executors["get_workflow_status"]({})
    assert "ch_099" in listed["active"]


def test_dante_action_toolkit_exposes_high_level_actions():
    assert DANTE_ACTION_TOOLKIT == {
        "summarize_ideation",
        "confirm_ideation_summary",
        "generate_outline_draft",
        "confirm_outline_scope",
        "run_chapter_preflight",
        "delegate_chapter_write",
        "delegate_chapter_review",
    }
    assert "get_status" not in DANTE_ACTION_TOOLKIT
    assert "write_chapter" not in DANTE_ACTION_TOOLKIT


def test_build_dante_tool_layers_exposes_callable_action_executors(
    monkeypatch, tmp_path: Path
):
    executors = {
        "get_status": lambda a: {"ok": True},
        "get_context": lambda a: {"ok": True},
        "query_world": lambda a: {"ok": True},
        "write_chapter": lambda a: {"ok": True},
    }

    def fake_factory(project_root: Path):
        assert project_root == tmp_path
        return executors

    monkeypatch.setattr(tool_layers_module, "build_tool_executors", fake_factory)

    layers = cli_module.build_dante_tool_layers(tmp_path)

    assert layers["direct_toolkit"] == DANTE_DIRECT_TOOLKIT
    assert layers["action_toolkit"] == DANTE_ACTION_TOOLKIT
    assert layers["direct_tool_executors"] == {
        name: executors[name] for name in DANTE_DIRECT_TOOLKIT if name in executors
    }
    assert "write_chapter" not in layers["direct_tool_executors"]
    assert layers["tool_executors"] is executors
    assert layers["action_tool_executors"]
    assert set(layers["action_tool_executors"].keys()) == DANTE_ACTION_TOOLKIT
    assert all(callable(fn) for fn in layers["action_tool_executors"].values())
    actions = layers["action_tool_executors"]
    assert actions["summarize_ideation"]({})["action"] == "summarize_ideation"
    assert (
        actions["confirm_ideation_summary"]({})["action"]
        == "confirm_ideation_summary"
    )
    assert actions["generate_outline_draft"]({})["action"] == "generate_outline_draft"
    assert (
        actions["run_chapter_preflight"]({"chapter_id": "ch_001"})["action"]
        == "run_chapter_preflight"
    )


def test_dante_write_action_preserves_generation_parameters(monkeypatch, tmp_path: Path):
    from tools.agent.orchestrator import OpenWriteOrchestrator
    from tools.init_project import init_project

    init_project(tmp_path, "demo")
    captured: dict[str, object] = {}

    def fake_delegate(
        self,
        chapter_id: str,
        preflight_result=None,
        guidance: str = "",
        target_words: int = 0,
        temperature: float = 0.7,
    ):
        captured.update(
            chapter_id=chapter_id,
            guidance=guidance,
            target_words=target_words,
            temperature=temperature,
        )
        return {"ok": True, "chapter_id": chapter_id}

    monkeypatch.setattr(OpenWriteOrchestrator, "delegate_writing", fake_delegate)
    layers = tool_layers_module.build_dante_tool_layers(tmp_path)

    result = layers["action_tool_executors"]["delegate_chapter_write"](
        {
            "chapter_id": "ch_008",
            "guidance": "保持克制",
            "target_words": 3200,
            "temperature": 0.15,
        }
    )

    assert result["ok"] is True
    assert captured == {
        "chapter_id": "ch_008",
        "guidance": "保持克制",
        "target_words": 3200,
        "temperature": 0.15,
    }


def test_dante_preflight_action_requires_explicit_chapter_id(
    monkeypatch, tmp_path: Path
):
    def fake_factory(project_root: Path):
        assert project_root == tmp_path
        return {
            "get_status": lambda a: {"ok": True},
        }

    monkeypatch.setattr(tool_layers_module, "build_tool_executors", fake_factory)

    layers = cli_module.build_dante_tool_layers(tmp_path)
    result = layers["action_tool_executors"]["run_chapter_preflight"]({})

    assert result["action"] == "run_chapter_preflight"
    assert result["ok"] is False
    assert result["blocked"] is True
    assert result["error"] == "missing_chapter_id"
    assert result["chapter_id"] == ""
