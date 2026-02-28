"""Tests for Phase 6 skills: character, world, foreshadowing."""

import pytest
from pathlib import Path
import tempfile
import yaml

from skills.character.tools import CharacterQuery
from skills.world.tools import WorldQuery
from skills.foreshadowing.tools import ForeshadowingQuery
from skills.skill_loader import SkillLoader
from skills.skill_registry import SkillRegistry


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def temp_project():
    """创建临时项目目录。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_root = Path(tmpdir)

        # 创建目录结构
        (
            project_root
            / "data"
            / "novels"
            / "test_novel"
            / "characters"
            / "text_profiles"
        ).mkdir(parents=True)
        (project_root / "data" / "novels" / "test_novel" / "world").mkdir(parents=True)
        (project_root / "data" / "novels" / "test_novel" / "foreshadowing").mkdir(
            parents=True
        )
        (project_root / "skills").mkdir(parents=True)
        (project_root / "tools").mkdir(parents=True)

        yield project_root


@pytest.fixture
def sample_character(temp_project):
    """创建示例角色。"""
    char_file = (
        temp_project
        / "data"
        / "novels"
        / "test_novel"
        / "characters"
        / "text_profiles"
        / "char_001.yaml"
    )
    char_data = {
        "id": "char_001",
        "name": "李逍遥",
        "char_type": "主角",
        "appearance": "剑眉星目，身材修长",
        "personality_and_voice": "性格开朗，说话直爽",
        "skills_and_abilities": "蜀山剑法，御剑术",
        "items": "七星剑，灵珠",
        "attributes": "境界：金丹期，阵营：蜀山",
    }
    with char_file.open("w", encoding="utf-8") as f:
        yaml.dump(char_data, f, allow_unicode=True)
    return char_data


@pytest.fixture
def sample_world(temp_project):
    """创建示例世界观。"""
    world_file = (
        temp_project / "data" / "novels" / "test_novel" / "world" / "graph.yaml"
    )
    world_data = {
        "entities": {
            "shushan": {
                "name": "蜀山",
                "type": "location",
                "description": "修仙门派所在地",
            },
            "miao_jiang": {
                "name": "苗疆",
                "type": "location",
                "description": "神秘之地",
            },
        },
        "edges": [
            {"from": "shushan", "to": "miao_jiang", "type": "opposes"},
        ],
    }
    with world_file.open("w", encoding="utf-8") as f:
        yaml.dump(world_data, f, allow_unicode=True)
    return world_data


@pytest.fixture
def sample_foreshadowing(temp_project):
    """创建示例伏笔。"""
    fs_file = (
        temp_project / "data" / "novels" / "test_novel" / "foreshadowing" / "dag.yaml"
    )
    fs_data = {
        "nodes": {
            "f001": {
                "content": "主角发现父亲留下的神秘玉佩",
                "weight": 9,
                "layer": "主线",
                "target_chapter": "ch_015",
                "tags": ["人物相关", "道具相关"],
            },
            "f002": {
                "content": "路边老人的预言",
                "weight": 5,
                "layer": "支线",
                "target_chapter": "ch_010",
                "tags": ["预言"],
            },
        },
        "status": {
            "f001": "埋伏",
            "f002": "待收",
        },
        "edges": [],
    }
    with fs_file.open("w", encoding="utf-8") as f:
        yaml.dump(fs_data, f, allow_unicode=True)
    return fs_data


# ============================================================
# CharacterQuery Tests
# ============================================================


class TestCharacterQuery:
    """CharacterQuery 测试。"""

    def test_list_characters(self, temp_project, sample_character):
        """测试列出角色。"""
        query = CharacterQuery(project_dir=temp_project, novel_id="test_novel")
        characters = query.list_characters()

        assert len(characters) == 1
        assert characters[0].name == "李逍遥"
        assert characters[0].tier == "主角"

    def test_list_characters_by_tier(self, temp_project, sample_character):
        """测试按层级过滤角色。"""
        query = CharacterQuery(project_dir=temp_project, novel_id="test_novel")

        # 过滤主角
        characters = query.list_characters(tier="主角")
        assert len(characters) == 1

        # 过滤配角
        characters = query.list_characters(tier="配角")
        assert len(characters) == 0

    def test_get_current_state(self, temp_project, sample_character):
        """测试获取角色状态。"""
        query = CharacterQuery(project_dir=temp_project, novel_id="test_novel")
        state = query.get_current_state("李逍遥")

        assert "error" not in state
        assert state["name"] == "李逍遥"

    def test_get_character_context(self, temp_project, sample_character):
        """测试获取角色上下文。"""
        query = CharacterQuery(project_dir=temp_project, novel_id="test_novel")
        context = query.get_character_context("李逍遥")

        assert "李逍遥" in context
        assert "主角" in context


# ============================================================
# WorldQuery Tests
# ============================================================


class TestWorldQuery:
    """WorldQuery 测试。"""

    def test_list_entities(self, temp_project, sample_world):
        """测试列出实体。"""
        query = WorldQuery(project_dir=temp_project, novel_id="test_novel")
        entities = query.list_entities()

        assert len(entities) == 2
        names = [e.name for e in entities]
        assert "蜀山" in names
        assert "苗疆" in names

    def test_list_entities_by_type(self, temp_project, sample_world):
        """测试按类型过滤实体。"""
        query = WorldQuery(project_dir=temp_project, novel_id="test_novel")
        entities = query.list_entities(entity_type="location")

        assert len(entities) == 2

    def test_get_entity(self, temp_project, sample_world):
        """测试获取实体。"""
        query = WorldQuery(project_dir=temp_project, novel_id="test_novel")
        result = query.get_entity("shushan")

        assert "error" not in result
        assert result["entity"]["name"] == "蜀山"

    def test_get_relationships(self, temp_project, sample_world):
        """测试获取关系。"""
        query = WorldQuery(project_dir=temp_project, novel_id="test_novel")
        relationships = query.get_relationships()

        assert len(relationships) == 1
        assert relationships[0].from_entity == "shushan"
        assert relationships[0].to_entity == "miao_jiang"

    def test_check_conflicts(self, temp_project, sample_world):
        """测试冲突检查。"""
        query = WorldQuery(project_dir=temp_project, novel_id="test_novel")
        conflicts = query.check_conflicts()

        # 没有冲突
        assert len(conflicts) == 0

    def test_get_world_summary(self, temp_project, sample_world):
        """测试世界观摘要。"""
        query = WorldQuery(project_dir=temp_project, novel_id="test_novel")
        summary = query.get_world_summary()

        assert "蜀山" in summary
        assert "苗疆" in summary


# ============================================================
# ForeshadowingQuery Tests
# ============================================================


class TestForeshadowingQuery:
    """ForeshadowingQuery 测试。"""

    def test_get_node(self, temp_project, sample_foreshadowing):
        """测试获取伏笔节点。"""
        query = ForeshadowingQuery(project_dir=temp_project, novel_id="test_novel")
        result = query.get_node("f001")

        assert "error" not in result
        assert "玉佩" in result["node"]["content"]

    def test_get_pending_nodes(self, temp_project, sample_foreshadowing):
        """测试获取待回收伏笔。"""
        query = ForeshadowingQuery(project_dir=temp_project, novel_id="test_novel")
        pending = query.get_pending_nodes()

        assert len(pending) == 2
        # 按权重排序
        assert pending[0].weight >= pending[1].weight

    def test_get_pending_nodes_min_weight(self, temp_project, sample_foreshadowing):
        """测试按权重过滤伏笔。"""
        query = ForeshadowingQuery(project_dir=temp_project, novel_id="test_novel")
        pending = query.get_pending_nodes(min_weight=7)

        assert len(pending) == 1
        assert pending[0].id == "f001"

    def test_get_statistics(self, temp_project, sample_foreshadowing):
        """测试获取伏笔统计。"""
        query = ForeshadowingQuery(project_dir=temp_project, novel_id="test_novel")
        stats = query.get_statistics()

        assert stats["total_nodes"] == 2
        assert stats["total_edges"] == 0
        assert "埋伏" in stats["by_status"]
        assert "待收" in stats["by_status"]

    def test_validate_dag(self, temp_project, sample_foreshadowing):
        """测试 DAG 验证。"""
        query = ForeshadowingQuery(project_dir=temp_project, novel_id="test_novel")
        result = query.validate_dag()

        assert result["is_valid"] is True
        assert len(result["errors"]) == 0

    def test_get_foreshadowing_summary(self, temp_project, sample_foreshadowing):
        """测试伏笔摘要。"""
        query = ForeshadowingQuery(project_dir=temp_project, novel_id="test_novel")
        summary = query.get_foreshadowing_summary()

        assert "伏笔摘要" in summary
        assert "总计" in summary


# ============================================================
# Skill Loader Tests
# ============================================================


class TestSkillLoaderPhase6:
    """Phase 6 Skill 加载测试。"""

    def test_load_all_phase6_skills(self):
        """测试加载所有 Phase 6 skills。"""
        # 使用当前工作目录（项目根目录）
        import os
        project_root = Path.cwd()

        loader = SkillLoader(project_root=project_root)
        registry = SkillRegistry()
        loader.load_all(registry=registry)

        # 检查所有 skills 都已加载
        skill_names = [s.name for s in registry.list_all()]

        # Phase 1-5 skills
        assert "outline" in skill_names
        assert "writing" in skill_names
        assert "style" in skill_names

        # Phase 6 skills
        assert "character" in skill_names
        assert "world" in skill_names
        assert "foreshadowing" in skill_names

    def test_match_character_trigger(self):
        # 使用当前工作目录（项目根目录）
        project_root = Path.cwd()

        loader = SkillLoader(project_root=project_root)
        registry = SkillRegistry()
        loader.load_all(registry=registry)

        # 测试触发器匹配
        skill = registry.match_trigger("创建角色")
        assert skill is not None
        assert skill.name == "character"

    def test_match_world_trigger(self):
        # 使用当前工作目录（项目根目录）
        project_root = Path.cwd()

        loader = SkillLoader(project_root=project_root)
        registry = SkillRegistry()
        loader.load_all(registry=registry)

        skill = registry.match_trigger("查询世界观")
        assert skill is not None
        assert skill.name == "world"

    def test_match_foreshadowing_trigger(self):
        # 使用当前工作目录（项目根目录）
        project_root = Path.cwd()

        loader = SkillLoader(project_root=project_root)
        registry = SkillRegistry()
        loader.load_all(registry=registry)

        skill = registry.match_trigger("待回收伏笔")
        assert skill is not None
        assert skill.name == "foreshadowing"
