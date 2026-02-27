"""LLM 配置模型 — Pydantic v2 数据结构 + YAML 加载。

支持多模型路由：不同任务类型（决策/生成/审查）可指定不同模型链。
API key 通过环境变量注入，不存储在配置文件中。
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import yaml
from pydantic import BaseModel, Field


class ModelRoute(BaseModel):
    """单个模型路由配置。

    Attributes:
        model: LiteLLM 模型标识符（如 "anthropic/claude-opus-4-20250918"）
        api_base: OpenAI 兼容端点 URL（用于 Kimi/MiniMax 等）
        api_key_env: 环境变量名，运行时读取 API key
        max_tokens: 最大生成 token 数
        temperature: 采样温度
        timeout: 请求超时秒数
    """

    model: str
    api_base: Optional[str] = None
    api_key_env: str = ""
    max_tokens: int = 4096
    temperature: float = 0.7
    timeout: int = 120


class TaskRouteConfig(BaseModel):
    """任务类型的模型路由链 — 按优先级尝试，失败自动 fallback。

    Attributes:
        primary: 首选模型
        fallbacks: 备选模型列表，按顺序尝试
    """

    primary: ModelRoute
    fallbacks: List[ModelRoute] = Field(default_factory=list)


class LLMConfig(BaseModel):
    """全局 LLM 配置。

    Attributes:
        enabled: 全局开关，False 时所有 Agent 使用规则模拟
        default_route: 未指定任务类型时的默认路由
        routes: 按任务类型的模型路由映射
        retry_count: 单个模型的重试次数
        retry_delay: 重试间隔秒数
    """

    enabled: bool = False
    default_route: TaskRouteConfig = Field(
        default_factory=lambda: TaskRouteConfig(
            primary=ModelRoute(
                model="deepseek/deepseek-chat", api_key_env="DEEPSEEK_API_KEY"
            )
        )
    )
    routes: Dict[str, TaskRouteConfig] = Field(default_factory=dict)
    retry_count: int = 2
    retry_delay: float = 1.0


def load_llm_config(config_path: Optional[Path] = None) -> LLMConfig:
    """从 YAML 文件加载 LLM 配置。

    Args:
        config_path: 配置文件路径，默认为项目根目录的 llm_config.yaml

    Returns:
        LLMConfig 实例。文件不存在时返回默认配置（disabled）。
    """
    if config_path is None:
        # 尝试多个常见位置
        candidates = [
            Path("llm_config.yaml"),
            Path("config/llm_config.yaml"),
        ]
        for candidate in candidates:
            if candidate.exists():
                config_path = candidate
                break

    if config_path is None or not config_path.exists():
        return LLMConfig(enabled=False)

    with config_path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not raw or not isinstance(raw, dict):
        return LLMConfig(enabled=False)

    return _parse_config(raw)


def _parse_config(raw: dict) -> LLMConfig:
    """解析原始 YAML dict 为 LLMConfig。"""
    enabled = raw.get("enabled", False)
    retry_count = raw.get("retry_count", 2)
    retry_delay = raw.get("retry_delay", 1.0)

    # 解析 default_route
    default_raw = raw.get("default_route", {})
    default_route = _parse_task_route(default_raw) if default_raw else None

    # 解析 routes
    routes: Dict[str, TaskRouteConfig] = {}
    for task_type, route_raw in raw.get("routes", {}).items():
        routes[task_type] = _parse_task_route(route_raw)

    kwargs: dict = {
        "enabled": enabled,
        "retry_count": retry_count,
        "retry_delay": retry_delay,
        "routes": routes,
    }
    if default_route:
        kwargs["default_route"] = default_route

    return LLMConfig(**kwargs)


def _parse_task_route(raw: dict) -> TaskRouteConfig:
    """解析单个任务路由配置。"""
    primary = ModelRoute(**raw.get("primary", {}))
    fallbacks = [ModelRoute(**fb) for fb in raw.get("fallbacks", [])]
    return TaskRouteConfig(primary=primary, fallbacks=fallbacks)
