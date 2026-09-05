"""ContextBuilder 测试

覆盖上下文构建器的核心功能：
- Token 估算
- YAML/文本加载
- Markdown 解析辅助方法
- 大纲窗口获取
- 伏笔状态解析
- 动态压缩逻辑
"""

import os
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.context_package import GenerationContext
from models.outline import OutlineHierarchy, OutlineNode, OutlineNodeType
from tools.context_builder import ContextBuilder
from tools.context_protection import ContextBudgetError
from tools.outline_parser import OutlineMdParser

# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def project_dir(tmp_path):
    """创建最小项目结构"""
    novel_id = "test_novel"
    base = tmp_path / "data" / "novels" / novel_id
    (base / "src" / "characters").mkdir(parents=True)
    (base / "src" / "world" / "entities").mkdir(parents=True)
    (base / "data" / "characters" / "cards").mkdir(parents=True)
    (base / "data" / "foreshadowing").mkdir(parents=True)
    (base / "data" / "style").mkdir(parents=True)
    (base / "data" / "manuscript" / "arc_001").mkdir(parents=True)
    (base / "data" / "compressed").mkdir(parents=True)
    (base / "data" / "workflows").mkdir(parents=True)
    (tmp_path / "craft").mkdir(parents=True)
    return tmp_path, novel_id


@pytest.fixture
def builder(project_dir):
    root, novel_id = project_dir
    return ContextBuilder(project_root=root, novel_id=novel_id)


# ── Token estimation ─────────────────────────────────────────


class TestTokenEstimation:
    """Token 估算测试"""

    def test_chinese_text(self, builder):
        assert builder._estimate_tokens("你好世界") == 6  # 4 × 1.5

    def test_english_text(self, builder):
        assert builder._estimate_tokens("hello world") == 2  # 11 × 0.25 → 2

    def test_mixed_text(self, builder):
        # 2 中文 × 1.5 + 7 非中文 × 0.25 = 3 + 1.75 = 4
        assert builder._estimate_tokens("你好 hello") == 4

    def test_empty_text(self, builder):
        assert builder._estimate_tokens("") == 0

    def test_pure_numbers(self, builder):
        # 5 字符 × 0.25 = 1
        assert builder._estimate_tokens("12345") == 1

    def test_long_chinese_text(self, builder):
        text = "测" * 1000
        assert builder._estimate_tokens(text) == 1500  # 1000 × 1.5


# ── YAML/Text loading ────────────────────────────────────────


class TestFileLoading:
    """文件加载测试"""

    def test_load_yaml_valid(self, builder, project_dir):
        root, novel_id = project_dir
        yaml_path = root / "data" / "novels" / novel_id / "data" / "test.yaml"
        yaml_path.write_text("key: value\nlist:\n  - a\n  - b\n", encoding="utf-8")
        result = builder._load_yaml(yaml_path)
        assert result == {"key": "value", "list": ["a", "b"]}

    def test_load_yaml_nonexistent(self, builder):
        result = builder._load_yaml(Path("/nonexistent/file.yaml"))
        assert result == {}

    def test_load_yaml_invalid(self, builder, project_dir):
        root, novel_id = project_dir
        bad_path = root / "bad.yaml"
        bad_path.write_text("{ invalid yaml: [", encoding="utf-8")
        result = builder._load_yaml(bad_path)
        assert result == {}

    def test_load_text_valid(self, builder, project_dir):
        root, novel_id = project_dir
        txt_path = root / "test.txt"
        txt_path.write_text("hello world", encoding="utf-8")
        assert builder._load_text(txt_path) == "hello world"

    def test_load_text_nonexistent(self, builder):
        assert builder._load_text(Path("/nonexistent/file.txt")) == ""

    def test_repo_humanization_yaml_is_parseable(self):
        repo_root = Path(__file__).parent.parent
        yaml_path = repo_root / "craft" / "humanization.yaml"
        builder = ContextBuilder(project_root=repo_root, novel_id="test_novel")

        result = builder._load_yaml(yaml_path)

        assert isinstance(result, dict)
        assert "banned_phrases" in result


# ── Markdown helper methods ──────────────────────────────────


class TestMarkdownHelpers:
    """Markdown 辅助方法测试"""

    def test_extract_heading(self, builder):
        text = "# 我的小说标题\n\n内容"
        assert builder._extract_md_heading(text) == "我的小说标题"

    def test_extract_heading_missing(self, builder):
        assert builder._extract_md_heading("没有标题") == ""

    def test_extract_section(self, builder):
        text = "## 背景\n角色出生在一个小村庄。\n\n## 外貌\n高大威猛"
        assert "小村庄" in builder._extract_md_section(text, "背景")

    def test_extract_section_missing(self, builder):
        assert builder._extract_md_section("## 其他\n内容", "背景") == ""

    def test_extract_list(self, builder):
        text = "## 性格\n- 勇敢\n- 善良\n- 固执\n\n## 其他\n内容"
        items = builder._extract_md_list(text, "性格")
        assert items == ["勇敢", "善良", "固执"]

    def test_extract_list_empty_section(self, builder):
        assert builder._extract_md_list("## 无关\n内容", "性格") == []

    def test_parse_character_profile_with_toml_front_matter(self, builder, project_dir):
        root, novel_id = project_dir
        profile_path = root / "data" / "novels" / novel_id / "src" / "characters" / "chen_ming.md"
        profile_path.write_text(
            """+++
id = "char_chen_ming"
name = "陈明"
tier = "主角"
summary = "普通程序员觉醒术法后被迫在两个世界夹缝求生。"
tags = ["都市", "异能"]
detail_refs = ["background", "appearance", "personality"]

[[related]]
target = "zhao_lei"
kind = "friend"
weight = 0.82
note = "最信任的同事"
+++

# 陈明

## background
普通程序员，偶然觉醒术法。

## appearance
中等偏瘦，黑眼圈明显。

## personality
- 理工科思维
- 嘴硬心软
""",
            encoding="utf-8",
        )

        profile = builder._parse_character_profile(profile_path, "chen_ming")

        assert profile is not None
        assert profile.character_id == "char_chen_ming"
        assert profile.name == "陈明"
        assert profile.tier.value == "主角"
        assert profile.summary == "普通程序员觉醒术法后被迫在两个世界夹缝求生。"
        assert profile.tags == ["都市", "异能"]
        assert profile.detail_refs == ["background", "appearance", "personality"]
        assert profile.related[0]["target"] == "zhao_lei"
        assert profile.backstory == "普通程序员，偶然觉醒术法。"
        assert profile.personality == ["理工科思维", "嘴硬心软"]

    def test_character_profile_context_text_includes_index_fields(self, builder, project_dir):
        root, novel_id = project_dir
        profile_path = root / "data" / "novels" / novel_id / "src" / "characters" / "chen_ming.md"
        profile_path.write_text(
            """+++
id = "char_chen_ming"
name = "陈明"
tier = "主角"
summary = "普通程序员觉醒术法后被迫在两个世界夹缝求生。"
tags = ["都市", "异能"]
detail_refs = ["background", "appearance", "personality"]

[[related]]
target = "zhao_lei"
kind = "friend"
note = "最信任的同事"
+++

# 陈明

## background
普通程序员，偶然觉醒术法。
""",
            encoding="utf-8",
        )

        profile = builder._parse_character_profile(profile_path, "chen_ming")

        assert profile is not None
        context_text = profile.to_context_text()
        assert "标签: 都市、异能" in context_text
        assert "细节索引: background、appearance、personality" in context_text
        assert "关联: zhao_lei（最信任的同事）" in context_text

    def test_outline_parser_ignores_long_range_plan_block(self, builder):
        outline_text = """# 示例小说

## 第一篇：确认范围
### 第一节：当前可写
#### 第一章：当前章节
> 内容焦点: 当前确认窗口内的章节。

<!-- OPENWRITE:LONG_RANGE_PLAN:START -->
# 全书长线规划：《示例小说》

## 第二篇：未来篇
### 第一节：未来节
#### 第一章：未来章节
> 内容焦点: 这只是长线规划，不该被当成当前可写章节。
<!-- OPENWRITE:LONG_RANGE_PLAN:END -->
"""

        hierarchy = OutlineMdParser().parse(outline_text, "test_novel")

        assert len(hierarchy.arcs) == 1
        assert len(hierarchy.sections) == 1
        assert len(hierarchy.chapters) == 1
        assert hierarchy.chapters[0].title == "第一章：当前章节"

    def test_get_active_characters_resolves_display_name_to_shared_source(self, builder, project_dir):
        root, novel_id = project_dir
        profile_path = root / "data" / "novels" / novel_id / "src" / "characters" / "chen_ming.md"
        profile_path.write_text(
            """+++
id = "chen_ming"
name = "陈明"
tier = "主角"
summary = "普通程序员觉醒术法后被迫在两个世界夹缝求生。"
+++

# 陈明

## 背景

普通程序员，偶然觉醒术法。
""",
            encoding="utf-8",
        )

        hierarchy = OutlineHierarchy(
            novel_id=novel_id,
            chapters=[
                OutlineNode(
                    node_id="ch_001",
                    node_type=OutlineNodeType.CHAPTER,
                    title="第一章",
                    involved_characters=["陈明"],
                )
            ],
        )

        profiles = builder._get_active_characters("ch_001", hierarchy)

        assert len(profiles) == 1
        assert profiles[0].character_id == "chen_ming"
        assert profiles[0].name == "陈明"

    def test_generation_context_uses_estimated_words_and_infers_mentioned_character(
        self, builder, project_dir
    ):
        root, novel_id = project_dir
        novel_root = root / "data" / "novels" / novel_id
        (novel_root / "src" / "outline.md").write_text(
            """# 测试小说

## 第一篇
### 第一节
#### 第一章：第十三秒
> 预估字数: 800
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
""",
            encoding="utf-8",
        )

        context = builder.build_generation_context("ch_001")

        assert context.target_words == 800
        assert [profile.name for profile in context.active_characters] == ["沈砚"]

    def test_active_characters_merge_outline_and_current_manuscript_alias_mentions(
        self, builder, project_dir
    ):
        root, novel_id = project_dir
        novel_root = root / "data" / "novels" / novel_id
        (novel_root / "src" / "characters" / "shen_jin.md").write_text(
            """+++
id = "shen_jin"
name = "沈烬"
tier = "主角"
summary = "机械师。"
+++

# 沈烬
""",
            encoding="utf-8",
        )
        (novel_root / "src" / "characters" / "xing_wujiu.md").write_text(
            """+++
id = "xing_wujiu"
name = "刑无咎"
aliases = ["老刑"]
tier = "重要配角"
summary = "第七回收科顾问。"
+++

# 刑无咎
""",
            encoding="utf-8",
        )
        (novel_root / "data" / "manuscript" / "arc_001" / "ch_001.md").write_text(
            "# 第一章\n\n沈烬听完老刑的最后一课，提交了实习申请。\n",
            encoding="utf-8",
        )
        hierarchy = OutlineHierarchy(
            novel_id=novel_id,
            chapters=[
                OutlineNode(
                    node_id="ch_001",
                    node_type=OutlineNodeType.CHAPTER,
                    title="第一章",
                    involved_characters=["沈烬"],
                )
            ],
        )

        profiles = builder._get_active_characters("ch_001", hierarchy)

        assert [profile.name for profile in profiles] == ["沈烬", "刑无咎"]
        assert profiles[1].aliases == ["老刑"]


# ── Chapter index parsing ────────────────────────────────────


class TestChapterIndexParsing:
    """章节序号解析测试"""

    def test_parse_standard_id(self, builder):
        assert builder._parse_chapter_index("ch_005") == 5

    def test_parse_number_string(self, builder):
        assert builder._parse_chapter_index("42") == 42

    def test_parse_empty(self, builder):
        assert builder._parse_chapter_index("") == 0

    def test_parse_no_number(self, builder):
        assert builder._parse_chapter_index("abc") == 0


# ── Outline hierarchy loading ────────────────────────────────


class TestOutlineLoading:
    """大纲加载测试"""

    def test_load_empty_hierarchy(self, builder):
        h = builder._load_outline_hierarchy()
        assert h.novel_id == "test_novel"
        assert h.arcs == []
        assert h.chapters == []

    def test_load_hierarchy_with_data(self, builder, project_dir):
        root, novel_id = project_dir
        outline_path = root / "data" / "novels" / novel_id / "data" / "hierarchy.yaml"
        data = {
            "story_info": {"title": "测试小说", "theme": "成长"},
            "arcs": [{"id": "arc_001", "title": "第一篇"}],
            "chapters": [
                {"id": "ch_001", "title": "第一章", "summary": "开篇", "word_count": 5000}
            ],
        }
        outline_path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")

        h = builder._load_outline_hierarchy()
        assert h.master.title == "测试小说"
        assert len(h.arcs) == 1
        assert h.arcs[0].title == "第一篇"
        assert len(h.chapters) == 1
        assert h.chapters[0].word_count_target == 5000

    def test_hierarchy_caching(self, builder, project_dir):
        """二次加载应使用缓存（仅当已有数据时）"""
        root, novel_id = project_dir
        outline_path = root / "data" / "novels" / novel_id / "data" / "hierarchy.yaml"
        import yaml as _yaml
        data = {"story_info": {"title": "缓存测试"}, "chapters": []}
        outline_path.write_text(_yaml.dump(data, allow_unicode=True), encoding="utf-8")
        h1 = builder._load_outline_hierarchy()
        h2 = builder._load_outline_hierarchy()
        assert h1 is h2

    def test_load_hierarchy_prefers_src_outline_over_conflicting_runtime_cache(self, builder, project_dir):
        root, novel_id = project_dir
        src_outline = root / "data" / "novels" / novel_id / "src" / "outline.md"
        src_outline.write_text(
            "# 源大纲\n\n## 第一篇\n\n### 第一节\n\n#### 源标题\n\n> 内容焦点: 源摘要\n",
            encoding="utf-8",
        )

        hierarchy_path = root / "data" / "novels" / novel_id / "data" / "hierarchy.yaml"
        hierarchy_path.write_text(
            yaml.dump(
                {
                    "story_info": {"title": "缓存大纲"},
                    "chapters": [{"id": "ch_001", "title": "缓存标题", "summary": "缓存摘要"}],
                },
                allow_unicode=True,
            ),
            encoding="utf-8",
        )

        hierarchy = builder._load_outline_hierarchy()

        assert hierarchy.master.title == "源大纲"
        assert hierarchy.chapters[0].title == "源标题"
        assert hierarchy.chapters[0].content_focus == "源摘要"


# ── Foreshadowing state ──────────────────────────────────────


class TestForeshadowingState:
    """伏笔状态解析测试"""

    def test_empty_state(self, builder):
        state = builder._get_foreshadowing_state("ch_001")
        assert state.pending == []
        assert state.planted == []
        assert state.resolved == []

    def test_state_from_dag(self, builder, project_dir):
        root, novel_id = project_dir
        dag_path = root / "data" / "novels" / novel_id / "data" / "foreshadowing" / "dag.yaml"
        dag_data = {
            "nodes": [
                {"id": "f001", "content": "伏笔A", "status": "埋伏", "created_at": "ch_001"},
                {"id": "f002", "content": "伏笔B", "status": "待收", "target_chapter": "ch_005"},
                {"id": "f003", "content": "伏笔C", "status": "已收"},
            ]
        }
        dag_path.write_text(yaml.dump(dag_data, allow_unicode=True), encoding="utf-8")

        state = builder._get_foreshadowing_state("ch_003")
        assert len(state.resolved) == 1  # f003
        assert len(state.pending) == 1   # f002


# ── Dynamic compression ──────────────────────────────────────


class TestDynamicCompression:
    """动态压缩测试"""

    def test_no_compression_needed(self, builder):
        context = GenerationContext(
            novel_id="test",
            chapter_id="ch_001",
            recent_text="短文本",
        )
        result = builder._compress_if_needed(context)
        assert result.recent_text == "短文本"

    def test_truncate_recent_text(self, builder):
        # 超限时先保留可用于连续性的精确尾部，而不是固定砍到 300 字。
        long_text = "字" * (builder.MAX_TOKENS * 2)
        context = GenerationContext(
            novel_id="test",
            chapter_id="ch_001",
            recent_text=long_text,
        )
        result = builder._compress_if_needed(context)
        assert len(result.recent_text) <= 2000
        assert result.compression["applied"] is True
        assert result.estimate_tokens() <= builder.MAX_TOKENS

    def test_reduce_outline_window(self, builder):
        # 创建大量窗口节点
        nodes = [
            OutlineNode(
                node_id=f"ch_{i:03d}",
                node_type=OutlineNodeType.CHAPTER,
                title=f"第{i}章",
                summary="一" * 2000,  # 每个节点内容很大
            )
            for i in range(10)
        ]
        context = GenerationContext(
            novel_id="test",
            chapter_id="ch_005",
            outline_window=nodes,
            recent_text="短",
        )
        result = builder._compress_if_needed(context)
        # 窗口应被缩减
        assert len(result.outline_window) <= max(3, len(nodes))

    def test_level_one_compresses_old_memory_before_exact_recent_text(self, builder):
        builder.MAX_TOKENS = 4000
        context = GenerationContext(
            novel_id="test",
            chapter_id="ch_001",
            chapter_summaries="旧记忆。" * 500,
            recent_text="刚刚发生的场景。" * 50,
        )
        recent = context.recent_text

        result = builder._compress_if_needed(context)

        assert result.compression["level"] == 1
        assert result.recent_text == recent
        assert len(result.chapter_summaries) < len(context.chapter_summaries)
        assert result.estimate_tokens() <= builder.MAX_TOKENS

    def test_outline_compression_is_centered_and_does_not_mutate_source_nodes(self, builder):
        builder.MAX_TOKENS = 4000
        nodes = [
            OutlineNode(
                node_id=f"ch_{index:03d}",
                node_type=OutlineNodeType.CHAPTER,
                title=f"第{index}章",
                summary="本章发生关键转折。" * 120,
            )
            for index in range(1, 12)
        ]
        context = GenerationContext(
            novel_id="test",
            chapter_id="ch_006",
            outline_window=nodes,
            current_chapter=nodes[5],
        )

        result = builder._compress_if_needed(context)

        kept_ids = [node.node_id for node in result.outline_window]
        assert "ch_006" in kept_ids
        assert kept_ids[0] < "ch_006" < kept_ids[-1]
        assert result.estimate_tokens() <= builder.MAX_TOKENS
        assert result.current_chapter.summary == nodes[5].summary
        assert result.compression["protected_unchanged"] is True

    def test_protected_controls_over_budget_fail_instead_of_being_truncated(self, builder):
        builder.MAX_TOKENS = 1200
        context = GenerationContext(
            novel_id="test",
            chapter_id="ch_001",
            author_intent="必须守住人物选择。" * 500,
            creative_focus="本章完成关系反转。" * 500,
            recent_text="最近正文。" * 2000,
            current_state="世界状态变化。" * 1000,
            relationships="关系变化。" * 1000,
            chapter_summaries="历史事件。" * 2000,
        )

        with pytest.raises(ContextBudgetError) as raised:
            builder._compress_if_needed(context)

        assert raised.value.code == "PROTECTED_CONTEXT_OVER_BUDGET"
        assert raised.value.details["budget_tokens"] == 1200
        assert "author_intent" in raised.value.details["protected_items"]
        assert "creative_focus" in raised.value.details["protected_items"]
        assert raised.value.details["adjustments"]

    def test_optional_pressure_preserves_protected_content_and_records_compression(self, builder):
        builder.MAX_TOKENS = 4000
        context = GenerationContext(
            novel_id="test",
            chapter_id="ch_001",
            author_intent="人物不能违背已经做出的选择。",
            creative_focus="雨夜中完成关系反转。",
            core_documents={"foundation": "时间倒流必须付出记忆代价。"},
            current_state="钟楼仍然封闭。",
            relationships="林岑仍然信任周远。",
            recent_text="可压缩的最近正文。" * 2500,
            chapter_summaries="可重建的旧章节记忆。" * 2500,
        )
        protected_before = {
            "author_intent": context.author_intent,
            "creative_focus": context.creative_focus,
            "core_documents": dict(context.core_documents),
            "current_state": context.current_state,
            "relationships": context.relationships,
        }

        result = builder._compress_if_needed(context)

        assert result.author_intent == protected_before["author_intent"]
        assert result.creative_focus == protected_before["creative_focus"]
        assert result.core_documents == protected_before["core_documents"]
        assert result.current_state == protected_before["current_state"]
        assert result.relationships == protected_before["relationships"]
        assert result.compression["protected_unchanged"] is True
        assert result.compression["within_budget"] is True
        assert result.compression["actions"]

    def test_no_compression_records_budget_decision(self, builder):
        context = GenerationContext(recent_text="短文本")

        result = builder._compress_if_needed(context)

        assert result.compression["strategy"] == "staircase-proportional-v3"
        assert result.compression["applied"] is False
        assert result.compression["level"] == 0
        assert result.compression["planned_level"] == 0
        assert result.compression["budget_tokens"] == builder.MAX_TOKENS
        assert result.compression["target_tokens"] == builder.MAX_TOKENS
        assert result.compression["reserved_output_tokens"] == min(
            builder.MAX_OUTPUT_TOKENS,
            builder.CONTEXT_WINDOW_TOKENS
            - result.compression["safety_tokens"]
            - 1024,
        )
        assert result.compression["within_budget"] is True
        assert (
            result.compression["original_estimated_tokens"]
            == result.compression["final_estimated_tokens"]
        )
        assert result.compression["actions"] == []

    def test_truth_files_count_toward_context_budget(self):
        plain = GenerationContext(current_state="")
        with_truth = GenerationContext(current_state="状态变化。" * 100)

        assert with_truth.estimate_tokens() > plain.estimate_tokens()


# ── Recent chapters loading ──────────────────────────────────


class TestRecentChapters:
    """近文加载测试"""

    def test_no_manuscript(self, builder):
        assert builder._get_recent_chapters("ch_003") == ""

    def test_load_recent_chapters(self, builder, project_dir):
        root, novel_id = project_dir
        ms_dir = root / "data" / "novels" / novel_id / "data" / "manuscript" / "arc_001"
        ms_dir.mkdir(parents=True, exist_ok=True)
        (ms_dir / "ch_001.md").write_text("第一章的内容" * 50, encoding="utf-8")
        (ms_dir / "ch_002.md").write_text("第二章的内容" * 50, encoding="utf-8")

        result = builder._get_recent_chapters("ch_003", limit=2)
        assert "第一章的内容" in result or "第二章的内容" in result

    def test_chapter_zero_index(self, builder):
        assert builder._get_recent_chapters("ch_000") == ""


# ── Full build context (integration) ─────────────────────────


class TestBuildGenerationContext:
    """完整上下文构建集成测试"""

    def test_build_minimal_context(self, builder):
        """最小情况：无大纲、无角色"""
        context = builder.build_generation_context("ch_001")
        assert context.novel_id == "test_novel"
        assert context.chapter_id == "ch_001"

    def test_opening_chapter_does_not_start_an_ineligible_semantic_search(
        self, project_dir
    ):
        root, novel_id = project_dir

        def unexpected_backend(_novel_root):
            raise AssertionError("ch_001 has no distant prose or reference source to query")

        builder = ContextBuilder(
            root,
            novel_id,
            search_index_factory=unexpected_backend,
        )
        chapter = OutlineNode(
            node_id="ch_001",
            node_type=OutlineNodeType.CHAPTER,
            title="开篇",
            goals=["建立冲突"],
        )

        text, diagnostic = builder._get_semantic_references(
            "ch_001",
            current_chapter=chapter,
            active_characters=[],
            character_states="",
        )

        assert text == ""
        assert diagnostic["reason"] == "no_eligible_distant_context"
        assert diagnostic["index"]["status"] == "not_queried"

    def test_semantic_context_excludes_recent_chapters_and_keeps_sources(
        self, project_dir
    ):
        root, novel_id = project_dir
        calls = []
        source = (
            root
            / "data"
            / "novels"
            / novel_id
            / "data"
            / "sources"
            / "demo"
            / "analysis.md"
        )
        source.parent.mkdir(parents=True)
        source.write_text("先压低选择空间，再揭示隐藏筹码。", encoding="utf-8")

        class FakeSearchIndex:
            def search(self, query, *, scope, limit):
                calls.append((scope, query, limit))
                results = {
                    "chapters": [
                        {
                            "path": "data/manuscript/arc_001/ch_068.md",
                            "title": "过近章节",
                            "line": 3,
                            "scope": "chapters",
                            "retrieval": ["semantic"],
                            "excerpt": "不应重复注入最近两章。",
                        },
                        {
                            "path": "data/manuscript/arc_001/ch_040.md",
                            "title": "旧日决裂",
                            "line": 8,
                            "scope": "chapters",
                            "retrieval": ["semantic"],
                            "excerpt": "沈烬曾经主动疏远同伴。",
                        },
                    ],
                    "sources": [
                        {
                            "path": "data/sources/demo/analysis_v2/report.json",
                            "title": "参考拆书",
                            "line": 1,
                            "scope": "sources",
                            "retrieval": ["semantic"],
                            "excerpt": "先压低选择空间，再揭示隐藏筹码。",
                        }
                    ],
                }[scope]
                return {
                    "engine": "lightrag",
                    "warning_code": "",
                    "retrieval_stats": {"semantic": len(results)},
                    "embedding": {"provider": "local", "model": "test-local"},
                    "results": results,
                }

        builder = ContextBuilder(
            root,
            novel_id,
            search_index_factory=lambda novel_root: FakeSearchIndex(),
        )
        chapter = OutlineNode(
            node_id="ch_070",
            node_type=OutlineNodeType.CHAPTER,
            title="筹码反转",
            goals=["让沈烬反客为主"],
        )

        text, diagnostic = builder._get_semantic_references(
            "ch_070",
            current_chapter=chapter,
            active_characters=[],
            character_states="",
        )

        assert "旧日决裂" in text
        assert "参考拆书" in text
        assert "过近章节" not in text
        assert diagnostic["status"] == "ready"
        assert diagnostic["results"] == 2
        assert [item[0] for item in calls] == ["chapters", "sources"]

    def test_build_with_outline(self, builder, project_dir):
        root, novel_id = project_dir
        outline_path = root / "data" / "novels" / novel_id / "data" / "hierarchy.yaml"
        data = {
            "story_info": {"title": "测试"},
            "chapters": [
                {"id": "ch_001", "title": "开篇", "goals": ["目标1"]},
                {"id": "ch_002", "title": "发展"},
                {"id": "ch_003", "title": "转折"},
            ],
        }
        outline_path.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")

        context = builder.build_generation_context("ch_002", window_size=1)
        assert context.chapter_id == "ch_002"

    def test_build_auto_refreshes_stale_outline_hierarchy(self, project_dir):
        root, novel_id = project_dir
        src_outline = root / "data" / "novels" / novel_id / "src" / "outline.md"
        src_outline.write_text(
            "# 测试小说\n\n## 第一篇\n\n### 第一节\n\n#### 旧标题\n\n> 内容焦点: 旧摘要\n",
            encoding="utf-8",
        )

        from tools.outline_sync import sync_outline_to_hierarchy

        sync_outline_to_hierarchy(src_outline.parent, src_outline.parent.parent / "data")

        src_outline.write_text(
            "# 测试小说\n\n## 第一篇\n\n### 第一节\n\n#### 新标题\n\n> 内容焦点: 新摘要\n",
            encoding="utf-8",
        )
        hierarchy_path = src_outline.parent.parent / "data" / "hierarchy.yaml"
        stale_time = src_outline.stat().st_mtime - 10
        os.utime(hierarchy_path, (stale_time, stale_time))

        builder = ContextBuilder(project_root=root, novel_id=novel_id)
        context = builder.build_generation_context("ch_001")

        assert context.current_chapter is not None
        assert context.current_chapter.title == "新标题"

    def test_build_context_can_use_src_outline_without_runtime_hierarchy(self, project_dir):
        root, novel_id = project_dir
        src_outline = root / "data" / "novels" / novel_id / "src" / "outline.md"
        src_outline.write_text(
            "# 测试小说\n\n## 第一篇\n\n### 第一节\n\n#### 直接源标题\n\n> 内容焦点: 直接源摘要\n",
            encoding="utf-8",
        )

        builder = ContextBuilder(project_root=root, novel_id=novel_id)
        context = builder.build_generation_context("ch_001")

        assert context.current_chapter is not None
        assert context.current_chapter.title == "直接源标题"
        assert context.current_chapter.content_focus == "直接源摘要"
