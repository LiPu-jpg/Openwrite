from pathlib import Path

import pytest

from tools.outline_tree import (
    OutlineEditError,
    build_outline_structure,
    mutate_outline_structure,
)


def _write_outline(root: Path) -> None:
    outline = root / "src" / "outline.md"
    outline.parent.mkdir(parents=True)
    outline.write_text(
        """+++
id = "outline"
+++

# 第一卷：雾城

## 第一幕：来信

### 第一节：钟楼

这一节让主角发现钟楼异动。

#### 第一章：雨夜

收到一封没有寄件人的信。

#### 第二章：少掉的十三秒

调查钟楼，并留下新的时间谜团。

## 第二幕：回声

### 第二节：地下室

#### 第三章：门后

# 附录

## 人物表

### 主角
""",
        encoding="utf-8", newline="",
    )


def test_outline_tree_projects_volume_act_section_chapter_and_appendix(tmp_path: Path):
    _write_outline(tmp_path)

    result = build_outline_structure(tmp_path)

    assert result["counts"] == {
        "volume": 1,
        "act": 2,
        "section": 2,
        "chapter": 3,
        "appendix": 3,
    }
    volume = result["roots"][0]
    assert volume["kind"] == "volume"
    assert volume["children"][0]["kind"] == "act"
    assert volume["children"][0]["children"][0]["kind"] == "section"
    assert volume["children"][0]["children"][0]["children"][0]["id"] == "ch_001"
    assert result["roots"][1]["kind"] == "appendix"
    assert result["roots"][1]["children"][0]["kind"] == "appendix"
    assert result["roots"][0]["line"] == 5


def test_outline_tree_exposes_one_prose_summary_format_at_all_four_levels(tmp_path: Path):
    outline = tmp_path / "src" / "outline.md"
    outline.parent.mkdir(parents=True)
    outline.write_text(
        """+++
summary = "全书事件梗概。"
+++

# 第一卷
> 核心主题: 选择

## 第一幕

本幕事件梗概。

### 第一节

本节事件梗概。

#### 第一章
> 内容焦点: 本章事件梗概。
> 情感弧线: 平静 -> 戒备
""",
        encoding="utf-8", newline="",
    )

    volume = build_outline_structure(tmp_path)["roots"][0]
    act = volume["children"][0]
    section = act["children"][0]
    chapter = section["children"][0]

    assert volume["summary"] == "全书事件梗概。"
    assert act["summary"] == "本幕事件梗概。"
    assert section["summary"] == "本节事件梗概。"
    assert chapter["summary"] == "本章事件梗概。"


def test_outline_tree_recommends_first_planned_chapter_and_recent_word_average(tmp_path: Path):
    _write_outline(tmp_path)
    manuscript = tmp_path / "data" / "manuscript" / "arc_001"
    manuscript.mkdir(parents=True)
    (manuscript / "ch_001.md").write_text("甲" * 4200, encoding="utf-8", newline="")

    result = build_outline_structure(tmp_path)
    recommendation = result["recommendation"]

    assert recommendation["chapter_id"] == "ch_002"
    assert recommendation["breadcrumb"] == [
        "第一卷：雾城",
        "第一幕：来信",
        "第一节：钟楼",
        "第二章：少掉的十三秒",
    ]
    assert recommendation["target_words"] == 4200
    assert "调查钟楼" in recommendation["guidance"]
    assert recommendation["status"] == "planned"


def test_outline_tree_prefers_explicit_chapter_target_over_project_default(tmp_path: Path):
    outline = tmp_path / "src" / "outline.md"
    outline.parent.mkdir(parents=True)
    outline.write_text(
        "# 第一卷\n## 第一幕\n### 第一节\n"
        "#### 第一章：开门\n> 预估字数: 4200\n脚印。\n",
        encoding="utf-8", newline="",
    )

    result = build_outline_structure(
        tmp_path,
        writing_targets={
            "chapter_words": 3200,
            "outline_chapter_words": 240,
        },
    )
    chapter = result["roots"][0]["children"][0]["children"][0]["children"][0]

    assert result["recommendation"]["target_words"] == 4200
    assert result["recommendation"]["target_source"] == "outline"
    assert chapter["chapter_target_words"] == 4200
    assert chapter["detail_target_words"] == 240


def test_outline_tree_can_select_drafted_chapter_without_overwriting_it(tmp_path: Path):
    _write_outline(tmp_path)
    manuscript = tmp_path / "data" / "manuscript" / "arc_001"
    manuscript.mkdir(parents=True)
    (manuscript / "ch_001.md").write_text("已有正文", encoding="utf-8", newline="")

    selected = build_outline_structure(tmp_path, chapter_id="ch_001")["recommendation"]

    assert selected["chapter_id"] == "ch_001"
    assert selected["status"] == "drafted"
    assert selected["reason"] == "用户选择的章纲"


def test_outline_tree_understands_chinese_chapter_numbers(tmp_path: Path):
    outline = tmp_path / "src" / "outline.md"
    outline.parent.mkdir(parents=True)
    outline.write_text(
        "# 第一卷\n## 第一幕\n### 第一节\n#### 第一百零四章：终点\n",
        encoding="utf-8", newline="",
    )

    recommendation = build_outline_structure(tmp_path)["recommendation"]

    assert recommendation["chapter_id"] == "ch_104"


def test_outline_tree_exposes_safe_inline_edit_capabilities(tmp_path: Path):
    _write_outline(tmp_path)

    result = build_outline_structure(tmp_path)
    volume = result["roots"][0]
    section = volume["children"][0]["children"][0]

    assert volume["child_kind"] == "act"
    assert section["child_kind"] == "chapter"
    assert section["descendant_count"] == 2
    assert section["end_line"] > section["line"]
    assert section["editable"] is True
    assert section["can_delete"] is True
    assert result["roots"][1]["editable"] is False


def test_outline_tree_can_rename_add_and_delete_one_local_subtree(tmp_path: Path):
    _write_outline(tmp_path)
    outline_path = tmp_path / "src" / "outline.md"
    original = outline_path.read_text(encoding="utf-8")
    structure = build_outline_structure(tmp_path)

    renamed = mutate_outline_structure(
        tmp_path,
        operation="rename",
        revision=structure["revision"],
        node_id="act_001",
        title="第一幕：雨中来信",
    )
    assert "## 第一幕：雨中来信" in renamed["content"]
    assert "收到一封没有寄件人的信。" in renamed["content"]
    assert len(renamed["content"]) - len(original) == len("雨中")
    outline_path.write_text(renamed["content"], encoding="utf-8", newline="")

    structure = build_outline_structure(tmp_path)
    added = mutate_outline_structure(
        tmp_path,
        operation="add_child",
        revision=structure["revision"],
        node_id="section_001",
        kind="chapter",
        title="第四章：新的钟声",
    )
    assert "#### 第四章：新的钟声" in added["content"]
    assert added["content"].index("#### 第四章：新的钟声") < added["content"].index("## 第二幕：回声")
    outline_path.write_text(added["content"], encoding="utf-8", newline="")

    structure = build_outline_structure(tmp_path)
    deleted = mutate_outline_structure(
        tmp_path,
        operation="delete",
        revision=structure["revision"],
        node_id="ch_002",
    )
    assert "第二章：少掉的十三秒" not in deleted["content"]
    assert "调查钟楼，并留下新的时间谜团。" not in deleted["content"]
    assert "第一章：雨夜" in deleted["content"]
    assert "第三章：新的钟声" in deleted["content"]
    assert "第二章：门后" in deleted["content"]
    assert len(deleted["renumbered"]) == 2
    assert "连续重编号 2 个" in deleted["message"]


def test_outline_tree_can_update_node_content_without_touching_children(tmp_path: Path):
    _write_outline(tmp_path)
    outline_path = tmp_path / "src" / "outline.md"
    structure = build_outline_structure(tmp_path)

    edited = mutate_outline_structure(
        tmp_path,
        operation="update_summary",
        revision=structure["revision"],
        node_id="section_001",
        summary="这一节改成直接在树上维护。\n- 保留两个子章",
    )

    assert "这一节让主角发现钟楼异动。" not in edited["content"]
    assert "这一节改成直接在树上维护。" in edited["content"]
    assert "- 保留两个子章" in edited["content"]
    assert "#### 第一章：雨夜" in edited["content"]
    assert "#### 第二章：少掉的十三秒" in edited["content"]
    outline_path.write_text(edited["content"], encoding="utf-8", newline="")
    section = build_outline_structure(tmp_path)["roots"][0]["children"][0]["children"][0]
    assert section["content"] == "这一节改成直接在树上维护。\n- 保留两个子章"
    assert "保留两个子章" in section["summary"]


def test_outline_tree_updates_chapter_summary_without_removing_execution_metadata(tmp_path: Path):
    outline = tmp_path / "src" / "outline.md"
    outline.parent.mkdir(parents=True)
    outline.write_text(
        "# 第一卷\n## 第一幕\n### 第一节\n#### 第一章：开门\n"
        "> 内容焦点: 发现门外脚印\n> 情感弧线: 平静 -> 戒备\n",
        encoding="utf-8", newline="",
    )
    structure = build_outline_structure(tmp_path)

    edited = mutate_outline_structure(
        tmp_path,
        operation="update_summary",
        revision=structure["revision"],
        node_id="ch_001",
        summary="主角发现门外脚印，并决定追查来处。",
    )

    assert "#### 第一章：开门\n\n主角发现门外脚印，并决定追查来处。" in edited["content"]
    assert "> 内容焦点: 发现门外脚印" in edited["content"]
    assert "> 情感弧线: 平静 -> 戒备" in edited["content"]


def test_deleting_chapter_fourteen_continuously_renumbers_later_chapters(
    tmp_path: Path,
):
    outline = tmp_path / "src" / "outline.md"
    outline.parent.mkdir(parents=True)
    outline.write_text(
        "# 第一卷\n## 第一幕\n### 第一节\n"
        "#### 第13章：留下\n"
        "#### 第14章（拟定）：删除\n"
        "#### 第15章：追踪\n"
        "#### 第16章：抵达\n",
        encoding="utf-8", newline="",
    )
    structure = build_outline_structure(tmp_path)

    deleted = mutate_outline_structure(
        tmp_path,
        operation="delete",
        revision=structure["revision"],
        node_id="ch_014",
    )

    assert "第14章（拟定）：删除" not in deleted["content"]
    assert "#### 第14章：追踪" in deleted["content"]
    assert "#### 第15章：抵达" in deleted["content"]
    assert [(item["old_id"], item["new_id"]) for item in deleted["renumbered"]] == [
        ("ch_015", "ch_014"),
        ("ch_016", "ch_015"),
    ]


def test_deleting_structure_subtree_renumbers_volume_act_section_and_chapter(
    tmp_path: Path,
):
    outline = tmp_path / "src" / "outline.md"
    outline.parent.mkdir(parents=True)
    outline.write_text(
        "# 第一卷：开端\n## 第一幕：初见\n### 第一节：门外\n#### 第一章：开始\n"
        "# 第二卷：删除\n## 第二幕：删除\n### 第二节：删除\n#### 第二章：删除\n"
        "# 第三卷：以后\n## 第三幕：深入\n### 第三节：门内\n#### 第三章：继续\n",
        encoding="utf-8", newline="",
    )
    structure = build_outline_structure(tmp_path)
    target = structure["roots"][1]
    assert target["delete_renumber_count"] == 4
    assert target["delete_renumber_preview"][0]["new_title"] == "第二卷：以后"

    deleted = mutate_outline_structure(
        tmp_path,
        operation="delete",
        revision=structure["revision"],
        node_id=target["id"],
    )

    assert "第二卷：以后" in deleted["content"]
    assert "第二幕：深入" in deleted["content"]
    assert "第二节：门内" in deleted["content"]
    assert "第二章：继续" in deleted["content"]


def test_deleting_chinese_numbered_chapter_preserves_style_and_skips_unnumbered(
    tmp_path: Path,
):
    outline = tmp_path / "src" / "outline.md"
    outline.parent.mkdir(parents=True)
    outline.write_text(
        "# 第一卷\n## 第一幕\n### 第一节\n"
        "#### 第一百零三章：之前\n"
        "#### 第一百零四章：删除\n"
        "#### 过场：无编号\n"
        "#### 第一百零五章：之后\n",
        encoding="utf-8", newline="",
    )
    structure = build_outline_structure(tmp_path)

    deleted = mutate_outline_structure(
        tmp_path,
        operation="delete",
        revision=structure["revision"],
        node_id="ch_104",
    )

    assert "第一百零四章：之后" in deleted["content"]
    assert "过场：无编号" in deleted["content"]
    assert deleted["skipped_renumbering"][0]["title"] == "过场：无编号"


def test_deletion_is_blocked_when_renumbering_would_move_a_drafted_chapter(
    tmp_path: Path,
):
    outline = tmp_path / "src" / "outline.md"
    outline.parent.mkdir(parents=True)
    outline.write_text(
        "# 第一卷\n## 第一幕\n### 第一节\n"
        "#### 第14章：删除\n#### 第15章：已有正文\n",
        encoding="utf-8", newline="",
    )
    manuscript = tmp_path / "data" / "manuscript" / "arc_001"
    manuscript.mkdir(parents=True)
    (manuscript / "ch_015.md").write_text("正文", encoding="utf-8", newline="")
    structure = build_outline_structure(tmp_path)
    target = next(
        node
        for node in structure["roots"][0]["children"][0]["children"][0]["children"]
        if node["id"] == "ch_014"
    )

    assert target["can_delete"] is False
    assert "正文文件与章纲错位" in target["delete_blocked_reason"]
    with pytest.raises(OutlineEditError, match="正文文件与章纲错位"):
        mutate_outline_structure(
            tmp_path,
            operation="delete",
            revision=structure["revision"],
            node_id="ch_014",
        )


def test_outline_tree_rejects_stale_duplicate_and_drafted_destructive_edits(tmp_path: Path):
    _write_outline(tmp_path)
    manuscript = tmp_path / "data" / "manuscript" / "arc_001"
    manuscript.mkdir(parents=True)
    (manuscript / "ch_001.md").write_text("已有正文", encoding="utf-8", newline="")
    structure = build_outline_structure(tmp_path)

    with pytest.raises(OutlineEditError, match="变化") as stale:
        mutate_outline_structure(
            tmp_path,
            operation="rename",
            revision="old-revision",
            node_id="act_001",
            title="第一幕：旧页面",
        )
    assert stale.value.code == "conflict"

    with pytest.raises(OutlineEditError, match="不能删除"):
        mutate_outline_structure(
            tmp_path,
            operation="delete",
            revision=structure["revision"],
            node_id="section_001",
        )

    with pytest.raises(OutlineEditError, match="已存在"):
        mutate_outline_structure(
            tmp_path,
            operation="add_child",
            revision=structure["revision"],
            node_id="section_001",
            kind="chapter",
            title="第二章：重复编号",
        )

    with pytest.raises(OutlineEditError, match="不能更换章节编号"):
        mutate_outline_structure(
            tmp_path,
            operation="rename",
            revision=structure["revision"],
            node_id="ch_001",
            title="第十章：换号",
        )


def test_add_after_places_a_new_node_after_the_target_at_the_right_level(tmp_path: Path):
    """`add_after` accepts the target's own sibling level and its child level.

    A container node has no sibling of the kind a caller usually asks for, so
    rejecting everything but `target["kind"]` made the operation impossible on
    every volume, act and section: an act after a volume was refused for every
    kind. The new node lands after the target's subtree either way - as the
    target's next sibling, or as the target's last child.
    """
    root = tmp_path / "container"
    _write_outline(root)
    structure = build_outline_structure(root)

    # An act after a volume becomes the volume's last child, before the next
    # volume-level node.
    added = mutate_outline_structure(
        root,
        operation="add_after",
        revision=structure["revision"],
        node_id="volume_001",
        kind="act",
        title="第三幕：夜奔",
    )
    content = added["content"]
    assert "## 第三幕：夜奔" in content
    assert content.index("## 第三幕：夜奔") > content.index("## 第二幕：回声")
    assert content.index("## 第三幕：夜奔") < content.index("# 附录")
    assert "已在“第一卷：雾城”新增幕“第三幕：夜奔”" in added["message"]

    # The same shape one level down: a section after an act lands after the
    # act's own children, not after the act's sibling.
    root = tmp_path / "act"
    _write_outline(root)
    structure = build_outline_structure(root)
    added = mutate_outline_structure(
        root,
        operation="add_after",
        revision=structure["revision"],
        node_id="act_001",
        kind="section",
        title="第二节：钟楼",
    )
    content = added["content"]
    assert "### 第二节：钟楼" in content
    assert content.index("### 第二节：钟楼") > content.index("#### 第二章：少掉的十三秒")
    assert content.index("### 第二节：钟楼") < content.index("## 第二幕：回声")

    # And one level down again: a chapter after a section is the section's last
    # child.
    root = tmp_path / "section"
    _write_outline(root)
    structure = build_outline_structure(root)
    added = mutate_outline_structure(
        root,
        operation="add_after",
        revision=structure["revision"],
        node_id="section_001",
        kind="chapter",
        title="第五章：新的钟声",
    )
    content = added["content"]
    assert "#### 第五章：新的钟声" in content
    assert content.index("#### 第五章：新的钟声") > content.index("#### 第二章：少掉的十三秒")
    assert content.index("#### 第五章：新的钟声") < content.index("## 第二幕：回声")

    # The sibling level keeps working: a chapter after a chapter stays the
    # chapter's next sibling.
    root = tmp_path / "sibling"
    _write_outline(root)
    structure = build_outline_structure(root)
    added = mutate_outline_structure(
        root,
        operation="add_after",
        revision=structure["revision"],
        node_id="ch_001",
        kind="chapter",
        title="第五章：新的钟声",
    )
    content = added["content"]
    assert "#### 第五章：新的钟声" in content
    assert content.index("#### 第五章：新的钟声") > content.index("收到一封没有寄件人的信。")
    assert content.index("#### 第五章：新的钟声") < content.index("#### 第二章：少掉的十三秒")


def test_add_after_rejects_a_level_the_target_cannot_take(tmp_path: Path):
    _write_outline(tmp_path)
    structure = build_outline_structure(tmp_path)

    with pytest.raises(OutlineEditError) as volume:
        mutate_outline_structure(
            tmp_path,
            operation="add_after",
            revision=structure["revision"],
            node_id="volume_001",
            kind="chapter",
            title="第一章：不该出现",
        )
    # The rejection names the levels that do fit, so a caller can recover
    # without guessing.
    assert "卷" in str(volume.value)
    assert "幕" in str(volume.value)

    with pytest.raises(OutlineEditError) as section:
        mutate_outline_structure(
            tmp_path,
            operation="add_after",
            revision=structure["revision"],
            node_id="section_001",
            kind="volume",
            title="第二卷：不该出现",
        )
    assert "节" in str(section.value)
    assert "章" in str(section.value)
