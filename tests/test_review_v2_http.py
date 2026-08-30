from __future__ import annotations

import json
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


def _start_server(tmp_path: Path, *, profiles: ModelProfileStore | None = None):
    registry = ProjectRegistry(tmp_path / "registry.yaml", allow_ephemeral=True)
    server = create_server(
        tmp_path,
        port=0,
        project_registry=registry,
        model_profile_store=profiles,
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

def test_model_profile_http_crud_routes_and_fallback_are_credential_free(tmp_path: Path):
    profiles = ModelProfileStore(tmp_path / "model-profiles")
    profiles.save_profile(_profile("fallback", "fallback-model"))
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
        assert created["profile"]["id"] == "writer"
        assert "api_key" not in json.dumps(created, ensure_ascii=False)
        routed = _request(
            opener,
            f"{base}/api/model/routes",
            method="POST",
            payload={"routes": {"chapter_write": "writer"}},
        )
        assert routed["model_profiles"]["routes"]["chapter_write"] == "writer"
        deleted = _request(
            opener,
            f"{base}/api/model/profiles/delete",
            method="POST",
            payload={"profile_id": "writer", "fallback_id": "fallback"},
        )
        assert deleted["routes"]["chapter_write"] == "fallback"
    finally:
        _stop_server(server, thread)


def test_benchmark_http_runs_background_task_and_reads_isolated_artifact(tmp_path: Path):
    init_project(tmp_path, "demo")
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
        assert task["status"] == "completed"
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
