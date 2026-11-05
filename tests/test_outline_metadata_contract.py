"""The chapter metadata contract: labels, structured writes, and the round trip.

A compliant outline must survive a structured write that changes nothing.
Two defects made that impossible and both corrupted a project in silence: a
write that appended a second line for a field the file already carried, and a
write that could not express the fields the outline contract requires.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tools.init_project import init_project
from tools.outline_fields import CHAPTER_FIELD_LABELS
from tools.outline_parser import OutlineMdParser
from tools.outline_tree import build_outline_structure, mutate_outline_structure

SAMPLE_OUTLINE = Path(
    os.environ.get(
        "OPENWRITE_SAMPLE_OUTLINE",
        "/Users/jiaoziang/nv/data/novels/blood/src/outline.md",
    )
)


def _compliant_outline(chapters: int = 24) -> str:
    """A four-level outline that carries every contract field."""
    parts = [
        "# 作品\n\n全书梗概。\n\n"
        "## 第1篇：篇\n\n本篇梗概。\n\n"
        "### 第1节：节\n\n本节梗概。\n\n"
    ]
    for number in range(1, chapters + 1):
        parts.append(
            f"#### 第{number}章：标题{number}\n\n"
            f"{1870 + number} 年取得医学博士学位的约翰·华生随军赴印。\n\n"
            "> 戏剧位置: 起\n"
            "> 内容焦点: 华生的来处与困境。\n"
            "> 本章目标: 建立叙述者困境\n"
            "> 预估字数: 2500\n"
            "> 字数预算: 2500\n"
            "> 章节承诺: 独自困在旅馆 -> 决定去见一个陌生人\n"
            "> 回收伏笔: hook_001\n"
            "> 章节功能: 推进, 关系\n"
            "> 出场角色: 约翰·H·华生, 斯坦福\n"
            "> 涉及设定: 世界底层规则\n"
            "> 情感弧线: 消沉 -> 好奇\n"
            "> 节拍: 医院走廊重逢, 决定去看房\n"
            "> 悬念: 化验室里的人究竟是谁\n\n"
        )
    return "".join(parts)


def _project(tmp_path: Path, chapters: int = 24) -> Path:
    init_project(tmp_path, "demo")
    root = tmp_path / "data" / "novels" / "demo"
    (root / "src" / "outline.md").write_text(_compliant_outline(chapters), encoding="utf-8")
    return root


def test_writing_the_same_metadata_leaves_a_compliant_outline_byte_identical(tmp_path: Path):
    root = _project(tmp_path)
    outline = root / "src" / "outline.md"
    before = outline.read_bytes()

    revision = build_outline_structure(root)["revision"]
    read = mutate_outline_structure(root, operation="get_meta", node_id="ch_001", revision=revision)
    metadata = read["metadata"]

    assert set(metadata) == set(CHAPTER_FIELD_LABELS), sorted(metadata)

    result = mutate_outline_structure(
        root, operation="set_meta", node_id="ch_001", revision=revision, metadata=metadata
    )

    assert result["content"].encode("utf-8") == before


def test_every_contract_field_is_writable(tmp_path: Path):
    root = _project(tmp_path, chapters=1)
    revision = build_outline_structure(root)["revision"]

    result = mutate_outline_structure(
        root,
        operation="set_meta",
        node_id="ch_001",
        revision=revision,
        metadata={
            "dramatic_position": "转",
            "content_focus": "新的焦点。",
            "goals": ["目标一", "目标二"],
            "target_words": 3000,
            "characters": ["甲", "乙"],
            "settings": ["设定一"],
            "emotional_arc": "平静 -> 紧张",
            "beats": ["节拍一", "节拍二"],
            "hooks": ["悬念一"],
            "promise": "A -> B",
            "payoff_of": ["hook_002"],
            "function": ["推进"],
        },
    )

    body = result["content"].split("#### 第1章", 1)[1]
    for label in (
        "> 戏剧位置: 转",
        "> 内容焦点: 新的焦点。",
        "> 本章目标: 目标一, 目标二",
        "> 预估字数: 3000",
        "> 出场角色: 甲, 乙",
        "> 涉及设定: 设定一",
        "> 情感弧线: 平静 -> 紧张",
        "> 节拍: 节拍一, 节拍二",
        "> 悬念: 悬念一",
        "> 章节承诺: A -> B",
        "> 回收伏笔: hook_002",
        "> 章节功能: 推进",
    ):
        assert label in body, label


def test_a_legacy_label_is_replaced_instead_of_duplicated(tmp_path: Path):
    root = _project(tmp_path, chapters=1)
    outline = root / "src" / "outline.md"
    outline.write_text(
        outline.read_text(encoding="utf-8").replace(
            "> 出场角色: 约翰·H·华生, 斯坦福",
            "> 出场角色: 约翰·H·华生, 斯坦福, 雷斯垂德\n> 涉及人物: 约翰·H·华生",
        ),
        encoding="utf-8",
    )
    revision = build_outline_structure(root)["revision"]

    result = mutate_outline_structure(
        root,
        operation="set_meta",
        node_id="ch_001",
        revision=revision,
        metadata={"characters": "夏洛克·福尔摩斯, 约翰·H·华生"},
    )

    body = result["content"].split("#### 第1章", 1)[1]
    assert body.count("> 出场角色:") == 1
    assert "> 涉及人物:" not in body
    assert "> 出场角色: 夏洛克·福尔摩斯, 约翰·H·华生" in body

    # mutate_outline_structure returns the new body; the caller writes it.
    outline.write_text(result["content"], encoding="utf-8")
    read = mutate_outline_structure(
        root,
        operation="get_meta",
        node_id="ch_001",
        revision=build_outline_structure(root)["revision"],
    )
    assert read["metadata"]["characters"] == "夏洛克·福尔摩斯, 约翰·H·华生"


def test_reading_merges_the_contract_label_with_a_legacy_one(tmp_path: Path):
    root = _project(tmp_path, chapters=1)
    outline = root / "src" / "outline.md"
    outline.write_text(
        outline.read_text(encoding="utf-8").replace(
            "> 出场角色: 约翰·H·华生, 斯坦福",
            "> 出场角色: 约翰·H·华生, 斯坦福\n> 涉及人物: 雷斯垂德",
        ),
        encoding="utf-8",
    )
    revision = build_outline_structure(root)["revision"]

    read = mutate_outline_structure(root, operation="get_meta", node_id="ch_001", revision=revision)

    assert read["metadata"]["characters"] == "约翰·H·华生, 斯坦福, 雷斯垂德"


def test_the_parser_merges_two_lines_of_the_same_field_without_repeating_a_name(tmp_path: Path):
    root = _project(tmp_path, chapters=1)
    outline = root / "src" / "outline.md"
    text = outline.read_text(encoding="utf-8").replace(
        "> 出场角色: 约翰·H·华生, 斯坦福",
        "> 出场角色: 约翰·H·华生, 斯坦福\n> 涉及人物: 约翰·H·华生, 雷斯垂德",
    )

    chapter = OutlineMdParser().parse(text, "demo").chapters[0]

    assert chapter.involved_characters == ["约翰·H·华生", "斯坦福", "雷斯垂德"]


def test_the_tree_keeps_the_leading_year_of_a_summary(tmp_path: Path):
    root = _project(tmp_path, chapters=1)

    structure = build_outline_structure(root)

    chapter = structure["roots"][0]["children"][0]["children"][0]["children"][0]
    assert chapter["summary"].startswith("1871 年取得医学博士学位"), chapter["summary"][:40]


def test_a_string_field_with_a_comma_is_not_split_and_rejoined(tmp_path: Path):
    # `promise` is a plain string in the model (models/outline.py). Reading it
    # through the list path split it on the comma and rejoined it with ", ",
    # which rewrote the file's bytes and lost the author's punctuation.
    root = _project(tmp_path, chapters=1)
    outline = root / "src" / "outline.md"
    outline.write_text(
        outline.read_text(encoding="utf-8").replace(
            "> 章节承诺: 独自困在旅馆 -> 决定去见一个陌生人",
            "> 章节承诺: 独自困在旅馆 -> 决定去见一个陌生人，随后回到旅馆",
        ),
        encoding="utf-8",
    )
    before = outline.read_bytes()

    revision = build_outline_structure(root)["revision"]
    read = mutate_outline_structure(root, operation="get_meta", node_id="ch_001", revision=revision)

    assert read["metadata"]["promise"] == "独自困在旅馆 -> 决定去见一个陌生人，随后回到旅馆"

    result = mutate_outline_structure(
        root, operation="set_meta", node_id="ch_001", revision=revision, metadata=read["metadata"]
    )

    assert result["content"].encode("utf-8") == before


def test_a_list_field_rejects_a_non_string_item_by_naming_the_field(tmp_path: Path):
    root = _project(tmp_path, chapters=1)
    revision = build_outline_structure(root)["revision"]

    with pytest.raises(ValueError) as rejected:
        mutate_outline_structure(
            root,
            operation="set_meta",
            node_id="ch_001",
            revision=revision,
            metadata={"characters": ["约翰·H·华生", 42]},
        )

    assert "characters" in str(rejected.value)
    assert "array of strings" in str(rejected.value)


def test_a_scalar_field_rejects_an_array(tmp_path: Path):
    root = _project(tmp_path, chapters=1)
    revision = build_outline_structure(root)["revision"]

    with pytest.raises(ValueError) as rejected:
        mutate_outline_structure(
            root,
            operation="set_meta",
            node_id="ch_001",
            revision=revision,
            metadata={"dramatic_position": ["起", "承"]},
        )

    assert "dramatic_position" in str(rejected.value)


@pytest.mark.skipif(
    not SAMPLE_OUTLINE.is_file(),
    reason=f"sample outline not available at {SAMPLE_OUTLINE}",
)
def test_the_author_sample_outline_survives_an_unchanged_write(tmp_path: Path):
    root = tmp_path / "data" / "novels" / "demo"
    (root / "src").mkdir(parents=True)
    outline = root / "src" / "outline.md"
    outline.write_bytes(SAMPLE_OUTLINE.read_bytes())
    before = outline.read_bytes()

    revision = build_outline_structure(root)["revision"]
    chapters = build_outline_structure(root)["roots"][0]["children"][0]["children"][0]["children"]

    for chapter in chapters:
        read = mutate_outline_structure(
            root, operation="get_meta", node_id=chapter["id"], revision=revision
        )
        result = mutate_outline_structure(
            root,
            operation="set_meta",
            node_id=chapter["id"],
            revision=revision,
            metadata=read["metadata"],
        )
        assert result["content"].encode("utf-8") == before, chapter["id"]
        break
