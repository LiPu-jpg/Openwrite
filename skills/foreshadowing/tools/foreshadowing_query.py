"""Foreshadowing query helpers.

提供伏笔查询功能，包括：
- 获取伏笔节点
- 获取待回收伏笔
- 伏笔统计
- DAG 验证

Usage:
    from skills.foreshadowing.tools import ForeshadowingQuery

    query = ForeshadowingQuery(project_dir=Path.cwd(), novel_id="my_novel")
    pending = query.get_pending_nodes(min_weight=5)
    stats = query.get_statistics()
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class ForeshadowingNodeSummary(BaseModel):
    """伏笔节点摘要。"""

    id: str
    content: str
    weight: int
    layer: str
    status: str
    target_chapter: Optional[str] = None
    tags: List[str] = []


class ForeshadowingQuery:
    """伏笔查询工具。

    提供统一的伏笔信息查询接口。

    Args:
        project_dir: 项目根目录
        novel_id: 小说 ID

    Usage:
        query = ForeshadowingQuery(project_dir=Path.cwd(), novel_id="my_novel")
        pending = query.get_pending_nodes()
    """

    def __init__(
        self,
        project_dir: Optional[Path] = None,
        novel_id: str = "my_novel",
    ):
        self.project_dir = project_dir or self._find_project_dir()
        self.novel_id = novel_id
        self.fs_dir = (
            self.project_dir / "data" / "novels" / self.novel_id / "foreshadowing"
        )
        self.dag_file = self.fs_dir / "dag.yaml"
        self.logs_dir = self.fs_dir / "logs"

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

    def _load_dag(self) -> Dict[str, Any]:
        """加载伏笔 DAG。"""
        return self._load_yaml(self.dag_file)

    def get_node(self, node_id: str) -> Dict[str, Any]:
        """获取伏笔节点。

        Args:
            node_id: 节点 ID

        Returns:
            节点信息
        """
        dag = self._load_dag()
        nodes = dag.get("nodes", {})
        status = dag.get("status", {})

        if node_id in nodes:
            node = nodes[node_id].copy()
            node["status"] = status.get(node_id, "未知")
            return {"node": node}

        return {"error": f"Node not found: {node_id}"}

    def get_pending_nodes(
        self,
        min_weight: int = 1,
        layer: Optional[str] = None,
    ) -> List[ForeshadowingNodeSummary]:
        """获取待回收的伏笔节点。

        Args:
            min_weight: 最小权重
            layer: 层级过滤（可选）

        Returns:
            待回收节点列表
        """
        dag = self._load_dag()
        nodes = dag.get("nodes", {})
        status = dag.get("status", {})
        result = []

        for node_id, node_data in nodes.items():
            node_status = status.get(node_id, "")

            # 只返回埋伏或待收状态
            if node_status not in ["埋伏", "待收"]:
                continue

            weight = node_data.get("weight", 0)
            node_layer = node_data.get("layer", "")

            # 过滤
            if weight < min_weight:
                continue
            if layer and layer != node_layer:
                continue

            result.append(
                ForeshadowingNodeSummary(
                    id=node_id,
                    content=node_data.get("content", ""),
                    weight=weight,
                    layer=node_layer,
                    status=node_status,
                    target_chapter=node_data.get("target_chapter"),
                    tags=node_data.get("tags", []),
                )
            )

        # 按权重降序排序
        result.sort(key=lambda x: x.weight, reverse=True)
        return result

    def get_overdue_nodes(
        self,
        current_chapter: str,
    ) -> List[ForeshadowingNodeSummary]:
        """获取逾期未回收的伏笔。

        Args:
            current_chapter: 当前章节 ID

        Returns:
            逾期节点列表
        """
        dag = self._load_dag()
        nodes = dag.get("nodes", {})
        status = dag.get("status", {})
        result = []

        for node_id, node_data in nodes.items():
            node_status = status.get(node_id, "")
            target = node_data.get("target_chapter")

            # 只检查有目标章节的埋伏/待收伏笔
            if node_status not in ["埋伏", "待收"]:
                continue
            if not target:
                continue

            # 简单比较：假设章节 ID 格式为 ch_XXX
            try:
                current_num = int(
                    current_chapter.replace("ch_", "").replace("chapter_", "")
                )
                target_num = int(target.replace("ch_", "").replace("chapter_", ""))

                if current_num > target_num:
                    result.append(
                        ForeshadowingNodeSummary(
                            id=node_id,
                            content=node_data.get("content", ""),
                            weight=node_data.get("weight", 0),
                            layer=node_data.get("layer", ""),
                            status="逾期",
                            target_chapter=target,
                            tags=node_data.get("tags", []),
                        )
                    )
            except ValueError:
                pass

        return result

    def get_statistics(self) -> Dict[str, Any]:
        """获取伏笔统计信息。

        Returns:
            统计信息字典
        """
        dag = self._load_dag()
        nodes = dag.get("nodes", {})
        edges = dag.get("edges", [])
        status = dag.get("status", {})

        stats = {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "by_status": {},
            "by_layer": {},
            "by_weight": {},
        }

        # 按状态统计
        for node_id, node_status in status.items():
            stats["by_status"][node_status] = stats["by_status"].get(node_status, 0) + 1

        # 按层级统计
        for node_id, node_data in nodes.items():
            layer = node_data.get("layer", "未知")
            stats["by_layer"][layer] = stats["by_layer"].get(layer, 0) + 1

        # 按权重统计
        for node_id, node_data in nodes.items():
            weight = node_data.get("weight", 0)
            weight_key = str(weight)
            stats["by_weight"][weight_key] = stats["by_weight"].get(weight_key, 0) + 1

        return stats

    def validate_dag(self) -> Dict[str, Any]:
        """验证 DAG 有效性。

        Returns:
            验证结果，包含 errors, warnings, is_valid
        """
        dag = self._load_dag()
        nodes = dag.get("nodes", {})
        edges = dag.get("edges", [])

        errors = []
        warnings = []

        # 检查边引用的节点是否存在
        for edge in edges:
            from_node = edge.get("from", edge.get("from_", ""))
            to_node = edge.get("to", "")

            if from_node and from_node not in nodes:
                errors.append(f"边引用了不存在的源节点: {from_node}")
            if to_node and to_node not in nodes and not to_node.endswith("_recover"):
                errors.append(f"边引用了不存在的目标节点: {to_node}")

        # 检查循环依赖 (DFS)
        adjacency: Dict[str, List[str]] = {}
        for edge in edges:
            src = edge.get("from", edge.get("from_", ""))
            dst = edge.get("to", "")
            if src and dst:
                adjacency.setdefault(src, []).append(dst)

        WHITE, GRAY, BLACK = 0, 1, 2
        color: Dict[str, int] = {nid: WHITE for nid in nodes}

        def _dfs_cycle(node: str) -> bool:
            color[node] = GRAY
            for neighbor in adjacency.get(node, []):
                if color.get(neighbor, WHITE) == GRAY:
                    errors.append(f"检测到循环引用: {node} -> {neighbor}")
                    return True
                if color.get(neighbor, WHITE) == WHITE:
                    if _dfs_cycle(neighbor):
                        return True
            color[node] = BLACK
            return False

        for nid in nodes:
            if color[nid] == WHITE:
                _dfs_cycle(nid)

        # 检查主线伏笔是否有目标章节
        for node_id, node_data in nodes.items():
            layer = node_data.get("layer", "")
            weight = node_data.get("weight", 0)
            target = node_data.get("target_chapter")

            if layer == "主线" and weight >= 9 and not target:
                warnings.append(f"主线伏笔 {node_id} 未指定回收章节")

        return {
            "errors": errors,
            "warnings": warnings,
            "is_valid": len(errors) == 0,
        }

    def get_dependencies(self, node_id: str) -> Dict[str, Any]:
        """获取伏笔的依赖关系。

        Args:
            node_id: 节点 ID

        Returns:
            依赖信息
        """
        dag = self._load_dag()
        edges = dag.get("edges", [])

        dependencies = []
        dependents = []

        for edge in edges:
            from_node = edge.get("from", edge.get("from_", ""))
            to_node = edge.get("to", "")
            edge_type = edge.get("type", "")

            if to_node == node_id:
                dependencies.append(
                    {
                        "node": from_node,
                        "type": edge_type,
                    }
                )

            if from_node == node_id:
                dependents.append(
                    {
                        "node": to_node,
                        "type": edge_type,
                    }
                )

        return {
            "node_id": node_id,
            "dependencies": dependencies,
            "dependents": dependents,
        }

    def get_foreshadowing_summary(self) -> str:
        """获取伏笔摘要。

        用于 AI 上下文的伏笔信息摘要。

        Returns:
            伏笔摘要文本
        """
        stats = self.get_statistics()
        pending = self.get_pending_nodes(min_weight=5)

        parts = ["【伏笔摘要】"]
        parts.append(f"总计：{stats['total_nodes']} 个伏笔")

        # 状态统计
        status_parts = []
        for status, count in stats["by_status"].items():
            status_parts.append(f"{status}:{count}")
        parts.append(f"状态：{', '.join(status_parts)}")

        # 待回收的高权重伏笔
        if pending:
            parts.append(f"\n待回收伏笔（权重≥5）：")
            for node in pending[:5]:
                parts.append(
                    f"  - [{node.layer}] {node.content[:30]}... (权重:{node.weight})"
                )

        return "\n".join(parts)
