"""Regression coverage for OpenAI-compatible Embedding dimensions negotiation."""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from tools.embedding_runtime import (
    EmbeddingDimensionMismatch,
    EmbeddingRuntime,
    EmbeddingSettings,
)
from tools.llm.test_errors import connection_test_failure


class FakeHttpError(Exception):
    status_code = 400


def _mock_openai(monkeypatch, callback):
    calls = []

    async def create(**params):
        calls.append(params)
        return await callback(params)

    def client(**kwargs):
        assert kwargs["api_key"] == "fake-test-only-secret"
        return SimpleNamespace(embeddings=SimpleNamespace(create=create))

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(AsyncOpenAI=client))
    return calls


def _runtime(dimension: int):
    return EmbeddingRuntime(
        EmbeddingSettings(
            provider="openai",
            model="Qwen3-Embedding-8B",
            dimension=dimension,
            max_tokens=26000,
            base_url="https://ai.gitee.com/v1",
            api_key="fake-test-only-secret",
        )
    )


def _reply(texts, dimensions):
    return SimpleNamespace(
        data=[
            SimpleNamespace(index=i, embedding=np.ones(dimensions).tolist())
            for i, _ in enumerate(texts)
        ]
    )


def test_embedding_sends_configured_dimensions_to_provider(monkeypatch):
    async def respond(params):
        return _reply(params["input"], params["dimensions"])

    calls = _mock_openai(monkeypatch, respond)
    vectors = asyncio.run(_runtime(4096).embed(["文本 A", "文本 B"]))

    assert vectors.shape == (2, 4096)
    assert calls == [{
        "model": "Qwen3-Embedding-8B",
        "input": ["文本 A", "文本 B"],
        "encoding_format": "float",
        "dimensions": 4096,
    }]


def test_embedding_falls_back_only_for_unsupported_dimensions(monkeypatch):
    async def respond(params):
        if "dimensions" in params:
            raise FakeHttpError("unknown parameter: dimensions")
        return _reply(params["input"], 1024)

    calls = _mock_openai(monkeypatch, respond)
    vectors = asyncio.run(_runtime(1024).embed(["文本 A"]))
    assert vectors.shape == (1, 1024)
    assert len(calls) == 2
    assert calls[0]["dimensions"] == 1024
    assert "dimensions" not in calls[1]


def test_embedding_invalid_dimensions_does_not_fallback(monkeypatch):
    async def respond(params):
        raise FakeHttpError("invalid dimensions: model permits 1024 through 4096")

    calls = _mock_openai(monkeypatch, respond)
    with pytest.raises(Exception, match="Embedding 请求失败: FakeHttpError"):
        asyncio.run(_runtime(5000).embed(["文本 A"]))
    assert len(calls) == 1


def test_embedding_mismatch_reports_actual_and_configured_dimensions(monkeypatch):
    async def respond(params):
        return _reply(params["input"], 1024)

    _mock_openai(monkeypatch, respond)
    with pytest.raises(EmbeddingDimensionMismatch) as raised:
        asyncio.run(_runtime(4096).embed(["文本 A", "文本 B"]))

    failure = connection_test_failure(raised.value)
    assert failure.code == "MODEL_TEST_INVALID_RESPONSE"
    assert failure.http_status == 502
    assert "1024" in failure.message
    assert "4096" in failure.message
    assert "配置" in failure.message
    assert "fake-test-only-secret" not in failure.message
