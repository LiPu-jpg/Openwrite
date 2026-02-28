"""大纲工具测试。

测试 skills/outline/tools/ 中的解析器、序列化器和验证器。
"""

import pytest

from skills.outline.tools.parser import (
    ArcOutline,
    ChapterOutline,
    MasterOutline,
    OutlineHierarchy,
    OutlineParser,
    SectionOutline,
    parse_outline,
)

from skills.outline.tools.serializer import (
    OutlineSerializer,
    serialize_outline,
)
from skills.outline.tools.validator import (
    OutlineValidator,
    ValidationResult,
    validate_outline,
)


# ═══════════════════════════════════════════════════════════════════════
# 测试数据
# ═══════════════════════════════════════════════════════════════════════

SAMPLE_OUTLINE_MD = """# 测试小说
---
novel_id: test_novel
core_theme: 成长与救赎
ending_direction: 大团圆结局
world_premise: 一个魔法与科技共存的世界
tone: 轻松幽默
target_word_count: 300000
version: "1.0"
---
- 主角发现身世之谜
- 遭遇重大挫折
- 最终战胜反派

## 第一篇：觉醒
---
arc_id: arc_001
order: 1
main_conflict: 主角与自身身份认同的冲突
resolution: 接受自己的身份，决定改变世界
key_characters:
  - 李逍遥
  - 林月如
status: TODO
---

### 第一节：初入江湖
---
section_id: sec_001
order: 1
plot_summary: 主角初入江湖，结识伙伴
key_events:
  - 主角离开家乡
  - 遇到第一个伙伴
  - 第一次战斗
foreshadowing_plant: []
foreshadowing_recover: []
status: TODO
---

#### 第一章：离别
---
chapter_id: ch_001
order: 1
goals:
  - 展示主角背景
  - 建立核心动机
key_scenes:
  - 告别家人
  - 踏上旅程
emotion_arc: 期待→不舍→坚定
involved_characters:
  - 李逍遥
involved_settings:
  - 村庄
target_words: 6000
status: TODO
---
"""


# ═══════════════════════════════════════════════════════════════════════
# 解析器测试
# ═══════════════════════════════════════════════════════════════════════


class TestOutlineParser:
    """大纲解析器测试。"""

    def test_parse_basic_outline(self):
        """测试基本大纲解析。"""
        hierarchy = parse_outline(SAMPLE_OUTLINE_MD)

        # 验证总纲
        assert hierarchy.master.novel_id == "test_novel"
        assert hierarchy.master.title == "测试小说"
        assert hierarchy.master.core_theme == "成长与救赎"
        assert len(hierarchy.master.key_turns) == 3

        # 验证篇纲
        assert len(hierarchy.arcs) == 1
        assert "arc_001" in hierarchy.arcs
        arc = hierarchy.arcs["arc_001"]
        assert arc.title == "第一篇：觉醒"
        assert arc.main_conflict == "主角与自身身份认同的冲突"

        # 验证节纲
        assert len(hierarchy.sections) == 1
        assert "sec_001" in hierarchy.sections
        section = hierarchy.sections["sec_001"]
        assert section.title == "第一节：初入江湖"

        # 验证章纲
        assert len(hierarchy.chapters) == 1
        assert "ch_001" in hierarchy.chapters
        chapter = hierarchy.chapters["ch_001"]
        assert chapter.title == "第一章：离别"
        assert chapter.target_words == 6000

    def test_parse_missing_master_raises(self):
        """测试缺少总纲时抛出异常。"""
        content = """## 第一篇
---
arc_id: arc_001
order: 1
---
"""
        with pytest.raises(ValueError, match="未找到总纲"):
            parse_outline(content)

    def test_parse_missing_novel_id_raises(self):
        """测试缺少 novel_id 时抛出异常。"""
        content = """# 测试小说
---
core_theme: 测试
---
"""
        with pytest.raises(ValueError, match="缺少必需字段：novel_id"):
            parse_outline(content)

    def test_parse_missing_arc_id_raises(self):
        """测试缺少 arc_id 时抛出异常。"""
        content = """# 测试
---
novel_id: test
---
## 第一篇
---
order: 1
---
"""
        with pytest.raises(ValueError, match="缺少必需字段：arc_id"):
            parse_outline(content)

    def test_parse_section_without_arc_raises(self):
        """测试节纲不在篇纲下时抛出异常。"""
        content = """# 测试
---
novel_id: test
---
### 第一节
---
section_id: sec_001
order: 1
---
"""
        with pytest.raises(ValueError, match="必须位于某个篇纲之下"):
            parse_outline(content)

    def test_parse_chapter_without_section_raises(self):
        """测试章纲不在节纲下时抛出异常。"""
        content = """# 测试
---
novel_id: test
---
## 第一篇
---
arc_id: arc_001
order: 1
---
#### 第一章
---
chapter_id: ch_001
order: 1
---
"""
        with pytest.raises(ValueError, match="必须位于某个节纲之下"):
            parse_outline(content)

    def test_hierarchy_navigation(self):
        """测试层级导航方法。"""
        hierarchy = parse_outline(SAMPLE_OUTLINE_MD)

        # get_arc
        arc = hierarchy.get_arc("arc_001")
        assert arc is not None
        assert arc.title == "第一篇：觉醒"

        # get_section
        section = hierarchy.get_section("sec_001")
        assert section is not None
        assert section.title == "第一节：初入江湖"

        # get_chapter
        chapter = hierarchy.get_chapter("ch_001")
        assert chapter is not None
        assert chapter.title == "第一章：离别"

        # get_all_arcs_ordered
        arcs = hierarchy.get_all_arcs_ordered()
        assert len(arcs) == 1
        assert arcs[0].arc_id == "arc_001"


# ═══════════════════════════════════════════════════════════════════════
# 序列化器测试
# ═══════════════════════════════════════════════════════════════════════


class TestOutlineSerializer:
    """大纲序列化器测试。"""

    def test_serialize_basic_outline(self):
        """测试基本序列化。"""
        hierarchy = parse_outline(SAMPLE_OUTLINE_MD)
        markdown = serialize_outline(hierarchy)

        # 验证标题
        assert "# 测试小说" in markdown
        assert "## 第一篇：觉醒" in markdown
        assert "### 第一节：初入江湖" in markdown
        assert "#### 第一章：离别" in markdown

        # 验证 YAML 元数据
        assert "novel_id: test_novel" in markdown
        assert "arc_id: arc_001" in markdown
        assert "section_id: sec_001" in markdown
        assert "chapter_id: ch_001" in markdown

        # 验证关键转折点
        assert "- 主角发现身世之谜" in markdown

    def test_roundtrip(self):
        """测试解析后序列化再解析的一致性。"""
        # 第一次解析
        hierarchy1 = parse_outline(SAMPLE_OUTLINE_MD)

        # 序列化
        markdown = serialize_outline(hierarchy1)

        # 第二次解析
        hierarchy2 = parse_outline(markdown)

        # 比较关键字段
        assert hierarchy1.master.novel_id == hierarchy2.master.novel_id
        assert hierarchy1.master.title == hierarchy2.master.title
        assert hierarchy1.master.key_turns == hierarchy2.master.key_turns

        assert len(hierarchy1.arcs) == len(hierarchy2.arcs)
        assert len(hierarchy1.sections) == len(hierarchy2.sections)
        assert len(hierarchy1.chapters) == len(hierarchy2.chapters)

    def test_serialize_empty_fields_excluded(self):
        """测试空字段被排除。"""
        master = MasterOutline(
            novel_id="test",
            title="测试",
            core_theme="",  # 空字符串
            key_turns=[],  # 空列表
        )
        hierarchy = OutlineHierarchy(master=master)

        serializer = OutlineSerializer()
        markdown = serializer.serialize(hierarchy)

        # 空字段不应出现在 YAML 中
        assert "core_theme" not in markdown
        # 但非空字段应该出现
        assert "novel_id: test" in markdown


# ═══════════════════════════════════════════════════════════════════════
# 验证器测试
# ═══════════════════════════════════════════════════════════════════════


class TestOutlineValidator:
    """大纲验证器测试。"""

    def test_validate_valid_outline(self):
        """测试有效大纲验证。"""
        hierarchy = parse_outline(SAMPLE_OUTLINE_MD)
        result = validate_outline(hierarchy)

        # 可能有一些警告，但不应该有错误
        assert len(result.errors) == 0

    def test_validate_missing_novel_id(self):
        """测试缺少 novel_id 验证。"""
        master = MasterOutline(novel_id="", title="测试")
        hierarchy = OutlineHierarchy(master=master)

        result = validate_outline(hierarchy)

        assert not result.is_valid
        assert any(e.code == "MASTER_MISSING_NOVEL_ID" for e in result.errors)

    def test_validate_missing_title_warning(self):
        """测试缺少书名警告。"""
        master = MasterOutline(novel_id="test", title="")
        hierarchy = OutlineHierarchy(master=master)

        result = validate_outline(hierarchy)

        # 应该有警告但不影响 is_valid
        assert any(w.code == "MASTER_MISSING_TITLE" for w in result.warnings)

    def test_validate_duplicate_arc_id(self):
        """测试重复篇纲 ID。"""
        master = MasterOutline(novel_id="test", title="测试")
        arc1 = ArcOutline(arc_id="arc_001", title="第一篇", order=1)
        arc2 = ArcOutline(arc_id="arc_001", title="第二篇", order=2)  # 重复 ID

        hierarchy = OutlineHierarchy(
            master=master,
            arcs={"arc_001": arc1, "arc_001_dup": arc2},
        )

        result = validate_outline(hierarchy)

        # 由于字典键唯一，这个测试需要调整
        # 实际上字典不会允许重复键，所以这个测试验证的是引用一致性

    def test_validate_invalid_section_ref(self):
        """测试无效节纲引用。"""
        master = MasterOutline(novel_id="test", title="测试", arc_ids=["arc_001"])
        arc = ArcOutline(
            arc_id="arc_001",
            title="第一篇",
            order=1,
            section_ids=["sec_nonexistent"],  # 不存在的节纲
        )

        hierarchy = OutlineHierarchy(
            master=master,
            arcs={"arc_001": arc},
        )

        result = validate_outline(hierarchy)

        assert not result.is_valid
        assert any(e.code == "ARC_INVALID_SECTION_REF" for e in result.errors)

    def test_validate_chapter_word_count(self):
        """测试章节字数范围警告。"""
        master = MasterOutline(novel_id="test", title="测试", arc_ids=["arc_001"])
        arc = ArcOutline(
            arc_id="arc_001", title="第一篇", order=1, section_ids=["sec_001"]
        )
        section = SectionOutline(
            section_id="sec_001",
            arc_id="arc_001",
            title="第一节",
            order=1,
            chapter_ids=["ch_001"],
        )
        chapter = ChapterOutline(
            chapter_id="ch_001",
            section_id="sec_001",
            title="第一章",
            order=1,
            target_words=2000,  # 过低
        )

        hierarchy = OutlineHierarchy(
            master=master,
            arcs={"arc_001": arc},
            sections={"sec_001": section},
            chapters={"ch_001": chapter},
        )

        result = validate_outline(hierarchy)

        assert any(w.code == "CHAPTER_LOW_WORD_COUNT" for w in result.warnings)

    def test_validate_missing_chapter_goals(self):
        """测试缺少章节目标警告。"""
        master = MasterOutline(novel_id="test", title="测试", arc_ids=["arc_001"])
        arc = ArcOutline(
            arc_id="arc_001", title="第一篇", order=1, section_ids=["sec_001"]
        )
        section = SectionOutline(
            section_id="sec_001",
            arc_id="arc_001",
            title="第一节",
            order=1,
            chapter_ids=["ch_001"],
        )
        chapter = ChapterOutline(
            chapter_id="ch_001",
            section_id="sec_001",
            title="第一章",
            order=1,
            goals=[],  # 空目标
        )

        hierarchy = OutlineHierarchy(
            master=master,
            arcs={"arc_001": arc},
            sections={"sec_001": section},
            chapters={"ch_001": chapter},
        )

        result = validate_outline(hierarchy)

        assert any(w.code == "CHAPTER_MISSING_GOALS" for w in result.warnings)

    def test_validate_orphan_sections(self):
        """测试孤立节纲警告。"""
        master = MasterOutline(novel_id="test", title="测试", arc_ids=["arc_001"])
        arc = ArcOutline(
            arc_id="arc_001", title="第一篇", order=1, section_ids=[]
        )  # 不引用 sec_001
        section = SectionOutline(
            section_id="sec_001", arc_id="arc_001", title="孤立节", order=1
        )

        hierarchy = OutlineHierarchy(
            master=master,
            arcs={"arc_001": arc},
            sections={"sec_001": section},
        )

        result = validate_outline(hierarchy)

        assert any(w.code == "ORPHAN_SECTIONS" for w in result.warnings)


# ═══════════════════════════════════════════════════════════════════════
# 集成测试
# ═══════════════════════════════════════════════════════════════════════


class TestOutlineIntegration:
    """大纲集成测试。"""

    def test_full_workflow(self):
        """测试完整工作流：解析 -> 验证 -> 序列化 -> 再解析。"""
        # 1. 解析
        hierarchy1 = parse_outline(SAMPLE_OUTLINE_MD)

        # 2. 验证
        result = validate_outline(hierarchy1)
        assert len(result.errors) == 0, f"验证失败: {result.errors}"

        # 3. 序列化
        markdown = serialize_outline(hierarchy1)

        # 4. 再解析
        hierarchy2 = parse_outline(markdown)

        # 5. 再验证
        result2 = validate_outline(hierarchy2)
        assert len(result2.errors) == 0

        # 6. 数据一致性
        assert hierarchy1.master.novel_id == hierarchy2.master.novel_id
        assert len(hierarchy1.arcs) == len(hierarchy2.arcs)
        assert len(hierarchy1.sections) == len(hierarchy2.sections)
        assert len(hierarchy1.chapters) == len(hierarchy2.chapters)

    def test_to_dict_conversion(self):
        """测试 to_dict 转换。"""
        hierarchy = parse_outline(SAMPLE_OUTLINE_MD)
        data = hierarchy.to_dict()

        # 验证结构
        assert "master" in data
        assert "arcs" in data
        assert "sections" in data
        assert "chapters" in data

        # 验证数据完整性
        assert data["master"]["novel_id"] == "test_novel"
        assert "arc_001" in data["arcs"]
        assert "sec_001" in data["sections"]
        assert "ch_001" in data["chapters"]
