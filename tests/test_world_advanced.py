"""Phase 7A 世界观高级功能测试 — 规则引擎、冲突检查、子图查询、实体抽取、渲染器。"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from tools.models.world import (
    EntityStateSnapshot,
    WorldEntity,
    WorldGraph,
    WorldRelation,
    WorldStateLog,
)
from tools.world_conflict_checker import ConflictItem, WorldConflictChecker
from tools.world_entity_extractor import (
    ExtractionResult,
    ExtractedEntity,
    WorldEntityExtractor,
)
from tools.world_graph_manager import WorldGraphManager
from tools.world_graph_renderer import render_world_graph_html
from tools.world_rule_engine import (
    RuleType,
    RuleViolation,
    Severity,
    WorldRule,
    WorldRuleEngine,
)


# ── helpers ──────────────────────────────────────────────────────────


def _make_graph() -> WorldGraph:
    """构建测试用世界观图谱。"""
    entities = {
        "张三": WorldEntity(
            id="张三",
            name="张三",
            type="character",
            attributes={"realm": "筑基", "location": "青云山"},
        ),
        "李四": WorldEntity(
            id="李四", name="李四", type="character", attributes={"realm": "炼气"}
        ),
        "青云山": WorldEntity(id="青云山", name="青云山", type="location"),
        "青云门": WorldEntity(
            id="青云门",
            name="青云门",
            type="organization",
            attributes={"alignment": "正道"},
        ),
        "魔道": WorldEntity(
            id="魔道",
            name="魔道",
            type="organization",
            attributes={"alignment": "魔道"},
        ),
        "飞剑": WorldEntity(id="飞剑", name="飞剑", type="item"),
    }
    relations = [
        WorldRelation(
            source_id="张三", target_id="青云门", relation="belongs_to", weight=5
        ),
        WorldRelation(
            source_id="张三", target_id="青云山", relation="located_at", weight=3
        ),
        WorldRelation(
            source_id="李四", target_id="青云门", relation="belongs_to", weight=3
        ),
        WorldRelation(source_id="张三", target_id="飞剑", relation="owns", weight=2),
        WorldRelation(
            source_id="张三",
            target_id="李四",
            relation="ally",
            weight=4,
            chapter_id="ch_001",
        ),
    ]
    snapshots = [
        EntityStateSnapshot(
            entity_id="张三",
            chapter_id="ch_001",
            attributes={"realm": "炼气", "location": "青云山"},
        ),
        EntityStateSnapshot(
            entity_id="张三",
            chapter_id="ch_002",
            attributes={"realm": "筑基", "location": "青云山"},
        ),
        EntityStateSnapshot(
            entity_id="张三",
            chapter_id="ch_003",
            attributes={"realm": "筑基", "location": "落霞谷"},
        ),
    ]
    return WorldGraph(
        entities=entities,
        relations=relations,
        state_log=WorldStateLog(snapshots=snapshots),
    )


# ══════════════════════════════════════════════════════════════════════
# 1. WorldRuleEngine
# ══════════════════════════════════════════════════════════════════════


class TestWorldRuleEngine:
    """规则推理引擎测试。"""

    def test_add_and_remove_rule(self):
        engine = WorldRuleEngine()
        rule = WorldRule(id="r1", rule_type=RuleType.UNIQUENESS, description="test")
        engine.add_rule(rule)
        assert len(engine.rules) == 1
        engine.remove_rule("r1")
        assert len(engine.rules) == 0

    def test_add_rule_dedup(self):
        engine = WorldRuleEngine()
        engine.add_rule(
            WorldRule(id="r1", rule_type=RuleType.UNIQUENESS, description="v1")
        )
        engine.add_rule(
            WorldRule(id="r1", rule_type=RuleType.UNIQUENESS, description="v2")
        )
        assert len(engine.rules) == 1
        assert engine.rules[0].description == "v2"

    def test_inheritance_violation(self):
        graph = _make_graph()
        engine = WorldRuleEngine()
        engine.add_rule(
            WorldRule(
                id="inherit_alignment",
                rule_type=RuleType.INHERITANCE,
                params={"relation": "belongs_to", "attributes": ["alignment"]},
            )
        )
        violations = engine.evaluate(graph)
        # 张三和李四 belongs_to 青云门，但没有 alignment 属性
        assert len(violations) >= 2
        assert all(v.rule_type == RuleType.INHERITANCE for v in violations)

    def test_mutual_exclusive_violation(self):
        graph = _make_graph()
        # 让张三同时属于青云门和魔道
        graph.relations.append(
            WorldRelation(
                source_id="张三", target_id="魔道", relation="belongs_to", weight=1
            )
        )
        engine = WorldRuleEngine()
        engine.add_rule(
            WorldRule(
                id="faction_exclusive",
                rule_type=RuleType.MUTUAL_EXCLUSIVE,
                params={"relation": "belongs_to", "groups": [["青云门", "魔道"]]},
            )
        )
        violations = engine.evaluate(graph)
        assert len(violations) == 1
        assert "互斥" in violations[0].message

    def test_required_relation(self):
        graph = _make_graph()
        engine = WorldRuleEngine()
        engine.add_rule(
            WorldRule(
                id="char_needs_location",
                rule_type=RuleType.REQUIRED_RELATION,
                params={"entity_type": "character", "relation": "located_at"},
            )
        )
        violations = engine.evaluate(graph)
        # 李四没有 located_at 关系
        assert any("李四" in v.message for v in violations)

    def test_attribute_constraint(self):
        graph = _make_graph()
        engine = WorldRuleEngine()
        engine.add_rule(
            WorldRule(
                id="char_needs_realm",
                rule_type=RuleType.ATTRIBUTE_CONSTRAINT,
                params={"entity_type": "character", "required_attributes": ["realm"]},
            )
        )
        violations = engine.evaluate(graph)
        # 所有 character 都有 realm → 无违规
        assert len(violations) == 0

    def test_attribute_constraint_pattern(self):
        graph = _make_graph()
        engine = WorldRuleEngine()
        engine.add_rule(
            WorldRule(
                id="realm_pattern",
                rule_type=RuleType.ATTRIBUTE_CONSTRAINT,
                severity=Severity.WARNING,
                params={
                    "entity_type": "character",
                    "required_attributes": [],
                    "pattern": {"realm": r"^(炼气|筑基|金丹)$"},
                },
            )
        )
        violations = engine.evaluate(graph)
        assert len(violations) == 0  # 炼气、筑基 都匹配

    def test_uniqueness_violation(self):
        graph = _make_graph()
        # 添加同名实体
        graph.entities["张三2"] = WorldEntity(id="张三2", name="张三", type="character")
        engine = WorldRuleEngine()
        engine.add_rule(
            WorldRule(
                id="unique_name",
                rule_type=RuleType.UNIQUENESS,
                params={"entity_type": "character", "attribute": "name"},
            )
        )
        violations = engine.evaluate(graph)
        assert len(violations) == 1
        assert "重复" in violations[0].message

    def test_cardinality_max(self):
        graph = _make_graph()
        engine = WorldRuleEngine()
        engine.add_rule(
            WorldRule(
                id="max_one_faction",
                rule_type=RuleType.CARDINALITY,
                params={
                    "entity_type": "character",
                    "relation": "belongs_to",
                    "direction": "outgoing",
                    "max": 1,
                },
            )
        )
        violations = engine.evaluate(graph)
        assert len(violations) == 0  # 张三和李四各只有一个 belongs_to

    def test_cardinality_min(self):
        graph = _make_graph()
        engine = WorldRuleEngine()
        engine.add_rule(
            WorldRule(
                id="min_one_member",
                rule_type=RuleType.CARDINALITY,
                params={
                    "entity_type": "organization",
                    "relation": "belongs_to",
                    "direction": "incoming",
                    "min": 1,
                },
            )
        )
        violations = engine.evaluate(graph)
        # 魔道没有 incoming belongs_to
        assert any("魔道" in v.message for v in violations)

    def test_evaluate_summary(self):
        graph = _make_graph()
        engine = WorldRuleEngine()
        engine.add_rule(
            WorldRule(
                id="r1",
                rule_type=RuleType.UNIQUENESS,
                params={"entity_type": "character", "attribute": "name"},
            )
        )
        summary = engine.evaluate_summary(graph)
        assert "total_rules" in summary
        assert "is_valid" in summary
        assert summary["total_rules"] == 1

    def test_load_save_yaml(self, tmp_path: Path):
        engine = WorldRuleEngine()
        engine.add_rule(
            WorldRule(id="r1", rule_type=RuleType.UNIQUENESS, description="唯一性")
        )
        engine.add_rule(
            WorldRule(
                id="r2", rule_type=RuleType.CARDINALITY, severity=Severity.WARNING
            )
        )
        yaml_path = tmp_path / "rules.yaml"
        engine.save_rules_to_yaml(yaml_path)
        assert yaml_path.exists()

        engine2 = WorldRuleEngine()
        loaded = engine2.load_rules_from_yaml(yaml_path)
        assert loaded == 2
        assert len(engine2.rules) == 2

    def test_disabled_rule_skipped(self):
        graph = _make_graph()
        graph.entities["张三2"] = WorldEntity(id="张三2", name="张三", type="character")
        engine = WorldRuleEngine()
        engine.add_rule(
            WorldRule(
                id="unique_name",
                rule_type=RuleType.UNIQUENESS,
                params={"entity_type": "character", "attribute": "name"},
                enabled=False,
            )
        )
        violations = engine.evaluate(graph)
        assert len(violations) == 0


# ══════════════════════════════════════════════════════════════════════
# 2. WorldConflictChecker
# ══════════════════════════════════════════════════════════════════════


class TestWorldConflictChecker:
    """跨章节冲突检查器测试。"""

    def test_no_conflicts_clean_graph(self):
        graph = _make_graph()
        checker = WorldConflictChecker()
        result = checker.check(graph)
        assert "is_valid" in result
        assert "statistics" in result

    def test_location_conflict(self):
        graph = _make_graph()
        # 张三在 ch_002 同时出现在两个位置
        graph.state_log.snapshots.append(
            EntityStateSnapshot(
                entity_id="张三",
                chapter_id="ch_002",
                attributes={"location": "落霞谷"},
            )
        )
        checker = WorldConflictChecker()
        result = checker.check(graph)
        location_errors = [
            c for c in result["conflicts"] if c.conflict_type == "location_conflict"
        ]
        assert len(location_errors) >= 1

    def test_relation_contradiction(self):
        graph = _make_graph()
        # 张三和李四在同一章节既是 ally 又是 enemy
        graph.relations.append(
            WorldRelation(
                source_id="张三",
                target_id="李四",
                relation="enemy",
                weight=3,
                chapter_id="ch_001",
            )
        )
        checker = WorldConflictChecker()
        result = checker.check(graph)
        contradictions = [
            c
            for c in result["conflicts"]
            if c.conflict_type == "relation_contradiction"
        ]
        assert len(contradictions) >= 1

    def test_orphan_reference(self):
        graph = _make_graph()
        graph.relations.append(
            WorldRelation(
                source_id="不存在的人", target_id="张三", relation="ally", weight=1
            )
        )
        checker = WorldConflictChecker()
        result = checker.check(graph)
        orphans = [
            c for c in result["conflicts"] if c.conflict_type == "orphan_reference"
        ]
        assert len(orphans) >= 1
        assert not result["is_valid"]

    def test_state_jump(self):
        graph = WorldGraph(
            entities={"张三": WorldEntity(id="张三", name="张三", type="character")},
            state_log=WorldStateLog(
                snapshots=[
                    EntityStateSnapshot(
                        entity_id="张三",
                        chapter_id="ch_001",
                        attributes={"power": "10"},
                    ),
                    EntityStateSnapshot(
                        entity_id="张三",
                        chapter_id="ch_002",
                        attributes={"power": "100"},
                    ),
                ]
            ),
        )
        checker = WorldConflictChecker()
        result = checker.check(graph)
        jumps = [c for c in result["conflicts"] if c.conflict_type == "state_jump"]
        assert len(jumps) >= 1

    def test_attribute_regression(self):
        graph = WorldGraph(
            entities={"张三": WorldEntity(id="张三", name="张三", type="character")},
            state_log=WorldStateLog(
                snapshots=[
                    EntityStateSnapshot(
                        entity_id="张三", chapter_id="ch_001", attributes={"level": "5"}
                    ),
                    EntityStateSnapshot(
                        entity_id="张三", chapter_id="ch_002", attributes={"level": "3"}
                    ),
                ]
            ),
        )
        checker = WorldConflictChecker()
        result = checker.check(graph)
        regressions = [
            c for c in result["conflicts"] if c.conflict_type == "attribute_regression"
        ]
        assert len(regressions) >= 1

    def test_auto_infer_chapters(self):
        graph = _make_graph()
        checker = WorldConflictChecker()
        result = checker.check(graph, chapters=None)
        assert result["statistics"]["chapters_checked"] >= 1


# ══════════════════════════════════════════════════════════════════════
# 3. Subgraph Queries (WorldGraphManager)
# ══════════════════════════════════════════════════════════════════════


class TestSubgraphQueries:
    """子图查询 API 测试。"""

    @pytest.fixture()
    def manager(self, tmp_path: Path) -> WorldGraphManager:
        mgr = WorldGraphManager(project_dir=tmp_path, novel_id="test_novel")
        mgr.upsert_entity(entity_id="张三", name="张三", entity_type="character")
        mgr.upsert_entity(entity_id="李四", name="李四", entity_type="character")
        mgr.upsert_entity(entity_id="青云山", name="青云山", entity_type="location")
        mgr.upsert_entity(entity_id="飞剑", name="飞剑", entity_type="item")
        mgr.add_relation(source_id="张三", target_id="青云山", relation="located_at")
        mgr.add_relation(source_id="张三", target_id="李四", relation="ally")
        mgr.add_relation(source_id="李四", target_id="飞剑", relation="owns")
        return mgr

    def test_neighbors_1hop(self, manager: WorldGraphManager):
        result = manager.neighbors("张三", hops=1)
        assert result["center"] == "张三"
        ids = {e["id"] for e in result["entities"]}
        assert "青云山" in ids
        assert "李四" in ids

    def test_neighbors_2hop(self, manager: WorldGraphManager):
        result = manager.neighbors("张三", hops=2)
        ids = {e["id"] for e in result["entities"]}
        assert "飞剑" in ids  # 张三→李四→飞剑

    def test_neighbors_direction_outgoing(self, manager: WorldGraphManager):
        result = manager.neighbors("张三", hops=1, direction="outgoing")
        ids = {e["id"] for e in result["entities"]}
        assert "张三" in ids  # center always included

    def test_neighbors_relation_filter(self, manager: WorldGraphManager):
        result = manager.neighbors("张三", hops=1, relation_filter="located_at")
        ids = {e["id"] for e in result["entities"]}
        assert "青云山" in ids
        assert "李四" not in ids

    def test_neighbors_nonexistent(self, manager: WorldGraphManager):
        result = manager.neighbors("不存在")
        assert result["entities"] == []

    def test_find_path(self, manager: WorldGraphManager):
        paths = manager.find_path("张三", "飞剑")
        assert len(paths) >= 1
        assert paths[0][0] == "张三"
        assert paths[0][-1] == "飞剑"

    def test_find_path_no_path(self, manager: WorldGraphManager):
        manager.upsert_entity(entity_id="孤岛", name="孤岛", entity_type="location")
        paths = manager.find_path("张三", "孤岛")
        assert paths == []

    def test_subgraph_by_type(self, manager: WorldGraphManager):
        result = manager.subgraph_by_type("character")
        ids = {e["id"] for e in result["entities"]}
        assert ids == {"张三", "李四"}
        assert len(result["relations"]) >= 1  # ally 关系

    def test_subgraph_by_type_no_relations(self, manager: WorldGraphManager):
        result = manager.subgraph_by_type("character", include_relations=False)
        assert result["relations"] == []

    def test_subgraph_by_chapter(self, manager: WorldGraphManager):
        # 默认关系没有 chapter_id → 全局关系都会包含
        result = manager.subgraph_by_chapter("ch_001")
        assert len(result["entities"]) >= 1


# ══════════════════════════════════════════════════════════════════════
# 4. WorldEntityExtractor
# ══════════════════════════════════════════════════════════════════════


class TestWorldEntityExtractor:
    """实体抽取器测试（规则引擎分支）。"""

    def test_extract_characters(self):
        extractor = WorldEntityExtractor()
        text = "「张三」说道：「我们去青云山吧。」「李四」笑了笑。"
        result = extractor.extract(text, chapter_id="ch_001")
        assert result.method == "rule"
        names = {e.name for e in result.entities}
        assert "张三" in names
        assert "李四" in names

    def test_extract_locations(self):
        extractor = WorldEntityExtractor()
        text = "他们来到了青云山，又前往落霞谷。"
        result = extractor.extract(text)
        names = {e.name for e in result.entities}
        assert "青云山" in names or "落霞谷" in names

    def test_extract_items(self):
        extractor = WorldEntityExtractor()
        text = "张三取出了「天罡剑」，祭出「护身符」。"
        result = extractor.extract(text)
        names = {e.name for e in result.entities}
        assert "天罡剑" in names or "护身符" in names

    def test_extract_relations(self):
        extractor = WorldEntityExtractor()
        text = "「张三」说道，他属于青云门。「李四」也是青云门的弟子。"
        result = extractor.extract(text, existing_entities=["青云门"])
        # 可能抽取到 belongs_to 关系
        assert isinstance(result.relations, list)

    def test_extract_empty_text(self):
        extractor = WorldEntityExtractor()
        result = extractor.extract("")
        assert result.entities == []
        assert result.relations == []

    def test_to_id_short_name(self):
        assert WorldEntityExtractor._to_id("a") == ""
        assert WorldEntityExtractor._to_id("") == ""
        assert WorldEntityExtractor._to_id("张三") != ""

    def test_parse_llm_response_valid(self):
        content = '```json\n{"entities": [{"name": "test"}], "relations": []}\n```'
        parsed = WorldEntityExtractor._parse_llm_response(content)
        assert len(parsed["entities"]) == 1

    def test_parse_llm_response_invalid(self):
        parsed = WorldEntityExtractor._parse_llm_response("not json at all")
        assert parsed == {"entities": [], "relations": []}


# ══════════════════════════════════════════════════════════════════════
# 5. WorldGraphRenderer
# ══════════════════════════════════════════════════════════════════════


class TestWorldGraphRenderer:
    """D3 力导向图渲染器测试。"""

    def test_render_basic(self):
        graph = _make_graph()
        html = render_world_graph_html(graph)
        assert "<!DOCTYPE html>" in html
        assert "d3.v7" in html
        assert "张三" in html

    def test_render_empty_graph(self):
        graph = WorldGraph()
        html = render_world_graph_html(graph)
        assert "<!DOCTYPE html>" in html

    def test_render_custom_title(self):
        graph = _make_graph()
        html = render_world_graph_html(graph, title="测试图谱")
        assert "测试图谱" in html

    def test_render_to_file(self, tmp_path: Path):
        graph = _make_graph()
        out = tmp_path / "graph.html"
        html = render_world_graph_html(graph, output_path=out)
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert content == html

    def test_render_contains_all_entities(self):
        graph = _make_graph()
        html = render_world_graph_html(graph)
        for name in ["张三", "李四", "青云山", "青云门", "飞剑"]:
            assert name in html
