"""LLM integration package for OpenWrite.

Provides:
- LLMClient: LiteLLM wrapper with retry and fallback
- ModelRouter: Task-based model routing
- LLMConfig: Configuration models
- PromptBuilder: Agent prompts
- Tool schema generation for LLM tool calling
"""

from .client import LLMClient, LLMResponse
from .config import LLMConfig, ModelConfig, TaskRouteConfig, load_llm_config
from .router import ModelRouter, TaskType
from .prompts import PromptBuilder

# Tool schema generation (for LLM tool calling)
try:
    from .tool_schema import (
        skill_to_tool_schema,
        executor_tool_to_schema,
        get_all_tool_schemas,
        get_director_tool_schemas,
        format_tools_for_prompt,
    )
except ImportError:
    # tool_schema.py may not exist yet
    pass

__all__ = [
    # Client
    "LLMClient",
    "LLMResponse",
    # Config
    "LLMConfig",
    "ModelConfig",
    "TaskRouteConfig",
    "load_llm_config",
    # Router
    "TaskType",
    "ModelRouter",
    # Prompts
    "PromptBuilder",
    # Tool schema
    "skill_to_tool_schema",
    "executor_tool_to_schema",
    "get_all_tool_schemas",
    "get_director_tool_schemas",
    "format_tools_for_prompt",
]
