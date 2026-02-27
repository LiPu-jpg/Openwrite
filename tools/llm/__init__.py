"""LLM integration package for OpenWrite.

提供 LiteLLM 封装、多模型路由、配置管理。
所有 Agent 通过 LLMClient 可选接入 LLM，不接入时保持原有规则模拟。
"""

from tools.llm.client import LLMClient
from tools.llm.config import LLMConfig, ModelRoute, load_llm_config
from tools.llm.router import TaskType, ModelRouter

__all__ = [
    "LLMClient",
    "LLMConfig",
    "ModelRoute",
    "load_llm_config",
    "TaskType",
    "ModelRouter",
]
