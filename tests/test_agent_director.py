"""MultiAgentDirector 与 ChapterAssemblerV2 回归测试。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.agent.director import MultiAgentDirector
from tools.agent.reviewer import ReviewResult
from tools.agent.writer import WritingResult
from tools.chapter_assembler import ChapterAssemblerV2, ChapterAssemblyPacket
from tools.frontmatter import parse_toml_front_matter
from tools.init_project import init_project
from tools.truth_manager import TruthFilesManager


def _bootstrap_novel(tmp_path: Path, novel_id: str = "demo") -> Path:
    init_project(tmp_path, novel_id)
    novel_root = tmp_path / "data" / "novels" / novel_id

    hierarchy = {
        "story_info": {"title": "测试小说", "theme": "测试主题"},
        "arcs": [
            {
                "id": "arc_001",
                "title": "第一篇",
                "description": "开篇",
                "chapters": ["ch_001"],
            }
        ],
        "sections": [
            {
                "id": "sec_001",
                "title": "第一节",
                "arc_id": "arc_001",
                "chapters": ["ch_001"],
            }
        ],
        "chapters": [
            {
                "id": "ch_001",
                "title": "第一章",
                "summary": "开篇",
                "goals": ["建立主角"],
                "involved_characters": ["chen_ming"],
                "involved_settings": ["company"],
            }
        ],
    }
    (novel_root / "data" / "hierarchy.yaml").write_text(
        yaml.safe_dump(hierarchy, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    story_dir = novel_root / "src" / "story"
    story_dir.mkdir(parents=True, exist_ok=True)
    (story_dir / "background.md").write_text("# 背景\n\n测试背景。", encoding="utf-8")
    (story_dir / "foundation.md").write_text("# 设定\n\n测试设定。", encoding="utf-8")

    (novel_root / "src" / "characters" / "chen_ming.md").write_text(
        "# 陈明\n\n## 背景\n\n角色背景。\n\n## 外貌\n\n普通。\n\n## 性格\n\n- 冷静\n",
        encoding="utf-8",
    )
    (novel_root / "src" / "world" / "rules.md").write_text(
        "# 世界规则\n\n## 力量体系\n- 静态规则\n",
        encoding="utf-8",
    )
    (novel_root / "src" / "world" / "terminology.md").write_text(
        "# 术语表\n\n| 术语 | 定义 | 分类 |\n|------|------|------|\n| 公司 | 主舞台 | location |\n",
        encoding="utf-8",
    )
    entities_dir = novel_root / "src" / "world" / "entities"
    entities_dir.mkdir(parents=True, exist_ok=True)
    (entities_dir / "company.md").write_text(
        "# 公司\n\n> location | building | active\n\n主舞台。\n",
        encoding="utf-8",
    )

    truth_manager = TruthFilesManager(tmp_path, novel_id)
    truth = truth_manager.load_truth_files()
    truth.current_state = "这是运行态 current_state。"
    truth.particle_ledger = "这是运行态 ledger。"
    truth.character_matrix = "这是运行态 relationships。"
    truth_manager.save_truth_files(truth)
    return novel_root


def test_assemble_packet_includes_runtime_truth_files(tmp_path: Path):
    _bootstrap_novel(tmp_path)

    assembler = ChapterAssemblerV2(project_root=tmp_path, novel_id="demo")
    packet = assembler.assemble("ch_001")

    assert packet.current_state == "这是运行态 current_state。"
    assert packet.ledger == "这是运行态 ledger。"
    assert packet.relationships == "这是运行态 relationships。"

    markdown = packet.to_markdown()
    assert "## 运行态真相文件" in markdown
    assert "这是运行态 current_state。" in markdown
    assert "这是运行态 ledger。" in markdown
    assert "这是运行态 relationships。" in markdown


def test_director_run_uses_runtime_truth_files_for_writer_and_reviewer(tmp_path: Path):
    captured: dict[str, dict] = {}
    ctx = SimpleNamespace(project_root=str(tmp_path))
    director = MultiAgentDirector(ctx, novel_id="demo")
    packet = ChapterAssemblyPacket(
        novel_id="demo",
        chapter_id="ch_001",
        character_documents={"陈明": "角色文档"},
        style_documents={"style": "风格"},
        concept_documents={"world.rules": "静态规则"},
        previous_chapter_content="上一章内容",
        current_state="这是运行态 current_state。",
        ledger="这是运行态 ledger。",
        relationships="这是运行态 relationships。",
    )

    class FakeWriter:
        async def write_chapter(
            self,
            context,
            chapter_number: int,
            temperature: float = 0.7,
            target_words: int = 4000,
        ):
            captured["writer"] = context
            return WritingResult(
                chapter_number=chapter_number,
                title="测试标题",
                content="测试正文",
                word_count=3210,
                state_updates={},
            )

    class FakeReviewer:
        async def review(self, content: str, context: dict):
            captured["reviewer"] = context
            return ReviewResult(passed=True, issues=[], summary="ok", score=95)

    director.writer = FakeWriter()
    director.reviewer = FakeReviewer()
    director.assemble_packet = lambda chapter_id: packet

    result = asyncio.run(director.run("ch_001"))

    assert result.packet is packet
    assert captured["writer"]["current_state"] == "这是运行态 current_state。"
    assert captured["writer"]["ledger"] == "这是运行态 ledger。"
    assert captured["writer"]["relationships"] == "这是运行态 relationships。"
    assert "particle_ledger" not in captured["writer"]
    assert "character_matrix" not in captured["writer"]
    assert captured["writer"]["current_state"] != "静态规则"
    assert captured["reviewer"]["current_state"] == "这是运行态 current_state。"
    assert "particle_ledger" not in captured["reviewer"]
    assert "character_matrix" not in captured["reviewer"]


def test_apply_state_updates_accepts_canonical_truth_keys(tmp_path: Path):
    init_project(tmp_path, "demo")
    ctx = SimpleNamespace(project_root=str(tmp_path))
    director = MultiAgentDirector(ctx, novel_id="demo")

    applied = director._apply_state_updates(
        {
            "current_state": "状态更新",
            "ledger": "账本更新",
            "relationships": "关系更新",
        }
    )

    truth = director.truth_manager.load_truth_files()
    assert applied == {
        "current_state": "状态更新",
        "ledger": "账本更新",
        "relationships": "关系更新",
    }
    assert truth.current_state == "状态更新"
    assert truth.ledger == "账本更新"
    assert truth.relationships == "关系更新"


def test_curate_new_concepts_writes_frontmatter_entity_document(tmp_path: Path):
    init_project(tmp_path, "demo")
    ctx = SimpleNamespace(project_root=str(tmp_path))
    director = MultiAgentDirector(ctx, novel_id="demo")

    created = director._curate_new_concepts("新概念：灵网回声", {})

    entity_path = (
        tmp_path
        / "data"
        / "novels"
        / "demo"
        / "src"
        / "world"
        / "entities"
        / "灵网回声.md"
    )
    text = entity_path.read_text(encoding="utf-8")
    meta, body = parse_toml_front_matter(text)

    assert created == ["灵网回声"]
    assert meta["id"] == "灵网回声"
    assert meta["name"] == "灵网回声"
    assert meta["type"] == "concept"
    assert meta["detail_refs"] == ["规则", "特征", "关联"]
    assert body.lstrip().startswith("# 灵网回声")
    assert "## 规则" in body
    assert "## 特征" in body
    assert "## 关联" in body


def test_assembler_prefers_src_outline_over_runtime_hierarchy(tmp_path: Path):
    novel_root = _bootstrap_novel(tmp_path)
    (novel_root / "src" / "outline.md").write_text(
        "# 源大纲\n\n## 第一篇\n\n### 第一节\n\n#### 源标题\n\n> 内容焦点: 源摘要\n",
        encoding="utf-8",
    )
    (novel_root / "data" / "hierarchy.yaml").write_text(
        yaml.safe_dump(
            {
                "story_info": {"title": "缓存大纲"},
                "chapters": [{"id": "ch_001", "title": "缓存标题", "summary": "缓存摘要"}],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    assembler = ChapterAssemblerV2(project_root=tmp_path, novel_id="demo")
    hierarchy = assembler._load_hierarchy()

    assert hierarchy.master.title == "源大纲"
    assert hierarchy.get_node("ch_001").title == "源标题"
    assert hierarchy.get_node("ch_001").content_focus == "源摘要"


def test_assembler_uses_explicit_arc_and_section_summaries_from_outline_body(tmp_path: Path):
    novel_root = _bootstrap_novel(tmp_path)
    (novel_root / "src" / "outline.md").write_text(
        (
            "# 测试小说\n\n"
            "## 第一篇：觉醒篇\n\n"
            "这是篇梗概专用文本。它明确说明这一篇从主角的异常觉醒写到第一次主动修补异常，"
            "并强调职场压力、隐藏身份和现实物证逐步收紧的整体推进。\n\n"
            "> 篇弧线: 觉醒 → 试探 → 卷入\n"
            "> 篇情感: 困惑 → 紧张 → 决断\n"
            "> 起止章节: ch_001 - ch_001\n\n"
            "### 第一节：意外觉醒\n\n"
            "这是节梗概专用文本。它说明这一节如何从加班夜异常开始，推进到会议室失控与"
            "主角确认自身变化，同时交代赵磊和林月分别从朋友与上司视角感受到不对劲。\n\n"
            "> 节结构: 起(ch_001)\n"
            "> 节情感: 困惑 → 失控 → 接受\n\n"
            "#### 第一章：加班\n\n"
            "> 戏剧位置: 起\n"
            "> 内容焦点: 开篇\n"
            "> 出场角色: chen_ming\n"
            "> 涉及设定: company\n"
        ),
        encoding="utf-8",
    )

    packet = ChapterAssemblerV2(project_root=tmp_path, novel_id="demo").assemble("ch_001")

    assert "篇梗概专用文本" in packet.historical_arc_summaries[0].summary
    assert "节梗概专用文本" in packet.current_arc_sections[0].summary


def test_outline_parser_keeps_section_summary_on_later_sections(tmp_path: Path):
    novel_root = _bootstrap_novel(tmp_path)
    outline_text = (
        "# 测试小说\n\n"
        "## 第一篇：觉醒篇\n\n"
        "篇梗概一。\n\n"
        "### 第一节：A\n\n"
        "第一节梗概。\n\n"
        "> 节结构: 起(ch_001)\n\n"
        "#### 第一章：甲\n\n"
        "> 内容焦点: 甲摘要\n"
        "> 出场角色: chen_ming\n"
        "> 涉及设定: company\n\n"
        "### 第二节：B\n\n"
        "第二节梗概。\n\n"
        "> 节结构: 起(ch_002)\n\n"
        "#### 第二章：乙\n\n"
        "> 内容焦点: 乙摘要\n"
        "> 出场角色: chen_ming\n"
        "> 涉及设定: company\n"
    )
    (novel_root / "src" / "outline.md").write_text(outline_text, encoding="utf-8")

    hierarchy = ChapterAssemblerV2(project_root=tmp_path, novel_id="demo")._load_hierarchy()

    assert hierarchy.sections[0].summary == "第一节梗概。"
    assert hierarchy.sections[1].summary == "第二节梗概。"


def test_assembler_resolves_character_documents_by_display_name(tmp_path: Path):
    novel_root = _bootstrap_novel(tmp_path)
    (novel_root / "src" / "outline.md").write_text(
        (
            "# 测试小说\n\n"
            "## 第一篇：觉醒篇\n\n"
            "篇梗概。\n\n"
            "### 第一节：意外觉醒\n\n"
            "节梗概。\n\n"
            "#### 第一章：加班\n\n"
            "> 内容焦点: 开篇\n"
            "> 出场角色: 陈明\n"
            "> 涉及设定: 公司\n"
        ),
        encoding="utf-8",
    )
    (novel_root / "src" / "characters" / "chen_ming.md").write_text(
        """+++
id = "chen_ming"
name = "陈明"
tier = "主角"
summary = "普通程序员觉醒术法。"
+++

# 陈明

## 背景

普通程序员。
""",
        encoding="utf-8",
    )

    packet = ChapterAssemblerV2(project_root=tmp_path, novel_id="demo").assemble("ch_001")

    assert "陈明" in packet.character_documents
    assert "普通程序员觉醒术法" in packet.character_documents["陈明"]


def test_assembler_infers_character_from_chapter_text_when_metadata_is_missing(
    tmp_path: Path,
):
    novel_root = _bootstrap_novel(tmp_path)
    (novel_root / "src" / "outline.md").write_text(
        """# 测试小说

## 第一篇
### 第一节
#### 第一章：异常磁带
> 内容焦点: 沈砚在雨夜修复一盒异常磁带。
""",
        encoding="utf-8",
    )
    (novel_root / "src" / "characters" / "shen_yan.md").write_text(
        """+++
id = "shen_yan"
name = "沈砚"
tier = "主角"
summary = "谨慎的磁带修复师。"
+++

# 沈砚

## 基本信息

磁带修复师。

## 背景

妹妹三年前去世。

## 外貌

常穿深灰工作衫。

## 性格

谨慎、程序化。

## 关系

只有妹妹会叫他“阿迟”。
""",
        encoding="utf-8",
    )

    packet = ChapterAssemblerV2(project_root=tmp_path, novel_id="demo").assemble("ch_001")

    assert "沈砚" in packet.character_documents
    assert "谨慎的磁带修复师" in packet.character_documents["沈砚"]
    assert "阿迟" in packet.character_documents["沈砚"]
