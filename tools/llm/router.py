"""模型路由器 — 根据任务类型从模型池中选择模型链。

任务类型分类：
- reasoning: 调度决策、路由分析（Director）
- generation: 文本生成、草稿写作（Librarian）
- review: 逻辑审查、一致性检查（LoreChecker）
- style: 风格分析、润色（Stylist/Reader/StyleDirector）
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from tools.llm.config import LLMConfig, ModelConfig


class TaskType(str, Enum):
    """Agent 任务类型，决定模型路由。"""

    REASONING = "reasoning"  # Director 路由决策
    GENERATION = "generation"  # Librarian 草稿生成
    REVIEW = "review"  # LoreChecker 逻辑审查
    STYLE = "style"  # Stylist 风格润色 / Reader 抽取 / StyleDirector 分析


class ModelRouter:
    """根据任务类型从模型池中选择模型路由链。

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

    def get_routes(self, task_type: TaskType) -> List[Dict[str, Any]]:
        """获取指定任务类型的模型路由链（按优先级排序）。

        返回格式兼容 LLMClient.complete_with_fallback() 的 routes 参数。

        Args:
            task_type: 任务类型枚举

        Returns:
            模型路由字典列表，按优先级排序
        """
        route_config = self._config.routes.get(task_type.value)
        if not route_config or not route_config.models:
            # 无配置时返回空列表，由 LLMClient fallback 到规则引擎
            return []

        routes: List[Dict[str, Any]] = []
        # 首选模型
        primary_name = route_config.models[route_config.primary_index]
        if primary_name in self._config.models:
            routes.append(self._model_to_dict(self._config.models[primary_name]))

        # 备选模型（跳过首选）
        for i, model_name in enumerate(route_config.models):
            if i != route_config.primary_index and model_name in self._config.models:
                routes.append(self._model_to_dict(self._config.models[model_name]))

        return routes

    def get_primary_model(self, task_type: TaskType) -> Optional[str]:
        """获取指定任务类型的首选模型名。"""
        route_config = self._config.routes.get(task_type.value)
        if not route_config or not route_config.models:
            return None
        primary_name = route_config.models[route_config.primary_index]
        model_cfg = self._config.models.get(primary_name)
        return model_cfg.model if model_cfg else None

    @staticmethod
    def _model_to_dict(model: ModelConfig) -> Dict[str, Any]:
        """将 ModelConfig 转为 dict，供 LLMClient 使用。"""
        result: Dict[str, Any] = {
            "model": model.model,
            "max_tokens": model.max_tokens,
            "temperature": model.temperature,
            "timeout": model.timeout,
        }
        if model.api_base:
            result["api_base"] = model.api_base
        if model.api_key_env:
            result["api_key_env"] = model.api_key_env
        return result
