"""Agent 基类

提供:
- 统一的 LLM 调用接口 (chat / chat_with_search)
- 日志记录
- 流式输出支持
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Optional, Callable

from ..llm import LLMClient, LLMConfig, LLMResponse, Message
from ..llm.errors import LLMWrappedError

logger = logging.getLogger(__name__)


class AgentContext:
    """Agent 上下文

    用于在 Agent 之间传递共享资源。
    """

    def __init__(
        self,
        client: LLMClient,
        model: str,
        project_root: str,
        book_id: Optional[str] = None,
        on_progress: Optional[Callable] = None,
    ):
        self.client = client
        self.model = model
        self.project_root = project_root
        self.book_id = book_id
        self.on_progress = on_progress


class BaseAgent(ABC):
    """Agent 基类

    所有具体 Agent 都应继承此类并实现 get_name() 方法。

    用法:
        class MyAgent(BaseAgent):
            def get_name(self) -> str:
                return "my_agent"

            def do_something(self):
                response = self.chat([...])
                ...

        agent = MyAgent(context)
        agent.do_something()
    """

    def __init__(self, ctx: AgentContext):
        self.ctx = ctx
        self._setup_logging()

    def _setup_logging(self):
        """设置日志"""
        self.log = logger.getChild(self.get_name())

    @property
    def name(self) -> str:
        """Agent 名称"""
        return self.get_name()

    @abstractmethod
    def get_name(self) -> str:
        """返回 Agent 名称（子类必须实现）"""
        pass

    def chat(
        self,
        messages: list[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        operation: str = "",
    ) -> LLMResponse:
        """调用 LLM 进行对话

        Args:
            messages: 对话消息列表
            temperature: 温度参数
            max_tokens: 最大 token 数

        Returns:
            LLMResponse 响应对象
        """
        self.log.debug(f"[{self.name}] Calling chat with {len(messages)} messages")

        try:
            kwargs = {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False,
                "on_progress": self.ctx.on_progress,
            }
            if operation:
                kwargs["operation"] = operation
            response = self.ctx.client.chat(**kwargs)
            from ..llm.response import classify_response

            classify_response(
                response.content,
                finish_reason=getattr(response, "finish_reason", ""),
                reasoning=getattr(response, "reasoning", ""),
            )
            self.log.debug(
                f"[{self.name}] Response: {len(response.content)} chars, "
                f"tokens={response.total_tokens}"
            )
            return response
        except LLMWrappedError:
            raise
        except Exception as e:
            self.log.error(f"[{self.name}] Chat failed: {e}")
            raise

    def stream_chat(
        self,
        messages: list[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """流式调用 LLM

        Args:
            messages: 对话消息列表
            temperature: 温度参数
            max_tokens: 最大 token 数

        Yields:
            LLMResponse 响应对象（增量）
        """
        self.log.debug(f"[{self.name}] Calling stream_chat with {len(messages)} messages")

        try:
            response = self.ctx.client.chat(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                on_progress=self.ctx.on_progress,
            )
            return response
        except LLMWrappedError:
            raise
        except Exception as e:
            self.log.error(f"[{self.name}] Stream chat failed: {e}")
            raise

    def chat_with_search(
        self,
        messages: list[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """带网页搜索的对话

        当 provider 是 OpenAI 时使用原生搜索，
        其他 provider 使用 Tavily API 搜索后注入上下文。

        Args:
            messages: 对话消息列表
            temperature: 温度参数
            max_tokens: 最大 token 数

        Returns:
            LLMResponse 响应对象
        """
        # OpenAI 原生搜索
        if self.ctx.client.config.provider == "openai":
            return self.chat(messages, temperature, max_tokens)

        # 其他 provider 使用 Tavily
        last_user_msg = None
        for m in reversed(messages):
            if m.role == "user":
                last_user_msg = m
                break

        if not last_user_msg:
            return self.chat(messages, temperature, max_tokens)

        query = last_user_msg.content[:200]
        self.log.info(f"[search] Searching: {query[:60]}...")

        try:
            results = self._search_web(query, top_k=3)
            if not results:
                self.log.warning("[search] No results found, falling back to regular chat")
                return self.chat(messages, temperature, max_tokens)

            search_context = self._build_search_context(results)
            augmented_messages = []
            for m in messages:
                if m == last_user_msg:
                    augmented_messages.append(
                        Message(m.role, f"{search_context}\n\n---\n\n{m.content}")
                    )
                else:
                    augmented_messages.append(m)

            return self.chat(augmented_messages, temperature, max_tokens)
        except Exception as e:
            self.log.warning(f"[search] Search failed: {e}, falling back to regular chat")
            return self.chat(messages, temperature, max_tokens)

    def _search_web(self, query: str, top_k: int = 3) -> list[dict]:
        """执行网页搜索"""
        try:
            from tavily import TavilyClient

            api_key = self._get_env("TAVILY_API_KEY")
            if not api_key:
                return []

            client = TavilyClient(api_key=api_key)
            results = client.search(query=query, max_results=top_k)
            return results.get("results", [])
        except ImportError:
            self.log.warning("Tavily not installed, skipping web search")
            return []
        except Exception as e:
            self.log.warning(f"Web search failed: {e}")
            return []

    def _build_search_context(self, results: list[dict]) -> str:
        """构建搜索结果上下文"""
        lines = ["## Web Search Results\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. **{r.get('title', 'Untitled')}**")
            lines.append(f"   {r.get('url', '')}")
            lines.append(f"   {r.get('content', '')[:200]}")
        return "\n".join(lines)

    def _get_env(self, key: str) -> Optional[str]:
        """获取环境变量"""
        import os

        return os.getenv(key)
