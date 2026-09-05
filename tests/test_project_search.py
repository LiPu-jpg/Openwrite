import asyncio
import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import tools.project_search as project_search_module
from tools.model_profiles import activate_model_profile
from tools.project_search import (
    MANIFEST_VERSION,
    BackendSearchResult,
    IndexedDocument,
    LightRAGConfiguration,
    LightRAGSearchBackend,
    ProjectSearchIndex,
    RetrievedChunk,
    SearchConfigurationError,
)
from tools.reading_order import ReadingOrderService


def test_project_search_maps_lightrag_chunks_back_to_scoped_source_lines(tmp_path: Path):
    novel_root = tmp_path / "novel"
    character = novel_root / "src" / "characters" / "lin_cen.md"
    world = novel_root / "src" / "world" / "clocktower.md"
    character.parent.mkdir(parents=True)
    world.parent.mkdir(parents=True)
    character.write_text(
        "# 林岑\n\n## 未解目标\n\n她在雨夜寻找失踪的旧信。\n",
        encoding="utf-8",
    )
    world.write_text("# 旧钟楼\n\n钟楼会吞掉寄出的信。\n", encoding="utf-8")
    captured = {}

    class FakeBackend:
        def search(self, documents, query, *, limit):
            captured["query"] = query
            del limit
            by_path = {document.path: document for document in documents}
            return BackendSearchResult(
                chunks=[
                    RetrievedChunk(
                        by_path["src/world/clocktower.md"].source_key,
                        "钟楼会吞掉寄出的信。",
                        1,
                    ),
                    RetrievedChunk(
                        by_path["src/characters/lin_cen.md"].source_key,
                        LightRAGSearchBackend._rag_document_body(
                            by_path["src/characters/lin_cen.md"]
                        ),
                        2,
                    ),
                ],
                inserted=2,
            )

        def refresh(self, documents):
            return BackendSearchResult(chunks=[], inserted=len(documents))

    payload = ProjectSearchIndex(
        novel_root,
        backend_factory=lambda root: FakeBackend(),
    ).search("她一直在追查什么", scope="characters")

    assert payload["engine"] == "lightrag"
    assert payload["index_updates"]["inserted"] == 2
    assert len(payload["results"]) == 1
    assert payload["results"][0]["path"] == "src/characters/lin_cen.md"
    assert payload["results"][0]["line"] == 5
    assert payload["results"][0]["heading"] == "未解目标"
    assert payload["results"][0]["scope"] == "characters"
    assert payload["results"][0]["category_label"] == "配角"
    assert payload["results"][0]["document_id"].startswith("doc_")
    assert payload["results"][0]["revision"].startswith("sha256:")
    assert payload["results"][0]["locator"] == {
        "line": 5,
        "quote": payload["results"][0]["snippet"],
        "quote_sha256": "sha256:"
        + hashlib.sha256(payload["results"][0]["snippet"].encode("utf-8")).hexdigest(),
    }
    assert captured["query"].startswith("OpenWrite 资料范围：角色\n")
    assert "OpenWrite 资料范围" not in payload["results"][0]["snippet"]


def test_project_search_uses_explicit_literal_fallback_when_lightrag_is_unconfigured(
    tmp_path: Path,
):
    novel_root = tmp_path / "novel"
    story = novel_root / "src" / "story" / "background.md"
    story.parent.mkdir(parents=True)
    story.write_text("# 背景\n\n钟楼每天少走十三秒。\n", encoding="utf-8")

    def unavailable(root):
        del root
        raise SearchConfigurationError("缺少 embedding")

    payload = ProjectSearchIndex(novel_root, backend_factory=unavailable).search(
        "十三秒",
        scope="story",
    )

    assert payload["engine"] == "literal-fallback"
    assert payload["scope"] == "core"
    assert payload["warning_code"] == "LIGHTRAG_NOT_CONFIGURED"
    assert payload["results"][0]["line"] == 3


def test_manuscript_search_identity_and_revision_match_canonical_reading_order(
    tmp_path: Path,
):
    novel_root = tmp_path / "data" / "novels" / "demo"
    chapter = novel_root / "data" / "manuscript" / "arc_001" / "ch_001.md"
    chapter.parent.mkdir(parents=True)
    chapter.write_text("# 第一章\n\n钟楼每天少走十三秒。\n", encoding="utf-8")

    def unavailable(root):
        del root
        raise SearchConfigurationError("缺少 embedding")

    result = ProjectSearchIndex(
        novel_root, backend_factory=unavailable
    ).search("十三秒", scope="chapters")["results"][0]
    reading = ReadingOrderService(tmp_path, "demo").surface()["documents"][0]

    assert result["document_id"] == reading["document_id"]
    assert result["revision"] == reading["revision"]
    assert result["locator"]["line"] == 3


def test_lightrag_runtime_is_serialized_across_distinct_workspaces(
    tmp_path: Path,
    monkeypatch,
):
    active = 0
    maximum_active = 0
    guard = threading.Lock()

    def fake_run_async(factory):
        nonlocal active, maximum_active
        del factory
        with guard:
            active += 1
            maximum_active = max(maximum_active, active)
        time.sleep(0.05)
        with guard:
            active -= 1
        return BackendSearchResult(chunks=[])

    monkeypatch.setattr(project_search_module, "_run_async", fake_run_async)
    backends = [
        LightRAGSearchBackend.__new__(LightRAGSearchBackend),
        LightRAGSearchBackend.__new__(LightRAGSearchBackend),
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda backend: backend.search([], "query", limit=1), backends))

    assert len(results) == 2
    assert maximum_active == 1


def test_literal_fallback_matches_taxonomy_and_uses_yaml_display_name(tmp_path: Path):
    novel_root = tmp_path / "novel"
    progression = novel_root / "src" / "progression" / "clock_sense.yaml"
    progression.parent.mkdir(parents=True)
    progression.write_text(
        "id: clock_sense\nname: 时感\nkind: ability\nsummary: 感知丢失的时间\n",
        encoding="utf-8",
    )

    def unavailable(root):
        del root
        raise SearchConfigurationError("缺少 embedding")

    payload = ProjectSearchIndex(novel_root, backend_factory=unavailable).search(
        "规则与体系",
        scope="settings",
    )

    assert payload["engine"] == "literal-fallback"
    assert payload["results"][0]["title"] == "时感"
    assert payload["results"][0]["category"] == "setting_systems"
    assert payload["results"][0]["snippet"] == "规则与体系"


def test_lightrag_manifest_tracks_incremental_insert_update_and_delete(tmp_path: Path):
    configuration = LightRAGConfiguration(
        provider="openai",
        llm_model="test-model",
        llm_base_url="https://models.example/v1",
        llm_api_key="llm-secret",
        timeout_seconds=30,
        embedding_provider="openai",
        embedding_model="test-embedding",
        embedding_base_url="https://embeddings.example/v1",
        embedding_api_key="embedding-secret",
        embedding_dimension=8,
        embedding_max_tokens=512,
        query_mode="mix",
    )
    backend = LightRAGSearchBackend(tmp_path, configuration=configuration)

    class FakeRAG:
        def __init__(self):
            self.inserted = []
            self.deleted = []

        async def ainsert(self, body, *, ids, file_paths):
            self.inserted.extend(zip(ids, file_paths, body))

        async def adelete_by_doc_id(self, doc_id):
            self.deleted.append(doc_id)
            return SimpleNamespace(status="success")

    first = IndexedDocument(
        path="src/story/background.md",
        title="背景",
        body="第一版背景",
        scope="core",
        category="core_premise",
        category_label="故事基础",
        revision="rev-1",
        doc_id="doc-1",
        source_key="source-1.md",
    )
    second = IndexedDocument(
        path="src/world/rules.md",
        title="规则",
        body="世界规则",
        scope="settings",
        category="setting_systems",
        category_label="规则与体系",
        revision="rev-2",
        doc_id="doc-2",
        source_key="source-2.md",
    )
    rag = FakeRAG()

    initial = asyncio.run(backend._sync_documents(rag, [first, second]))
    unchanged = asyncio.run(backend._sync_documents(rag, [first, second]))
    revised = IndexedDocument(
        **{
            **first.__dict__,
            "body": "第二版背景",
            "revision": "rev-3",
            "doc_id": "doc-3",
        }
    )
    changed = asyncio.run(backend._sync_documents(rag, [revised]))

    assert initial == {"inserted": 2, "updated": 0, "deleted": 0}
    assert unchanged == {"inserted": 0, "updated": 0, "deleted": 0}
    assert changed == {"inserted": 0, "updated": 1, "deleted": 1}
    assert rag.deleted == ["doc-2", "doc-1"]
    assert [item[0] for item in rag.inserted] == ["doc-1", "doc-2", "doc-3"]
    assert "OpenWrite 资料范围：作品核心" in rag.inserted[0][2]
    assert "OpenWrite 子分类：故事基础" in rag.inserted[0][2]
    manifest = backend._load_manifest()
    assert manifest["version"] == MANIFEST_VERSION
    assert list(manifest["documents"]) == ["src/story/background.md"]
    assert manifest["documents"]["src/story/background.md"]["doc_id"] == "doc-3"


def test_local_vector_configuration_needs_no_chat_api_key(monkeypatch):
    for name in (
        "LLM_API_KEY",
        "OPENWRITE_LIGHTRAG_EMBEDDING_PROVIDER",
        "OPENWRITE_LIGHTRAG_EMBEDDING_API_KEY",
        "OPENWRITE_LIGHTRAG_MODE",
    ):
        monkeypatch.delenv(name, raising=False)
    active = {
        "provider": "openai",
        "base_url": "https://models.example/v1",
        "model": "unused-in-vector-mode",
        "api_format": "responses",
        "api_key": "",
        "search_mode": "vector",
        "embedding_provider": "local",
        "embedding_model": "BAAI/bge-small-zh-v1.5",
        "embedding_dimension": 512,
        "embedding_max_tokens": 512,
    }

    with activate_model_profile(active):
        configuration = LightRAGConfiguration.from_runtime()

    assert configuration.query_mode == "naive"
    assert configuration.embedding_provider == "local"
    assert configuration.llm_api_key == ""


def test_search_configuration_uses_search_chat_route_and_reuses_vector_workspace(
    monkeypatch,
):
    for name in (
        "LLM_API_KEY",
        "OPENWRITE_LIGHTRAG_EMBEDDING_PROVIDER",
        "OPENWRITE_LIGHTRAG_EMBEDDING_API_KEY",
        "OPENWRITE_LIGHTRAG_MODE",
    ):
        monkeypatch.delenv(name, raising=False)
    writer = {
        "provider": "openai",
        "base_url": "https://writer.example/v1",
        "model": "writer-model",
        "api_format": "chat",
        "api_key": "writer-key",
    }
    search = {
        "provider": "openai",
        "base_url": "https://search.example/v1",
        "model": "search-model",
        "api_format": "chat",
        "api_key": "search-key",
        "search_mode": "vector",
        "embedding_provider": "local",
        "embedding_model": "BAAI/bge-small-zh-v1.5",
        "embedding_dimension": 512,
        "embedding_max_tokens": 512,
    }

    with activate_model_profile(writer, search_profile=search):
        configuration = LightRAGConfiguration.from_runtime()

    equivalent = LightRAGConfiguration(
        **{
            **configuration.__dict__,
            "llm_model": "another-unused-chat-model",
            "llm_base_url": "https://another-writer.example/v1",
        }
    )
    assert configuration.llm_model == "search-model"
    assert configuration.llm_api_key == "search-key"
    assert configuration.workspace == equivalent.workspace


def test_vector_manifest_syncs_chunks_without_graph_extraction(
    tmp_path: Path,
):
    configuration = LightRAGConfiguration(
        provider="openai",
        llm_model="unused-in-vector-mode",
        llm_base_url="https://models.example/v1",
        llm_api_key="",
        timeout_seconds=30,
        embedding_provider="local",
        embedding_model="test-embedding",
        embedding_base_url="",
        embedding_api_key="",
        embedding_dimension=8,
        embedding_max_tokens=512,
        query_mode="naive",
    )
    backend = LightRAGSearchBackend(tmp_path, configuration=configuration)

    class FakeStore:
        def __init__(self):
            self.upserts = []
            self.deletes = []
            self.callbacks = 0

        async def upsert(self, payload):
            self.upserts.append(payload)

        async def delete(self, ids):
            self.deletes.append(list(ids))

        async def index_done_callback(self):
            self.callbacks += 1

    class FakeTokenizer:
        def encode(self, content):
            return list(content)

    class FakeRAG:
        def __init__(self):
            self.tokenizer = FakeTokenizer()
            self.chunks_vdb = FakeStore()
            self.text_chunks = FakeStore()
            self.full_docs = FakeStore()

        async def ainsert(self, *args, **kwargs):
            raise AssertionError("vector 模式不应调用图谱抽取")

    first = IndexedDocument(
        path="data/manuscript/arc_001/ch_001.md",
        title="第一章",
        body="雨夜里，沈烬主动疏远了同伴。",
        scope="chapters",
        category="chapter_manuscript",
        category_label="章节正文",
        revision="rev-1",
        doc_id="doc-1",
        source_key="source-1.md",
    )
    second = IndexedDocument(
        path="data/sources/opening/analysis_v2/report.json",
        title="开篇拆书",
        body="先压低选择空间，再揭示隐藏筹码。",
        scope="sources",
        category="source_analysis",
        category_label="拆书分析",
        revision="rev-2",
        doc_id="doc-2",
        source_key="source-2.json",
    )
    rag = FakeRAG()

    initial = asyncio.run(backend._sync_documents(rag, [first, second]))
    initial_manifest = backend._load_manifest()
    first_chunk_ids = initial_manifest["documents"][first.path]["chunk_ids"]
    second_chunk_ids = initial_manifest["documents"][second.path]["chunk_ids"]
    unchanged = asyncio.run(backend._sync_documents(rag, [first, second]))
    revised = IndexedDocument(
        **{
            **first.__dict__,
            "body": "雨停以后，沈烬重新接纳了同伴。",
            "revision": "rev-3",
            "doc_id": "doc-3",
        }
    )
    changed = asyncio.run(backend._sync_documents(rag, [revised]))

    assert initial == {"inserted": 2, "updated": 0, "deleted": 0}
    assert unchanged == {"inserted": 0, "updated": 0, "deleted": 0}
    assert changed == {"inserted": 0, "updated": 1, "deleted": 1}
    assert len(rag.chunks_vdb.upserts[0]) == 2
    assert rag.chunks_vdb.deletes == [second_chunk_ids, first_chunk_ids]
    assert rag.text_chunks.deletes == [second_chunk_ids, first_chunk_ids]
    assert rag.full_docs.deletes == [["doc-2"], ["doc-1"]]
    assert rag.chunks_vdb.callbacks == 2
    manifest = backend._load_manifest()
    assert manifest["index_kind"] == "vector"
    assert list(manifest["documents"]) == [revised.path]
    assert manifest["documents"][revised.path]["doc_id"] == "doc-3"
    assert len(manifest["documents"][revised.path]["chunk_ids"]) == 1


def test_vector_chunking_preserves_unicode_and_token_budget():
    class ByteTokenizer:
        def encode(self, content):
            return list(content.encode("utf-8"))

        def decode(self, tokens):
            return bytes(tokens).decode("utf-8", errors="replace")

    text = "范围说明\n\n沈烬与老刑在雨夜确认同盟。裴织留下未登记回响的线索。"
    rows = LightRAGSearchBackend._unicode_safe_token_chunks(
        ByteTokenizer(),
        text,
        chunk_token_size=18,
        chunk_overlap_token_size=6,
    )

    assert len(rows) > 2
    assert all("\ufffd" not in row["content"] for row in rows)
    assert all(row["tokens"] <= 18 for row in rows)
    assert all(row["content"] in text for row in rows)


def test_semantic_snippet_ignores_frontmatter_and_broken_utf8_prefix(tmp_path: Path):
    novel_root = tmp_path / "novel"
    outline = novel_root / "src" / "outline.md"
    outline.parent.mkdir(parents=True)
    outline.write_text(
        "+++\ntitle = \"第一卷\"\n+++\n\n# 第一卷\n\n"
        "老刑吸纳沈烬为低级归墟使，两人决定调查未登记回响。\n",
        encoding="utf-8",
    )

    class FakeBackend:
        def search(self, documents, query, *, limit):
            del query, limit
            document = documents[0]
            return BackendSearchResult(
                chunks=[
                    RetrievedChunk(
                        document.source_key,
                        "�吸纳沈烬为低级归墟使，两人决定调查未登记回响。",
                        1,
                    )
                ]
            )

        def refresh(self, documents):
            return BackendSearchResult(chunks=[])

    payload = ProjectSearchIndex(
        novel_root, backend_factory=lambda root: FakeBackend()
    ).search("沈烬与老刑形成同盟并调查未登记回响")

    result = payload["results"][0]
    assert result["snippet"] == "吸纳沈烬为低级归墟使，两人决定调查未登记回响。"
    assert result["line"] == 7
    assert "\ufffd" not in result["snippet"]
    assert "老刑吸纳沈烬" in result["excerpt"]
    assert "+++" not in result["excerpt"]


def test_project_search_masks_inline_state_annotations_without_shifting_lines(
    tmp_path: Path,
):
    novel_root = tmp_path / "novel"
    chapter = novel_root / "data" / "manuscript" / "arc_001" / "ch_070.md"
    chapter.parent.mkdir(parents=True)
    chapter.write_text(
        "# 第七十章\n\n//**沈烬[位置]：工坊 -> 归墟港**\n\n他推开了旧门。\n",
        encoding="utf-8",
    )
    captured = {}

    class FakeBackend:
        def search(self, documents, query, *, limit):
            del query, limit
            captured["documents"] = documents
            return BackendSearchResult(chunks=[])

        def refresh(self, documents):
            return BackendSearchResult(chunks=[])

    payload = ProjectSearchIndex(
        novel_root, backend_factory=lambda root: FakeBackend()
    ).search("旧门", scope="chapters")

    body = captured["documents"][0].body
    assert "//**" not in body
    assert len(body.splitlines()) == 5
    assert payload["results"][0]["line"] == 5


def test_project_search_indexes_structured_source_analysis(tmp_path: Path):
    novel_root = tmp_path / "novel"
    report = (
        novel_root
        / "data"
        / "sources"
        / "opening"
        / "analysis_v2"
        / "report.json"
    )
    report.parent.mkdir(parents=True)
    report.write_text(
        """{
  "source_id": "opening",
  "summary": "身份暴露后反客为主。",
  "findings": [{
    "category": "structure",
    "claim": "先压低选择空间，再揭示隐藏筹码。",
    "evidence": []
  }]
}
""",
        encoding="utf-8",
    )

    def unavailable(root):
        del root
        raise SearchConfigurationError("缺少 embedding")

    payload = ProjectSearchIndex(
        novel_root, backend_factory=unavailable
    ).search("隐藏筹码", scope="sources")

    assert payload["scope_label"] == "参考资料"
    assert payload["results"][0]["category_label"] == "拆书分析"
    assert payload["results"][0]["title"] == "opening · 拆书分析"
    assert payload["results"][0]["retrieval"] == ["literal"]
