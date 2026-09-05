from pathlib import Path

import yaml

from models.character import CharacterProfile
from models.context_package import GenerationContext
from tools.agent.tool_runtime import build_tool_executors
from tools.character_state_index import (
    CharacterStateIndex,
    parse_character_state_annotations,
    parse_relation_annotations,
    strip_character_state_annotations,
)
from tools.manuscript_acceptance import ManuscriptAcceptanceService


def _project(tmp_path: Path) -> tuple[Path, Path]:
    novel_root = tmp_path / "data" / "novels" / "demo"
    (novel_root / "src").mkdir(parents=True)
    (novel_root / "data" / "manuscript" / "arc_001").mkdir(parents=True)
    (tmp_path / "novel_config.yaml").write_text(
        "novel_id: demo\ncurrent_chapter: ch_070\n", encoding="utf-8"
    )
    return tmp_path, novel_root


def _accept_manuscript(root: Path) -> None:
    service = ManuscriptAcceptanceService(root, "demo")
    operation = service.establish_baseline(confirm=True)
    service.resume(
        operation["operation_id"],
        analyzer=lambda chapter_id, title, content, prior: {
            "chapter_summary": "",
            "observations": "",
            "legacy_updates": {},
            "state_delta": {},
        },
    )


def test_parser_infers_chapters_and_ignores_fenced_examples():
    text = """# 第一卷

#### 第六十三章：回港

//**沈烬[位置]：贫民区工坊 -> 归墟港**
//**沈烬：仍在试探 -> 确认白续是敌人**

```text
//**示例人物[位置]：甲地 -> 乙地**
```

//**沈烬[伤势]@ch_018：左臂轻伤 -> 已恢复**
"""

    records, diagnostics = parse_character_state_annotations(
        text,
        source_path="src/outline.md",
        source_kind="planned",
    )

    assert diagnostics == []
    assert [(item.name, item.field, item.chapter_id) for item in records] == [
        ("沈烬", "位置", "ch_063"),
        ("沈烬", "综合状态", "ch_063"),
        ("沈烬", "伤势", "ch_018"),
    ]


def test_parser_reports_unscoped_and_malformed_annotations():
    records, diagnostics = parse_character_state_annotations(
        "//**沈烬[位置]：甲地 -> 乙地**\n//**缺少箭头**\n",
        source_path="src/characters/shen_jin.md",
        source_kind="reference",
    )

    assert records == []
    assert [item["code"] for item in diagnostics] == [
        "unscoped_annotation",
        "invalid_annotation",
    ]


def test_relation_annotation_parser_is_explicit_and_ignores_fenced_examples():
    text = """//**沈烬~>白续:互相试探的敌对关系**

```text
//**示例甲~>示例乙:不应注册**
```

## 关系网络
- **裴织**：普通正文不应注册
"""

    records, diagnostics = parse_relation_annotations(
        text, source_path="src/characters/shen_jin.md"
    )
    state_records, state_diagnostics = parse_character_state_annotations(
        text,
        source_path="src/characters/shen_jin.md",
        source_kind="reference",
    )

    assert diagnostics == []
    assert [(item.source, item.target, item.description) for item in records] == [
        ("沈烬", "白续", "互相试探的敌对关系")
    ]
    assert state_records == []
    assert state_diagnostics == []

    legacy, legacy_diagnostics = parse_relation_annotations(
        "//**沈烬~白续:旧项目关系**\n", source_path="src/characters/shen_jin.md"
    )
    assert [(item.source, item.target) for item in legacy] == [("沈烬", "白续")]
    assert legacy_diagnostics == []

    malformed, malformed_diagnostics = parse_relation_annotations(
        "//**沈烬~>白续**\n", source_path="src/characters/shen_jin.md"
    )
    assert malformed == []
    assert malformed_diagnostics[0]["code"] == "invalid_relation_annotation"


def test_query_returns_old_current_state_outside_recent_history(tmp_path: Path):
    root, novel_root = _project(tmp_path)
    manuscript = novel_root / "data" / "manuscript" / "arc_001"
    (manuscript / "ch_010.md").write_text(
        "# 第十章\n\n//**沈烬[伤势]：左臂轻伤 -> 已恢复**\n", encoding="utf-8"
    )
    (manuscript / "ch_063.md").write_text(
        "# 第六十三章\n\n//**沈烬[位置]：贫民区工坊 -> 归墟港**\n",
        encoding="utf-8",
    )
    (manuscript / "ch_070.md").write_text("# 第七十章\n", encoding="utf-8")
    _accept_manuscript(root)

    result = CharacterStateIndex(root, "demo").query("沈烬", lookback=50)

    assert result["target_chapter"] == "ch_070"
    assert result["target_source"] == "latest_manuscript"
    current = {item["field"]: item for item in result["current"]}
    assert current["伤势"]["state"] == "已恢复"
    assert current["伤势"]["within_lookback"] is False
    assert current["位置"]["state"] == "归墟港"
    assert [(item["field"], item["chapter_id"]) for item in result["history"]] == [
        ("位置", "ch_063")
    ]


def test_query_uses_active_book_state_when_editing_older_chapter(tmp_path: Path):
    root, novel_root = _project(tmp_path)
    manuscript = novel_root / "data" / "manuscript" / "arc_001"
    (manuscript / "ch_030.md").write_text(
        "# 第三十章\n//**沈烬[位置]：旧城 -> 北港**\n", encoding="utf-8"
    )
    (manuscript / "ch_070.md").write_text(
        "# 第七十章\n//**沈烬[位置]：北港 -> 南港**\n", encoding="utf-8"
    )
    state_path = novel_root / "data" / "workflows" / "book_state.yaml"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(
        yaml.safe_dump(
            {
                "novel_id": "demo",
                "stage": "drafting",
                "current_chapter": "ch_030",
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    _accept_manuscript(root)

    result = CharacterStateIndex(root, "demo").query("沈烬")

    assert result["target_chapter"] == "ch_030"
    assert result["target_source"] == "book_state"
    assert result["current"][0]["state"] == "北港"


def test_actual_annotation_wins_over_outline_at_same_chapter(tmp_path: Path):
    root, novel_root = _project(tmp_path)
    previous = novel_root / "data" / "manuscript" / "arc_001" / "ch_062.md"
    previous.write_text(
        "# 第六十二章\n//**沈烬[位置]：旧城 -> 工坊**\n", encoding="utf-8"
    )
    (novel_root / "src" / "outline.md").write_text(
        "#### 第六十三章\n//**沈烬[位置]：工坊 -> 计划地点**\n", encoding="utf-8"
    )
    chapter = novel_root / "data" / "manuscript" / "arc_001" / "ch_063.md"
    chapter.write_text(
        "# 第六十三章\n//**沈烬[位置]：工坊 -> 实际地点**\n", encoding="utf-8"
    )
    _accept_manuscript(root)

    result = CharacterStateIndex(root, "demo").query(
        "沈烬", target_chapter="ch_063"
    )

    assert result["current"][0]["state"] == "实际地点"
    assert result["current"][0]["source_kind"] == "actual"
    assert result["continuity_conflicts"] == []
    assert [item["source_kind"] for item in result["history"]] == [
        "actual",
        "planned",
        "actual",
    ]


def test_query_refreshes_rebuildable_index_after_external_edit(tmp_path: Path):
    root, novel_root = _project(tmp_path)
    chapter = novel_root / "data" / "manuscript" / "arc_001" / "ch_063.md"
    chapter.write_text(
        "# 第六十三章\n//**沈烬[位置]：工坊 -> 归墟港**\n", encoding="utf-8"
    )
    _accept_manuscript(root)
    index = CharacterStateIndex(root, "demo")

    first = index.query("沈烬", target_chapter="ch_063")
    chapter.write_text(
        "# 第六十三章\n//**沈烬[位置]：工坊 -> 旧剧场**\n", encoding="utf-8"
    )
    second = index.query("沈烬", target_chapter="ch_063")

    assert first["current"][0]["state"] == "归墟港"
    assert second["current"] == []
    assert ManuscriptAcceptanceService(root, "demo").inspect()["status"] == "external_change"
    assert index.index_path.is_file()


def test_strip_annotations_preserves_surrounding_prose():
    text = (
        "第一段。\n"
        "//**沈烬[位置]：工坊 -> 归墟港**\n"
        "//**沈烬~>白续:敌对关系**\n"
        "第二段。\n"
    )

    assert strip_character_state_annotations(text) == "第一段。\n第二段。\n"


def test_agent_tool_only_needs_character_name(tmp_path: Path):
    root, novel_root = _project(tmp_path)
    chapter = novel_root / "data" / "manuscript" / "arc_001" / "ch_070.md"
    chapter.write_text(
        "# 第七十章\n//**沈烬[位置]：工坊 -> 归墟港**\n", encoding="utf-8"
    )
    _accept_manuscript(root)

    result = build_tool_executors(root)["get_character_state"]({"name": "沈烬"})

    assert result["ok"] is True
    assert result["target_chapter"] == "ch_070"
    assert result["current"][0]["state"] == "归墟港"


def test_context_builder_renders_latest_state_for_active_characters(tmp_path: Path):
    from tools.context_builder import ContextBuilder

    root, novel_root = _project(tmp_path)
    chapter = novel_root / "data" / "manuscript" / "arc_001" / "ch_063.md"
    chapter.write_text(
        "# 第六十三章\n//**沈烬[位置]：工坊 -> 归墟港**\n", encoding="utf-8"
    )
    _accept_manuscript(root)
    builder = ContextBuilder(root, "demo")

    rendered = builder._get_inline_character_states(
        [CharacterProfile(name="沈烬")], "ch_070"
    )
    context = GenerationContext(character_states=rendered)

    assert "位置：归墟港" in rendered
    assert "ch_063，正文" in rendered
    assert context.to_prompt_sections()["人物当前状态（内联批注）"] == rendered


def test_writer_prompt_receives_inline_character_state_context():
    from tools.agent.writer import WriterAgent

    prompt = WriterAgent._build_creative_user_prompt(
        object(),
        {"character_states": "【沈烬】\n- 位置：归墟港（ch_063，正文）"},
        chapter_number=70,
        target_words=3000,
    )

    assert "## 人物当前状态（内联批注）" in prompt
    assert "位置：归墟港" in prompt
