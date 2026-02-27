"""模型路由器 — 根据任务类型选择模型链。

任务类型分类：
- reasoning: 调度决策、路由分析（首选 Opus 4.6）
- generation: 文本生成、草稿写作（首选 Kimi K2.5 / MiniMax M2.5）
- review: 逻辑审查、一致性检查（首选 Opus 4.6）
- style: 风格分析、润色（首选 Kimi K2.5）
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from tools.llm.config import LLMConfig, TaskRouteConfig


class TaskType(str, Enum):
    """Agent 任务类型，决定模型路由。"""

    REASONING = "reasoning"  # Director 路由决策
    GENERATION = "generation"  # Librarian 草稿生成
    REVIEW = "review"  # LoreChecker 逻辑审查
    STYLE = "style"  # Stylist 风格润色 / Reader 抽取 / StyleDirector 分析


class ModelRouter:
    """根据任务类型从 LLMConfig 中选择模型路由链。

    用法：
        config = load_llm_config()
        router = ModelRouter(config)
        routes = router.get_routes(TaskType.GENERATION)
        response = client.complete_with_fallback(messages, routes)
    """

    def __init__(self, config: LLMConfig):
        self._config = config

    @property
    def enabled(self) -> bool:
        """LLM 是否全局启用。"""
        return self._config.enabled

    def get_route_config(self, task_type: TaskType) -> TaskRouteConfig:
        """获取指定任务类型的路由配置。

        Args:
            task_type: 任务类型枚举

        Returns:
            TaskRouteConfig，未找到时返回 default_route
        """
        return self._config.routes.get(task_type.value, self._config.default_route)

    def get_routes(self, task_type: TaskType) -> List[Dict[str, Any]]:
        """获取指定任务类型的模型路由链（primary + fallbacks）。

        返回格式兼容 LLMClient.complete_with_fallback() 的 routes 参数。

        Args:
            task_type: 任务类型枚举

        Returns:
            模型路由字典列表，按优先级排序
        """
        route_config = self.get_route_config(task_type)
        routes: List[Dict[str, Any]] = []

        # Primary
        routes.append(self._route_to_dict(route_config.primary))

        # Fallbacks
        for fb in route_config.fallbacks:
            routes.append(self._route_to_dict(fb))

        return routes

    def get_primary_model(self, task_type: TaskType) -> str:
        """获取指定任务类型的首选模型名。"""
        route_config = self.get_route_config(task_type)
        return route_config.primary.model

    @staticmethod
    def _route_to_dict(route: Any) -> Dict[str, Any]:
        """将 ModelRoute 转为 dict，供 LLMClient 使用。"""
        result: Dict[str, Any] = {
            "model": route.model,
            "max_tokens": route.max_tokens,
            "temperature": route.temperature,
            "timeout": route.timeout,
        }
        if route.api_base:
            result["api_base"] = route.api_base
        if route.api_key_env:
            result["api_key_env"] = route.api_key_env
        return result
