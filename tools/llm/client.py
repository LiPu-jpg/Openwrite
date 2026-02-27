"""LLM 客户端 — LiteLLM 封装，支持重试、fallback、流式输出。

核心设计：
- 所有 LLM 调用通过 LLMClient.complete() 统一入口
- 自动按 fallback 链尝试多个模型
- 支持同步调用（默认）和流式输出
- API key 从环境变量读取，不硬编码
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class LLMResponse:
    """LLM 调用结果。

    Attributes:
        content: 生成的文本内容
        model: 实际使用的模型标识符
        usage: token 用量统计
        raw: 原始响应对象（调试用）
    """

    content: str
    model: str
    usage: Dict[str, int] = field(default_factory=dict)
    raw: Optional[Any] = None


class LLMClient:
    """LiteLLM 封装客户端。

    用法：
        client = LLMClient()
        response = client.complete(
            messages=[{"role": "user", "content": "你好"}],
            model="anthropic/claude-opus-4-20250918",
        )
        print(response.content)
    """

    def __init__(
        self,
        retry_count: int = 2,
        retry_delay: float = 1.0,
    ):
        self.retry_count = retry_count
        self.retry_delay = retry_delay
        self._litellm = None

    def _ensure_litellm(self) -> Any:
        """延迟导入 litellm，避免未安装时影响其他功能。"""
        if self._litellm is None:
            try:
                import litellm

                litellm.drop_params = True  # 忽略不支持的参数
                self._litellm = litellm
            except ImportError:
                raise ImportError(
                    "litellm 未安装。请运行: pip install litellm\n"
                    "或在 requirements.txt 中添加 litellm>=1.40.0"
                )
        return self._litellm

    def complete(
        self,
        messages: List[Dict[str, str]],
        model: str,
        api_base: Optional[str] = None,
        api_key_env: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.7,
        timeout: int = 120,
        **kwargs: Any,
    ) -> LLMResponse:
        """调用 LLM 生成文本。

        Args:
            messages: OpenAI 格式的消息列表
            model: LiteLLM 模型标识符
            api_base: OpenAI 兼容端点（用于 Kimi/MiniMax 等）
            api_key_env: 环境变量名，读取 API key
            max_tokens: 最大生成 token 数
            temperature: 采样温度
            timeout: 请求超时秒数
            **kwargs: 传递给 litellm.completion 的额外参数

        Returns:
            LLMResponse 包含生成内容和元数据

        Raises:
            RuntimeError: 所有重试均失败
        """
        litellm = self._ensure_litellm()

        # 构建调用参数
        call_kwargs: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "timeout": timeout,
        }

        # API key 注入
        if api_key_env:
            api_key = os.environ.get(api_key_env, "")
            if api_key:
                call_kwargs["api_key"] = api_key

        # OpenAI 兼容端点
        if api_base:
            call_kwargs["api_base"] = api_base

        call_kwargs.update(kwargs)

        last_error: Optional[Exception] = None
        for attempt in range(self.retry_count + 1):
            try:
                response = litellm.completion(**call_kwargs)
                content = response.choices[0].message.content or ""
                usage = {}
                if hasattr(response, "usage") and response.usage:
                    usage = {
                        "prompt_tokens": getattr(response.usage, "prompt_tokens", 0),
                        "completion_tokens": getattr(
                            response.usage, "completion_tokens", 0
                        ),
                        "total_tokens": getattr(response.usage, "total_tokens", 0),
                    }
                return LLMResponse(
                    content=content,
                    model=model,
                    usage=usage,
                    raw=response,
                )
            except Exception as e:
                last_error = e
                logger.warning(
                    "LLM 调用失败 (model=%s, attempt=%d/%d): %s",
                    model,
                    attempt + 1,
                    self.retry_count + 1,
                    str(e),
                )
                if attempt < self.retry_count:
                    time.sleep(self.retry_delay * (attempt + 1))

        raise RuntimeError(
            f"LLM 调用失败，已重试 {self.retry_count} 次。"
            f"模型: {model}, 最后错误: {last_error}"
        )

    def complete_with_fallback(
        self,
        messages: List[Dict[str, str]],
        routes: List[Dict[str, Any]],
        **kwargs: Any,
    ) -> LLMResponse:
        """按 fallback 链依次尝试多个模型。

        Args:
            messages: OpenAI 格式的消息列表
            routes: 模型路由列表，每项包含 model, api_base, api_key_env 等
            **kwargs: 传递给 complete() 的额外参数

        Returns:
            第一个成功的 LLMResponse

        Raises:
            RuntimeError: 所有模型均失败
        """
        errors: List[str] = []
        for route in routes:
            try:
                merged = {**route, **kwargs}
                return self.complete(messages=messages, **merged)
            except (RuntimeError, Exception) as e:
                model_name = route.get("model", "unknown")
                errors.append(f"{model_name}: {str(e)}")
                logger.warning("Fallback: %s 失败，尝试下一个模型", model_name)

        raise RuntimeError(
            f"所有模型均失败。尝试顺序:\n" + "\n".join(f"  - {e}" for e in errors)
        )
