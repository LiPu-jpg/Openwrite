"""OpenWrite Skill 单元测试

覆盖核心工具的关键功能。
"""

import sys
import tempfile
from pathlib import Path

import pytest

# 确保 models/ 和 tools/ 可导入
sys.path.insert(0, str(Path(__file__).parent.parent))

from models.outline import OutlineNode, OutlineNodeType, OutlineHierarchy
from models.foreshadowing import ForeshadowingNode, ForeshadowingEdge, ForeshadowingGraph
from models.character import CharacterCard, CharacterProfile, CharacterTier
from models.context_package import GenerationContext
from tools.outline_parser import OutlineMdParser
from tools.outline_serializer import OutlineMdSerializer
from tools.foreshadowing_manager import ForeshadowingDAGManager


# ── Models ───────────────────────────────────────────────────


class TestOutlineNode:
    """OutlineNode 模型测试"""

    def test_default_fields(self):
        node = OutlineNode(
            node_id="ch_001",
            node_type=OutlineNodeType.CHAPTER,
            title="第一章",
        )
        assert node.node_id == "ch_001"
        assert node.node_type == OutlineNodeType.CHAPTER
        assert node.emotional_arc == ""
        assert node.beats == []
        assert node.hooks == []

    def test_emotion_arc_alias(self):
        """emotion_arc 属性应该是 emotional_arc 的别名"""
        node = OutlineNode(
            node_id="ch_001",
            node_type=OutlineNodeType.CHAPTER,
            title="第一章",
            emotional_arc="平静 → 惊讶",
        )
        assert node.emotional_arc == "平静 → 惊讶"
        assert node.emotion_arc == "平静 → 惊讶"

    def test_hierarchy_get_node(self):
        master = OutlineNode(
            node_id="master", node_type=OutlineNodeType.MASTER, title="总纲"
        )
        ch = OutlineNode(
            node_id="ch_001", node_type=OutlineNodeType.CHAPTER, title="第一章"
        )
        h = OutlineHierarchy(novel_id="test", master=master, chapters=[ch])
        assert h.get_node("master") == master
        assert h.get_node("ch_001") == ch
        assert h.get_node("nonexistent") is None


class TestForeshadowingModels:
    def test_node_defaults(self):
        node = ForeshadowingNode(
            id="f001",
            content="测试伏笔",
            weight=5,
            layer="支线",
            status="埋伏",
            created_at="ch_001",
        )
        assert node.weight == 5
        assert node.status == "埋伏"
        assert node.layer == "支线"

    def test_graph_empty(self):
        g = ForeshadowingGraph()
        assert g.nodes == {}
        assert g.edges == []
        assert g.status == {}


# ── OutlineParser ────────────────────────────────────────────


class TestOutlineParser:
    """大纲 Markdown 解析测试"""

    @pytest.fixture
    def parser(self):
        return OutlineMdParser()

    def test_parse_minimal(self, parser):
        md = "# 我的小说\n"
        h = parser.parse(md, "test")
        assert h.novel_id == "test"
        assert h.master is not None
        assert h.master.title == "我的小说"
        assert h.master.node_type == OutlineNodeType.MASTER

    def test_parse_full_hierarchy(self, parser):
        md = """# 雾城来信

> 核心主题: 成长与选择
> 目标字数: 2000000

## 第一篇：觉醒篇

主角从平静日常遭遇异常，在震惊后接受觉醒事实并主动进入术界。

### 第一节：初入术界

> 目的: 展示觉醒过程
> 涉及人物: 林岑, 周岚

#### 第一章：平凡的早晨

> 预估字数: 6000
> 情感弧线: 平静 → 惊讶

**节拍:**
1. 日常起床
2. 路上异常
3. 第一次使用能力

**悬念:**
- 神秘人窥视
"""
        h = parser.parse(md, "test")

        # 总纲
        assert h.master.title == "雾城来信"
        assert h.master.core_theme == "成长与选择"
        assert h.master.word_count_target == 2000000

        # 篇纲
        assert len(h.arcs) == 1
        assert h.arcs[0].title == "第一篇：觉醒篇"
        assert h.arcs[0].summary == "主角从平静日常遭遇异常，在震惊后接受觉醒事实并主动进入术界。"

        # 节纲
        assert len(h.sections) == 1
        assert h.sections[0].purpose == "展示觉醒过程"
        assert h.sections[0].involved_characters == ["林岑", "周岚"]

        # 章纲
        assert len(h.chapters) == 1
        ch = h.chapters[0]
        assert ch.estimated_words == 6000
        assert ch.emotional_arc == "平静 → 惊讶"
        assert len(ch.beats) == 3
        assert len(ch.hooks) == 1
        assert "神秘人窥视" in ch.hooks[0]

    def test_parse_key_turns(self, parser):
        md = """# 测试小说

## 关键转折点

- 第10章：主角觉醒
- 第50章：加入组织

## 第一篇
"""
        h = parser.parse(md, "test")
        assert h.master is not None
        assert "第10章：主角觉醒" in h.master.key_turns
        assert "第50章：加入组织" in h.master.key_turns
        assert len(h.arcs) == 1

    def test_parse_master_story_intro_body(self, parser):
        md = """# 测试小说

> 核心主题: 成长与选择
> 世界前提: 现代都市隐藏着异常

这是一个普通程序员在公司与异常世界夹缝求生的故事。

他最开始只想保住工作，后来却被迫介入更大的秘密。

## 第一篇：觉醒篇
"""
        h = parser.parse(md, "test")

        assert h.master is not None
        assert "普通程序员" in h.master.summary
        assert "被迫介入更大的秘密" in h.master.summary

    def test_parse_chapter_range(self):
        result = OutlineMdParser._parse_chapter_range("ch_001 - ch_003")
        assert result == ["ch_001", "ch_002", "ch_003"]

    def test_parse_chapter_range_comma(self):
        result = OutlineMdParser._parse_chapter_range("ch_001, ch_003, ch_005")
        assert result == ["ch_001", "ch_003", "ch_005"]

    def test_parse_chapter_range_empty(self):
        assert OutlineMdParser._parse_chapter_range("") == []

    def test_parent_child_linking(self, parser):
        md = """# 总纲
## 第一篇
### 第一节
#### 第一章
#### 第二章
"""
        h = parser.parse(md, "test")
        assert "arc_001" in h.master.children_ids
        assert "sec_001" in h.arcs[0].children_ids
        assert "ch_001" in h.sections[0].children_ids
        assert "ch_002" in h.sections[0].children_ids


# ── OutlineSerializer ────────────────────────────────────────


class TestOutlineSerializer:
    """解析 → 序列化 → 再解析 的往返测试"""

    def test_roundtrip(self):
        md = """# 测试小说

> 核心主题: 测试主题
> 基调: 轻松

这是一个普通人在异常世界里慢慢成长的故事。

## 第一篇

主角确认异常正在扩散，并决定主动追查源头。

### 第一节

> 目的: 开篇

主角在平静日常中发现异常，并决定追查线索。

#### 第一章

主角目睹异常显形，并决定先保护现场再追查来源。

> 预估字数: 5000
> 情感弧线: 平静 → 紧张
"""
        parser = OutlineMdParser()
        serializer = OutlineMdSerializer()

        h1 = parser.parse(md, "test")
        md2 = serializer.serialize(h1)
        h2 = parser.parse(md2, "test")

        # 核心结构应一致
        assert h2.master.title == h1.master.title
        assert h2.master.core_theme == h1.master.core_theme
        assert h2.master.summary == h1.master.summary
        assert len(h2.arcs) == len(h1.arcs)
        assert h2.arcs[0].summary == h1.arcs[0].summary
        assert len(h2.sections) == len(h1.sections)
        assert h2.sections[0].summary == h1.sections[0].summary
        assert len(h2.chapters) == len(h1.chapters)
        assert h2.chapters[0].summary == h1.chapters[0].summary
        assert h2.chapters[0].emotional_arc == h1.chapters[0].emotional_arc
        assert "# 测试小说\n\n这是一个普通人在异常世界里慢慢成长的故事。" in md2
        assert "## 第一篇\n\n主角确认异常正在扩散，并决定主动追查源头。" in md2
        assert "### 第一节\n\n主角在平静日常中发现异常，并决定追查线索。" in md2
        assert "#### 第一章\n\n主角目睹异常显形，并决定先保护现场再追查来源。" in md2


# ── ForeshadowingDAGManager ─────────────────────────────────


class TestForeshadowingDAGManager:
    """伏笔 DAG 管理器测试"""

    @pytest.fixture
    def manager(self, tmp_path):
        """在临时目录创建 manager"""
        # 建立最小项目结构
        data_dir = tmp_path / "data" / "novels" / "test_novel"
        (data_dir / "foreshadowing").mkdir(parents=True)
        (tmp_path / "tools").mkdir(parents=True)
        return ForeshadowingDAGManager(
            project_dir=tmp_path, novel_id="test_novel"
        )

    def test_create_node(self, manager):
        ok = manager.create_node(
            node_id="f001",
            content="神秘玉佩",
            weight=9,
            layer="主线",
            created_at="ch_001",
        )
        assert ok is True

        node = manager.get_node("f001")
        assert node is not None
        assert node.content == "神秘玉佩"
        assert node.weight == 9
        assert node.layer == "主线"

    def test_create_duplicate_node(self, manager):
        manager.create_node(node_id="f001", content="测试")
        ok = manager.create_node(node_id="f001", content="重复")
        assert ok is False

    def test_update_node_status(self, manager):
        manager.create_node(node_id="f001", content="测试")
        ok = manager.update_node_status("f001", "已收")
        assert ok is True

        node = manager.get_node("f001")
        assert node.status == "已收"

    def test_delete_node(self, manager):
        manager.create_node(node_id="f001", content="测试")
        ok = manager.delete_node("f001")
        assert ok is True
        assert manager.get_node("f001") is None

    def test_delete_nonexistent(self, manager):
        assert manager.delete_node("nope") is False

    def test_create_edge(self, manager):
        manager.create_node(node_id="f001", content="伏笔A")
        manager.create_node(node_id="f002", content="伏笔B")
        ok = manager.create_edge("f001", "f002", "依赖")
        assert ok is True

    def test_create_edge_nonexistent_source(self, manager):
        assert manager.create_edge("nope", "any", "依赖") is False

    def test_create_duplicate_edge(self, manager):
        manager.create_node(node_id="f001", content="伏笔A")
        manager.create_edge("f001", "ch_010", "依赖")
        ok = manager.create_edge("f001", "ch_010", "依赖")
        assert ok is False

    def test_get_pending_nodes(self, manager):
        manager.create_node(node_id="f001", content="A", weight=3, layer="支线")
        manager.create_node(node_id="f002", content="B", weight=8, layer="主线")
        manager.create_node(node_id="f003", content="C", weight=6, layer="主线")
        manager.update_node_status("f003", "已收")

        pending = manager.get_pending_nodes(min_weight=5)
        assert len(pending) == 1
        assert pending[0].id == "f002"

    def test_get_pending_with_layer_filter(self, manager):
        manager.create_node(node_id="f001", content="A", weight=5, layer="支线")
        manager.create_node(node_id="f002", content="B", weight=5, layer="主线")

        pending = manager.get_pending_nodes(layer="主线")
        assert len(pending) == 1
        assert pending[0].id == "f002"

    def test_get_nodes_for_chapter(self, manager):
        manager.create_node(
            node_id="f001", content="埋伏", created_at="ch_001"
        )
        manager.create_node(
            node_id="f002", content="回收", target_chapter="ch_001"
        )
        manager.create_node(
            node_id="f003", content="无关", created_at="ch_002"
        )

        nodes = manager.get_nodes_for_chapter("ch_001")
        node_ids = {n.id for n in nodes}
        assert "f001" in node_ids
        assert "f002" in node_ids
        assert "f003" not in node_ids

    def test_validate_dag_valid(self, manager):
        manager.create_node(node_id="f001", content="A")
        manager.create_node(node_id="f002", content="B")
        manager.create_edge("f001", "f002")

        is_valid, errors = manager.validate_dag()
        assert is_valid is True
        assert errors == []

    def test_validate_dag_missing_source(self, manager):
        """边引用不存在的源节点应报错"""
        manager.create_node(node_id="f001", content="A")
        # 手动注入一个无效边
        dag = manager._load_dag()
        dag.edges.append(ForeshadowingEdge(from_="ghost", to="f001", type="依赖"))
        manager._save_dag(dag)

        is_valid, errors = manager.validate_dag()
        assert is_valid is False
        assert any("ghost" in e for e in errors)

    def test_validate_dag_flags_overdue_foreshadowing(self, manager, tmp_path):
        manager.create_node(
            node_id="f_overdue",
            content="应在 ch_002 回收",
            created_at="ch_001",
            target_chapter="ch_002",
        )
        manager.update_node_status("f_overdue", "埋伏")
        (tmp_path / "novel_config.yaml").write_text(
            "novel_id: test_novel\ncurrent_chapter: ch_005\n",
            encoding="utf-8",
        )
        manuscript = (
            tmp_path / "data" / "novels" / "test_novel" / "data" / "manuscript" / "arc_001"
        )
        manuscript.mkdir(parents=True, exist_ok=True)
        (manuscript / "ch_005.md").write_text("# 第五章\n\n正文", encoding="utf-8")

        is_valid, errors = manager.validate_dag()
        assert is_valid is False
        assert any("超期未回收" in error and "f_overdue" in error for error in errors)

    def test_statistics(self, manager):
        manager.create_node(node_id="f001", content="A", weight=3, layer="支线")
        manager.create_node(node_id="f002", content="B", weight=8, layer="主线")
        manager.update_node_status("f001", "已收")

        stats = manager.get_statistics()
        assert stats["total"] == 2
        assert stats["by_layer"]["支线"] == 1
        assert stats["by_layer"]["主线"] == 1

    def test_dag_yaml_persistence(self, manager):
        """验证 DAG 以 YAML 格式持久化"""
        manager.create_node(node_id="f001", content="持久化测试")

        # 直接读取文件内容，验证是 YAML 不是 JSON
        raw = manager.dag_file.read_text(encoding="utf-8")
        assert "{" not in raw or "nodes:" in raw  # YAML 格式
        assert "f001" in raw


# ── ContextBuilder token estimation ─────────────────────────


class TestTokenEstimation:
    """token 估算测试"""

    def test_chinese_text(self):
        from tools.context_builder import ContextBuilder
        cb = ContextBuilder.__new__(ContextBuilder)  # 绕过 __init__
        tokens = cb._estimate_tokens("你好世界")
        # 4 个中文字 × 1.5 = 6
        assert tokens == 6

    def test_english_text(self):
        from tools.context_builder import ContextBuilder
        cb = ContextBuilder.__new__(ContextBuilder)
        tokens = cb._estimate_tokens("hello world")
        # 11 字符 × 0.25 = 2.75 → 2
        assert tokens == 2

    def test_mixed_text(self):
        from tools.context_builder import ContextBuilder
        cb = ContextBuilder.__new__(ContextBuilder)
        tokens = cb._estimate_tokens("你好 hello")
        # 2 中文 × 1.5 + 7 非中文 × 0.25 = 3 + 1.75 = 4.75 → 4
        assert tokens == 4

    def test_empty_text(self):
        from tools.context_builder import ContextBuilder
        cb = ContextBuilder.__new__(ContextBuilder)
        assert cb._estimate_tokens("") == 0
