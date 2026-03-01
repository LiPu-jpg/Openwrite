"""Workflow Registry — 工作流注册表。

管理工作流定义，支持从 YAML 文件加载。
提供工作流匹配和查询功能。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

try:
    from tools.models.workflow import WorkflowDefinition, WorkflowPhase
    from tools.models.intent import TaskIntent
except ImportError:  # pragma: no cover
    from models.workflow import WorkflowDefinition, WorkflowPhase
    from models.intent import TaskIntent

logger = logging.getLogger(__name__)


class WorkflowRegistry:
    """工作流注册表。

    单例模式，管理所有已注册的工作流定义。
    支持：
    - 从 YAML 文件加载工作流
    - 根据意图和关键词匹配工作流
    - 按类别查询工作流
    """

    _instance: Optional["WorkflowRegistry"] = None

    def __new__(cls) -> "WorkflowRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._workflows: Dict[str, WorkflowDefinition] = {}
            cls._instance._intent_map: Dict[str, List[str]] = {}
            cls._instance._initialized = False
        return cls._instance

    def register(self, workflow: WorkflowDefinition) -> None:
        """注册工作流。

        Args:
            workflow: 工作流定义
        """
        self._workflows[workflow.workflow_id] = workflow

        # 建立意图到工作流的映射
        for intent_str in workflow.trigger_intents:
            if intent_str not in self._intent_map:
                self._intent_map[intent_str] = []
            if workflow.workflow_id not in self._intent_map[intent_str]:
                self._intent_map[intent_str].append(workflow.workflow_id)

        logger.debug(
            "Registered workflow: %s (intents: %s, keywords: %s)",
            workflow.workflow_id,
            workflow.trigger_intents,
            workflow.trigger_keywords,
        )

    def unregister(self, workflow_id: str) -> bool:
        """注销工作流。

        Args:
            workflow_id: 工作流ID

        Returns:
            是否成功注销
        """
        if workflow_id not in self._workflows:
            return False

        workflow = self._workflows.pop(workflow_id)

        # 从意图映射中移除
        for intent_str in workflow.trigger_intents:
            if intent_str in self._intent_map:
                if workflow_id in self._intent_map[intent_str]:
                    self._intent_map[intent_str].remove(workflow_id)

        logger.debug("Unregistered workflow: %s", workflow_id)
        return True

    def get_workflow(self, workflow_id: str) -> Optional[WorkflowDefinition]:
        """获取工作流定义。

        Args:
            workflow_id: 工作流ID

        Returns:
            工作流定义，不存在则返回 None
        """
        return self._workflows.get(workflow_id)

    def get_workflows_for_intent(self, intent: TaskIntent) -> List[WorkflowDefinition]:
        """获取处理某意图的所有工作流。

        Args:
            intent: 任务意图

        Returns:
            工作流列表，按优先级降序排列
        """
        intent_str = intent.value if isinstance(intent, TaskIntent) else str(intent)
        workflow_ids = self._intent_map.get(intent_str, [])
        workflows = [
            self._workflows[wid] for wid in workflow_ids if wid in self._workflows
        ]
        # 按优先级降序排列
        return sorted(workflows, key=lambda w: -w.priority)

    def match_workflow(
        self,
        intent: TaskIntent,
        user_message: str,
        context: Dict[str, Any],
    ) -> Optional[WorkflowDefinition]:
        """匹配最适合的工作流。

        根据意图、关键词和前置条件匹配最合适的工作流。

        Args:
            intent: 任务意图
            user_message: 用户消息
            context: 上下文数据

        Returns:
            匹配的工作流，无匹配则返回 None
        """
        candidates = self.get_workflows_for_intent(intent)

        if not candidates:
            logger.debug("No workflows found for intent: %s", intent)
            return None

        # 如果只有一个候选，检查前置条件后返回
        if len(candidates) == 1:
            if self._check_prerequisites(candidates[0], context):
                return candidates[0]
            return None

        # 根据关键词匹配度和前置条件选择
        best_match = None
        best_score = -1

        for workflow in candidates:
            # 检查前置条件
            if not self._check_prerequisites(workflow, context):
                continue

            # 计算关键词匹配分数
            score = 0
            for kw in workflow.trigger_keywords:
                if kw in user_message:
                    score += 1

            if score > best_score:
                best_score = score
                best_match = workflow

        # 如果没有关键词匹配，返回优先级最高的
        if best_match is None and candidates:
            for workflow in candidates:
                if self._check_prerequisites(workflow, context):
                    best_match = workflow
                    break

        logger.debug(
            "Matched workflow: %s (score: %s, intent: %s)",
            best_match.workflow_id if best_match else None,
            best_score,
            intent,
        )
        return best_match

    def _check_prerequisites(
        self,
        workflow: WorkflowDefinition,
        context: Dict[str, Any],
    ) -> bool:
        """检查工作流前置条件。

        Args:
            workflow: 工作流定义
            context: 上下文数据

        Returns:
            是否满足前置条件
        """
        if workflow.requires_novel_id and not context.get("novel_id"):
            return False

        if workflow.requires_outline and not context.get("has_outline"):
            return False

        if workflow.requires_characters and not context.get("has_characters"):
            return False

        return True

    def list_workflows(
        self,
        category: Optional[str] = None,
    ) -> List[WorkflowDefinition]:
        """列出所有工作流。

        Args:
            category: 可选的类别过滤

        Returns:
            工作流列表
        """
        workflows = list(self._workflows.values())
        if category:
            workflows = [w for w in workflows if w.category == category]
        return sorted(workflows, key=lambda w: (w.category, -w.priority, w.name))

    def list_categories(self) -> List[str]:
        """列出所有工作流类别。

        Returns:
            类别列表
        """
        categories = set(w.category for w in self._workflows.values())
        return sorted(categories)

    def load_from_yaml(self, path: Path) -> int:
        """从 YAML 文件加载工作流定义。

        Args:
            path: YAML 文件路径

        Returns:
            加载的工作流数量
        """
        if not path.exists():
            logger.warning("Workflow config file not found: %s", path)
            return 0

        try:
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            logger.error("Failed to parse YAML file %s: %s", path, e)
            return 0

        count = 0
        workflows_data = data.get("workflows", {})

        for workflow_id, workflow_data in workflows_data.items():
            try:
                # 解析阶段
                phases = []
                for phase_data in workflow_data.get("phases", []):
                    phases.append(WorkflowPhase(**phase_data))

                # 构建工作流定义
                workflow_dict = dict(workflow_data)
                workflow_dict["phases"] = phases
                workflow_dict["workflow_id"] = workflow_id

                workflow = WorkflowDefinition(**workflow_dict)
                self.register(workflow)
                count += 1

            except Exception as e:
                logger.error(
                    "Failed to load workflow %s from %s: %s",
                    workflow_id,
                    path,
                    e,
                )

        logger.info("Loaded %d workflows from %s", count, path)
        return count

    def load_from_directory(self, directory: Path) -> int:
        """从目录加载所有工作流定义。

        Args:
            directory: 目录路径

        Returns:
            加载的工作流总数
        """
        if not directory.exists():
            logger.warning("Workflow directory not found: %s", directory)
            return 0

        total = 0
        for yaml_file in sorted(directory.glob("*.yaml")):
            total += self.load_single_workflow(yaml_file)

        logger.info("Loaded %d total workflows from %s", total, directory)
        return total

    def load_single_workflow(self, path: Path) -> int:
        """从单个 YAML 文件加载工作流。

        支持两种格式：
        1. 直接定义工作流（workflow_id 作为顶级键）
        2. 包装格式（workflows: {id: ...}）

        Args:
            path: YAML 文件路径

        Returns:
            加载的工作流数量（0 或 1）
        """
        if not path.exists():
            return 0

        try:
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            logger.error("Failed to parse YAML file %s: %s", path, e)
            return 0

        # 检查是否是包装格式
        if "workflows" in data:
            return self.load_from_yaml(path)

        # 直接定义格式 - 检查是否有 workflow_id
        if "workflow_id" not in data:
            logger.warning("No workflow_id in %s", path)
            return 0

        try:
            # 解析阶段
            phases = []
            for phase_data in data.get("phases", []):
                phases.append(WorkflowPhase(**phase_data))

            # 构建工作流定义
            workflow_dict = dict(data)
            workflow_dict["phases"] = phases

            workflow = WorkflowDefinition(**workflow_dict)
            self.register(workflow)
            logger.info("Loaded workflow: %s from %s", workflow.workflow_id, path)
            return 1

        except Exception as e:
            logger.error("Failed to load workflow from %s: %s", path, e)
            return 0

    def clear(self) -> None:
        """清空所有已注册的工作流。"""
        self._workflows.clear()
        self._intent_map.clear()
        logger.debug("Cleared all workflows")

    def get_workflow_summary(self) -> Dict[str, Any]:
        """获取工作流注册表摘要。

        Returns:
            摘要信息
        """
        return {
            "total_workflows": len(self._workflows),
            "categories": self.list_categories(),
            "intent_coverage": {
                intent: len(workflows) for intent, workflows in self._intent_map.items()
            },
            "workflows": [
                {
                    "id": w.workflow_id,
                    "name": w.name,
                    "category": w.category,
                    "phases": len(w.phases),
                    "priority": w.priority,
                }
                for w in self._workflows.values()
            ],
        }


# 全局注册表实例
workflow_registry = WorkflowRegistry()


def init_workflows(project_dir: Optional[Path] = None) -> int:
    """初始化工作流系统。

    从多个位置加载工作流定义：
    1. 内置 workflows/ 目录
    2. skills/*/workflows/ 目录（技能工作流）
    3. 项目自定义 workflows/ 目录

    Args:
        project_dir: 项目目录（可选）

    Returns:
        加载的工作流总数
    """
    # 使用全局注册表
    registry = workflow_registry
    registry.clear()

    total = 0
    # workflow_registry.py 在 tools/ 下，所以 parent.parent 是项目根目录
    base_dir = Path(__file__).parent.parent

    # 1. 加载内置工作流
    builtin_dir = base_dir / "workflows"
    if builtin_dir.exists():
        total += registry.load_from_directory(builtin_dir)

    # 2. 加载技能工作流（skills/*/workflows/）
    skills_dir = base_dir / "skills"
    if skills_dir.exists():
        for skill_dir in skills_dir.iterdir():
            if skill_dir.is_dir():
                skill_workflow_dir = skill_dir / "workflows"
                if skill_workflow_dir.exists():
                    total += registry.load_from_directory(skill_workflow_dir)

    # 3. 加载项目自定义工作流
    if project_dir:
        project_workflow_dir = project_dir / "workflows"
        if project_workflow_dir.exists():
            total += registry.load_from_directory(project_workflow_dir)

    return total
