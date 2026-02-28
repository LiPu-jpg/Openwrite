"""World query helpers.

提供世界观查询功能，包括：
- 获取实体信息
- 获取实体关系
- 列出实体
- 冲突检测

Usage:
    from skills.world.tools import WorldQuery

    query = WorldQuery(project_dir=Path.cwd(), novel_id="my_novel")
    entity = query.get_entity("蜀山")
    relationships = query.get_relationships("蜀山")
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class WorldEntity(BaseModel):
    """世界实体摘要。"""

    id: str
    name: str
    type: str
    description: str = ""
    attributes: Dict[str, Any] = {}


class WorldRelationship(BaseModel):
    """世界关系。"""

    from_entity: str
    to_entity: str
    relation_type: str
    description: str = ""


class WorldQuery:
    """世界观查询工具。

    提供统一的世界观信息查询接口。

    Args:
        project_dir: 项目根目录
        novel_id: 小说 ID

    Usage:
        query = WorldQuery(project_dir=Path.cwd(), novel_id="my_novel")
        entity = query.get_entity("蜀山")
    """

    def __init__(
        self,
        project_dir: Optional[Path] = None,
        novel_id: str = "my_novel",
    ):
        self.project_dir = project_dir or self._find_project_dir()
        self.novel_id = novel_id
        self.world_dir = self.project_dir / "data" / "novels" / self.novel_id / "world"
        self.graph_file = self.world_dir / "graph.yaml"
        self.rules_file = self.world_dir / "rules.yaml"

    def _find_project_dir(self) -> Path:
        """查找项目根目录。"""
        cwd = Path.cwd()
        for parent in [cwd] + list(cwd.parents):
            if (parent / "data" / "novels").exists() and (parent / "tools").exists():
                return parent
        return cwd

    def _load_yaml(self, path: Path) -> Dict[str, Any]:
        """加载 YAML 文件。"""
        if not path.exists():
            return {}
        import yaml

        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def _load_graph(self) -> Dict[str, Any]:
        """加载世界图谱。"""
        return self._load_yaml(self.graph_file)

    def get_entity(self, entity_id: str) -> Dict[str, Any]:
        """获取实体信息。

        Args:
            entity_id: 实体 ID

        Returns:
            实体信息
        """
        graph = self._load_graph()
        entities = graph.get("entities", {})

        if entity_id in entities:
            return {"entity": entities[entity_id]}

        return {"error": f"Entity not found: {entity_id}"}

    def list_entities(
        self,
        entity_type: Optional[str] = None,
    ) -> List[WorldEntity]:
        """列出所有实体。

        Args:
            entity_type: 实体类型过滤（可选）

        Returns:
            实体列表
        """
        graph = self._load_graph()
        entities = graph.get("entities", {})
        result = []

        for entity_id, entity_data in entities.items():
            etype = entity_data.get("type", "")

            if entity_type and entity_type != etype:
                continue

            result.append(
                WorldEntity(
                    id=entity_id,
                    name=entity_data.get("name", entity_id),
                    type=etype,
                    description=entity_data.get("description", ""),
                    attributes=entity_data.get("attributes", {}),
                )
            )

        return result

    def get_relationships(
        self,
        entity_id: Optional[str] = None,
        relation_type: Optional[str] = None,
    ) -> List[WorldRelationship]:
        """获取实体关系。

        Args:
            entity_id: 实体 ID（可选，过滤相关关系）
            relation_type: 关系类型（可选）

        Returns:
            关系列表
        """
        graph = self._load_graph()
        edges = graph.get("edges", [])
        result = []

        for edge in edges:
            from_entity = edge.get("from", edge.get("from_", ""))
            to_entity = edge.get("to", "")
            rtype = edge.get("type", edge.get("relation_type", ""))

            # 过滤
            if entity_id and entity_id not in (from_entity, to_entity):
                continue
            if relation_type and relation_type != rtype:
                continue

            result.append(
                WorldRelationship(
                    from_entity=from_entity,
                    to_entity=to_entity,
                    relation_type=rtype,
                    description=edge.get("description", ""),
                )
            )

        return result

    def check_conflicts(self) -> List[Dict[str, Any]]:
        """检查世界观数据中的冲突。

        Returns:
            冲突列表
        """
        conflicts = []
        graph = self._load_graph()
        entities = graph.get("entities", {})
        edges = graph.get("edges", [])

        # 检查边引用的实体是否存在
        for edge in edges:
            from_entity = edge.get("from", edge.get("from_", ""))
            to_entity = edge.get("to", "")

            if from_entity and from_entity not in entities:
                conflicts.append(
                    {
                        "type": "missing_entity",
                        "message": f"边引用了不存在的实体: {from_entity}",
                        "edge": edge,
                    }
                )

            if to_entity and to_entity not in entities:
                conflicts.append(
                    {
                        "type": "missing_entity",
                        "message": f"边引用了不存在的实体: {to_entity}",
                        "edge": edge,
                    }
                )

        # 检查规则冲突
        rules = self._load_yaml(self.rules_file)
        for rule_id, rule in rules.items():
            if rule.get("conflict_with"):
                for conflict_id in rule["conflict_with"]:
                    if conflict_id in rules:
                        conflicts.append(
                            {
                                "type": "rule_conflict",
                                "message": f"规则 {rule_id} 与 {conflict_id} 冲突",
                                "rules": [rule_id, conflict_id],
                            }
                        )

        return conflicts

    def get_rules(self) -> Dict[str, Any]:
        """获取世界规则。

        Returns:
            规则字典
        """
        return self._load_yaml(self.rules_file)

    def get_world_summary(self) -> str:
        """获取世界观摘要。

        用于 AI 上下文的世界观信息摘要。

        Returns:
            世界观摘要文本
        """
        entities = self.list_entities()
        rules = self.get_rules()

        parts = ["【世界观摘要】"]

        # 按类型分组实体
        by_type: Dict[str, List[str]] = {}
        for entity in entities:
            by_type.setdefault(entity.type, []).append(entity.name)

        for etype, names in by_type.items():
            parts.append(f"\n{etype}：{', '.join(names)}")

        # 规则摘要
        if rules:
            parts.append(f"\n规则数：{len(rules)}")
            for rule_id, rule in list(rules.items())[:3]:
                parts.append(f"  - {rule_id}: {rule.get('description', '')[:50]}")

        return "\n".join(parts)
