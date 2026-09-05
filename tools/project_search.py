"""LightRAG-backed semantic and structural search for a novel project."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import logging
import os
import re
import tempfile
import threading
import time
from collections.abc import Callable, Coroutine, Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from types import TracebackType
from typing import Any, Protocol, TypeVar

from tools.embedding_runtime import (
    DEFAULT_LOCAL_DIMENSION,
    DEFAULT_LOCAL_MAX_TOKENS,
    EmbeddingRuntime,
    EmbeddingSettings,
    normalize_embedding_provider,
)
from tools.library_catalog import (
    SCOPE_LABELS,
    describe_document,
    document_title,
    normalize_search_scope,
    scope_for_path,
)

MAX_INDEXED_BYTES = 2 * 1024 * 1024
MAX_QUERY_CHARS = 200
LIGHTRAG_MODES = {"local", "global", "hybrid", "naive", "mix"}
# Bump whenever the indexed representation changes. The version participates
# in the LightRAG workspace key, forcing a clean rebuild for existing projects.
MANIFEST_VERSION = 7

logger = logging.getLogger(__name__)
T = TypeVar("T")

# LightRAG owns process-global asyncio locks even when its working directories differ.
# Serialize its synchronous entrypoints while surrounding writer jobs remain parallel.
_LIGHTRAG_RUNTIME_LOCK = threading.Lock()


def stable_document_id(novel_id: str, relative_path: str) -> str:
    """Return the path-stable identity used for non-manuscript documents."""
    digest = hashlib.sha256(f"{novel_id}\0{relative_path}".encode()).hexdigest()
    return f"doc_{digest[:24]}"


class SearchConfigurationError(RuntimeError):
    """Raised when LightRAG cannot be configured from the active model profile."""


class SearchBackendError(RuntimeError):
    """Raised when the LightRAG index cannot be updated or queried."""


class SearchIndexBusyError(SearchBackendError):
    """Raised when another process is currently updating the same LightRAG index."""


@dataclass(frozen=True)
class SearchResult:
    path: str
    title: str
    line: int
    heading: str
    snippet: str
    scope: str
    category: str
    category_label: str
    score: float
    retrieval: tuple[str, ...] = ()
    excerpt: str = ""
    document_id: str = ""
    revision: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "title": self.title,
            "line": self.line,
            "heading": self.heading,
            "snippet": self.snippet,
            "scope": self.scope,
            "scope_label": SCOPE_LABELS.get(self.scope, self.scope),
            "category": self.category,
            "category_label": self.category_label,
            "score": self.score,
            "retrieval": list(self.retrieval),
            "excerpt": self.excerpt or self.snippet,
            "document_id": self.document_id,
            "revision": self.revision,
            "locator": {
                "line": self.line,
                "quote": self.snippet,
                "quote_sha256": "sha256:"
                + hashlib.sha256(self.snippet.encode("utf-8")).hexdigest(),
            },
        }


@dataclass(frozen=True)
class IndexedDocument:
    path: str
    title: str
    body: str
    scope: str
    category: str
    category_label: str
    revision: str
    doc_id: str
    source_key: str
    document_id: str = ""
    current_revision: str = ""


@dataclass(frozen=True)
class RetrievedChunk:
    source_key: str
    content: str
    rank: int


@dataclass(frozen=True)
class BackendSearchResult:
    chunks: list[RetrievedChunk]
    inserted: int = 0
    updated: int = 0
    deleted: int = 0
    backend: dict[str, Any] | None = None


class SearchBackend(Protocol):
    def search(
        self,
        documents: list[IndexedDocument],
        query: str,
        *,
        limit: int,
    ) -> BackendSearchResult: ...

    def refresh(self, documents: list[IndexedDocument]) -> BackendSearchResult: ...


@dataclass(frozen=True)
class LightRAGConfiguration:
    provider: str
    llm_model: str
    llm_base_url: str
    llm_api_key: str
    timeout_seconds: int
    embedding_provider: str
    embedding_model: str
    embedding_base_url: str
    embedding_api_key: str
    embedding_dimension: int
    embedding_max_tokens: int
    query_mode: str

    @classmethod
    def from_runtime(cls) -> LightRAGConfiguration:
        from tools.llm.client import LLMConfig
        from tools.model_profiles import (
            ModelProfileStore,
            active_model_profile,
            active_search_model_profile,
        )

        search_profile = active_search_model_profile()
        active = search_profile or active_model_profile() or {}
        llm = LLMConfig.from_env()
        if search_profile:
            llm = LLMConfig(
                provider=search_profile.get("provider") or "openai",
                api_key=str(search_profile.get("api_key") or ""),
                base_url=str(search_profile.get("base_url") or ""),
                model=str(search_profile.get("model") or ""),
                api_format=search_profile.get("api_format") or "chat",
                timeout_seconds=float(search_profile.get("timeout_seconds") or 120),
            )
        explicit_query_mode = os.environ.get("OPENWRITE_LIGHTRAG_MODE", "").strip().lower()
        profile_search_mode = str(active.get("search_mode") or "vector").strip().lower()
        query_mode = explicit_query_mode or (
            "mix" if profile_search_mode == "graph" else "naive"
        )
        if query_mode not in LIGHTRAG_MODES:
            raise SearchConfigurationError("OPENWRITE_LIGHTRAG_MODE 配置无效")
        requires_chat_model = query_mode != "naive"
        if requires_chat_model and not llm.api_key.strip():
            raise SearchConfigurationError("LightRAG 需要已配置的模型 API Key")
        if requires_chat_model and llm.api_format == "responses":
            raise SearchConfigurationError(
                "LightRAG 搜索需要 Chat Completions 兼容的模型路由"
            )

        try:
            embedding = ModelProfileStore().resolve_embedding()
            embedding_provider = normalize_embedding_provider(embedding.get("provider"))
        except Exception as exc:
            raise SearchConfigurationError(str(exc)) from exc
        embedding_base_url = str(embedding.get("base_url") or "").rstrip("/")
        embedding_api_key = str(embedding.get("api_key") or "")

        if embedding_provider == "openai" and "deepseek.com" in embedding_base_url.casefold():
            raise SearchConfigurationError(
                "DeepSeek 接口不提供 embedding；请在模型档案中配置独立的 "
                "Embedding Base URL"
            )
        if embedding_provider == "openai" and not embedding_api_key:
            raise SearchConfigurationError("LightRAG 需要可用的 Embedding API Key")
        if embedding_provider == "local" and importlib.util.find_spec("fastembed") is None:
            raise SearchConfigurationError(
                "本地 Embedding 依赖未安装，请重新运行 OpenWrite 启动器"
            )

        embedding_model = str(embedding.get("model") or "").strip()
        embedding_dimension = _bounded_env_int(
            "OPENWRITE_LIGHTRAG_EMBEDDING_DIM",
            embedding.get("dimension"),
            default=DEFAULT_LOCAL_DIMENSION if embedding_provider == "local" else 1536,
            minimum=1,
            maximum=65536,
        )
        embedding_max_tokens = _bounded_env_int(
            "OPENWRITE_LIGHTRAG_EMBEDDING_MAX_TOKENS",
            embedding.get("max_tokens"),
            default=(
                DEFAULT_LOCAL_MAX_TOKENS if embedding_provider == "local" else 8192
            ),
            minimum=256,
            maximum=131072,
        )
        return cls(
            provider=llm.provider,
            llm_model=llm.model,
            llm_base_url=llm.base_url.rstrip("/"),
            llm_api_key=llm.api_key,
            timeout_seconds=max(1, int(llm.timeout_seconds)),
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
            embedding_base_url=embedding_base_url,
            embedding_api_key=embedding_api_key,
            embedding_dimension=embedding_dimension,
            embedding_max_tokens=embedding_max_tokens,
            query_mode=query_mode,
        )

    @property
    def workspace(self) -> str:
        payload = {
            "schema": MANIFEST_VERSION,
            "embedding_provider": self.embedding_provider,
            "embedding_model": self.embedding_model,
            "embedding_base_url": self.embedding_base_url,
            "embedding_dimension": self.embedding_dimension,
            "query_mode": self.query_mode,
        }
        if self.query_mode != "naive":
            payload.update(
                provider=self.provider,
                llm_model=self.llm_model,
                llm_base_url=self.llm_base_url,
            )
        encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
        return f"search-{hashlib.sha256(encoded).hexdigest()[:16]}"

    @property
    def embedding_settings(self) -> EmbeddingSettings:
        return EmbeddingSettings(
            provider=self.embedding_provider,
            model=self.embedding_model,
            dimension=self.embedding_dimension,
            max_tokens=self.embedding_max_tokens,
            base_url=self.embedding_base_url,
            api_key=self.embedding_api_key,
            timeout_seconds=self.timeout_seconds,
        )

    def public_payload(self) -> dict[str, Any]:
        return {
            **self.embedding_settings.public_payload(),
            "query_mode": self.query_mode,
            "workspace": self.workspace,
        }


class LightRAGSearchBackend:
    """Incremental LightRAG index using the library's local JSON/NanoVectorDB stores."""

    def __init__(
        self,
        novel_root: Path,
        *,
        configuration: LightRAGConfiguration | None = None,
    ) -> None:
        self.novel_root = Path(novel_root).resolve()
        self.configuration = configuration or LightRAGConfiguration.from_runtime()
        self.working_dir = self.novel_root / ".openwrite" / "lightrag"
        self.workspace = self.configuration.workspace
        self.manifest_path = (
            self.working_dir / self.workspace / "openwrite-search-manifest.json"
        )
        self.lock_path = self.working_dir / f"{self.workspace}.lock"

    def search(
        self,
        documents: list[IndexedDocument],
        query: str,
        *,
        limit: int,
    ) -> BackendSearchResult:
        with _LIGHTRAG_RUNTIME_LOCK:
            return _run_async(lambda: self._search(documents, query, limit=limit))

    def refresh(self, documents: list[IndexedDocument]) -> BackendSearchResult:
        with _LIGHTRAG_RUNTIME_LOCK:
            return _run_async(lambda: self._refresh(documents))

    async def _search(
        self,
        documents: list[IndexedDocument],
        query: str,
        *,
        limit: int,
    ) -> BackendSearchResult:
        with _IndexUpdateLock(self.lock_path):
            rag = self._create_rag()
            initialized = False
            try:
                await rag.initialize_storages()
                initialized = True
                stats = await self._sync_documents(rag, documents)
                from lightrag import QueryParam

                retrieval_limit = min(200, max(40, limit * 8))
                payload = await rag.aquery_data(
                    query,
                    param=QueryParam(
                        mode=self.configuration.query_mode,
                        top_k=min(100, max(20, limit * 4)),
                        chunk_top_k=retrieval_limit,
                        enable_rerank=False,
                    ),
                )
                chunks = self._chunks_from_payload(payload)
                return BackendSearchResult(
                    chunks=chunks,
                    backend=self.configuration.public_payload(),
                    **stats,
                )
            finally:
                if initialized:
                    await rag.finalize_storages()

    async def _refresh(self, documents: list[IndexedDocument]) -> BackendSearchResult:
        with _IndexUpdateLock(self.lock_path):
            rag = self._create_rag()
            initialized = False
            try:
                await rag.initialize_storages()
                initialized = True
                stats = await self._sync_documents(rag, documents)
                return BackendSearchResult(
                    chunks=[],
                    backend=self.configuration.public_payload(),
                    **stats,
                )
            finally:
                if initialized:
                    await rag.finalize_storages()

    def _create_rag(self) -> Any:
        config = self.configuration
        try:
            from lightrag import LightRAG
            from lightrag.llm.openai import openai_complete_if_cache
            from lightrag.utils import EmbeddingFunc
        except ImportError as exc:
            raise SearchConfigurationError(
                "LightRAG 依赖未安装，请重新运行 OpenWrite 启动器安装依赖"
            ) from exc
        anthropic_complete_if_cache = None
        if config.provider == "anthropic" and config.query_mode != "naive":
            try:
                from lightrag.llm.anthropic import anthropic_complete_if_cache
            except ImportError as exc:
                raise SearchConfigurationError(
                    "LightRAG 的 Anthropic 适配器未安装，请重新运行 OpenWrite 启动器"
                ) from exc

        async def llm_model_func(
            prompt: str,
            system_prompt: str | None = None,
            history_messages: list[dict[str, Any]] | None = None,
            **kwargs: Any,
        ) -> Any:
            kwargs.pop("base_url", None)
            kwargs.pop("api_key", None)
            kwargs.setdefault("timeout", config.timeout_seconds)
            history = history_messages or []
            if config.provider == "anthropic":
                if anthropic_complete_if_cache is None:  # pragma: no cover - guarded above
                    raise SearchConfigurationError("Anthropic LightRAG 适配器不可用")
                return await anthropic_complete_if_cache(
                    config.llm_model,
                    prompt,
                    system_prompt=system_prompt,
                    history_messages=history,
                    base_url=config.llm_base_url,
                    api_key=config.llm_api_key,
                    **kwargs,
                )
            return await openai_complete_if_cache(
                config.llm_model,
                prompt,
                system_prompt=system_prompt,
                history_messages=history,
                base_url=config.llm_base_url,
                api_key=config.llm_api_key,
                **kwargs,
            )

        embedding_runtime = EmbeddingRuntime(config.embedding_settings)

        async def embedding_func(texts: list[str], **kwargs: Any) -> Any:
            context = str(kwargs.pop("context", "document"))
            return await embedding_runtime.embed(texts, context=context)

        return LightRAG(
            working_dir=str(self.working_dir),
            workspace=self.workspace,
            llm_model_func=llm_model_func,
            llm_model_name=config.llm_model,
            embedding_func=EmbeddingFunc(
                embedding_dim=config.embedding_dimension,
                max_token_size=config.embedding_max_tokens,
                model_name=config.embedding_model,
                supports_asymmetric=True,
                func=embedding_func,
            ),
            tiktoken_model_name="gpt-4o-mini",
            chunk_token_size=900,
            chunk_overlap_token_size=120,
            cosine_better_than_threshold=0.3,
            llm_model_max_async=2,
            embedding_func_max_async=4,
            addon_params={"language": "Chinese"},
        )

    async def _sync_documents(
        self,
        rag: Any,
        documents: list[IndexedDocument],
    ) -> dict[str, int]:
        if self.configuration.query_mode == "naive":
            return await self._sync_vector_documents(rag, documents)
        manifest = self._load_manifest()
        indexed = manifest["documents"]
        current = {document.path: document for document in documents}
        inserted = 0
        updated = 0
        deleted = 0
        pending: list[IndexedDocument] = []

        for path in sorted(set(indexed) - set(current)):
            await self._delete_document(rag, str(indexed[path].get("doc_id") or ""))
            indexed.pop(path, None)
            deleted += 1
            self._write_manifest(manifest)

        for document in documents:
            previous = indexed.get(document.path)
            if previous and previous.get("revision") == document.revision:
                continue
            if previous:
                await self._delete_document(rag, str(previous.get("doc_id") or ""))
                indexed.pop(document.path, None)
                updated += 1
                self._write_manifest(manifest)
            else:
                inserted += 1
            pending.append(document)

        if pending:
            # LightRAG can process a document list with its bounded parallel
            # insertion pipeline. Calling it once per file serializes graph
            # extraction and makes a first novel index unnecessarily slow.
            await rag.ainsert(
                [self._rag_document_body(document) for document in pending],
                ids=[document.doc_id for document in pending],
                file_paths=[document.source_key for document in pending],
            )
        for document in pending:
            indexed[document.path] = {
                "revision": document.revision,
                "doc_id": document.doc_id,
                "source_key": document.source_key,
                "scope": document.scope,
                "category": document.category,
                "category_label": document.category_label,
                "title": document.title,
            }
        if pending:
            self._write_manifest(manifest)

        return {"inserted": inserted, "updated": updated, "deleted": deleted}

    async def _sync_vector_documents(
        self,
        rag: Any,
        documents: list[IndexedDocument],
    ) -> dict[str, int]:
        """Maintain LightRAG chunk vectors without chat-model graph extraction."""
        manifest = self._load_manifest()
        indexed = manifest["documents"]
        current = {document.path: document for document in documents}
        inserted = 0
        updated = 0
        deleted = 0
        storage_changed = False

        async def delete_entry(entry: dict[str, Any]) -> None:
            nonlocal storage_changed
            chunk_ids = [str(item) for item in entry.get("chunk_ids", []) if str(item)]
            if chunk_ids:
                await asyncio.gather(
                    rag.chunks_vdb.delete(chunk_ids),
                    rag.text_chunks.delete(chunk_ids),
                )
            doc_id = str(entry.get("doc_id") or "")
            if doc_id:
                await rag.full_docs.delete([doc_id])
            storage_changed = storage_changed or bool(chunk_ids or doc_id)

        for path in sorted(set(indexed) - set(current)):
            await delete_entry(indexed[path])
            indexed.pop(path, None)
            deleted += 1

        pending: list[IndexedDocument] = []
        for document in documents:
            previous = indexed.get(document.path)
            if previous and previous.get("revision") == document.revision:
                continue
            if previous:
                await delete_entry(previous)
                indexed.pop(document.path, None)
                updated += 1
            else:
                inserted += 1
            pending.append(document)

        all_chunks: dict[str, dict[str, Any]] = {}
        full_docs: dict[str, dict[str, Any]] = {}
        chunk_limit = max(256, min(900, self.configuration.embedding_max_tokens - 32))
        overlap = min(100, max(32, chunk_limit // 6))
        for document in pending:
            body = self._rag_document_body(document)
            chunk_rows = self._unicode_safe_token_chunks(
                rag.tokenizer,
                body,
                chunk_token_size=chunk_limit,
                chunk_overlap_token_size=overlap,
            )
            chunk_ids: list[str] = []
            for index, row in enumerate(chunk_rows):
                content = str(row.get("content") or "").strip()
                if not content:
                    continue
                digest = hashlib.sha256(
                    f"{document.doc_id}\0{index}\0{content}".encode()
                ).hexdigest()
                chunk_id = f"chunk-{digest}"
                chunk_ids.append(chunk_id)
                all_chunks[chunk_id] = {
                    "content": content,
                    "full_doc_id": document.doc_id,
                    "tokens": len(rag.tokenizer.encode(content)),
                    "chunk_order_index": index,
                    "file_path": document.source_key,
                }
            full_docs[document.doc_id] = {
                "content": body,
                "file_path": document.source_key,
            }
            indexed[document.path] = {
                "revision": document.revision,
                "doc_id": document.doc_id,
                "source_key": document.source_key,
                "scope": document.scope,
                "category": document.category,
                "category_label": document.category_label,
                "title": document.title,
                "chunk_ids": chunk_ids,
            }

        if all_chunks:
            await asyncio.gather(
                rag.chunks_vdb.upsert(all_chunks),
                rag.text_chunks.upsert(all_chunks),
                rag.full_docs.upsert(full_docs),
            )
            storage_changed = True
        if storage_changed:
            await asyncio.gather(
                rag.chunks_vdb.index_done_callback(),
                rag.text_chunks.index_done_callback(),
                rag.full_docs.index_done_callback(),
            )
        if pending or deleted:
            manifest["index_kind"] = "vector"
            self._write_manifest(manifest)
        return {"inserted": inserted, "updated": updated, "deleted": deleted}

    @staticmethod
    def _unicode_safe_token_chunks(
        tokenizer: Any,
        content: str,
        *,
        chunk_token_size: int,
        chunk_overlap_token_size: int,
    ) -> list[dict[str, Any]]:
        """Split by token budget without decoding partial UTF-8 token windows."""
        text = str(content or "")
        if not text:
            return []
        budget = max(1, int(chunk_token_size))
        overlap = max(0, min(int(chunk_overlap_token_size), budget - 1))
        rows: list[dict[str, Any]] = []
        start = 0
        order = 0

        def token_count(value: str) -> int:
            return len(tokenizer.encode(value))

        while start < len(text):
            low = start + 1
            high = len(text)
            best_end = low
            while low <= high:
                middle = (low + high) // 2
                if token_count(text[start:middle]) <= budget:
                    best_end = middle
                    low = middle + 1
                else:
                    high = middle - 1

            piece = text[start:best_end].strip()
            if piece:
                rows.append(
                    {
                        "content": piece,
                        "tokens": token_count(piece),
                        "chunk_order_index": order,
                    }
                )
                order += 1
            if best_end >= len(text):
                break
            if overlap <= 0:
                start = best_end
                continue

            low = start + 1
            high = best_end
            next_start = best_end
            while low <= high:
                middle = (low + high) // 2
                if token_count(text[middle:best_end]) <= overlap:
                    next_start = middle
                    high = middle - 1
                else:
                    low = middle + 1
            start = max(start + 1, next_start)

        return rows

    @staticmethod
    def _rag_document_body(document: IndexedDocument) -> str:
        """Make logical scope and subtype available to graph/vector retrieval."""
        return (
            f"OpenWrite 资料范围：{SCOPE_LABELS.get(document.scope, document.scope)}\n"
            f"OpenWrite 子分类：{document.category_label}\n"
            f"OpenWrite 来源：{document.path}\n\n"
            f"{document.body}"
        )

    async def _delete_document(self, rag: Any, doc_id: str) -> None:
        if not doc_id:
            return
        result = await rag.adelete_by_doc_id(doc_id)
        status = str(getattr(result, "status", "") or "")
        if status not in {"success", "not_found"}:
            raise SearchBackendError("LightRAG 无法删除过期文档索引")

    def _load_manifest(self) -> dict[str, Any]:
        if self.manifest_path.is_file():
            try:
                payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                payload = {}
            if (
                isinstance(payload, dict)
                and payload.get("version") == MANIFEST_VERSION
                and isinstance(payload.get("documents"), dict)
            ):
                return payload
        return {
            "version": MANIFEST_VERSION,
            "engine": "HKUDS/LightRAG",
            "workspace": self.workspace,
            "documents": {},
        }

    def _write_manifest(self, manifest: dict[str, Any]) -> None:
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.manifest_path.parent,
            prefix=".openwrite-search-manifest.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(manifest, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            temp_path = Path(handle.name)
        temp_path.replace(self.manifest_path)

    @staticmethod
    def _chunks_from_payload(payload: Any) -> list[RetrievedChunk]:
        if not isinstance(payload, dict):
            return []
        data = payload.get("data")
        if not isinstance(data, dict):
            return []
        raw_chunks = data.get("chunks")
        if not isinstance(raw_chunks, list):
            return []
        chunks: list[RetrievedChunk] = []
        for rank, item in enumerate(raw_chunks, 1):
            if not isinstance(item, dict):
                continue
            source_key = str(item.get("file_path") or "").strip()
            content = str(item.get("content") or "").strip()
            if source_key and content:
                chunks.append(RetrievedChunk(source_key, content, rank))
        return chunks


class ProjectSearchIndex:
    """Compatibility surface backed by LightRAG with line-level source provenance."""

    def __init__(
        self,
        novel_root: Path,
        *,
        backend_factory: Callable[[Path], SearchBackend] | None = None,
    ) -> None:
        self.novel_root = Path(novel_root).resolve()
        self.index_path = self.novel_root / ".openwrite" / "lightrag"
        self._backend_factory = backend_factory or LightRAGSearchBackend

    def search(
        self,
        query: str,
        *,
        scope: str = "all",
        limit: int = 20,
    ) -> dict[str, Any]:
        normalized_scope = normalize_search_scope(scope)
        clean_query = " ".join(str(query or "").strip().split())[:MAX_QUERY_CHARS]
        if not clean_query:
            return {
                "query": "",
                "scope": normalized_scope,
                "scope_label": SCOPE_LABELS[normalized_scope],
                "results": [],
                "indexed": 0,
                "engine": "none",
                "warning": "",
            }
        limit = min(50, max(1, int(limit)))
        documents = self._documents()
        literal_results = self._literal_results(
            documents,
            clean_query,
            scope=normalized_scope,
        )
        warning = ""
        warning_code = ""

        try:
            backend = self._backend_factory(self.novel_root)
            backend_result = backend.search(
                documents,
                self._semantic_query(clean_query, normalized_scope),
                limit=limit,
            )
        except SearchConfigurationError as exc:
            backend_result = BackendSearchResult(chunks=[])
            warning = f"{exc}；已使用精确文本搜索"
            warning_code = "LIGHTRAG_NOT_CONFIGURED"
        except SearchIndexBusyError:
            backend_result = BackendSearchResult(chunks=[])
            warning = (
                "LightRAG 索引正在由另一任务更新；本次已使用精确文本搜索"
            )
            warning_code = "LIGHTRAG_INDEX_BUSY"
        except Exception:
            logger.warning("LightRAG project search failed", exc_info=True)
            backend_result = BackendSearchResult(chunks=[])
            warning = "LightRAG 索引或检索失败；本次已使用精确文本搜索"
            warning_code = "LIGHTRAG_SEARCH_FAILED"

        semantic_results = self._semantic_results(
            documents,
            backend_result.chunks,
            clean_query,
            scope=normalized_scope,
        )
        results = self._merge_results(semantic_results, literal_results, limit=limit)
        engine = "lightrag" if semantic_results or not warning else "literal-fallback"
        return {
            "query": clean_query,
            "scope": normalized_scope,
            "scope_label": SCOPE_LABELS[normalized_scope],
            "results": [item.to_dict() for item in results],
            "indexed": len(documents),
            "engine": engine,
            "warning": warning,
            "warning_code": warning_code,
            "retrieval_stats": {
                "semantic": len(semantic_results),
                "literal": len(literal_results),
                "fused": len(results),
            },
            "index_updates": {
                "inserted": backend_result.inserted,
                "updated": backend_result.updated,
                "deleted": backend_result.deleted,
            },
            "embedding": dict(backend_result.backend or {}),
        }

    def refresh(self) -> int:
        documents = self._documents()
        try:
            self._backend_factory(self.novel_root).refresh(documents)
        except SearchConfigurationError:
            pass
        return len(documents)

    def _documents(self) -> list[IndexedDocument]:
        documents = []
        canonical_ids = self._canonical_document_ids()
        for path in self._iter_documents():
            try:
                raw_body = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            relative = self._relative(path)
            body = self._indexable_body(relative, raw_body)
            if not body.strip():
                continue
            descriptor = describe_document(relative, raw_body)
            revision = self._revision(body, descriptor)
            documents.append(
                IndexedDocument(
                    path=relative,
                    title=self._document_title(path, raw_body),
                    body=body,
                    scope=descriptor.scope,
                    category=descriptor.category,
                    category_label=descriptor.category_label,
                    revision=revision,
                    doc_id=self._doc_id(relative, revision),
                    source_key=self._source_key(relative),
                    document_id=canonical_ids.get(
                        relative, self._stable_document_id(relative)
                    ),
                    current_revision="sha256:"
                    + hashlib.sha256(raw_body.encode("utf-8")).hexdigest(),
                )
            )
        return documents

    def _canonical_document_ids(self) -> dict[str, str]:
        """Map manuscript paths to reading-order identities when available."""
        try:
            from tools.reading_order import ReadingOrderService

            project_root = self.novel_root.parents[2]
            surface = ReadingOrderService(project_root, self.novel_root.name).surface()
        except (IndexError, OSError, RuntimeError, ValueError):
            return {}
        return {
            str(item.get("path") or ""): str(item.get("document_id") or "")
            for item in surface.get("documents", [])
            if isinstance(item, dict)
            and str(item.get("path") or "")
            and str(item.get("document_id") or "")
        }

    def _stable_document_id(self, relative: str) -> str:
        return stable_document_id(self.novel_root.name, relative)

    def _iter_documents(self) -> Iterable[Path]:
        roots = [
            (self.novel_root / "src", {".md", ".yaml", ".yml"}),
            (self.novel_root / "data" / "manuscript", {".md"}),
            (self.novel_root / "data" / "world", {".md"}),
            (
                self.novel_root / "data" / "foreshadowing",
                {".md", ".yaml", ".yml"},
            ),
            (self.novel_root / "data" / "style", {".md", ".yaml", ".yml"}),
        ]
        for root, suffixes in roots:
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*")):
                try:
                    if (
                        path.is_file()
                        and not path.is_symlink()
                        and path.suffix.lower() in suffixes
                        and path.stat().st_size <= MAX_INDEXED_BYTES
                    ):
                        yield path
                except OSError:
                    continue
        sources_root = self.novel_root / "data" / "sources"
        if sources_root.is_dir():
            for path in sorted(sources_root.rglob("*")):
                relative = path.relative_to(sources_root).as_posix()
                is_report = path.name == "report.json" and "/analysis_v2/" in f"/{relative}"
                is_snapshot = "/analysis_v2/snapshots/" in f"/{relative}" and path.suffix == ".txt"
                is_style = "/style/" in f"/{relative}" and path.suffix.lower() in {
                    ".md",
                    ".yaml",
                    ".yml",
                }
                try:
                    if (
                        (is_report or is_snapshot or is_style)
                        and path.is_file()
                        and not path.is_symlink()
                        and path.stat().st_size <= MAX_INDEXED_BYTES
                    ):
                        yield path
                except OSError:
                    continue

    @staticmethod
    def _indexable_body(relative: str, raw_body: str) -> str:
        from tools.character_state_index import mask_character_state_annotations

        if relative.endswith("/analysis_v2/report.json"):
            return ProjectSearchIndex._render_source_report(raw_body)
        if relative.endswith(".md"):
            return mask_character_state_annotations(raw_body)
        return raw_body

    @staticmethod
    def _render_source_report(raw_body: str) -> str:
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError:
            return ""
        if not isinstance(payload, dict):
            return ""
        lines = [f"# 拆书分析：{payload.get('source_id') or '参考资料'}"]
        summary = str(payload.get("summary") or "").strip()
        if summary:
            lines.extend(("", "## 总结", summary))
        findings = payload.get("findings")
        if isinstance(findings, list):
            lines.extend(("", "## 可检索发现"))
            for item in findings:
                if not isinstance(item, dict):
                    continue
                claim = str(item.get("claim") or "").strip()
                if claim:
                    lines.append(f"- [{item.get('category') or 'finding'}] {claim}")
                evidence = item.get("evidence")
                if isinstance(evidence, list):
                    for source in evidence[:2]:
                        if isinstance(source, dict) and str(source.get("quote") or "").strip():
                            lines.append(f"  - 原文：{str(source['quote']).strip()}")
        return "\n".join(lines).strip() + "\n"

    @staticmethod
    def _document_title(path: Path, raw_body: str) -> str:
        if path.name == "report.json":
            try:
                payload = json.loads(raw_body)
            except json.JSONDecodeError:
                payload = {}
            if isinstance(payload, dict) and payload.get("source_id"):
                return f"{payload['source_id']} · 拆书分析"
        return document_title(path, raw_body)

    def _relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.novel_root).as_posix()

    @staticmethod
    def _doc_id(relative: str, revision: str) -> str:
        digest = hashlib.sha256(f"{relative}\0{revision}".encode()).hexdigest()
        return f"doc-{digest}"

    @staticmethod
    def _source_key(relative: str) -> str:
        suffix = Path(relative).suffix.lower() or ".md"
        digest = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:24]
        return f"openwrite-{digest}{suffix}"

    @staticmethod
    def _revision(body: str, descriptor: Any) -> str:
        taxonomy = "\0".join(
            (
                str(descriptor.scope),
                str(descriptor.scope_label),
                str(descriptor.category),
                str(descriptor.category_label),
            )
        )
        return hashlib.sha256(f"{taxonomy}\0{body}".encode()).hexdigest()

    @staticmethod
    def _semantic_query(query: str, scope: str) -> str:
        if scope == "all":
            return query
        return f"OpenWrite 资料范围：{SCOPE_LABELS[scope]}\n{query}"

    @staticmethod
    def _scope(relative: str) -> str:
        return scope_for_path(relative)

    def _semantic_results(
        self,
        documents: list[IndexedDocument],
        chunks: list[RetrievedChunk],
        query: str,
        *,
        scope: str,
    ) -> list[SearchResult]:
        by_source = {document.source_key: document for document in documents}
        query_terms = self._semantic_anchor_terms(query)
        results: list[SearchResult] = []
        seen_paths: set[str] = set()
        for chunk in chunks:
            document = by_source.get(chunk.source_key)
            if document is None or document.path in seen_paths:
                continue
            if scope != "all" and document.scope != scope:
                continue
            line, heading, snippet, literal_hits = self._locate_chunk(
                document.body,
                chunk.content,
                query_terms,
            )
            results.append(
                SearchResult(
                    path=document.path,
                    title=document.title,
                    line=line,
                    heading=heading,
                    snippet=snippet,
                    scope=document.scope,
                    category=document.category,
                    category_label=document.category_label,
                    score=1000.0 - chunk.rank + literal_hits,
                    retrieval=("semantic",),
                    excerpt=self._source_excerpt(document.body, line),
                    document_id=document.document_id,
                    revision=document.current_revision,
                )
            )
            seen_paths.add(document.path)
        return results

    def _literal_results(
        self,
        documents: list[IndexedDocument],
        query: str,
        *,
        scope: str,
    ) -> list[SearchResult]:
        terms = self._query_terms(query)
        results = []
        for document in documents:
            if scope != "all" and document.scope != scope:
                continue
            match = self._match_document(document, terms)
            if match is not None:
                results.append(match)
        results.sort(key=lambda item: (-item.score, item.path, item.line))
        return results

    @staticmethod
    def _merge_results(
        semantic: list[SearchResult],
        literal: list[SearchResult],
        *,
        limit: int,
    ) -> list[SearchResult]:
        # Weighted reciprocal-rank fusion keeps semantic recall dominant while
        # allowing exact name and terminology matches to reinforce its rank.
        semantic_by_path = {item.path: (rank, item) for rank, item in enumerate(semantic, 1)}
        literal_by_path = {item.path: (rank, item) for rank, item in enumerate(literal, 1)}
        fused: list[tuple[float, int, SearchResult]] = []
        for path in set(semantic_by_path) | set(literal_by_path):
            score = 0.0
            ranks: list[int] = []
            retrieval: list[str] = []
            if path in semantic_by_path:
                rank, semantic_item = semantic_by_path[path]
                score += 0.7 / (60 + rank)
                ranks.append(rank)
                retrieval.append("semantic")
            else:
                semantic_item = None
            if path in literal_by_path:
                rank, literal_item = literal_by_path[path]
                score += 0.3 / (60 + rank)
                ranks.append(rank)
                retrieval.append("literal")
            else:
                literal_item = None
            selected = literal_item or semantic_item
            if selected is None:  # pragma: no cover - guarded by path union
                continue
            fused.append(
                (
                    score,
                    min(ranks),
                    replace(
                        selected,
                        score=round(score * 100000, 4),
                        retrieval=tuple(retrieval),
                        excerpt=(
                            semantic_item.excerpt
                            if semantic_item is not None and semantic_item.excerpt
                            else selected.excerpt
                        ),
                    ),
                )
            )
        fused.sort(key=lambda item: (-item[0], item[1], item[2].path))
        return [item[2] for item in fused[:limit]]

    @staticmethod
    def _query_terms(query: str) -> list[str]:
        return [item.casefold() for item in query.split() if item]

    @staticmethod
    def _semantic_anchor_terms(query: str) -> list[str]:
        terms: list[str] = []
        seen: set[str] = set()

        def add(value: str) -> None:
            folded = value.casefold().strip()
            if len(folded) >= 2 and folded not in seen:
                seen.add(folded)
                terms.append(folded)

        for token in re.findall(r"[A-Za-z0-9_]{2,}|[\u3400-\u9fff]{2,}", query):
            add(token)
            if re.fullmatch(r"[\u3400-\u9fff]+", token) and len(token) > 4:
                for size in (4, 3, 2):
                    for index in range(0, len(token) - size + 1):
                        add(token[index : index + size])
        return terms[:80]

    @classmethod
    def _locate_chunk(
        cls,
        body: str,
        chunk: str,
        terms: list[str],
    ) -> tuple[int, str, str, float]:
        chunk_text = cls._strip_rag_metadata(chunk).replace("\ufffd", "")
        offset = body.find(chunk_text) if chunk_text else -1
        if offset < 0 and chunk_text:
            for probe in (
                line.strip()
                for line in chunk_text.splitlines()
                if len(line.strip()) >= 12
            ):
                offset = body.find(probe)
                if offset >= 0:
                    break
        start_line = body[: max(0, offset)].count("\n") + 1 if offset >= 0 else 1
        chunk_lines = chunk_text.splitlines() or [chunk_text]
        best: tuple[float, int, str] | None = None
        for index, line in enumerate(chunk_lines):
            stripped = line.strip()
            if not cls._is_substantive_snippet(stripped):
                continue
            folded = stripped.casefold()
            hit_weight = sum(min(6, len(term)) for term in terms if term in folded)
            prose_bonus = min(3.0, len(stripped) / 80)
            syntax_penalty = 1.5 if re.match(r"^[A-Za-z0-9_.-]+\s*[:=]", stripped) else 0
            score = float(hit_weight * 2 + prose_bonus - syntax_penalty)
            candidate = (score, start_line + index, stripped[:280])
            if best is None or candidate[0] > best[0]:
                best = candidate
        if best is None:
            fallback = next(
                (line.strip() for line in chunk_lines if line.strip()),
                chunk_text[:280],
            )
            best = (0.0, start_line, fallback[:280])
        literal_hits, line, snippet = best
        heading = cls._heading_for_line(body, line)
        return line, heading, snippet, literal_hits

    @staticmethod
    def _is_substantive_snippet(value: str) -> bool:
        if not value or value in {"+++", "---", "***"}:
            return False
        if re.fullmatch(r"[#>*_`~+\-=|:：；，。！？、,.!?;\s]+", value):
            return False
        visible = re.sub(r"^[#>*_`~+\-=|\s]+", "", value).strip()
        return len(re.sub(r"\W", "", visible, flags=re.UNICODE)) >= 2

    @classmethod
    def _source_excerpt(
        cls,
        body: str,
        target_line: int,
        *,
        maximum_chars: int = 1600,
    ) -> str:
        lines = body.splitlines()
        if not lines:
            return ""
        center = max(0, min(len(lines) - 1, int(target_line) - 1))
        start = max(0, center - 3)
        end = min(len(lines), center + 6)
        selected = [
            line.strip()
            for line in lines[start:end]
            if cls._is_substantive_snippet(line.strip())
        ]
        excerpt = "\n".join(selected).strip()
        return excerpt[:maximum_chars]

    @staticmethod
    def _strip_rag_metadata(chunk: str) -> str:
        prefixes = (
            "OpenWrite 资料范围：",
            "OpenWrite 子分类：",
            "OpenWrite 来源：",
        )
        lines = str(chunk or "").strip().splitlines()
        while lines and any(lines[0].startswith(prefix) for prefix in prefixes):
            lines.pop(0)
        while lines and not lines[0].strip():
            lines.pop(0)
        return "\n".join(lines).strip()

    @staticmethod
    def _heading_for_line(body: str, target_line: int) -> str:
        heading = ""
        for number, line in enumerate(body.splitlines(), 1):
            if number > target_line:
                break
            match = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
            if match:
                heading = match.group(1).strip()
        return heading

    @staticmethod
    def _match_document(
        document: IndexedDocument,
        terms: list[str],
    ) -> SearchResult | None:
        title_folded = document.title.casefold()
        heading = ""
        best: tuple[float, int, str, str] | None = None
        taxonomy_text = (
            f"{document.title}\n{SCOPE_LABELS.get(document.scope, document.scope)}\n"
            f"{document.category_label}"
        ).casefold()
        taxonomy_hits = sum(term in taxonomy_text for term in terms)
        if taxonomy_hits:
            best = (
                float(taxonomy_hits + (4 if taxonomy_hits == len(terms) else 0)),
                1,
                document.title,
                document.category_label,
            )
        for number, line in enumerate(document.body.splitlines(), 1):
            heading_match = re.match(r"^#{1,6}\s+(.+?)\s*$", line)
            if heading_match:
                heading = heading_match.group(1).strip()
            haystack = f"{document.title}\n{heading}\n{line}".casefold()
            hits = sum(term in haystack for term in terms)
            if not hits:
                continue
            all_terms = hits == len(terms)
            title_hits = sum(term in title_folded for term in terms)
            heading_hits = sum(term in heading.casefold() for term in terms)
            score = hits + title_hits * 3 + heading_hits * 2 + (4 if all_terms else 0)
            snippet = line.strip() or heading
            candidate = (float(score), number, heading, snippet[:280])
            if best is None or candidate[0] > best[0]:
                best = candidate
        if best is None:
            return None
        score, line, matched_heading, snippet = best
        return SearchResult(
            path=document.path,
            title=document.title,
            line=line,
            heading=matched_heading,
            snippet=snippet,
            scope=document.scope,
            category=document.category,
            category_label=document.category_label,
            score=score,
            retrieval=("literal",),
            document_id=document.document_id,
            revision=document.current_revision,
        )


class _IndexUpdateLock:
    def __init__(self, path: Path, *, stale_after_seconds: int = 6 * 60 * 60) -> None:
        self.path = path
        self.stale_after_seconds = stale_after_seconds
        self.acquired = False

    def __enter__(self) -> _IndexUpdateLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                if self._is_stale():
                    self.path.unlink(missing_ok=True)
                    continue
                raise SearchIndexBusyError("LightRAG index is busy") from None
            payload = json.dumps({"pid": os.getpid()}).encode("ascii")
            os.write(descriptor, payload)
            os.close(descriptor)
            self.acquired = True
            return self
        raise SearchIndexBusyError("LightRAG index lock could not be recovered")

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.acquired:
            self.path.unlink(missing_ok=True)
            self.acquired = False

    def _is_stale(self) -> bool:
        try:
            age = max(0.0, time.time() - self.path.stat().st_mtime)
            if age > self.stale_after_seconds:
                return True
            payload = json.loads(self.path.read_text(encoding="ascii"))
            pid = int(payload.get("pid") or 0)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return True
        if pid <= 0:
            return True
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        return False


def _bounded_env_int(
    name: str,
    profile_value: Any,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = os.environ.get(name, "").strip()
    value = raw if raw else profile_value
    try:
        parsed = int(default if value in {None, ""} else value)
    except (TypeError, ValueError) as exc:
        raise SearchConfigurationError(f"{name} 必须是整数") from exc
    if not minimum <= parsed <= maximum:
        raise SearchConfigurationError(f"{name} 必须在 {minimum}-{maximum} 之间")
    return parsed


def _run_async(factory: Callable[[], Coroutine[Any, Any, T]]) -> T:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    result: list[T] = []
    errors: list[BaseException] = []

    def runner() -> None:
        try:
            result.append(asyncio.run(factory()))
        except BaseException as exc:  # pragma: no cover - exercised only inside async hosts
            errors.append(exc)

    thread = threading.Thread(target=runner, name="openwrite-lightrag", daemon=True)
    thread.start()
    thread.join()
    if errors:
        raise errors[0]
    return result[0]
