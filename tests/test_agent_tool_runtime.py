import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import tools.agent.tool_layers as tool_layers_module
import tools.cli as cli_module
from tools.agent.tool_runtime import build_tool_executors
from tools.agent.toolkits import (
    DANTE_ACTION_TOOLKIT,
    DANTE_DIRECT_TOOLKIT,
    ORCHESTRATOR_TOOLKIT,
    WRITING_TOOLKIT,
)


def test_build_tool_executors_contains_existing_openwrite_tools(tmp_path: Path):
    executors = build_tool_executors(project_root=tmp_path)
    assert ORCHESTRATOR_TOOLKIT.issubset(executors.keys())
    assert WRITING_TOOLKIT.issubset(executors.keys())


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
    assert executors["get_context"]({"chapter_id": "ch_001"})["chapter_id"] == "ch_001"
    assert executors["list_chapters"]({}) == {"chapters": []}
    assert "current_state" in executors["get_truth_files"]({})
    assert executors["query_world"]({})["count"] >= 0
    assert "relations" in executors["get_world_relations"]({})


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
    }


def test_dante_direct_toolkit_exposes_only_light_tools():
    assert DANTE_DIRECT_TOOLKIT == {
        "get_status",
        "get_context",
        "list_chapters",
        "get_truth_files",
        "query_world",
        "get_world_relations",
    }
    assert "write_chapter" not in DANTE_DIRECT_TOOLKIT
    assert "review_chapter" not in DANTE_DIRECT_TOOLKIT


def test_dante_action_toolkit_exposes_high_level_actions():
    assert DANTE_ACTION_TOOLKIT == {
        "summarize_ideation",
        "confirm_ideation_summary",
        "generate_outline_draft",
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
