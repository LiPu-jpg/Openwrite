"""伏笔 DAG 管理器

支持：
- 节点 CRUD（创建/读取/更新/删除）
- 权重过滤查询
- 依赖关系管理
- DAG 拓扑验证（环检测）
- 状态统计
"""

from __future__ import annotations

import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime

import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from tools.file_ops import atomic_write
from models.foreshadowing import (
    ForeshadowingNode,
    ForeshadowingEdge,
    ForeshadowingGraph,
)


class ForeshadowingDagError(RuntimeError):
    """The foreshadowing DAG could not be read or written.

    Raised rather than swallowed: an unreadable DAG used to degrade to an empty
    graph, which silently erased every foreshadowing record.
    """


class ForeshadowingDAGManager:
    """伏笔 DAG 管理器

    Usage:
        manager = ForeshadowingDAGManager(
            project_dir=Path("/path/to/project"),
            novel_id="my_novel"
        )

        # 创建伏笔节点
        manager.create_node(
            node_id="f001",
            content="主角发现父亲留下的神秘玉佩",
            weight=9,
            layer="主线",
            created_at="ch_001",
            target_chapter="ch_015"
        )

        # 查询待回收伏笔
        pending = manager.get_pending_nodes(min_weight=5)

        # 验证 DAG（环检测）
        is_valid, errors = manager.validate_dag()
    """

    def __init__(self, project_dir: Optional[Path] = None, novel_id: str = "my_novel"):
        self.project_dir = (
            Path(project_dir).resolve() if project_dir else self._find_project_dir()
        )
        self.novel_id = novel_id
        self.dag_file = (
            self.project_dir
            / "data"
            / "novels"
            / self.novel_id
            / "data"
            / "foreshadowing"
            / "dag.yaml"
        )
        self.logs_dir = (
            self.project_dir
            / "data"
            / "novels"
            / self.novel_id
            / "data"
            / "foreshadowing"
            / "logs"
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
                data = yaml.safe_load(f) or {}
                return ForeshadowingGraph.model_validate(data)
        except Exception as e:
            # An unreadable DAG used to be swallowed into an empty graph, so a
            # truncated write made every foreshadowing record vanish with no
            # error anywhere. Preserve the file and refuse instead.
            raise ForeshadowingDagError(
                f"伏笔 DAG 无法读取（文件已保留，未覆盖）: {e}"
            ) from e

    def _save_dag(self, dag: ForeshadowingGraph) -> None:
        """保存 DAG 配置"""
        # Atomic replace: a bare open(...,"w") truncates in place, so a crash
        # mid-dump left a half-written DAG that the next read parsed as empty.
        atomic_write(
            self.dag_file,
            yaml.dump(
                dag.model_dump(by_alias=True),
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            ),
        )

    # ── 节点操作 ──────────────────────────────────────────────────

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
        """创建伏笔节点

        Args:
            node_id: 伏笔唯一标识
            content: 伏笔内容描述
            weight: 权重 1-10（默认5）
            layer: 层级（主线/支线/彩蛋）
            created_at: 创建章节
            target_chapter: 计划回收章节
            tags: 标签列表

        Returns:
            True 创建成功，False 已存在
        """
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

    def get_node(self, node_id: str) -> Optional[ForeshadowingNode]:
        """获取伏笔节点"""
        dag = self._load_dag()
        return dag.nodes.get(node_id)

    def update_node_status(self, node_id: str, new_status: str) -> bool:
        """更新伏笔节点状态

        Args:
            node_id: 节点 ID
            new_status: 新状态（埋伏/待收/已收/废弃）
        """
        dag = self._load_dag()

        if node_id not in dag.nodes:
            print(f"伏笔节点不存在: {node_id}")
            return False

        node = dag.nodes[node_id]
        node.status = new_status
        dag.status[node_id] = new_status
        self._save_dag(dag)

        self._log_operation("update_status", f"{node_id}: {new_status}")
        return True

    def delete_node(self, node_id: str) -> bool:
        """删除伏笔节点"""
        dag = self._load_dag()

        if node_id not in dag.nodes:
            return False

        del dag.nodes[node_id]
        if node_id in dag.status:
            del dag.status[node_id]

        # 删除相关边
        dag.edges = [e for e in dag.edges if e.from_ != node_id and e.to != node_id]

        self._save_dag(dag)
        self._log_operation("delete_node", f"删除伏笔节点: {node_id}")
        return True

    # ── 边操作 ──────────────────────────────────────────────────

    def create_edge(
        self, from_node: str, to_node: str, edge_type: str = "依赖"
    ) -> bool:
        """创建伏笔关系边

        Args:
            from_node: 源节点 ID
            to_node: 目标节点 ID（可以是另一个伏笔或章节）
            edge_type: 关系类型（依赖/强化/反转）
        """
        dag = self._load_dag()

        # 检查源节点存在
        if from_node not in dag.nodes:
            print(f"源伏笔节点不存在: {from_node}")
            return False

        # 检查边是否已存在
        for edge in dag.edges:
            if edge.from_ == from_node and edge.to == to_node:
                print(f"边已存在: {from_node} -> {to_node}")
                return False

        edge = ForeshadowingEdge(from_=from_node, to=to_node, type=edge_type)
        dag.edges.append(edge)
        self._save_dag(dag)

        self._log_operation("create_edge", f"{from_node} -> {to_node} ({edge_type})")
        return True

    # ── 查询操作 ──────────────────────────────────────────────────

    def get_pending_nodes(
        self, min_weight: int = 1, layer: Optional[str] = None
    ) -> List[ForeshadowingNode]:
        """获取待回收的伏笔节点

        Args:
            min_weight: 最小权重过滤
            layer: 层级过滤（可选）
        """
        dag = self._load_dag()
        results = []

        for node_id, node in dag.nodes.items():
            if dag.status.get(node_id) not in ["埋伏", "待收"]:
                continue
            if node.weight < min_weight:
                continue
            if layer and node.layer != layer:
                continue
            results.append(node)

        # 按权重降序
        results.sort(key=lambda n: n.weight, reverse=True)
        return results

    def get_nodes(
        self,
        *,
        status: Optional[str] = None,
        min_weight: int = 1,
        layer: Optional[str] = None,
    ) -> List[ForeshadowingNode]:
        """List nodes with the filters exposed by the public tool contract."""
        dag = self._load_dag()
        results = [
            node
            for node_id, node in dag.nodes.items()
            if (not status or dag.status.get(node_id, node.status) == status)
            and node.weight >= min_weight
            and (not layer or node.layer == layer)
        ]
        results.sort(key=lambda node: node.weight, reverse=True)
        return results

    def get_nodes_for_chapter(self, chapter_id: str) -> List[ForeshadowingNode]:
        """获取某章节相关的伏笔

        包括：
        - 在该章节埋下的
        - 计划在该章节回收的
        """
        dag = self._load_dag()
        results = []

        for node in dag.nodes.values():
            # 在该章节埋下
            if node.created_at == chapter_id:
                results.append(node)
            # 计划在该章节回收
            elif node.target_chapter == chapter_id:
                results.append(node)

        return results

    # ── DAG 验证 ──────────────────────────────────────────────────

    def validate_dag(self) -> tuple[bool, List[str]]:
        """验证 DAG 拓扑结构

        Returns:
            (is_valid, errors)
            - is_valid: 是否有效
            - errors: 错误列表
        """
        dag = self._load_dag()
        errors = []

        # 1. 检测环
        visited = set()
        rec_stack = set()

        def dfs(node_id: str) -> bool:
            """DFS 检测环"""
            if node_id in rec_stack:
                return True  # 发现环
            if node_id in visited:
                return False

            visited.add(node_id)
            rec_stack.add(node_id)

            # 遍历出边
            for edge in dag.edges:
                if edge.from_ == node_id:
                    if dfs(edge.to):
                        return True

            rec_stack.remove(node_id)
            return False

        for node_id in dag.nodes:
            if node_id not in visited:
                if dfs(node_id):
                    errors.append(f"检测到环: 涉及节点 {node_id}")

        # 2. 检查孤立节点（有边引用但不存在的节点）
        all_node_ids = set(dag.nodes.keys())
        for edge in dag.edges:
            if edge.from_ not in all_node_ids:
                errors.append(f"边引用了不存在的源节点: {edge.from_}")
            # 目标可以是章节，不一定是伏笔节点

        # 3. 检查超期未回收的伏笔（相对当前最新正文/配置章节）
        current_chapter_num = self._resolve_current_chapter_number()
        if current_chapter_num is not None:
            open_statuses = {"埋伏", "待收", "pending", "open"}
            for node_id, node in dag.nodes.items():
                status = str(dag.status.get(node_id) or node.status or "").strip()
                if status not in open_statuses:
                    continue
                target = str(node.target_chapter or "").strip()
                target_num = self._chapter_number(target)
                if target_num is None:
                    continue
                if current_chapter_num > target_num:
                    errors.append(
                        f"伏笔超期未回收: {node_id} 目标 {target}，"
                        f"当前已推进到 ch_{current_chapter_num:03d}"
                    )

        is_valid = len(errors) == 0
        return is_valid, errors

    def _resolve_current_chapter_number(self) -> int | None:
        config_path = self.project_dir / "novel_config.yaml"
        candidates: list[int] = []
        if config_path.is_file():
            try:
                data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError):
                data = {}
            if isinstance(data, dict):
                num = self._chapter_number(str(data.get("current_chapter") or ""))
                if num is not None:
                    candidates.append(num)

        manuscript_root = (
            self.project_dir
            / "data"
            / "novels"
            / self.novel_id
            / "data"
            / "manuscript"
        )
        if manuscript_root.is_dir():
            for path in manuscript_root.glob("arc_*/ch_*.md"):
                num = self._chapter_number(path.stem)
                if num is not None:
                    candidates.append(num)
        return max(candidates) if candidates else None

    @staticmethod
    def _chapter_number(value: str) -> int | None:
        import re

        match = re.search(r"(\d+)", str(value or ""))
        return int(match.group(1)) if match else None

    # ── 统计 ──────────────────────────────────────────────────

    def get_statistics(self) -> Dict[str, Any]:
        """获取伏笔统计信息"""
        dag = self._load_dag()
        stats = {
            "total": len(dag.nodes),
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
        for node in dag.nodes.values():
            layer = node.layer
            if layer not in stats["by_layer"]:
                stats["by_layer"][layer] = 0
            stats["by_layer"][layer] += 1

        # 按权重统计
        for node in dag.nodes.values():
            weight = str(node.weight)
            if weight not in stats["by_weight"]:
                stats["by_weight"][weight] = 0
            stats["by_weight"][weight] += 1

        return stats

    # ── 日志 ──────────────────────────────────────────────────

    def _log_operation(self, operation: str, message: str) -> None:
        """记录操作日志"""
        log_file = self.logs_dir / f"{datetime.now().strftime('%Y%m%d')}.log"
        log_entry = f"[{datetime.now().isoformat()}] {operation}: {message}\n"

        with open(log_file, "a", encoding="utf-8") as f:
            f.write(log_entry)


# ┺─ 示例使用 ──────────────────────────────────────────────────
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
