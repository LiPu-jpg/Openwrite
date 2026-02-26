"""
伏笔状态检查器
提供伏笔的验证、状态检查和错误报告功能
"""

from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
from rich.panel import Panel
from rich.console import Console
from rich.table import Table

try:
    from tools.graph.foreshadowing_dag import ForeshadowingDAGManager
    from tools.models.foreshadowing import ForeshadowingNode
except ImportError:  # pragma: no cover - supports legacy path injection
    from graph.foreshadowing_dag import ForeshadowingDAGManager
    from models.foreshadowing import ForeshadowingNode


console = Console()


class ForeshadowingChecker:
    """伏笔状态检查器"""

    def __init__(self, project_dir: Optional[Path] = None):
        self.project_dir = project_dir or self._find_project_dir()
        self.dag_manager = ForeshadowingDAGManager(self.project_dir)

    def _find_project_dir(self) -> Path:
        """查找项目根目录"""
        cwd = Path.cwd()
        for parent in [cwd] + list(cwd.parents):
            if (parent / "data" / "novels").exists() and (parent / "tools").exists():
                return parent
        return cwd

    def check_all(self) -> Dict[str, Any]:
        """执行所有检查"""
        results = {
            "timestamp": datetime.now().isoformat(),
            "errors": [],
            "warnings": [],
            "info": [],
            "statistics": {},
        }

        # 1. 检查 DAG 结构完整性
        dag_results = self._check_dag_integrity()
        results["errors"].extend(dag_results.get("errors", []))
        results["warnings"].extend(dag_results.get("warnings", []))

        # 2. 检查伏笔状态一致性
        status_results = self._check_status_consistency()
        results["errors"].extend(status_results.get("errors", []))
        results["warnings"].extend(status_results.get("warnings", []))

        # 3. 检查主线伏笔回收计划
        mainline_results = self._check_mainline_recovery_plan()
        results["warnings"].extend(mainline_results.get("warnings", []))
        results["info"].extend(mainline_results.get("info", []))

        # 4. 检查权重合理性
        weight_results = self._check_weight_reasonableness()
        results["warnings"].extend(weight_results.get("warnings", []))

        # 5. 生成统计信息
        results["statistics"] = self.dag_manager.get_statistics()

        return results

    def _check_dag_integrity(self) -> Dict[str, List[str]]:
        """检查 DAG 结构完整性"""
        results = {"errors": [], "warnings": []}
        dag = self.dag_manager._load_dag()

        # 检查边引用的节点是否存在
        for edge in dag.edges:
            edge_data = edge if isinstance(edge, dict) else edge.model_dump(by_alias=True)
            from_node = edge_data.get("from")
            to_node = edge_data.get("to")

            if from_node not in dag.nodes:
                results["errors"].append(f"错误: 边引用了不存在的源节点 '{from_node}'")

            if to_node not in dag.nodes and not (isinstance(to_node, str) and to_node.endswith("_recover")):
                results["errors"].append(f"错误: 边引用了不存在的目标节点 '{to_node}'")

        # 检查是否有孤立节点（没有边的节点）
        connected_nodes = set()
        for edge in dag.edges:
            edge_data = edge if isinstance(edge, dict) else edge.model_dump(by_alias=True)
            connected_nodes.add(edge_data.get("from"))
            connected_nodes.add(edge_data.get("to"))

        isolated = set(dag.nodes.keys()) - connected_nodes
        if isolated:
            results["warnings"].append(
                f"警告: 以下伏笔节点没有关联边（孤立节点）: {', '.join(isolated)}"
            )

        return results

    def _check_status_consistency(self) -> Dict[str, List[str]]:
        """检查伏笔状态一致性"""
        results = {"errors": [], "warnings": []}
        dag = self.dag_manager._load_dag()

        for node_id, node_data in dag.nodes.items():
            status = dag.status.get(node_id, "")
            node = node_data if isinstance(node_data, ForeshadowingNode) else ForeshadowingNode(**node_data)

            # 检查状态值是否有效
            valid_statuses = ["埋伏", "待收", "已收", "废弃"]
            if status not in valid_statuses:
                results["errors"].append(
                    f"错误: 伏笔 '{node_id}' 的状态 '{status}' 无效，"
                    f"应为: {', '.join(valid_statuses)}"
                )

            # 检查主线高权重伏笔的状态
            if node.layer == "主线" and node.weight >= 9:
                if status == "废弃":
                    results["warnings"].append(
                        f"警告: 主线高权重伏笔 '{node_id}' (权重{node.weight})被标记为废弃，"
                        f"请确认是否故意为之"
                    )

            # 检查已收状态但没有 target_chapter
            if status == "已收" and not node.target_chapter:
                results["info"].append(f"信息: 伏笔 '{node_id}' 已回收但未记录回收章节")

        return results

    def _check_mainline_recovery_plan(self) -> Dict[str, List[str]]:
        """检查主线伏笔回收计划"""
        results = {"warnings": [], "info": []}
        dag = self.dag_manager._load_dag()

        for node_id, node_data in dag.nodes.items():
            node = node_data if isinstance(node_data, ForeshadowingNode) else ForeshadowingNode(**node_data)
            status = dag.status.get(node_id, "")

            # 主线伏笔（权重 >= 9）应该有明确的回收计划
            if node.layer == "主线" and node.weight >= 9:
                if not node.target_chapter:
                    if status in ["埋伏", "待收"]:
                        results["warnings"].append(
                            f"警告: 主线伏笔 '{node_id}' (权重{node.weight})"
                            f"未指定预期回收章节"
                        )
                else:
                    results["info"].append(
                        f"信息: 主线伏笔 '{node_id}' 计划在 {node.target_chapter} 回收"
                    )

        return results

    def _check_weight_reasonableness(self) -> Dict[str, List[str]]:
        """检查权重合理性"""
        results = {"warnings": []}
        dag = self.dag_manager._load_dag()

        weight_distribution = {"主线": [], "支线": [], "彩蛋": []}

        for node_id, node_data in dag.nodes.items():
            node = node_data if isinstance(node_data, ForeshadowingNode) else ForeshadowingNode(**node_data)
            if node.layer in weight_distribution:
                weight_distribution[node.layer].append((node_id, node.weight))

        # 检查主线伏笔权重是否都 >= 7
        for node_id, weight in weight_distribution["主线"]:
            if weight < 7:
                results["warnings"].append(
                    f"警告: 主线伏笔 '{node_id}' 权重为 {weight}，建议主线伏笔权重 >= 7"
                )

        # 检查彩蛋伏笔权重是否都 <= 5
        for node_id, weight in weight_distribution["彩蛋"]:
            if weight > 5:
                results["warnings"].append(
                    f"警告: 彩蛋伏笔 '{node_id}' 权重为 {weight}，建议彩蛋伏笔权重 <= 5"
                )

        return results

    def get_recovery_timeline(self) -> List[Dict[str, Any]]:
        """获取伏笔回收时间线"""
        dag = self.dag_manager._load_dag()
        timeline = []

        for node_id, node_data in dag.nodes.items():
            node = node_data if isinstance(node_data, ForeshadowingNode) else ForeshadowingNode(**node_data)
            status = dag.status.get(node_id, "")

            if node.target_chapter and status in ["埋伏", "待收"]:
                timeline.append(
                    {
                        "node_id": node_id,
                        "target_chapter": node.target_chapter,
                        "weight": node.weight,
                        "layer": node.layer,
                        "content": node.content[:50] + "..."
                        if len(node.content) > 50
                        else node.content,
                    }
                )

        # 按目标章节排序
        timeline.sort(key=lambda x: x["target_chapter"])
        return timeline

    def print_report(self, results: Dict[str, Any]):
        """打印检查报告"""
        console.print(
            Panel("[bold cyan]伏笔状态检查报告[/bold cyan]", border_style="cyan")
        )

        # 统计信息
        stats = results["statistics"]
        console.print("\n[bold]统计信息:[/bold]")
        console.print(f"  总伏笔数: {stats.get('total_nodes', 0)}")
        console.print(f"  总关系数: {stats.get('total_edges', 0)}")

        if "by_status" in stats:
            console.print("\n[bold]按状态分布:[/bold]")
            for status, count in stats["by_status"].items():
                console.print(f"  {status}: {count}")

        if "by_layer" in stats:
            console.print("\n[bold]按层级分布:[/bold]")
            for layer, count in stats["by_layer"].items():
                console.print(f"  {layer}: {count}")

        # 错误
        if results["errors"]:
            console.print("\n[bold red]错误 ({}):[/bold red]".format(len(results["errors"])))
            for error in results["errors"]:
                console.print(f"  • {error}")

        # 警告
        if results["warnings"]:
            console.print(
                "\n[bold yellow]警告 ({}):[/bold yellow]".format(len(results["warnings"]))
            )
            for warning in results["warnings"]:
                console.print(f"  • {warning}")

        # 信息
        if results["info"]:
            console.print(
                "\n[bold blue]信息 ({}):[/bold blue]".format(len(results["info"]))
            )
            for info in results["info"]:
                console.print(f"  • {info}")

        # 如果没有问题
        if not results["errors"] and not results["warnings"]:
            console.print("\n[bold green]所有检查通过，没有发现问题。[/bold green]")

        # 回收时间线
        timeline = self.get_recovery_timeline()
        if timeline:
            console.print("\n[bold]伏笔回收计划:[/bold]")
            table = Table(show_header=True, header_style="bold magenta")
            table.add_column("章节", style="cyan")
            table.add_column("伏笔ID", style="green")
            table.add_column("权重", style="yellow")
            table.add_column("层级", style="blue")
            table.add_column("内容", style="white")

            for item in timeline[:10]:  # 只显示前10个
                table.add_row(
                    item["target_chapter"],
                    item["node_id"],
                    str(item["weight"]),
                    item["layer"],
                    item["content"],
                )

            console.print(table)

            if len(timeline) > 10:
                console.print(f"... 还有 {len(timeline) - 10} 个伏笔待回收")


# 便捷函数
def check_foreshadowings(project_dir: Optional[Path] = None) -> Dict[str, Any]:
    """快速检查伏笔状态"""
    checker = ForeshadowingChecker(project_dir)
    results = checker.check_all()
    checker.print_report(results)
    return results


if __name__ == "__main__":
    # 示例：运行检查
    results = check_foreshadowings()
