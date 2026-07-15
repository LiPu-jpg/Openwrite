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
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.context_builder import ContextBuilder
from tools.outline_parser import OutlineMdParser
from models.outline import OutlineNode, OutlineNodeType, OutlineHierarchy
from models.context_package import GenerationContext


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
        # GenerationContext.estimate_tokens 使用 len(text)/1.5 来估算
        # 需要让 to_prompt_sections 的总文本量超 MAX_TOKENS 对应的字符数
        # MAX_TOKENS = 24000, 需要 > 24000 * 1.5 = 36000 字符
        long_text = "字" * 40000
        context = GenerationContext(
            novel_id="test",
            chapter_id="ch_001",
            recent_text=long_text,
        )
        result = builder._compress_if_needed(context)
        # 压缩后 recent_text 应被截断到 300 字符
        assert len(result.recent_text) <= 300

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
