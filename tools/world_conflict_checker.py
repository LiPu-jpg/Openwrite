"""世界观跨章节冲突检查器 — 检测实体状态的时序一致性问题。

检查类型：
- 位置矛盾：角色在同一章节出现在多个不兼容位置
- 属性回退：属性值在后续章节意外回退到早期状态
- 关系冲突：同章节内出现矛盾的关系（如同时敌对和结盟）
- 状态跳变：属性在相邻章节间发生不合理的剧烈变化
- 孤立实体：被引用但从未定义的实体
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from tools.models.world import (
    EntityStateSnapshot,
    WorldEntity,
    WorldGraph,
    WorldRelation,
    WorldStateLog,
)


def _chapter_order(chapter_id: str) -> int:
    """从章节 ID 提取数字序号。"""
    match = re.search(r"\d+", chapter_id)
    return int(match.group()) if match else 0


@dataclass
class ConflictItem:
    """一条冲突记录。"""

    conflict_type: str
    severity: str  # "error" | "warning"
    message: str
    chapter_id: str = ""
    entities: List[str] = field(default_factory=list)


class WorldConflictChecker:
    """世界观跨章节冲突检查器。"""

    # 位置相关的属性键
    LOCATION_ATTRS: Set[str] = {"location", "位置", "所在地", "located_at"}
    # 互斥关系对
    CONTRADICTORY_RELATIONS: List[Tuple[str, str]] = [
        ("ally", "enemy"),
        ("盟友", "敌对"),
        ("belongs_to", "opposes"),
        ("从属", "对立"),
    ]

    def check(
        self,
        graph: WorldGraph,
        chapters: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """执行全部跨章节冲突检查。

        Args:
            graph: 世界观图谱。
            chapters: 章节顺序列表（用于时序判断），为空则从 state_log 推断。

        Returns:
            包含 errors, warnings, is_valid 的结果字典。
        """
        if chapters is None:
            ch_set: Set[str] = set()
            for snap in graph.state_log.snapshots:
                ch_set.add(snap.chapter_id)
            for rel in graph.relations:
                if rel.chapter_id:
                    ch_set.add(rel.chapter_id)
            chapters = sorted(ch_set, key=_chapter_order)

        conflicts: List[ConflictItem] = []
        conflicts.extend(self._check_location_conflicts(graph, chapters))
        conflicts.extend(self._check_attribute_regression(graph, chapters))
        conflicts.extend(self._check_relation_contradictions(graph, chapters))
        conflicts.extend(self._check_state_jumps(graph, chapters))
        conflicts.extend(self._check_orphan_references(graph))

        errors = [c for c in conflicts if c.severity == "error"]
        warnings = [c for c in conflicts if c.severity == "warning"]

        return {
            "errors": [c.message for c in errors],
            "warnings": [c.message for c in warnings],
            "conflicts": conflicts,
            "is_valid": len(errors) == 0,
            "statistics": {
                "total_checks": 5,
                "total_conflicts": len(conflicts),
                "chapters_checked": len(chapters),
            },
        }

    def _get_snapshots_by_entity(
        self, graph: WorldGraph
    ) -> Dict[str, List[EntityStateSnapshot]]:
        """按实体分组快照，每组按章节排序。"""
        by_entity: Dict[str, List[EntityStateSnapshot]] = {}
        for snap in graph.state_log.snapshots:
            by_entity.setdefault(snap.entity_id, []).append(snap)
        for snaps in by_entity.values():
            snaps.sort(key=lambda s: _chapter_order(s.chapter_id))
        return by_entity

    def _check_location_conflicts(
        self, graph: WorldGraph, chapters: List[str]
    ) -> List[ConflictItem]:
        """检查同一章节内角色出现在多个不兼容位置。"""
        conflicts: List[ConflictItem] = []
        by_entity = self._get_snapshots_by_entity(graph)

        for entity_id, snaps in by_entity.items():
            # 按章节分组
            by_chapter: Dict[str, List[str]] = {}
            for snap in snaps:
                for key in self.LOCATION_ATTRS:
                    loc = snap.attributes.get(key, "")
                    if loc:
                        by_chapter.setdefault(snap.chapter_id, []).append(loc)

            for ch_id, locations in by_chapter.items():
                unique = set(locations)
                if len(unique) > 1:
                    entity = graph.entities.get(entity_id)
                    name = entity.name if entity else entity_id
                    conflicts.append(
                        ConflictItem(
                            conflict_type="location_conflict",
                            severity="error",
                            message=(
                                f"「{name}」在 {ch_id} 同时出现在多个位置: "
                                f"{', '.join(sorted(unique))}"
                            ),
                            chapter_id=ch_id,
                            entities=[entity_id],
                        )
                    )
        return conflicts

    def _check_attribute_regression(
        self, graph: WorldGraph, chapters: List[str]
    ) -> List[ConflictItem]:
        """检查属性值在后续章节意外回退。

        例如：ch_001 境界=筑基 → ch_003 境界=炼气（回退）
        仅对数值型或有明确序列的属性检查。
        """
        conflicts: List[ConflictItem] = []
        by_entity = self._get_snapshots_by_entity(graph)

        for entity_id, snaps in by_entity.items():
            if len(snaps) < 2:
                continue
            entity = graph.entities.get(entity_id)
            name = entity.name if entity else entity_id

            # 追踪每个属性的历史值
            attr_history: Dict[str, List[Tuple[str, str]]] = {}
            for snap in snaps:
                for key, val in snap.attributes.items():
                    attr_history.setdefault(key, []).append((snap.chapter_id, val))

            for attr_key, history in attr_history.items():
                # 尝试数值比较
                prev_num: Optional[float] = None
                prev_ch = ""
                for ch_id, val in history:
                    try:
                        num = float(val)
                    except (ValueError, TypeError):
                        prev_num = None
                        prev_ch = ch_id
                        continue
                    if prev_num is not None and num < prev_num:
                        # 位置属性不做数值回退检查
                        if attr_key not in self.LOCATION_ATTRS:
                            conflicts.append(
                                ConflictItem(
                                    conflict_type="attribute_regression",
                                    severity="warning",
                                    message=(
                                        f"「{name}」的 {attr_key} 从 {prev_ch} 的 "
                                        f"{prev_num} 回退到 {ch_id} 的 {num}"
                                    ),
                                    chapter_id=ch_id,
                                    entities=[entity_id],
                                )
                            )
                    prev_num = num
                    prev_ch = ch_id
        return conflicts

    def _check_relation_contradictions(
        self, graph: WorldGraph, chapters: List[str]
    ) -> List[ConflictItem]:
        """检查同章节内出现矛盾关系。"""
        conflicts: List[ConflictItem] = []

        # 按章节分组关系
        by_chapter: Dict[str, List[WorldRelation]] = {}
        for rel in graph.relations:
            ch = rel.chapter_id or "_global"
            by_chapter.setdefault(ch, []).append(rel)

        for ch_id, rels in by_chapter.items():
            # 构建 (source, target) -> set of relations
            pair_rels: Dict[Tuple[str, str], Set[str]] = {}
            for rel in rels:
                pair = (rel.source_id, rel.target_id)
                pair_rev = (rel.target_id, rel.source_id)
                pair_rels.setdefault(pair, set()).add(rel.relation)
                pair_rels.setdefault(pair_rev, set()).add(rel.relation)

            for pair, rel_types in pair_rels.items():
                for contra_a, contra_b in self.CONTRADICTORY_RELATIONS:
                    if contra_a in rel_types and contra_b in rel_types:
                        src = graph.entities.get(pair[0])
                        tgt = graph.entities.get(pair[1])
                        src_name = src.name if src else pair[0]
                        tgt_name = tgt.name if tgt else pair[1]
                        conflicts.append(
                            ConflictItem(
                                conflict_type="relation_contradiction",
                                severity="error",
                                message=(
                                    f"「{src_name}」与「{tgt_name}」在 {ch_id} "
                                    f"同时存在矛盾关系: {contra_a} 和 {contra_b}"
                                ),
                                chapter_id=ch_id,
                                entities=list(pair),
                            )
                        )
        return conflicts

    def _check_state_jumps(
        self, graph: WorldGraph, chapters: List[str]
    ) -> List[ConflictItem]:
        """检查相邻章节间属性的不合理剧变。

        当一个属性在相邻快照间变化超过阈值时报告。
        """
        conflicts: List[ConflictItem] = []
        by_entity = self._get_snapshots_by_entity(graph)
        jump_threshold = 5  # 数值属性跳变阈值

        for entity_id, snaps in by_entity.items():
            if len(snaps) < 2:
                continue
            entity = graph.entities.get(entity_id)
            name = entity.name if entity else entity_id

            for i in range(1, len(snaps)):
                prev = snaps[i - 1]
                curr = snaps[i]
                # 检查相邻章节
                prev_order = _chapter_order(prev.chapter_id)
                curr_order = _chapter_order(curr.chapter_id)
                if curr_order - prev_order > 2:
                    continue  # 跨度太大，不算相邻

                for key in set(prev.attributes) & set(curr.attributes):
                    try:
                        prev_val = float(prev.attributes[key])
                        curr_val = float(curr.attributes[key])
                        delta = abs(curr_val - prev_val)
                        if delta >= jump_threshold:
                            conflicts.append(
                                ConflictItem(
                                    conflict_type="state_jump",
                                    severity="warning",
                                    message=(
                                        f"「{name}」的 {key} 在 {prev.chapter_id}→"
                                        f"{curr.chapter_id} 间剧变: "
                                        f"{prev_val}→{curr_val} (Δ={delta})"
                                    ),
                                    chapter_id=curr.chapter_id,
                                    entities=[entity_id],
                                )
                            )
                    except (ValueError, TypeError):
                        pass
        return conflicts

    def _check_orphan_references(self, graph: WorldGraph) -> List[ConflictItem]:
        """检查关系中引用了不存在的实体。"""
        conflicts: List[ConflictItem] = []
        entity_ids = set(graph.entities.keys())

        for rel in graph.relations:
            if rel.source_id not in entity_ids:
                conflicts.append(
                    ConflictItem(
                        conflict_type="orphan_reference",
                        severity="error",
                        message=f"关系引用了不存在的源实体: {rel.source_id}",
                        entities=[rel.source_id],
                    )
                )
            if rel.target_id not in entity_ids:
                conflicts.append(
                    ConflictItem(
                        conflict_type="orphan_reference",
                        severity="error",
                        message=f"关系引用了不存在的目标实体: {rel.target_id}",
                        entities=[rel.target_id],
                    )
                )
        return conflicts
