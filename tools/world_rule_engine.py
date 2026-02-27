"""世界观规则推理引擎 — 对 WorldGraph 执行自定义规则检查。

支持的规则类型：
- inheritance: 继承传递（如「弟子」继承「门派」的属性）
- mutual_exclusive: 互斥约束（如一个角色不能同时属于两个对立阵营）
- required_relation: 必需关系（如「境界」实体必须有 above/below 关系）
- attribute_constraint: 属性约束（如「境界」实体必须有 level 属性）
- uniqueness: 唯一性约束（如同类型实体 name 不可重复）
- cardinality: 基数约束（如一个角色最多属于一个门派）

规则从 YAML 文件加载，也可通过 API 动态添加。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import yaml

from tools.models.world import WorldEntity, WorldGraph, WorldRelation

logger = logging.getLogger(__name__)


class RuleType(str, Enum):
    """规则类型。"""

    INHERITANCE = "inheritance"
    MUTUAL_EXCLUSIVE = "mutual_exclusive"
    REQUIRED_RELATION = "required_relation"
    ATTRIBUTE_CONSTRAINT = "attribute_constraint"
    UNIQUENESS = "uniqueness"
    CARDINALITY = "cardinality"


class Severity(str, Enum):
    """违规严重程度。"""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class WorldRule:
    """一条世界观规则。"""

    id: str
    rule_type: RuleType
    description: str = ""
    severity: Severity = Severity.ERROR
    params: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True


@dataclass
class RuleViolation:
    """一条规则违规记录。"""

    rule_id: str
    rule_type: RuleType
    severity: Severity
    message: str
    entities: List[str] = field(default_factory=list)
    relations: List[str] = field(default_factory=list)


class WorldRuleEngine:
    """世界观规则推理引擎。"""

    def __init__(self) -> None:
        self._rules: List[WorldRule] = []

    @property
    def rules(self) -> List[WorldRule]:
        return list(self._rules)

    # ------------------------------------------------------------------
    # 规则管理
    # ------------------------------------------------------------------

    def add_rule(self, rule: WorldRule) -> None:
        """添加一条规则。"""
        # 去重
        self._rules = [r for r in self._rules if r.id != rule.id]
        self._rules.append(rule)

    def remove_rule(self, rule_id: str) -> bool:
        """移除规则，返回是否成功。"""
        before = len(self._rules)
        self._rules = [r for r in self._rules if r.id != rule_id]
        return len(self._rules) < before

    def load_rules_from_yaml(self, path: Path) -> int:
        """从 YAML 文件加载规则，返回加载数量。"""
        if not path.exists():
            return 0
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not data or not isinstance(data, dict):
            return 0
        rules_data = data.get("rules", [])
        if not isinstance(rules_data, list):
            return 0
        count = 0
        for item in rules_data:
            if not isinstance(item, dict):
                continue
            try:
                rule = WorldRule(
                    id=item["id"],
                    rule_type=RuleType(item["type"]),
                    description=item.get("description", ""),
                    severity=Severity(item.get("severity", "error")),
                    params=item.get("params", {}),
                    enabled=item.get("enabled", True),
                )
                self.add_rule(rule)
                count += 1
            except (KeyError, ValueError) as e:
                logger.warning("跳过无效规则: %s — %s", item.get("id", "?"), e)
        return count

    def save_rules_to_yaml(self, path: Path) -> None:
        """保存当前规则到 YAML。"""
        rules_data = []
        for r in self._rules:
            rules_data.append(
                {
                    "id": r.id,
                    "type": r.rule_type.value,
                    "description": r.description,
                    "severity": r.severity.value,
                    "params": r.params,
                    "enabled": r.enabled,
                }
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(
                {"rules": rules_data}, f, allow_unicode=True, sort_keys=False
            )

    # ------------------------------------------------------------------
    # 推理执行
    # ------------------------------------------------------------------

    def evaluate(self, graph: WorldGraph) -> List[RuleViolation]:
        """对图谱执行所有启用的规则，返回违规列表。"""
        violations: List[RuleViolation] = []
        for rule in self._rules:
            if not rule.enabled:
                continue
            handler = self._HANDLERS.get(rule.rule_type)
            if handler:
                violations.extend(handler(self, graph, rule))
            else:
                logger.warning("未知规则类型: %s", rule.rule_type)
        return violations

    def evaluate_summary(self, graph: WorldGraph) -> Dict[str, Any]:
        """执行规则并返回摘要。"""
        violations = self.evaluate(graph)
        errors = [v for v in violations if v.severity == Severity.ERROR]
        warnings = [v for v in violations if v.severity == Severity.WARNING]
        infos = [v for v in violations if v.severity == Severity.INFO]
        return {
            "total_rules": len([r for r in self._rules if r.enabled]),
            "total_violations": len(violations),
            "errors": len(errors),
            "warnings": len(warnings),
            "infos": len(infos),
            "violations": violations,
            "is_valid": len(errors) == 0,
        }

    # ------------------------------------------------------------------
    # 各规则类型的检查实现
    # ------------------------------------------------------------------

    def _check_inheritance(
        self, graph: WorldGraph, rule: WorldRule
    ) -> List[RuleViolation]:
        """继承传递：子实体应继承父实体的指定属性。

        params:
          relation: str — 表示继承的关系类型（如 "belongs_to"）
          attributes: List[str] — 需要继承的属性键列表
        """
        violations: List[RuleViolation] = []
        relation = rule.params.get("relation", "belongs_to")
        attrs = rule.params.get("attributes", [])
        if not attrs:
            return violations

        for rel in graph.relations:
            if rel.relation != relation:
                continue
            child = graph.entities.get(rel.source_id)
            parent = graph.entities.get(rel.target_id)
            if not child or not parent:
                continue
            for attr_key in attrs:
                parent_val = parent.attributes.get(attr_key)
                if parent_val is None:
                    continue
                child_val = child.attributes.get(attr_key)
                if child_val is None:
                    violations.append(
                        RuleViolation(
                            rule_id=rule.id,
                            rule_type=rule.rule_type,
                            severity=rule.severity,
                            message=(
                                f"「{child.name}」缺少从「{parent.name}」"
                                f"继承的属性 {attr_key}={parent_val}"
                            ),
                            entities=[child.id, parent.id],
                        )
                    )
        return violations

    def _check_mutual_exclusive(
        self, graph: WorldGraph, rule: WorldRule
    ) -> List[RuleViolation]:
        """互斥约束：一个实体不能同时与互斥组中的多个实体有指定关系。

        params:
          relation: str — 关系类型（如 "belongs_to"）
          groups: List[List[str]] — 互斥实体组（如 [["正道", "魔道"]]）
        """
        violations: List[RuleViolation] = []
        relation = rule.params.get("relation", "belongs_to")
        groups = rule.params.get("groups", [])

        # 构建 source -> set of targets 映射
        source_targets: Dict[str, Set[str]] = {}
        for rel in graph.relations:
            if rel.relation != relation:
                continue
            source_targets.setdefault(rel.source_id, set()).add(rel.target_id)

        for group in groups:
            group_set = set(group)
            for source_id, targets in source_targets.items():
                overlap = targets & group_set
                if len(overlap) > 1:
                    source = graph.entities.get(source_id)
                    names = [
                        graph.entities[eid].name
                        for eid in overlap
                        if eid in graph.entities
                    ]
                    violations.append(
                        RuleViolation(
                            rule_id=rule.id,
                            rule_type=rule.rule_type,
                            severity=rule.severity,
                            message=(
                                f"「{source.name if source else source_id}」"
                                f"同时属于互斥组: {', '.join(names)}"
                            ),
                            entities=[source_id] + list(overlap),
                        )
                    )
        return violations

    def _check_required_relation(
        self, graph: WorldGraph, rule: WorldRule
    ) -> List[RuleViolation]:
        """必需关系：指定类型的实体必须有某种关系。

        params:
          entity_type: str — 实体类型（如 "character"）
          relation: str — 必需的关系类型（如 "located_at"）
          direction: str — "outgoing"（默认）或 "incoming"
        """
        violations: List[RuleViolation] = []
        entity_type = rule.params.get("entity_type", "")
        relation = rule.params.get("relation", "")
        direction = rule.params.get("direction", "outgoing")

        if not entity_type or not relation:
            return violations

        # 收集有该关系的实体
        has_relation: Set[str] = set()
        for rel in graph.relations:
            if rel.relation != relation:
                continue
            if direction == "outgoing":
                has_relation.add(rel.source_id)
            else:
                has_relation.add(rel.target_id)

        for eid, entity in graph.entities.items():
            if entity.type != entity_type:
                continue
            if eid not in has_relation:
                violations.append(
                    RuleViolation(
                        rule_id=rule.id,
                        rule_type=rule.rule_type,
                        severity=rule.severity,
                        message=(
                            f"「{entity.name}」({entity_type}) "
                            f"缺少必需的 {direction} 关系: {relation}"
                        ),
                        entities=[eid],
                    )
                )
        return violations

    def _check_attribute_constraint(
        self, graph: WorldGraph, rule: WorldRule
    ) -> List[RuleViolation]:
        """属性约束：指定类型的实体必须有某些属性。

        params:
          entity_type: str — 实体类型
          required_attributes: List[str] — 必需属性键列表
          pattern: Dict[str, str] — 属性值正则约束（可选）
        """
        violations: List[RuleViolation] = []
        entity_type = rule.params.get("entity_type", "")
        required_attrs = rule.params.get("required_attributes", [])
        patterns = rule.params.get("pattern", {})

        for eid, entity in graph.entities.items():
            if entity_type and entity.type != entity_type:
                continue
            for attr_key in required_attrs:
                if attr_key not in entity.attributes:
                    violations.append(
                        RuleViolation(
                            rule_id=rule.id,
                            rule_type=rule.rule_type,
                            severity=rule.severity,
                            message=f"「{entity.name}」缺少必需属性: {attr_key}",
                            entities=[eid],
                        )
                    )
            for attr_key, pattern in patterns.items():
                val = entity.attributes.get(attr_key, "")
                if val and not re.match(pattern, val):
                    violations.append(
                        RuleViolation(
                            rule_id=rule.id,
                            rule_type=rule.rule_type,
                            severity=rule.severity,
                            message=(
                                f"「{entity.name}」属性 {attr_key}={val} "
                                f"不匹配模式: {pattern}"
                            ),
                            entities=[eid],
                        )
                    )
        return violations

    def _check_uniqueness(
        self, graph: WorldGraph, rule: WorldRule
    ) -> List[RuleViolation]:
        """唯一性约束：同类型实体的指定属性值不可重复。

        params:
          entity_type: str — 实体类型（空则全局）
          attribute: str — 需要唯一的属性键（"name" 检查 entity.name）
        """
        violations: List[RuleViolation] = []
        entity_type = rule.params.get("entity_type", "")
        attribute = rule.params.get("attribute", "name")

        seen: Dict[str, str] = {}  # value -> first entity id
        for eid, entity in graph.entities.items():
            if entity_type and entity.type != entity_type:
                continue
            if attribute == "name":
                val = entity.name
            else:
                val = entity.attributes.get(attribute, "")
            if not val:
                continue
            if val in seen:
                violations.append(
                    RuleViolation(
                        rule_id=rule.id,
                        rule_type=rule.rule_type,
                        severity=rule.severity,
                        message=(
                            f"「{entity.name}」与「{graph.entities[seen[val]].name}」"
                            f"的 {attribute} 重复: {val}"
                        ),
                        entities=[eid, seen[val]],
                    )
                )
            else:
                seen[val] = eid
        return violations

    def _check_cardinality(
        self, graph: WorldGraph, rule: WorldRule
    ) -> List[RuleViolation]:
        """基数约束：限制实体的某种关系数量。

        params:
          entity_type: str — 实体类型
          relation: str — 关系类型
          direction: str — "outgoing" 或 "incoming"
          min: int — 最小数量（默认 0）
          max: int — 最大数量（默认无限）
        """
        violations: List[RuleViolation] = []
        entity_type = rule.params.get("entity_type", "")
        relation = rule.params.get("relation", "")
        direction = rule.params.get("direction", "outgoing")
        min_count = rule.params.get("min", 0)
        max_count = rule.params.get("max", 999999)

        if not relation:
            return violations

        # 统计每个实体的关系数
        counts: Dict[str, int] = {}
        for rel in graph.relations:
            if rel.relation != relation:
                continue
            eid = rel.source_id if direction == "outgoing" else rel.target_id
            counts[eid] = counts.get(eid, 0) + 1

        for eid, entity in graph.entities.items():
            if entity_type and entity.type != entity_type:
                continue
            count = counts.get(eid, 0)
            if count < min_count:
                violations.append(
                    RuleViolation(
                        rule_id=rule.id,
                        rule_type=rule.rule_type,
                        severity=rule.severity,
                        message=(
                            f"「{entity.name}」的 {relation} 关系数 ({count}) "
                            f"少于最小要求 ({min_count})"
                        ),
                        entities=[eid],
                    )
                )
            elif count > max_count:
                violations.append(
                    RuleViolation(
                        rule_id=rule.id,
                        rule_type=rule.rule_type,
                        severity=rule.severity,
                        message=(
                            f"「{entity.name}」的 {relation} 关系数 ({count}) "
                            f"超过最大限制 ({max_count})"
                        ),
                        entities=[eid],
                    )
                )
        return violations

    # 规则类型 → 处理函数映射
    _HANDLERS = {
        RuleType.INHERITANCE: _check_inheritance,
        RuleType.MUTUAL_EXCLUSIVE: _check_mutual_exclusive,
        RuleType.REQUIRED_RELATION: _check_required_relation,
        RuleType.ATTRIBUTE_CONSTRAINT: _check_attribute_constraint,
        RuleType.UNIQUENESS: _check_uniqueness,
        RuleType.CARDINALITY: _check_cardinality,
    }
