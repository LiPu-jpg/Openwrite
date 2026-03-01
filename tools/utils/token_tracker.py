"""Token 使用量追踪器 — 会话级 token 统计。"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List

from pydantic import BaseModel, Field


class TokenUsage(BaseModel):
    """单次调用 token 用量。"""

    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class SessionSummary(BaseModel):
    """会话 token 统计摘要。"""

    session_id: str
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    call_count: int = 0
    by_model: Dict[str, int] = Field(default_factory=dict)
    started_at: str = ""
    updated_at: str = ""


class SessionTokenTracker:
    """会话级 token 使用量追踪器。

    用法：
        tracker = SessionTokenTracker(session_id="abc123")
        tracker.record({"prompt_tokens": 100, "completion_tokens": 50}, model="gpt-4")
        summary = tracker.summary()
    """

    def __init__(self, session_id: str):
        """初始化追踪器。

        Args:
            session_id: 会话标识符
        """
        self.session_id = session_id
        self._usages: List[TokenUsage] = []
        self._started_at = datetime.now().isoformat()

    def record(self, usage: Dict[str, int], model: str = "") -> None:
        """记录一次 token 使用。

        Args:
            usage: 包含 prompt_tokens, completion_tokens, total_tokens 的字典
            model: 使用的模型名称
        """
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)
        total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)

        token_usage = TokenUsage(
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )
        self._usages.append(token_usage)

    def summary(self) -> SessionSummary:
        """获取会话摘要。

        Returns:
            SessionSummary 包含累计 token 统计和按模型分组统计
        """
        total_prompt = 0
        total_completion = 0
        total = 0
        by_model: Dict[str, int] = {}

        for usage in self._usages:
            total_prompt += usage.prompt_tokens
            total_completion += usage.completion_tokens
            total += usage.total_tokens

            if usage.model:
                by_model[usage.model] = (
                    by_model.get(usage.model, 0) + usage.total_tokens
                )

        return SessionSummary(
            session_id=self.session_id,
            total_prompt_tokens=total_prompt,
            total_completion_tokens=total_completion,
            total_tokens=total,
            call_count=len(self._usages),
            by_model=by_model,
            started_at=self._started_at,
            updated_at=datetime.now().isoformat(),
        )

    def reset(self) -> None:
        """重置追踪器，清空所有记录。"""
        self._usages = []
        self._started_at = datetime.now().isoformat()
