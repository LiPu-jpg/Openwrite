"""World graph manager: CRUD, summary, and lightweight consistency checks."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import yaml

try:
    from tools.models.world import WorldEntity, WorldGraph, WorldRelation
except ImportError:  # pragma: no cover - supports legacy path injection
    from models.world import WorldEntity, WorldGraph, WorldRelation


class WorldGraphManager:
    """Manage world entities and relations for one novel."""

    def __init__(self, project_dir: Optional[Path] = None, novel_id: str = "my_novel"):
        self.project_dir = project_dir or self._find_project_dir()
        self.novel_id = novel_id
        self.world_dir = self.project_dir / "data" / "novels" / novel_id / "world"
        self.graph_file = self.world_dir / "world_graph.yaml"
        self.world_dir.mkdir(parents=True, exist_ok=True)

    def _find_project_dir(self) -> Path:
        cwd = Path.cwd()
        for parent in [cwd] + list(cwd.parents):
            if (parent / "tools").exists():
                return parent
        return cwd

    def _load_graph(self) -> WorldGraph:
        if not self.graph_file.exists():
            return WorldGraph()
        with self.graph_file.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        return WorldGraph.model_validate(data)

    def _save_graph(self, graph: WorldGraph) -> None:
        graph.updated_at = datetime.now().isoformat()
        with self.graph_file.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(graph.model_dump(), handle, allow_unicode=True, sort_keys=False)

    def upsert_entity(
        self,
        *,
        entity_id: str,
        name: str,
        entity_type: str = "concept",
        description: str = "",
        tags: Optional[List[str]] = None,
        attributes: Optional[Dict[str, str]] = None,
    ) -> WorldEntity:
        graph = self._load_graph()
        node = WorldEntity(
            id=entity_id,
            name=name,
            type=entity_type,
            description=description,
            tags=tags or [],
            attributes=attributes or {},
        )
        graph.entities[entity_id] = node
        self._save_graph(graph)
        return node

    def add_relation(
        self,
        *,
        source_id: str,
        target_id: str,
        relation: str,
        weight: int = 1,
        note: str = "",
    ) -> WorldRelation:
        graph = self._load_graph()
        if source_id not in graph.entities:
            raise ValueError(f"源实体不存在: {source_id}")
        if target_id not in graph.entities:
            raise ValueError(f"目标实体不存在: {target_id}")

        rel = WorldRelation(
            source_id=source_id,
            target_id=target_id,
            relation=relation,
            weight=weight,
            note=note,
        )
        graph.relations.append(rel)
        self._save_graph(graph)
        return rel

    def list_entities(self, entity_type: str = "") -> List[WorldEntity]:
        graph = self._load_graph()
        items = list(graph.entities.values())
        if entity_type:
            items = [item for item in items if item.type == entity_type]
        items.sort(key=lambda item: item.id)
        return items

    def list_relations(self, relation: str = "") -> List[WorldRelation]:
        graph = self._load_graph()
        items = list(graph.relations)
        if relation:
            items = [item for item in items if item.relation == relation]
        items.sort(key=lambda item: (item.source_id, item.relation, item.target_id))
        return items

    def related_entities(
        self, *, entity_id: str, relation: str = ""
    ) -> List[Tuple[WorldRelation, WorldEntity]]:
        graph = self._load_graph()
        pairs: List[Tuple[WorldRelation, WorldEntity]] = []
        for rel in graph.relations:
            if rel.source_id != entity_id:
                continue
            if relation and rel.relation != relation:
                continue
            target = graph.entities.get(rel.target_id)
            if target is None:
                continue
            pairs.append((rel, target))
        return pairs

    def summary(self, *, max_entities: int = 8, max_relations: int = 8) -> str:
        graph = self._load_graph()
        if not graph.entities:
            return "暂无世界观图谱"

        entities = sorted(graph.entities.values(), key=lambda item: item.id)[:max_entities]
        entity_part = ", ".join(f"{item.name}<{item.type}>" for item in entities)

        relations = sorted(
            graph.relations, key=lambda item: (item.weight * -1, item.relation)
        )[:max_relations]
        relation_parts: List[str] = []
        for rel in relations:
            source = graph.entities.get(rel.source_id)
            target = graph.entities.get(rel.target_id)
            if not source or not target:
                continue
            relation_parts.append(f"{source.name}-{rel.relation}->{target.name}")
        if relation_parts:
            return f"实体: {entity_part}; 关系: {'; '.join(relation_parts)}"
        return f"实体: {entity_part}; 关系: 暂无"

    def check_conflicts(self) -> Dict[str, object]:
        graph = self._load_graph()
        errors: List[str] = []
        warnings: List[str] = []

        for rel in graph.relations:
            if rel.source_id not in graph.entities:
                errors.append(f"关系源实体不存在: {rel.source_id}")
            if rel.target_id not in graph.entities:
                errors.append(f"关系目标实体不存在: {rel.target_id}")

        seen: Set[Tuple[str, str, str]] = set()
        for rel in graph.relations:
            key = (rel.source_id, rel.relation, rel.target_id)
            if key in seen:
                warnings.append(
                    f"重复关系: {rel.source_id}-{rel.relation}->{rel.target_id}"
                )
            seen.add(key)

        above_edges: Dict[str, List[str]] = {}
        for rel in graph.relations:
            if rel.relation != "above":
                continue
            above_edges.setdefault(rel.source_id, []).append(rel.target_id)

        cycle = self._find_cycle(above_edges)
        if cycle:
            path = " -> ".join(cycle)
            errors.append(f"境界层级存在循环: {path}")

        return {
            "errors": errors,
            "warnings": warnings,
            "statistics": {
                "entity_count": len(graph.entities),
                "relation_count": len(graph.relations),
            },
            "is_valid": len(errors) == 0,
        }

    @staticmethod
    def _find_cycle(edges: Dict[str, List[str]]) -> List[str]:
        visiting: Set[str] = set()
        visited: Set[str] = set()
        parent: Dict[str, str] = {}

        def dfs(node: str) -> List[str]:
            visiting.add(node)
            for nxt in edges.get(node, []):
                if nxt in visited:
                    continue
                if nxt in visiting:
                    cycle = [nxt, node]
                    cur = node
                    while parent.get(cur) and parent[cur] != nxt:
                        cur = parent[cur]
                        cycle.append(cur)
                    cycle.append(nxt)
                    cycle.reverse()
                    return cycle
                parent[nxt] = node
                found = dfs(nxt)
                if found:
                    return found
            visiting.remove(node)
            visited.add(node)
            return []

        for node in list(edges.keys()):
            if node in visited:
                continue
            found = dfs(node)
            if found:
                return found
        return []
    # ------------------------------------------------------------------
    # 子图查询 API
    # ------------------------------------------------------------------

    def neighbors(
        self,
        entity_id: str,
        *,
        hops: int = 1,
        entity_type: str = "",
        relation_filter: str = "",
        direction: str = "both",
    ) -> Dict[str, object]:
        """查询 N 跳邻居子图。

        Args:
            entity_id: 起点实体 ID。
            hops: 跳数（默认 1）。
            entity_type: 只返回指定类型的实体（空=全部）。
            relation_filter: 只跟随指定关系（空=全部）。
            direction: "outgoing" / "incoming" / "both"。

        Returns:
            {"entities": [...], "relations": [...], "center": entity_id}
        """
        graph = self._load_graph()
        if entity_id not in graph.entities:
            return {"entities": [], "relations": [], "center": entity_id}

        visited: Set[str] = {entity_id}
        frontier: Set[str] = {entity_id}
        collected_rels: List[Dict[str, str]] = []

        for _ in range(hops):
            next_frontier: Set[str] = set()
            for rel in graph.relations:
                if relation_filter and rel.relation != relation_filter:
                    continue
                src, tgt = rel.source_id, rel.target_id
                if direction in ("outgoing", "both") and src in frontier and tgt not in visited:
                    next_frontier.add(tgt)
                    collected_rels.append({
                        "source": src, "target": tgt,
                        "relation": rel.relation, "weight": rel.weight,
                    })
                if direction in ("incoming", "both") and tgt in frontier and src not in visited:
                    next_frontier.add(src)
                    collected_rels.append({
                        "source": src, "target": tgt,
                        "relation": rel.relation, "weight": rel.weight,
                    })
            visited |= next_frontier
            frontier = next_frontier

        # 过滤实体类型
        result_entities = []
        for eid in visited:
            entity = graph.entities.get(eid)
            if not entity:
                continue
            if entity_type and entity.type != entity_type:
                continue
            result_entities.append({
                "id": entity.id, "name": entity.name,
                "type": entity.type, "attributes": entity.attributes,
            })

        return {
            "center": entity_id,
            "entities": result_entities,
            "relations": collected_rels,
        }

    def find_path(
        self,
        source_id: str,
        target_id: str,
        *,
        max_depth: int = 5,
    ) -> List[List[str]]:
        """查找两个实体之间的所有路径（BFS，限制深度）。

        Returns:
            路径列表，每条路径是实体 ID 序列。
        """
        graph = self._load_graph()
        if source_id not in graph.entities or target_id not in graph.entities:
            return []

        # 构建邻接表（双向）
        adj: Dict[str, Set[str]] = {}
        for rel in graph.relations:
            adj.setdefault(rel.source_id, set()).add(rel.target_id)
            adj.setdefault(rel.target_id, set()).add(rel.source_id)

        paths: List[List[str]] = []
        queue: List[List[str]] = [[source_id]]

        while queue:
            path = queue.pop(0)
            node = path[-1]
            if node == target_id and len(path) > 1:
                paths.append(path)
                continue
            if len(path) > max_depth:
                continue
            for neighbor in adj.get(node, set()):
                if neighbor not in path:
                    queue.append(path + [neighbor])

        return paths

    def subgraph_by_type(
        self,
        entity_type: str,
        *,
        include_relations: bool = True,
    ) -> Dict[str, object]:
        """按实体类型提取子图。

        Returns:
            {"entities": [...], "relations": [...]}
        """
        graph = self._load_graph()
        type_ids: Set[str] = set()
        entities = []
        for eid, entity in graph.entities.items():
            if entity.type == entity_type:
                type_ids.add(eid)
                entities.append({
                    "id": entity.id, "name": entity.name,
                    "type": entity.type, "attributes": entity.attributes,
                })

        relations = []
        if include_relations:
            for rel in graph.relations:
                if rel.source_id in type_ids or rel.target_id in type_ids:
                    relations.append({
                        "source": rel.source_id, "target": rel.target_id,
                        "relation": rel.relation, "weight": rel.weight,
                    })

        return {"entities": entities, "relations": relations}

    def subgraph_by_chapter(
        self,
        chapter_id: str,
    ) -> Dict[str, object]:
        """提取指定章节相关的子图（关系有 chapter_id 标记 + 全局关系）。

        Returns:
            {"entities": [...], "relations": [...]}
        """
        graph = self._load_graph()
        relevant_ids: Set[str] = set()
        relations = []

        for rel in graph.relations:
            if not rel.chapter_id or rel.chapter_id == chapter_id:
                relevant_ids.add(rel.source_id)
                relevant_ids.add(rel.target_id)
                relations.append({
                    "source": rel.source_id, "target": rel.target_id,
                    "relation": rel.relation, "weight": rel.weight,
                    "chapter_id": rel.chapter_id,
                })

        # 也包含该章节的状态快照涉及的实体
        for snap in graph.state_log.snapshots:
            if snap.chapter_id == chapter_id:
                relevant_ids.add(snap.entity_id)

        entities = []
        for eid in relevant_ids:
            entity = graph.entities.get(eid)
            if entity:
                entities.append({
                    "id": entity.id, "name": entity.name,
                    "type": entity.type, "attributes": entity.attributes,
                })

        return {"entities": entities, "relations": relations}
