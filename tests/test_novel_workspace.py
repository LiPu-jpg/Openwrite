from pathlib import Path

import yaml

from models.context_package import GenerationContext
from tools.chapter_assembler import ChapterAssemblerV2
from tools.context_builder import ContextBuilder
from tools.init_project import init_project
from tools.novel_workspace import (
    build_workspace_snapshot,
    count_writing_units,
    export_manuscript,
    import_manuscript,
    load_creative_focus,
    save_creative_focus,
    split_manuscript,
)


def test_init_creates_novel_control_documents(tmp_path: Path):
    init_project(tmp_path, "demo", "雾城来信")

    story = tmp_path / "data" / "novels" / "demo" / "src" / "story"
    assert (story / "author_intent.md").exists()
    assert (story / "current_focus.md").exists()
    assert (story / "background.md").exists()
    assert (story / "foundation.md").exists()

    config = yaml.safe_load((tmp_path / "novel_config.yaml").read_text(encoding="utf-8"))
    assert config["title"] == "雾城来信"


def test_creative_focus_round_trip_and_prompt_priority(tmp_path: Path):
    init_project(tmp_path, "demo")
    save_creative_focus(
        tmp_path,
        "demo",
        goal="让主角第一次主动选择代价",
        must_keep=["雨夜意象", "克制的对话"],
        must_avoid=["突然升级"],
        notes=["结尾留下行动钩子"],
    )

    focus = load_creative_focus(tmp_path, "demo")
    assert focus.goal == "让主角第一次主动选择代价"
    assert focus.must_keep == ["雨夜意象", "克制的对话"]
    assert focus.must_avoid == ["突然升级"]

    context = GenerationContext(author_intent="长期承诺", creative_focus="近期目标")
    sections = context.to_prompt_sections()
    assert list(sections)[:2] == ["作者意图", "创作罗盘（当前最高优先级）"]

    built = ContextBuilder(tmp_path, "demo").build_generation_context("ch_001")
    assert "核心承诺" in built.author_intent
    assert "让主角第一次主动选择代价" in built.creative_focus


def test_chapter_packet_includes_author_intent_and_focus(tmp_path: Path):
    init_project(tmp_path, "demo")
    story = tmp_path / "data" / "novels" / "demo" / "src" / "story"
    (story / "author_intent.md").write_text("# 作者意图\n\n守住人物选择", encoding="utf-8")
    save_creative_focus(tmp_path, "demo", goal="本章必须完成一次关系反转")

    packet = ChapterAssemblerV2(tmp_path, "demo").assemble("ch_001")
    assert "守住人物选择" in packet.author_intent
    assert "关系反转" in packet.creative_focus
    rendered = packet.to_markdown()
    assert rendered.index("## 作者意图") < rendered.index("## 故事背景")
    assert rendered.index("## 创作罗盘") < rendered.index("## 故事背景")


def test_split_manuscript_does_not_treat_prose_as_heading():
    text = (
        "# 第一章 雨夜\n他推开门。\n\n"
        "# 第二章 回声\n第二章正文。\n第二章里，他其实没有听见。"
    )

    chunks = split_manuscript(text, fallback_title="旧稿")

    assert [title for title, _ in chunks] == ["第一章 雨夜", "第二章 回声"]
    content = chunks[1][1]
    assert content.startswith("第二章正文。")
    assert "第二章里，他其实没有听见。" in content


def test_split_manuscript_accepts_plain_and_markdown_headings():
    text = (
        "第一章归国的伤兵\n第一段。\n\n"
        "#### 第二章：回声\n第二段。\n\n"
        "Chapter 3 The End\n正文。"
    )

    chunks = split_manuscript(text, fallback_title="旧稿")

    assert [title for title, _ in chunks] == [
        "第一章归国的伤兵",
        "第二章：回声",
        "Chapter 3 The End",
    ]


def test_split_manuscript_rejects_long_marker_line_as_prose():
    long_prose = "第一章 " + "很长的正文" * 10

    chunks = split_manuscript(f"{long_prose}\n正文。", fallback_title="旧稿")

    assert [title for title, _ in chunks] == ["旧稿"]
    assert long_prose in chunks[0][1]


def test_split_import_and_export_existing_manuscript(tmp_path: Path):
    init_project(tmp_path, "demo", "雾城来信")
    source = tmp_path / "old.txt"
    source.write_text(
        "书名：雾城来信\n\n第一章 雨夜\n他推开门。\n\n第二章 回声\n门后没有人。",
        encoding="utf-8",
    )

    chunks = split_manuscript(source.read_text(encoding="utf-8"), fallback_title="旧稿")
    assert [title for title, _ in chunks] == ["第一章 雨夜", "第二章 回声"]
    assert chunks[0][1].startswith("书名：雾城来信")

    imported = import_manuscript(
        tmp_path,
        "demo",
        source,
        arc_id="arc_001",
    )
    assert [item.chapter_id for item in imported] == ["ch_001", "ch_002"]
    assert imported[0].writing_units == count_writing_units("书名：雾城来信\n\n他推开门。")
    imported[1].path.write_text(
        imported[1].path.read_text(encoding="utf-8")
        + "\n//**林舟[位置]：门外 -> 门后**\n",
        encoding="utf-8",
    )

    output = export_manuscript(
        tmp_path,
        "demo",
        tmp_path / "exports" / "demo.txt",
        format_name="txt",
        title="雾城来信",
    )
    exported = output.read_text(encoding="utf-8")
    assert exported.startswith("雾城来信")
    assert "第一章 雨夜" in exported
    assert "第二章 回声" in exported
    assert "//**" not in exported
    assert "#" not in exported


def test_workspace_snapshot_surfaces_novel_readiness(tmp_path: Path):
    init_project(tmp_path, "demo", "雾城来信")
    root = tmp_path / "data" / "novels" / "demo"
    (root / "src" / "story" / "author_intent.md").write_text(
        "# 作者意图\n\n写人在代价面前如何选择。", encoding="utf-8"
    )
    (root / "src" / "story" / "background.md").write_text(
        "# 故事背景\n\n一座只在雨夜出现的城。", encoding="utf-8"
    )
    (root / "src" / "story" / "foundation.md").write_text(
        "# 基础设定\n\n进入雾城的人会失去一段记忆。", encoding="utf-8"
    )
    (root / "src" / "characters" / "lin.md").write_text("# 林岑", encoding="utf-8")
    (root / "src" / "outline.md").write_text(
        "# 大纲\n\n## 第一篇\n\n### 开头\n\n#### 第一章\n\n> 内容焦点: 林岑进入雾城\n",
        encoding="utf-8",
    )
    save_creative_focus(tmp_path, "demo", goal="完成开篇承诺")

    config = yaml.safe_load((tmp_path / "novel_config.yaml").read_text(encoding="utf-8"))
    snapshot = build_workspace_snapshot(tmp_path, config)

    assert snapshot.title == "雾城来信"
    assert snapshot.readiness == {
        "author_intent": True,
        "background": True,
        "foundation": True,
        "characters": True,
        "outline": True,
        "creative_focus": True,
    }
    assert "Dante" in snapshot.next_actions[0]
    assert snapshot.next_action_items[0]["studio_action"] == "open_dante"
    assert snapshot.next_action_items[0]["cli"] == "openwrite dante"


def test_onboarding_checklist_for_empty_project(tmp_path: Path):
    from tools.novel_workspace import build_onboarding_checklist

    init_project(tmp_path, "demo", "雾城来信")
    checklist = build_onboarding_checklist(tmp_path, "demo")

    assert checklist["ready_to_write"] is False
    assert "作者意图" in checklist["missing_labels"]
    assert checklist["next_action_items"][0]["studio_action"] == "open_goethe"
    assert "题材" in checklist["suggested_first_message"]


def test_outline_readiness_rejects_placeholder_template(tmp_path: Path):
    init_project(tmp_path, "demo")
    config = yaml.safe_load((tmp_path / "novel_config.yaml").read_text(encoding="utf-8"))
    snapshot = build_workspace_snapshot(tmp_path, config)

    assert snapshot.readiness["outline"] is False
    assert snapshot.readiness["author_intent"] is False


def test_demo_short_template_creates_writable_assets(tmp_path: Path):
    init_project(tmp_path, "demo_novel", "雾城来信", template="demo_short")
    config = yaml.safe_load((tmp_path / "novel_config.yaml").read_text(encoding="utf-8"))
    snapshot = build_workspace_snapshot(tmp_path, config)

    assert snapshot.readiness["author_intent"] is True
    assert snapshot.readiness["background"] is True
    assert snapshot.readiness["foundation"] is True
    assert snapshot.readiness["characters"] is True
    assert snapshot.readiness["outline"] is True
    assert snapshot.readiness["creative_focus"] is True
    assert (tmp_path / "data" / "novels" / "demo_novel" / "src" / "characters" / "lin_zhou.md").exists()
    outline = (tmp_path / "data" / "novels" / "demo_novel" / "src" / "outline.md").read_text(encoding="utf-8")
    assert "第一章" in outline
    assert "待填写" not in outline


def test_split_manuscript_ignores_utf8_bom():
    text = "\ufeff# 第一章 雨夜\n\n他推开门。\n\n# 第二章 回声\n\n门后没有人。"

    chunks = split_manuscript(text, fallback_title="旧稿")

    assert [title for title, _ in chunks] == ["第一章 雨夜", "第二章 回声"]
    assert chunks[0][1] == "他推开门。"


def test_split_manuscript_strips_atx_closing_hashes():
    text = "# 第一章 雨夜 ###\n\n他推开门。"

    chunks = split_manuscript(text, fallback_title="旧稿")

    assert [title for title, _ in chunks] == ["第一章 雨夜"]
