"""Configurable cloud and on-device embedding runtime."""

from __future__ import annotations

import asyncio
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

EMBEDDING_PROVIDERS = {"openai", "local"}
DEFAULT_CLOUD_MODEL = "text-embedding-3-small"
DEFAULT_LOCAL_MODEL = "BAAI/bge-small-zh-v1.5"
DEFAULT_LOCAL_DIMENSION = 512
DEFAULT_LOCAL_MAX_TOKENS = 512


class EmbeddingRuntimeError(RuntimeError):
    """Raised when an embedding provider cannot be initialized or queried."""


def normalize_embedding_provider(value: Any) -> str:
    provider = str(value or "openai").strip().lower().replace("_", "-")
    aliases = {
        "cloud": "openai",
        "openai-compatible": "openai",
        "openai-compatible-api": "openai",
        "fastembed": "local",
        "on-device": "local",
    }
    provider = aliases.get(provider, provider)
    if provider not in EMBEDDING_PROVIDERS:
        raise EmbeddingRuntimeError("Embedding 提供方式无效")
    return provider


@dataclass(frozen=True)
class EmbeddingSettings:
    provider: str
    model: str
    dimension: int
    max_tokens: int
    base_url: str = ""
    api_key: str = ""
    timeout_seconds: int = 120

    def __post_init__(self) -> None:
        provider = normalize_embedding_provider(self.provider)
        object.__setattr__(self, "provider", provider)
        if not str(self.model or "").strip():
            raise EmbeddingRuntimeError("Embedding 模型名称不能为空")
        if int(self.dimension) <= 0:
            raise EmbeddingRuntimeError("Embedding 维度必须大于 0")
        if provider == "openai":
            if not str(self.base_url or "").strip():
                raise EmbeddingRuntimeError("云端 Embedding 需要 Base URL")
            if not str(self.api_key or "").strip():
                raise EmbeddingRuntimeError("云端 Embedding 需要 API Key")

    def public_payload(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "provider_label": "本地 FastEmbed" if self.provider == "local" else "云端 API",
            "model": self.model,
            "dimension": self.dimension,
            "max_tokens": self.max_tokens,
            "base_url": self.base_url if self.provider == "openai" else "",
        }


class _LocalModelHandle:
    def __init__(self, model: Any):
        self.model = model
        self.lock = threading.Lock()


_LOCAL_MODELS: dict[tuple[str, str], _LocalModelHandle] = {}
_LOCAL_MODELS_LOCK = threading.Lock()


class EmbeddingRuntime:
    """Return numpy-compatible vectors from a cloud API or FastEmbed model."""

    def __init__(self, settings: EmbeddingSettings):
        self.settings = settings

    async def embed(self, texts: list[str], *, context: str = "document") -> Any:
        clean = [str(text or "") for text in texts]
        if not clean:
            try:
                import numpy as np
            except ImportError as exc:  # pragma: no cover - dependency contract
                raise EmbeddingRuntimeError("缺少 numpy，无法生成向量") from exc
            return np.empty((0, self.settings.dimension), dtype=np.float32)
        if self.settings.provider == "local":
            return await asyncio.to_thread(self._embed_local, clean, context)
        return await self._embed_openai(clean)

    async def probe(self) -> dict[str, Any]:
        started = time.monotonic()
        vectors = await self.embed(
            ["小说人物在雨夜寻找失踪的旧信。", "检索与人物选择相关的历史场景。"],
            context="query",
        )
        shape = tuple(int(item) for item in getattr(vectors, "shape", ()))
        if len(shape) != 2 or shape[0] != 2:
            raise EmbeddingRuntimeError("Embedding 服务返回的向量数量无效")
        if shape[1] != self.settings.dimension:
            raise EmbeddingRuntimeError(
                f"Embedding 实际维度为 {shape[1]}，配置值为 {self.settings.dimension}"
            )
        return {
            "ok": True,
            **self.settings.public_payload(),
            "vectors": shape[0],
            "latency_ms": max(1, int((time.monotonic() - started) * 1000)),
        }

    async def _embed_openai(self, texts: list[str]) -> Any:
        try:
            import numpy as np
            from openai import AsyncOpenAI
        except ImportError as exc:  # pragma: no cover - dependency contract
            raise EmbeddingRuntimeError("缺少 OpenAI 或 numpy 依赖") from exc

        try:
            client = AsyncOpenAI(
                api_key=self.settings.api_key,
                base_url=self.settings.base_url.rstrip("/"),
                timeout=self.settings.timeout_seconds,
            )
            response = await client.embeddings.create(
                model=self.settings.model,
                input=texts,
                encoding_format="float",
            )
        except Exception as exc:
            # Construction-time failures (e.g. httpx InvalidURL from a bad
            # NO_PROXY) chain through __cause__ so test_errors can classify
            # them as local configuration problems.
            raise EmbeddingRuntimeError(f"云端 Embedding 请求失败: {type(exc).__name__}") from exc
        ordered = sorted(response.data, key=lambda item: int(item.index))
        vectors = np.asarray([item.embedding for item in ordered], dtype=np.float32)
        self._validate_vectors(vectors, len(texts))
        return vectors

    def _embed_local(self, texts: list[str], context: str) -> Any:
        try:
            import numpy as np
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise EmbeddingRuntimeError(
                "本地 Embedding 依赖未安装，请重新运行 OpenWrite 启动器"
            ) from exc

        cache_dir = os.environ.get("OPENWRITE_FASTEMBED_CACHE_DIR", "").strip()
        cache_key = (self.settings.model, str(Path(cache_dir).expanduser()) if cache_dir else "")
        with _LOCAL_MODELS_LOCK:
            handle = _LOCAL_MODELS.get(cache_key)
            if handle is None:
                kwargs: dict[str, Any] = {"model_name": self.settings.model}
                if cache_dir:
                    kwargs["cache_dir"] = str(Path(cache_dir).expanduser())
                try:
                    handle = _LocalModelHandle(TextEmbedding(**kwargs))
                except Exception as exc:
                    raise EmbeddingRuntimeError(
                        f"无法加载本地 Embedding 模型 {self.settings.model}: {type(exc).__name__}"
                    ) from exc
                _LOCAL_MODELS[cache_key] = handle

        try:
            with handle.lock:
                if context == "query":
                    output = handle.model.query_embed(texts)
                else:
                    output = handle.model.passage_embed(texts)
                vectors = np.asarray(list(output), dtype=np.float32)
        except Exception as exc:
            raise EmbeddingRuntimeError(
                f"本地 Embedding 生成失败: {type(exc).__name__}"
            ) from exc
        self._validate_vectors(vectors, len(texts))
        return vectors

    def _validate_vectors(self, vectors: Any, expected_count: int) -> None:
        shape = tuple(int(item) for item in getattr(vectors, "shape", ()))
        if len(shape) != 2 or shape[0] != expected_count:
            raise EmbeddingRuntimeError("Embedding 返回的数据形状无效")
        if shape[1] != self.settings.dimension:
            raise EmbeddingRuntimeError(
                f"Embedding 实际维度为 {shape[1]}，配置值为 {self.settings.dimension}"
            )


PROBE_TIMEOUT_MARGIN_SECONDS = 30


def run_embedding_probe(settings: EmbeddingSettings) -> dict[str, Any]:
    """Run a provider probe from synchronous Studio and CLI surfaces.

    The probe always executes on a daemon thread with a hard overall timeout:
    a wedged dependency load or a hung provider call must surface as a
    classifiable :class:`EmbeddingRuntimeError` instead of blocking the caller
    (and its request thread) forever.
    """
    result: dict[str, Any] = {}
    error: list[BaseException] = []

    def runner() -> None:
        try:
            result.update(asyncio.run(EmbeddingRuntime(settings).probe()))
        except BaseException as exc:  # pragma: no cover - defensive cross-thread relay
            error.append(exc)

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    deadline = max(5, int(settings.timeout_seconds)) + PROBE_TIMEOUT_MARGIN_SECONDS
    thread.join(deadline)
    if thread.is_alive():
        raise EmbeddingRuntimeError(f"Embedding 探测超时（{deadline} 秒无响应）")
    if error:
        raise error[0]
    return result
