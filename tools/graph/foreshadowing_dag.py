import json
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from tools.models.foreshadowing import (
        ForeshadowingEdge,
        ForeshadowingGraph,
        ForeshadowingNode,
    )
except ImportError:  # pragma: no cover - supports legacy path injection
    from models.foreshadowing import ForeshadowingEdge, ForeshadowingGraph, ForeshadowingNode


class ForeshadowingDAGManager:
    """伏笔 DAG 管理器"""

    def __init__(self, project_dir: Optional[Path] = None, novel_id: str = "my_novel"):
        self.project_dir = project_dir or self._find_project_dir()
        self.novel_id = novel_id
        self.dag_file = (
            self.project_dir / "data" / "novels" / self.novel_id / "foreshadowing" / "dag.yaml"
        )
        self.logs_dir = (
            self.project_dir / "data" / "novels" / self.novel_id / "foreshadowing" / "logs"
        )

        # 确保目录存在
        self.dag_file.parent.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def _find_project_dir(self) -> Path:
        """查找项目根目录"""
        cwd = Path.cwd()
        for parent in [cwd] + list(cwd.parents):
            if (parent / "data" / "novels").exists() and (parent / "tools").exists():
                return parent
        return cwd

    def _load_dag(self) -> ForeshadowingGraph:
        """加载 DAG 配置"""
        if not self.dag_file.exists():
            return ForeshadowingGraph()

        try:
            with open(self.dag_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return ForeshadowingGraph.model_validate(data)
        except Exception as e:
            print(f"加载 DAG 配置失败: {e}")
            return ForeshadowingGraph()

    def _save_dag(self, dag: ForeshadowingGraph):
        """保存 DAG 配置"""
        try:
            with open(self.dag_file, "w", encoding="utf-8") as f:
                json.dump(dag.model_dump(by_alias=True), f, indent=2, ensure_ascii=False)
            print(f"DAG 配置已保存")
        except Exception as e:
            print(f"保存 DAG 配置失败: {e}")

    def create_node(
        self,
        node_id: str,
        content: str,
        weight: int = 5,
        layer: str = "支线",
        created_at: str = "",
        target_chapter: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> bool:
        """创建伏笔节点"""
        dag = self._load_dag()

        if node_id in dag.nodes:
            print(f"伏笔节点已存在: {node_id}")
            return False

        node = ForeshadowingNode(
            id=node_id,
            content=content,
            weight=weight,
            layer=layer,
            status="埋伏",
            created_at=created_at,
            target_chapter=target_chapter,
            tags=tags or [],
        )

        dag.nodes[node_id] = node
        dag.status[node_id] = "埋伏"
        self._save_dag(dag)

        self._log_operation("create_node", f"创建伏笔节点: {node_id}")
        return True

    def create_edge(
        self, from_node: str, to_node: str, edge_type: str = "依赖"
    ) -> bool:
        """创建伏笔关系边"""
        dag = self._load_dag()

        # 验证节点存在
        if from_node not in dag.nodes:
            print(f"源节点不存在: {from_node}")
            return False
        if to_node not in dag.nodes and not to_node.endswith("_recover"):
            print(f"目标节点不存在: {to_node}")
            return False

        edge = ForeshadowingEdge(from_=from_node, to=to_node, type=edge_type)
        dag.edges.append(edge)
        self._save_dag(dag)

        self._log_operation("create_edge", f"创建伏笔边: {from_node} -> {to_node}")
        return True

    def update_node_status(self, node_id: str, status: str) -> bool:
        """更新伏笔节点状态"""
        dag = self._load_dag()

        if node_id not in dag.nodes:
            print(f"伏笔节点不存在: {node_id}")
            return False

        dag.status[node_id] = status
        self._save_dag(dag)

        self._log_operation("update_status", f"更新节点状态: {node_id} -> {status}")
        return True

    def get_pending_nodes(self, min_weight: int = 1) -> List[Dict[str, Any]]:
        """获取待回收的伏笔节点"""
        dag = self._load_dag()
        pending = []

        for node_id, node_data in dag.nodes.items():
            status = dag.status.get(node_id, "")
            if status in ["埋伏", "待收"]:
                if isinstance(node_data, ForeshadowingNode):
                    node = node_data
                else:
                    node = ForeshadowingNode.model_validate(node_data)
                if node.weight >= min_weight:
                    pending.append(node.model_dump())

        return pending

    def validate_dag(self) -> Dict[str, List[str]]:
        """验证 DAG 有效性"""
        dag = self._load_dag()
        errors = []
        warnings = []

        # 检查边引用的节点是否存在
        for edge in dag.edges:
            edge_data = edge if isinstance(edge, dict) else edge.model_dump(by_alias=True)
            from_node = edge_data.get("from")
            to_node = edge_data.get("to")

            if from_node not in dag.nodes:
                errors.append(f"边引用了不存在的源节点: {from_node}")
            if to_node not in dag.nodes and not (
                isinstance(to_node, str) and to_node.endswith("_recover")
            ):
                errors.append(f"边引用了不存在的目标节点: {to_node}")

        # 检查是否有循环引用
        node_stack = []
        for edge in dag.edges:
            edge_data = edge if isinstance(edge, dict) else edge.model_dump(by_alias=True)
            node_stack.append(edge_data["to"])

        # TODO: 实现完整的循环检测

        # 检查主线伏笔是否有目标章节
        for node_id, node_data in dag.nodes.items():
            node = node_data if isinstance(node_data, ForeshadowingNode) else ForeshadowingNode.model_validate(node_data)
            status = dag.status.get(node_id, "")
            if node.layer == "主线" and node.weight >= 9:
                if not node.target_chapter:
                    warnings.append(f"主线伏笔 {node_id} 未指定回收章节")

        # 检查待收伏笔是否超时（简化检查）
        # TODO: 实现完整的时间追踪

        return {"errors": errors, "warnings": warnings, "is_valid": len(errors) == 0}

    def get_statistics(self) -> Dict[str, Any]:
        """获取伏笔统计信息"""
        dag = self._load_dag()

        stats = {
            "total_nodes": len(dag.nodes),
            "total_edges": len(dag.edges),
            "by_status": {},
            "by_layer": {},
            "by_weight": {},
        }

        # 按状态统计
        for node_id, status in dag.status.items():
            if status not in stats["by_status"]:
                stats["by_status"][status] = 0
            stats["by_status"][status] += 1

        # 按层级统计
        for node_id, node_data in dag.nodes.items():
            layer = node_data.layer if isinstance(node_data, ForeshadowingNode) else node_data.get("layer", "")
            if layer not in stats["by_layer"]:
                stats["by_layer"][layer] = 0
            stats["by_layer"][layer] += 1

        # 按权重统计
        for node_id, node_data in dag.nodes.items():
            weight = node_data.weight if isinstance(node_data, ForeshadowingNode) else node_data.get("weight", 0)
            if str(weight) not in stats["by_weight"]:
                stats["by_weight"][str(weight)] = 0
            stats["by_weight"][str(weight)] += 1

        return stats

    def _log_operation(self, operation: str, message: str):
        """记录操作日志"""
        from datetime import datetime

        log_file = self.logs_dir / f"{datetime.now().strftime('%Y%m%d')}.log"
        log_entry = f"[{datetime.now().isoformat()}] {operation}: {message}\n"

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(log_entry)


# 示例使用
if __name__ == "__main__":
    # 在 OpenWrite 项目目录中运行
    manager = ForeshadowingDAGManager()

    # 创建示例伏笔节点
    manager.create_node(
        node_id="f001",
        content="主角发现父亲留下的神秘玉佩",
        weight=9,
        layer="主线",
        created_at="ch_001",
        target_chapter="ch_015",
        tags=["人物相关", "道具相关"],
    )

    # 创建伏笔边
    manager.create_edge("f001", "ch_015_recover", "依赖")

    # 更新状态
    manager.update_node_status("f001", "待收")

    # 查询统计
    stats = manager.get_statistics()
    print("伏笔统计:", stats)
