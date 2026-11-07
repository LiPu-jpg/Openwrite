"""ReAct tool schema contract tests."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.agent.dante import _build_dante_tool_definitions
from tools.agent.react import OPENWRITE_SYSTEM_PROMPT, OPENWRITE_TOOLS
from tools.goethe import DEFAULT_GOETHE_SYSTEM_PROMPT, _build_goethe_tool_definitions


def test_react_never_exposes_model_credentials_as_tools():
    names = {tool.name for tool in OPENWRITE_TOOLS}

    assert "configure_model" not in names
    assert "API Key" in OPENWRITE_SYSTEM_PROMPT
    assert "不得索取" in OPENWRITE_SYSTEM_PROMPT
    assert "接口格式" in OPENWRITE_SYSTEM_PROMPT
    assert "Base URL 与模型名由用户填写" in OPENWRITE_SYSTEM_PROMPT
    assert "CommonMark" in OPENWRITE_SYSTEM_PROMPT
    assert "Studio 会安全渲染" in OPENWRITE_SYSTEM_PROMPT


def test_writing_tool_schemas_expose_all_supported_generation_parameters():
    write_tool = next(tool for tool in OPENWRITE_TOOLS if tool.name == "write_chapter")
    delegate_tool = next(
        tool
        for tool in _build_dante_tool_definitions()
        if tool.name == "delegate_chapter_write"
    )

    assert {"target_words", "temperature"} <= set(write_tool.parameters["properties"])
    assert {"target_words", "temperature"} <= set(delegate_tool.parameters["properties"])
    assert write_tool.parameters["properties"]["temperature"]["default"] == 0.7
    assert delegate_tool.parameters["properties"]["temperature"]["default"] == 0.7


def test_update_truth_file_tool_schema_uses_canonical_names():
    tool = next(t for t in OPENWRITE_TOOLS if t.name == "update_truth_file")
    desc = tool.parameters["properties"]["file_name"]["description"]

    assert "current_state/ledger/relationships" in desc
    assert "particle_ledger" not in desc
    assert "character_matrix" not in desc
    assert tool.required == ["file_name", "content", "source_revision"]
    assert "source_revision" in tool.parameters["properties"]
    assert "confirm" in tool.parameters["properties"]
    assert "默认 false" in tool.parameters["properties"]["confirm"]["description"]
    assert "不覆盖整份文件" in tool.description
    assert "完整投影和 revision" in OPENWRITE_SYSTEM_PROMPT
    assert "禁止整份覆盖" in OPENWRITE_SYSTEM_PROMPT


def test_character_state_tool_infers_chapter_and_only_requires_name():
    tool = next(t for t in OPENWRITE_TOOLS if t.name == "get_character_state")

    assert tool.required == ["name"]
    assert tool.parameters["required"] == ["name"]
    assert "chapter" not in tool.parameters["properties"]
    assert tool.parameters["properties"]["lookback"]["default"] == 50
    assert "当前写作章节由系统自动推断" in tool.description


def test_relation_edit_tool_requires_preview_confirmation_contract():
    tool = next(t for t in OPENWRITE_TOOLS if t.name == "edit_world_relation")
    properties = tool.parameters["properties"]

    assert tool.required == ["source_id", "target_id"]
    assert "base_revision" in properties
    assert "confirm" in properties
    assert "默认 false" in properties["confirm"]["description"]
    assert properties["action"]["enum"] == ["upsert", "remove"]


def test_project_document_tools_require_revisioned_preview_contract():
    read_tool = next(t for t in OPENWRITE_TOOLS if t.name == "read_project_document")
    edit_tool = next(t for t in OPENWRITE_TOOLS if t.name == "edit_project_document")
    properties = edit_tool.parameters["properties"]

    assert read_tool.required == ["path"]
    assert "src、data/manuscript、data/foreshadowing" in read_tool.description
    assert edit_tool.required == []
    assert "old_text/new_text" in edit_tool.description
    assert "默认只预览 diff" in edit_tool.description
    assert "revision" in properties
    assert "preview_token" in properties
    assert "不可变" in edit_tool.description
    edit_properties = properties["edits"]["items"]["properties"]
    assert {"start_text", "end_text"}.issubset(edit_properties)
    assert properties["edits"]["items"]["required"] == ["new_text"]
    assert "confirm" in properties
    assert "默认 false" in properties["confirm"]["description"]


def test_library_and_search_tools_use_creator_facing_scopes():
    catalog = next(t for t in OPENWRITE_TOOLS if t.name == "query_library")
    search = next(t for t in OPENWRITE_TOOLS if t.name == "search_project")

    assert catalog.parameters["properties"]["scope"]["enum"] == [
        "all",
        "core",
        "characters",
        "settings",
    ]
    assert search.parameters["properties"]["scope"]["enum"] == [
        "all",
        "outline",
        "core",
        "characters",
        "settings",
        "continuity",
        "chapters",
        "sources",
    ]
    assert "story/world/assets" in search.parameters["properties"]["scope"]["description"]
    assert "管理作品核心、角色、设定与连续性资料" in OPENWRITE_SYSTEM_PROMPT


def test_batch_relation_tools_support_search_and_confirmed_writes():
    search_tool = next(t for t in OPENWRITE_TOOLS if t.name == "search_relation_targets")
    batch_tool = next(t for t in OPENWRITE_TOOLS if t.name == "edit_world_relations")
    properties = batch_tool.parameters["properties"]

    assert search_tool.required == ["query"]
    assert "出身地点" in search_tool.description
    assert "能力体系" in search_tool.description
    assert batch_tool.required == []
    assert "批量新增、更新或删除" in batch_tool.description
    assert "默认只预览所有源文件 diff" in batch_tool.description
    assert "base_revisions" in properties
    assert "preview_token" in properties
    assert "preview_tokens" in properties
    assert "不可变" in properties["preview_token"]["description"]
    assert properties["relations"]["items"]["required"] == ["source_id", "target_id"]
    assert (
        properties["relations"]["items"]["properties"]["action"]["enum"]
        == ["upsert", "remove"]
    )


def test_outline_structure_tool_is_read_only_and_supports_chapter_selection():
    tool = next(t for t in OPENWRITE_TOOLS if t.name == "get_outline_structure")

    assert tool.required == []
    assert "chapter_id" in tool.parameters["properties"]
    assert "只读" in tool.description


def test_world_relations_tool_contract_mentions_shared_search_surface():
    tool = next(t for t in OPENWRITE_TOOLS if t.name == "get_world_relations")

    assert "Studio 同源" in tool.description
    assert "名称、ID 或关系文字" in tool.description


def test_outline_edit_tool_requires_revision_and_bounded_operations():
    tool = next(t for t in OPENWRITE_TOOLS if t.name == "edit_outline_structure")

    assert tool.required == ["operation", "revision"]
    assert tool.parameters["properties"]["operation"]["enum"] == [
        "rename",
        "update_summary",
        "add_child",
        "add_after",
        "delete",
    ]
    assert "增量" in tool.description
    assert "修改节点内容" in tool.description
    assert "已有正文" in tool.description
    assert "连续补位" in tool.description
    assert "summary" in tool.parameters["properties"]
    assert "连续重编号" in tool.parameters["properties"]["operation"]["description"]
    # add_after takes either the reference node's own level or the level its
    # container accepts; the schema has to say which, or a caller cannot tell
    # why "新增层级与当前节点不匹配" came back.
    assert "卷→幕" in tool.parameters["properties"]["kind"]["description"]
    assert "同级兄弟" in tool.parameters["properties"]["kind"]["description"]
    assert "confirm" in tool.parameters["properties"]
    assert "默认 false" in tool.parameters["properties"]["confirm"]["description"]


def test_reference_adoption_tools_belong_to_goethe_not_dante():
    goethe_tools = {tool.name for tool in _build_goethe_tool_definitions()}
    dante_tools = {tool.name for tool in _build_dante_tool_definitions()}
    reference_tools = {
        "list_reference_library",
        "review_reference_source",
        "review_reference_profile",
        "preview_reference_adoption",
        "apply_reference_adoption",
    }

    assert reference_tools <= goethe_tools
    assert reference_tools.isdisjoint(dante_tools)
    assert "不读取或复述整本参考原文" in DEFAULT_GOETHE_SYSTEM_PROMPT
    assert "Dante 只消费确认后生成的 composed.md" in DEFAULT_GOETHE_SYSTEM_PROMPT
