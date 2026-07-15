"""WorldQuery 测试

覆盖世界观查询工具的核心功能：
- parse_entity() 解析各种 Markdown 格式
- _parse_relations() 边界情况
- list_entities() 列表与筛选
- get_entity() 获取单个实体
- get_relations_graph() 关系图谱汇总
"""

import sys
import subprocess
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.world_query import (
    parse_entity,
    _parse_relations,
    _normalize_section,
    list_entities,
    get_entity,
    get_relations_graph,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ── parse_entity ─────────────────────────────────────────────


class TestParseEntity:
    """解析单个 Markdown 实体文件"""

    def test_full_entity(self):
        entity = parse_entity(FIXTURES_DIR / "entity.md")
        assert entity["id"] == "entity"
        assert entity["name"] == "琅琊阁"
        assert entity["type"] == "组织"
        assert entity["subtype"] == "情报机构"
        assert entity["status"] == "active"
        assert "天下第一情报组织" in entity["description"]
        assert len(entity["rules"]) == 3
        assert len(entity["features"]) == 3
        assert len(entity["relations"]) == 3

    def test_minimal_entity(self):
        entity = parse_entity(FIXTURES_DIR / "entity_minimal.md")
        assert entity["name"] == "灵犀玉"
        assert entity["type"] == "物品"
        assert entity["subtype"] == "法器"
        assert entity["rules"] == []
        assert entity["relations"] == []

    def test_entity_without_blockquote(self):
        entity = parse_entity(FIXTURES_DIR / "entity_no_blockquote.md")
        assert entity["name"] == "无名之地"
        assert entity["type"] == ""  # 无 blockquote
        assert len(entity["features"]) == 2

    def test_entity_with_toml_front_matter(self, tmp_path):
        entity_path = tmp_path / "company.md"
        entity_path.write_text(
            """+++
id = "company"
name = "公司（互联网科技公司）"
type = "location"
subtype = "building"
status = "active"
summary = "陈明所在的互联网科技公司，是故事主要发生地。"
tags = ["公司", "都市", "主舞台"]
detail_refs = ["rules", "features", "relations"]

[[related]]
target = "chen_ming"
kind = "employee"
weight = 0.93
note = "主角所在公司"
+++

# 公司（互联网科技公司）

## rules
- 996工作制
- 有监控系统

## features
- 开放式工位

## relations
- zhao_lei — 同组同事
""",
            encoding="utf-8",
        )

        entity = parse_entity(entity_path)
        assert entity["id"] == "company"
        assert entity["name"] == "公司（互联网科技公司）"
        assert entity["type"] == "location"
        assert entity["subtype"] == "building"
        assert entity["status"] == "active"
        assert entity["description"] == "陈明所在的互联网科技公司，是故事主要发生地。"
        assert entity["tags"] == ["公司", "都市", "主舞台"]
        assert entity["detail_refs"] == ["rules", "features", "relations"]
        assert any(rel["target"] == "chen_ming" for rel in entity["relations"])
        assert any(rel["target"] == "zhao_lei" for rel in entity["relations"])

    def test_partial_front_matter_still_reads_legacy_blockquote(self, tmp_path):
        entity_path = tmp_path / "company.md"
        entity_path.write_text(
            """+++
id = "company"
name = "公司"
type = "location"
+++

# 公司

> location | building | active

故事主要发生地。
""",
            encoding="utf-8",
        )

        entity = parse_entity(entity_path)

        assert entity["type"] == "location"
        assert entity["subtype"] == "building"
        assert entity["status"] == "active"
        assert entity["description"] == "故事主要发生地。"


# ── _parse_relations ─────────────────────────────────────────


class TestParseRelations:
    """关联列表解析测试"""

    def test_em_dash_separator(self):
        items = ["张三 — 现任阁主"]
        result = _parse_relations(items)
        assert len(result) == 1
        assert result[0]["target"] == "张三"
        assert result[0]["description"] == "现任阁主"

    def test_hyphen_separator(self):
        items = ["李四 - 敌对关系"]
        result = _parse_relations(items)
        assert result[0]["target"] == "李四"
        assert result[0]["description"] == "敌对关系"

    def test_en_dash_separator(self):
        items = ["王五 – 盟友"]
        result = _parse_relations(items)
        assert result[0]["target"] == "王五"

    def test_no_separator(self):
        items = ["神秘实体"]
        result = _parse_relations(items)
        assert result[0]["target"] == "神秘实体"
        assert result[0]["description"] == ""

    def test_empty_list(self):
        assert _parse_relations([]) == []

    def test_multiple_items(self):
        items = ["A — 关系1", "B — 关系2", "C"]
        result = _parse_relations(items)
        assert len(result) == 3


# ── _normalize_section ───────────────────────────────────────


class TestNormalizeSection:
    def test_known_sections(self):
        assert _normalize_section("规则") == "rules"
        assert _normalize_section("特征") == "features"
        assert _normalize_section("关联") == "relations"

    def test_unknown_section(self):
        assert _normalize_section("其他") == ""
        assert _normalize_section("历史") == ""


# ── list_entities ────────────────────────────────────────────


class TestListEntities:
    """列出实体摘要"""

    @pytest.fixture
    def entity_project(self, tmp_path):
        """创建包含实体文件的项目"""
        entities_dir = tmp_path / "data" / "novels" / "test" / "src" / "world" / "entities"
        entities_dir.mkdir(parents=True)

        (entities_dir / "place_a.md").write_text(
            "# 山海城\n\n> 地点 | 城市 | active\n\n繁华的贸易都市。\n",
            encoding="utf-8",
        )
        (entities_dir / "org_b.md").write_text(
            "# 天山派\n\n> 组织 | 门派 | active\n\n修仙门派。\n",
            encoding="utf-8",
        )
        return tmp_path

    def test_list_all(self, entity_project):
        result = list_entities("test", project_root=entity_project)
        assert len(result) == 2
        names = {e["name"] for e in result}
        assert "山海城" in names
        assert "天山派" in names

    def test_list_by_type(self, entity_project):
        result = list_entities("test", entity_type="组织", project_root=entity_project)
        assert len(result) == 1
        assert result[0]["name"] == "天山派"


def test_world_query_supports_direct_script_execution(tmp_path: Path):
    repo_root = Path(__file__).parent.parent
    script = repo_root / "tools" / "world_query.py"
    entity_path = (
        tmp_path
        / "data"
        / "novels"
        / "script_test"
        / "src"
        / "world"
        / "entities"
        / "company.md"
    )
    entity_path.parent.mkdir(parents=True)
    entity_path.write_text(
        "# 公司（互联网科技公司）\n\n> 地点 | 建筑 | active\n\n故事主要发生地。\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "script_test",
            "company",
            "--project-root",
            str(tmp_path),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "公司（互联网科技公司）" in result.stdout

    def test_list_empty_dir(self, tmp_path):
        entities_dir = tmp_path / "data" / "novels" / "empty" / "src" / "world" / "entities"
        entities_dir.mkdir(parents=True)
        result = list_entities("empty", project_root=tmp_path)
        assert result == []

    def test_list_nonexistent_dir(self, tmp_path):
        result = list_entities("nonexistent", project_root=tmp_path)
        assert result == []

    def test_description_truncation(self, entity_project):
        result = list_entities("test", project_root=entity_project)
        for e in result:
            assert len(e["description"]) <= 63  # 60 + "..."

    def test_list_entities_from_front_matter_summary(self, tmp_path):
        entities_dir = tmp_path / "data" / "novels" / "test" / "src" / "world" / "entities"
        entities_dir.mkdir(parents=True)
        (entities_dir / "company.md").write_text(
            """+++
id = "company"
name = "公司"
type = "location"
subtype = "building"
status = "active"
summary = "陈明所在的互联网科技公司，是故事主要发生地。"
+++

# 公司
""",
            encoding="utf-8",
        )

        result = list_entities("test", project_root=tmp_path)
        assert len(result) == 1
        assert result[0]["name"] == "公司"
        assert result[0]["type"] == "location"
        assert result[0]["description"] == "陈明所在的互联网科技公司，是故事主要发生地。"


# ── get_entity ───────────────────────────────────────────────


class TestGetEntity:
    """获取单个实体详情"""

    @pytest.fixture
    def entity_project(self, tmp_path):
        entities_dir = tmp_path / "data" / "novels" / "test" / "src" / "world" / "entities"
        entities_dir.mkdir(parents=True)
        (entities_dir / "item_x.md").write_text(
            "# 天命之剑\n\n> 物品 | 武器 | active\n\n传说中的神兵。\n\n## 规则\n\n- 只有天命之人能拔出\n",
            encoding="utf-8",
        )
        return tmp_path

    def test_get_existing_entity(self, entity_project):
        entity = get_entity("test", "item_x", project_root=entity_project)
        assert entity is not None
        assert entity["name"] == "天命之剑"
        assert entity["type"] == "物品"
        assert len(entity["rules"]) == 1

    def test_get_nonexistent_entity(self, entity_project):
        assert get_entity("test", "nope", project_root=entity_project) is None


# ── get_relations_graph ──────────────────────────────────────


class TestGetRelationsGraph:
    """关系图谱汇总测试"""

    @pytest.fixture
    def relation_project(self, tmp_path):
        entities_dir = tmp_path / "data" / "novels" / "test" / "src" / "world" / "entities"
        entities_dir.mkdir(parents=True)

        (entities_dir / "a.md").write_text(
            "# 实体A\n\n> 概念 | | active\n\n描述A\n\n## 关联\n\n- b — 依赖\n",
            encoding="utf-8",
        )
        (entities_dir / "b.md").write_text(
            "# 实体B\n\n> 概念 | | active\n\n描述B\n\n## 关联\n\n- a — 被依赖\n",
            encoding="utf-8",
        )
        return tmp_path

    def test_graph_structure(self, relation_project):
        graph = get_relations_graph("test", project_root=relation_project)
        assert "a" in graph["entities"]
        assert "b" in graph["entities"]
        assert len(graph["relations"]) == 2

    def test_graph_empty_dir(self, tmp_path):
        graph = get_relations_graph("nonexistent", project_root=tmp_path)
        assert graph == {"entities": [], "relations": []}

    def test_relation_details(self, relation_project):
        graph = get_relations_graph("test", project_root=relation_project)
        a_to_b = [r for r in graph["relations"] if r["source"] == "a" and r["target"] == "b"]
        assert len(a_to_b) == 1
        assert a_to_b[0]["description"] == "依赖"

    def test_graph_supports_front_matter_related_entries(self, tmp_path):
        entities_dir = tmp_path / "data" / "novels" / "test" / "src" / "world" / "entities"
        entities_dir.mkdir(parents=True)
        (entities_dir / "company.md").write_text(
            """+++
id = "company"
name = "公司"
type = "location"
subtype = "building"
status = "active"
summary = "主舞台"

[[related]]
target = "chen_ming"
kind = "employee"
weight = 0.91
note = "主角所在公司"
+++

# 公司
""",
            encoding="utf-8",
        )

        graph = get_relations_graph("test", project_root=tmp_path)
        assert graph["entities"] == ["company"]
        assert graph["relations"][0]["target"] == "chen_ming"
        assert graph["relations"][0]["description"] == "主角所在公司"

    def test_graph_deduplicates_front_matter_and_section_relations(self, tmp_path):
        entities_dir = tmp_path / "data" / "novels" / "test" / "src" / "world" / "entities"
        entities_dir.mkdir(parents=True)
        (entities_dir / "company.md").write_text(
            """+++
id = "company"
name = "公司"
type = "location"
subtype = "building"

[[related]]
target = "chen_ming"
kind = "employee"
note = "主角所在公司"
+++

# 公司

## 关联
- chen_ming — 主角所在公司
""",
            encoding="utf-8",
        )

        graph = get_relations_graph("test", project_root=tmp_path)

        assert len(graph["relations"]) == 1
        assert graph["relations"][0] == {
            "source": "company",
            "target": "chen_ming",
            "description": "主角所在公司",
        }
