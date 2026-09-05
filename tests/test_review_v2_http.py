from __future__ import annotations

import json
import os
import time
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import pytest

from tools.init_project import init_project
from tools.model_benchmark import ModelBenchmarkService
from tools.model_profiles import ModelProfileStore
from tools.project_registry import ProjectRegistry
from tools.studio import StudioApplication, create_server
from tools.studio_preferences import StudioModelSettingsStore


def _wait(app: StudioApplication, task_id: str, timeout: float = 3) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        task = app.get_task(task_id)["task"]
        if task["status"] in {"completed", "failed", "cancelled", "interrupted"}:
            return task
        time.sleep(0.01)
    raise AssertionError(f"task {task_id} did not finish")


def _request(opener, url: str, *, method: str = "GET", payload: dict | None = None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if method != "GET":
        headers["X-OpenWrite-Studio"] = "1"
    request = Request(url, method=method, data=data, headers=headers)
    with opener.open(request) as response:
        return json.loads(response.read())


def _profile(profile_id: str, model: str) -> dict:
    return {
        "id": profile_id,
        "label": profile_id,
        "provider": "openai",
        "base_url": "https://models.invalid/v1",
        "model": model,
        "api_format": "chat",
        "context_tokens": 64000,
        "max_output_tokens": 4096,
    }


def _embedding_profile(profile_id: str, model: str) -> dict:
    return {
        "id": profile_id,
        "label": profile_id,
        "provider": "openai",
        "base_url": "https://embeddings.invalid/v1",
        "model": model,
        "dimension": 1536,
        "max_tokens": 8192,
    }


def _prepare_writable_chapter(project_root: Path, novel_id: str = "demo") -> None:
    novel_root = project_root / "data" / "novels" / novel_id
    (novel_root / "src" / "outline.md").write_text(
        "# 大纲\n\n## 第一篇\n\n### 开头\n\n#### 第一章\n\n> 内容焦点: 雨夜钟声揭开谜团\n",
        encoding="utf-8",
    )
    story = novel_root / "src" / "story"
    authored = {
        "author_intent.md": "# 作者意图\n\n描写人在真相与亲情之间的选择。\n",
        "current_focus.md": "# 当前章目标\n\n用三声钟响推动林岑进入旧宅。\n",
        "background.md": "# 故事背景\n\n雾城每逢雨夜会出现一座旧宅。\n",
        "foundation.md": "# 基础设定\n\n钟声只会被失去记忆的人听见。\n",
    }
    for name, content in authored.items():
        (story / name).write_text(content, encoding="utf-8")


def _start_server(
    tmp_path: Path,
    *,
    profiles: ModelProfileStore | None = None,
    settings: StudioModelSettingsStore | None = None,
):
    registry = ProjectRegistry(tmp_path / "registry.yaml", allow_ephemeral=True)
    server = create_server(
        tmp_path,
        port=0,
        project_registry=registry,
        model_profile_store=profiles,
        model_settings_store=settings,
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _stop_server(server, thread: Thread) -> None:
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)
    if server.app._task_runner is not None:
        server.app._task_runner.shutdown(wait=True)


def test_dog_graph_http_reads_materialized_records_without_running_models(tmp_path: Path):
    init_project(tmp_path, "demo")
    chapter_root = tmp_path / "data" / "novels" / "demo" / "data" / "dog" / "reviews" / "ch_001"
    chapter_root.mkdir(parents=True)
    (chapter_root / "review.json").write_text(
        json.dumps(
            {
                "schemaVersion": "dsh-novel.review.manifest.v2",
                "recordType": "review",
                "chapterId": "ch_001",
                "verdict": "pass",
                "qualityScore": 84,
            }
        ),
        encoding="utf-8",
    )
    (chapter_root / "domain.json").write_text(
        json.dumps({"status": "evaluated", "qualityScore": 84}),
        encoding="utf-8",
    )
    relative = chapter_root.relative_to(tmp_path)
    (chapter_root / "dog-graph.json").write_text(
        json.dumps(
            {
                "root": "root",
                "nodes": {
                    "root": {"target": str(relative / "review.json")},
                    "domain": {"target": str(relative / "domain.json")},
                    "missing": {"target": str(relative / "missing.json")},
                    "outside": {"target": "../outside.json"},
                    "not-json": {"target": str(relative / "note.txt")},
                },
                "contains": [],
                "dependsOn": [],
            }
        ),
        encoding="utf-8",
    )

    server, thread = _start_server(tmp_path)
    opener = build_opener(ProxyHandler({}))
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        result = _request(opener, f"{base}/api/dog/graphs?chapter=ch_001")
        assert result["chapter_id"] == "ch_001"
        assert result["chapters"] == ["ch_001"]
        assert result["review"]["manifest"]["qualityScore"] == 84
        assert result["review"]["records"] == {
            "root": {
                "schemaVersion": "dsh-novel.review.manifest.v2",
                "recordType": "review",
                "chapterId": "ch_001",
                "verdict": "pass",
                "qualityScore": 84,
            },
            "domain": {"status": "evaluated", "qualityScore": 84},
        }
        assert result["delivery"] is None

        with pytest.raises(HTTPError) as invalid:
            _request(opener, f"{base}/api/dog/graphs?chapter=../../etc")
        assert invalid.value.code == 400
        error = json.loads(invalid.value.read())
        assert error["code"] == "INVALID_CHAPTER_ID"
    finally:
        _stop_server(server, thread)


def test_review_framework_http_is_project_independent_and_versioned(tmp_path: Path):
    server, thread = _start_server(tmp_path)
    opener = build_opener(ProxyHandler({}))
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        framework = _request(opener, f"{base}/api/review/framework")
        assert framework["schema_version"] == "openwrite.review-dag-framework.v1"
        assert framework["id"] == "openwrite.standard-chapter-review"
        assert framework["revision"].startswith("sha256:")
        assert framework["invariants"]["node_count"] == 47
        assert framework["invariants"]["legacy_check_count"] == 37
        assert framework["topology_locked"] is True
    finally:
        _stop_server(server, thread)


def test_dog_graph_http_rejects_corrupt_artifacts_and_unknown_versions(tmp_path: Path):
    init_project(tmp_path, "demo")
    corrupt_root = tmp_path / "data" / "novels" / "demo" / "data" / "dog" / "deliveries" / "ch_002"
    corrupt_root.mkdir(parents=True)
    (corrupt_root / "dog-graph.json").write_text("{broken", encoding="utf-8")
    (corrupt_root / "delivery.json").write_text(
        json.dumps({"schemaVersion": "openwrite.delivery-dog.v2", "deliveryStatus": "blocked"}),
        encoding="utf-8",
    )

    server, thread = _start_server(tmp_path)
    opener = build_opener(ProxyHandler({}))
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        # Corrupt JSON is a contract failure, never a silently empty graph.
        with pytest.raises(HTTPError) as corrupt:
            _request(opener, f"{base}/api/dog/graphs?chapter=ch_002")
        assert corrupt.value.code == 400
        assert json.loads(corrupt.value.read())["code"] == "CONTRACT_INVALID"

        # Missing files are still tolerated as absent artifacts.
        absent = _request(opener, f"{base}/api/dog/graphs?chapter=ch_999")
        assert absent["chapter_id"] == "ch_999"
        assert absent["review"] is None
        assert absent["delivery"] is None
    finally:
        _stop_server(server, thread)


def test_dog_graph_http_rejects_unknown_review_manifest_version(tmp_path: Path):
    init_project(tmp_path, "demo")
    chapter_root = tmp_path / "data" / "novels" / "demo" / "data" / "dog" / "reviews" / "ch_003"
    chapter_root.mkdir(parents=True)
    (chapter_root / "review.json").write_text(
        json.dumps(
            {
                "schemaVersion": "dsh-novel.review.manifest.v999",
                "recordType": "review",
                "chapterId": "ch_003",
                "verdict": "pass",
            }
        ),
        encoding="utf-8",
    )
    (chapter_root / "dog-graph.json").write_text(
        json.dumps(
            {
                "root": "root",
                "nodes": {},
                "contains": [],
                "dependsOn": [],
            }
        ),
        encoding="utf-8",
    )

    server, thread = _start_server(tmp_path)
    opener = build_opener(ProxyHandler({}))
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with pytest.raises(HTTPError) as invalid:
            _request(opener, f"{base}/api/dog/graphs?chapter=ch_003")
        assert invalid.value.code == 400
        error = json.loads(invalid.value.read())
        assert error["code"] == "CONTRACT_INVALID"
        assert "v999" in error["error"]
    finally:
        _stop_server(server, thread)


def test_dog_graph_http_rejects_non_object_artifact_shapes(tmp_path: Path):
    """`review.json`/`delivery.json`/`dog-graph.json` written as `[]`/`null`
    must fail as CONTRACT_INVALID — only a missing file is tolerated."""
    init_project(tmp_path, "demo")
    server, thread = _start_server(tmp_path)
    opener = build_opener(ProxyHandler({}))
    base = f"http://127.0.0.1:{server.server_port}"
    dog_root = tmp_path / "data" / "novels" / "demo" / "data" / "dog"
    try:
        for artifact in ("reviews", "deliveries"):
            chapter = dog_root / artifact / "ch_010"
            chapter.mkdir(parents=True, exist_ok=True)
            for bad in ("[]", "null", '"text"', "3"):
                for filename in ("review.json", "delivery.json", "dog-graph.json"):
                    (chapter / filename).write_text(bad, encoding="utf-8")
                with pytest.raises(HTTPError) as invalid:
                    _request(opener, f"{base}/api/dog/graphs?chapter=ch_010")
                assert invalid.value.code == 400
                error = json.loads(invalid.value.read())
                assert error["code"] == "CONTRACT_INVALID", (artifact, bad)
                for filename in ("review.json", "delivery.json", "dog-graph.json"):
                    (chapter / filename).unlink()
    finally:
        _stop_server(server, thread)


def test_model_profile_http_exposes_safe_credential_rotation_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    timestamp = "2026-08-25T10:15:00Z"
    monkeypatch.setattr(
        ModelProfileStore,
        "_utc_timestamp",
        staticmethod(lambda: timestamp),
    )
    profiles = ModelProfileStore(tmp_path / "model-profiles")
    profiles.save_profile(
        _profile("writer", "writer-model"),
        api_key="http-test-credential",
    )
    server, thread = _start_server(tmp_path, profiles=profiles)
    opener = build_opener(ProxyHandler({}))
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        result = _request(opener, f"{base}/api/model/profiles")
        writer = next(item for item in result["data"]["profiles"] if item["id"] == "writer")
        serialized = json.dumps(result, ensure_ascii=False)

        assert writer["configured"] is True
        assert writer["credential_updated_at"] == timestamp
        assert "api_key" not in writer
        assert "http-test-credential" not in serialized
    finally:
        _stop_server(server, thread)

def test_model_profile_http_crud_routes_and_fallback_are_credential_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    profiles = ModelProfileStore(tmp_path / "model-profiles")
    profiles.save_profile(_profile("fallback", "fallback-model"), api_key="fallback-secret")
    server, thread = _start_server(tmp_path, profiles=profiles)
    opener = build_opener(ProxyHandler({}))
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        created = _request(
            opener,
            f"{base}/api/model/profiles",
            method="POST",
            payload=_profile("writer", "writer-model"),
        )
        assert created["ok"] is True
        assert created["error"] is None
        assert created["data"]["profile"]["id"] == "writer"
        assert "api_key" not in json.dumps(created, ensure_ascii=False)
        routed = _request(
            opener,
            f"{base}/api/model/routes",
            method="POST",
            payload={"routes": {"chapter_write": "writer"}},
        )
        assert routed["ok"] is True
        assert routed["data"]["model_profiles"]["routes"]["chapter_write"] == "writer"
        assert routed["data"]["impact"]["changed_routes"] == [
            {"route": "chapter_write", "from": None, "to": "writer"}
        ]
        assert routed["data"]["impact"]["profiles_affected"] == ["writer"]
        deleted = _request(
            opener,
            f"{base}/api/model/profiles/delete",
            method="POST",
            payload={"profile_id": "writer", "fallback_id": "fallback"},
        )
        assert deleted["ok"] is True
        assert deleted["data"]["routes"]["chapter_write"] == "fallback"
    finally:
        _stop_server(server, thread)


def test_benchmark_http_runs_background_task_and_reads_isolated_artifact(tmp_path: Path):
    init_project(tmp_path, "demo")
    _prepare_writable_chapter(tmp_path)
    profiles = ModelProfileStore(tmp_path / "model-profiles")
    profiles.save_profile(_profile("writer", "writer-model"), api_key="writer-test-secret")
    profiles.save_profile(_profile("critic", "critic-model"), api_key="critic-test-secret")
    profiles.save_routes({"chapter_write": "writer", "review": "critic"})
    routes_before = dict(profiles.load()["routes"])

    server, thread = _start_server(tmp_path, profiles=profiles)
    server.app._benchmark_service = ModelBenchmarkService(
        tmp_path,
        "demo",
        profiles,
        generation_executor=lambda profile, packet, chapter_number, target_words: {
            "title": "隔离候选",
            "content": "门外传来三声钟响。" * 40,
            "word_count": target_words,
            "finish_reason": "stop",
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "total_tokens": 30,
                "completion_tokens_details": {"reasoning_tokens": 3},
            },
        },
        review_executor=lambda profile, content, packet: {
            "score": 88,
            "passed": True,
            "issue_details": [],
            "usage": {"total_tokens": 12},
            "review_v2": {
                "execution_status": "completed",
                "quality_score": 88,
                "coverage": 1,
                "gate_status": "pass",
                "delivery_status": "pass",
            },
        },
    )
    opener = build_opener(ProxyHandler({}))
    base = f"http://127.0.0.1:{server.server_port}"
    manuscript_root = tmp_path / "data" / "novels" / "demo" / "data" / "manuscript"
    try:
        created = _request(
            opener,
            f"{base}/api/benchmarks",
            method="POST",
            payload={
                "chapter_id": "ch_001",
                "writer_profile_ids": ["writer"],
                "reviewer_profile_ids": ["critic"],
                "repeats": 1,
                "target_words": 800,
                "concurrency": 1,
                "execution_mode": "creative",
            },
        )
        task = _wait(server.app, created["data"]["task_id"])
        assert task["status"] == "completed", json.dumps(task, ensure_ascii=False, indent=2)
        run_id = task["result"]["run_id"]

        listed = _request(opener, f"{base}/api/benchmarks?limit=5")
        assert listed["data"]["runs"][0]["run_id"] == run_id
        detail = _request(opener, f"{base}/api/benchmarks/{run_id}")
        assert detail["data"]["config"]["blind_review"] is True
        assert detail["data"]["evaluations"][0]["quality_score"] == 88
        assert detail["data"]["candidates"][0]["reasoning_tokens"] == 3
        serialized = json.dumps(detail, ensure_ascii=False)
        assert "writer-test-secret" not in serialized
        assert "critic-test-secret" not in serialized
        assert profiles.load()["routes"] == routes_before
        assert not list(manuscript_root.rglob("*.md"))

        with pytest.raises(HTTPError) as missing:
            _request(opener, f"{base}/api/benchmarks/bench_00000000_missing")
        assert missing.value.code == 404
        assert json.loads(missing.value.read())["code"] == "BENCHMARK_NOT_FOUND"

        with pytest.raises(HTTPError) as invalid_limit:
            _request(opener, f"{base}/api/benchmarks?limit=nope")
        assert invalid_limit.value.code == 400
        assert json.loads(invalid_limit.value.read())["code"] == "INVALID_INPUT"
    finally:
        _stop_server(server, thread)


def test_benchmark_http_rejects_unknown_artifact_version(tmp_path: Path):
    init_project(tmp_path, "demo")
    server, thread = _start_server(tmp_path)
    opener = build_opener(ProxyHandler({}))
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        store = server.app._benchmarks().store
        store.save(
            {
                "schema_version": "openwrite.model-benchmark.v999",
                "run_id": "bench_version_v999",
                "status": "completed",
                "context_hash": "sha256:x",
                "config": {"writer_profile_ids": ["w"], "reviewer_profile_ids": ["r"]},
                "candidates": [],
                "evaluations": [],
            }
        )

        with pytest.raises(HTTPError) as invalid:
            _request(opener, f"{base}/api/benchmarks/bench_version_v999")
        assert invalid.value.code == 400
        error = json.loads(invalid.value.read())
        assert error["code"] == "CONTRACT_INVALID"
        assert "v999" in error["error"]
    finally:
        _stop_server(server, thread)


def test_model_post_routes_use_envelope_contract():
    from tools.studio_http import POST_ROUTES

    for route in (
        "/api/model",
        "/api/model/test",
        "/api/model/embedding/test",
        "/api/model/profiles",
        "/api/model/profiles/delete",
        "/api/model/profiles/delete-preview",
        "/api/model/routes",
        "/api/research/settings",
    ):
        assert POST_ROUTES[route].envelope is True, route


def test_model_post_endpoints_return_envelopes_and_uniform_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    from tools.studio_preferences import StudioModelSettingsStore

    init_project(tmp_path, "demo")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    profiles = ModelProfileStore(tmp_path / "model-profiles")
    profiles.save_profile(_profile("writer", "writer-model"), api_key="writer-secret")
    monkeypatch.setattr(
        "tools.studio_application.StudioApplication._default_model_connection_test",
        staticmethod(lambda _settings: {"reply": "OK"}),
    )
    monkeypatch.setattr(
        "tools.embedding_runtime.run_embedding_probe",
        lambda settings: {
            "ok": True,
            "provider": settings.provider,
            "provider_label": "云端 API",
            "model": settings.model,
            "dimension": settings.dimension,
            "max_tokens": settings.max_tokens,
            "base_url": settings.base_url,
            "vectors": 2,
            "latency_ms": 3,
        },
    )
    server, thread = _start_server(
        tmp_path,
        profiles=profiles,
        settings=StudioModelSettingsStore(tmp_path / "studio-settings"),
    )
    opener = build_opener(ProxyHandler({}))
    base = f"http://127.0.0.1:{server.server_port}"
    env_keys = ("LLM_PROVIDER", "LLM_MODEL", "LLM_API_FORMAT", "LLM_BASE_URL", "LLM_API_KEY")
    env_before = {key: os.environ.get(key) for key in env_keys}
    try:
        configured = _request(
            opener,
            f"{base}/api/model",
            method="POST",
            payload={
                "provider": "openai",
                "base_url": "https://models.invalid/v1",
                "model": "writer-model",
                "api_key": "configure-secret",
                "api_format": "chat",
                "context_tokens": 64000,
                "max_tokens": 4096,
            },
        )
        assert configured["ok"] is True
        assert configured["error"] is None
        assert configured["data"]["model"]["name"] == "writer-model"
        assert "configure-secret" not in json.dumps(configured, ensure_ascii=False)

        tested = _request(
            opener,
            f"{base}/api/model/test",
            method="POST",
            payload={**_profile("writer", "writer-model")},
        )
        assert tested["ok"] is True
        assert tested["data"]["status"] == "ok"
        assert tested["data"]["reply"] == "OK"

        embedding_profile = _embedding_profile("search-vector", "embedding-model")
        saved_embedding = _request(
            opener,
            f"{base}/api/model/embedding",
            method="POST",
            payload={**embedding_profile, "api_key": "embedding-secret"},
        )
        assert saved_embedding["ok"] is True

        embedded = _request(
            opener,
            f"{base}/api/model/embedding/test",
            method="POST",
            payload={**embedding_profile},
        )
        assert embedded["ok"] is True
        assert embedded["data"]["status"] == "ok"
        assert embedded["data"]["vectors"] == 2

        research = _request(
            opener,
            f"{base}/api/research/settings",
            method="POST",
            payload={"search_provider": "bocha"},
        )
        assert research["ok"] is True
        assert research["data"]["settings"]["search_provider"] == "bocha"

        # delete-preview: in-use without fallback → blocked; with a configured
        # fallback (the "default" profile configure_model saved) → resulting map.
        _request(
            opener,
            f"{base}/api/model/routes",
            method="POST",
            payload={"routes": {"chapter_write": "writer"}},
        )
        preview = _request(
            opener,
            f"{base}/api/model/profiles/delete-preview",
            method="POST",
            payload={"profile_id": "writer"},
        )
        assert preview["ok"] is True
        assert preview["data"]["deletable"] is False
        assert preview["data"]["blocking_reasons"] == ["MODEL_PROFILE_IN_USE"]
        assert preview["data"]["used_by_routes"] == ["chapter_write"]
        assert preview["data"]["routes_that_would_fail"] == ["chapter_write"]
        assert preview["data"]["resulting_routes"] is None

        preview_ok = _request(
            opener,
            f"{base}/api/model/profiles/delete-preview",
            method="POST",
            payload={"profile_id": "writer", "fallback_id": "default"},
        )
        assert preview_ok["data"]["deletable"] is True
        assert preview_ok["data"]["blocking_reasons"] == []
        assert preview_ok["data"]["resulting_routes"]["chapter_write"] == "default"
        # Preview is read-only: the stored route still points at writer.
        surface = _request(opener, f"{base}/api/model/profiles")
        assert surface["data"]["routes"]["chapter_write"] == "writer"
    finally:
        for key, value in env_before.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        _stop_server(server, thread)


def test_model_test_http_error_body_is_uniform(tmp_path: Path, monkeypatch):
    from tools.llm.errors import RateLimitError

    init_project(tmp_path, "demo")
    profiles = ModelProfileStore(tmp_path / "model-profiles")
    profiles.save_profile(_profile("writer", "writer-model"), api_key="writer-secret")

    def fail(_settings):
        raise RateLimitError("429 slow down")

    monkeypatch.setattr(
        "tools.studio_application.StudioApplication._default_model_connection_test",
        staticmethod(fail),
    )
    server, thread = _start_server(tmp_path, profiles=profiles)
    opener = build_opener(ProxyHandler({}))
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        with pytest.raises(HTTPError) as error:
            _request(
                opener,
                f"{base}/api/model/test",
                method="POST",
                payload={**_profile("writer", "writer-model")},
            )
        assert error.value.code == 502
        body = json.loads(error.value.read())
        assert body["code"] == "MODEL_TEST_RATE_LIMITED"
        assert body["recoverable"] is True
        assert body["details"] == {}
        assert body["request_id"].startswith("req_")
        assert "429 slow down" not in body["error"]
        assert "writer-secret" not in json.dumps(body, ensure_ascii=False)
    finally:
        _stop_server(server, thread)


def test_benchmark_task_reports_real_progress_units(tmp_path: Path):
    init_project(tmp_path, "demo")
    _prepare_writable_chapter(tmp_path)
    profiles = ModelProfileStore(tmp_path / "model-profiles")
    profiles.save_profile(_profile("writer", "writer-model"), api_key="writer-test-secret")
    profiles.save_profile(_profile("critic", "critic-model"), api_key="critic-test-secret")
    profiles.save_routes({"chapter_write": "writer", "review": "critic"})
    routes_before = dict(profiles.load()["routes"])

    server, thread = _start_server(tmp_path, profiles=profiles)
    server.app._benchmark_service = ModelBenchmarkService(
        tmp_path,
        "demo",
        profiles,
        generation_executor=lambda profile, packet, chapter_number, target_words: {
            "title": "隔离候选",
            "content": "门外传来三声钟响。" * 40,
            "word_count": target_words,
            "finish_reason": "stop",
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        },
        review_executor=lambda profile, content, packet: {
            "score": 88,
            "passed": True,
            "issue_details": [],
            "usage": {"total_tokens": 12},
            "review_v2": {
                "execution_status": "completed",
                "quality_score": 88,
                "coverage": 1,
                "gate_status": "pass",
                "delivery_status": "pass",
            },
        },
    )
    opener = build_opener(ProxyHandler({}))
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        created = _request(
            opener,
            f"{base}/api/benchmarks",
            method="POST",
            payload={
                "chapter_id": "ch_001",
                "writer_profile_ids": ["writer"],
                "reviewer_profile_ids": ["critic"],
                "repeats": 1,
                "target_words": 800,
                "concurrency": 1,
                "execution_mode": "creative",
            },
        )
        task_id = created["data"]["task_id"]
        task = _wait(server.app, task_id)
        assert task["status"] == "completed", json.dumps(task, ensure_ascii=False, indent=2)
        run_id = task["result"]["run_id"]

        # Canonical phase mapping: preparing → model → validating → committing → complete.
        events = server.app.get_task(task_id)["events"]
        phases = [event["phase"] for event in events if event["event"] == "task_phase_changed"]
        assert phases == ["preparing", "model", "validating", "committing"]
        assert task["phase"] == "complete"

        # Real unit accounting: 1 candidate then 1 evaluation, ratio ends at 1.0.
        progress_events = [
            event["details"] for event in events if event["event"] == "task_progress_updated"
        ]
        units = [
            (item["unit_kind"], item["completed_units"], item["total_units"])
            for item in progress_events
        ]
        assert units[0] == ("candidates", 0, 1)
        assert units[-1] == ("evaluations", 1, 1)
        candidate_units = [item[1] for item in units if item[0] == "candidates"]
        evaluation_units = [item[1] for item in units if item[0] == "evaluations"]
        assert candidate_units == sorted(candidate_units)
        assert evaluation_units == sorted(evaluation_units)

        # Task DTO: progress union + benchmark result_ref (M1a).
        assert task["progress"] == {
            "completed_units": 1,
            "total_units": 1,
            "ratio": 1.0,
            "unit_kind": "evaluations",
        }
        assert task["result_ref"] == {"type": "benchmark_run", "id": run_id}

        # Artifact: optional task_id/started_at + new summary fields.
        artifact = server.app.benchmark_run(run_id)
        assert artifact["task_id"] == task_id
        assert artifact["started_at"]
        assert artifact["summary"]["failed_candidates"] == 0
        latency = artifact["summary"]["latency_ms_total"]
        assert isinstance(latency, int) and latency >= 0
        assert latency == (
            artifact["candidates"][0]["latency_ms"] + artifact["evaluations"][0]["latency_ms"]
        )

        # Run-scoped activation never mutates global routes.
        assert profiles.load()["routes"] == routes_before
    finally:
        _stop_server(server, thread)
