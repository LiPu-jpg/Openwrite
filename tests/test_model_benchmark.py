import json
from pathlib import Path

import pytest

from tools.chapter_pipeline import execute_write_chapter
from tools.chapter_run_v2 import ChapterRunV2Store
from tools.init_project import init_project
from tools.llm.response import ProviderResponseError
from tools.model_benchmark import BenchmarkFrameworkError, ModelBenchmarkService
from tools.model_profiles import (
    ModelProfileStore,
    active_model_profile,
    active_search_model_profile,
)


def profile(profile_id: str, model: str) -> dict:
    return {
        "id": profile_id,
        "label": profile_id,
        "provider": "openai",
        "base_url": "https://openrouter.ai/api/v1",
        "model": model,
        "api_format": "chat",
        "context_tokens": 128000,
        "max_output_tokens": 16000,
        "temperature": 0.7,
        "timeout_seconds": 120,
    }


def test_benchmark_uses_fixed_context_and_run_scoped_profiles(tmp_path: Path):
    store = ModelProfileStore(tmp_path / "profiles")
    store.save_profile(profile("writer-a", "model-a"), api_key="secret-a")
    store.save_profile(profile("writer-b", "model-b"), api_key="secret-b")
    store.save_profile(profile("critic", "review-model"), api_key="secret-review")
    store.save_routes({"chapter_write": "writer-a", "review": "critic"})
    routes_before = dict(store.load()["routes"])

    manuscript = (
        tmp_path / "data" / "novels" / "book" / "data" / "manuscript" / "arc_001" / "ch_001.md"
    )
    manuscript.parent.mkdir(parents=True)
    manuscript.write_text("# 第一章\n\n正式正文", encoding="utf-8")
    original = manuscript.read_text(encoding="utf-8")

    def generate(profile_, packet, chapter_number, target_words):
        assert packet["outline"] == "固定大纲"
        return {
            "title": f"候选-{profile_['id']}",
            "content": f"{profile_['id']}正文" * 100,
            "word_count": target_words,
            "finish_reason": "stop",
            "usage": {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        }

    def review(profile_, content, packet):
        assert profile_["id"] == "critic"
        assert packet["outline"] == "固定大纲"
        score = 90 if "writer-a" in content else 75
        return {
            "score": score,
            "passed": True,
            "issue_details": [],
            "token_usage": {"total_tokens": 40},
            "review_v2": {
                "execution_status": "completed",
                "quality_score": score,
                "coverage": 1,
                "gate_status": "pass",
                "delivery_status": "pass",
                "production_gate_status": "disabled_uncalibrated",
                "domains": [
                    {
                        "id": "coherence_logic",
                        "status": "evaluated",
                        "coverage": 1,
                        "earned": 18,
                        "max": 20,
                        "potential_max": 20,
                    },
                    {
                        "id": "canon_references",
                        "status": "inconclusive",
                        "coverage": 0,
                        "earned": 0,
                        "max": 0,
                        "potential_max": 15,
                    },
                ],
                "gates": [
                    {
                        "id": "safety",
                        "status": "inconclusive",
                        "error": {
                            "code": "gate timeout",
                            "message": "synthetic provider detail must not persist",
                        },
                    }
                ],
                "provenance": {
                    "audit_calls": 8,
                    "errors": [
                        {
                            "domain": "canon_references",
                            "code": "malformed output",
                            "message": "synthetic response detail must not persist",
                        }
                    ],
                },
            },
        }

    service = ModelBenchmarkService(
        tmp_path,
        "book",
        store,
        generation_executor=generate,
        review_executor=review,
    )
    result = service.run(
        {
            "writer_profile_ids": ["writer-a", "writer-b"],
            "reviewer_profile_id": "critic",
            "repeats": 2,
            "target_words": 1000,
            "concurrency": 2,
            "execution_mode": "creative",
        },
        {
            "chapter_id": "ch_001",
            "target_words": 1000,
            "characters": ["甲"],
            "manifest": {"included": ["outline"]},
            "packet": {"outline": "固定大纲", "target_words": 1000},
        },
    )

    assert result["status"] == "completed"
    assert len(result["candidates"]) == 4
    assert len(result["evaluations"]) == 4
    assert {item["quality_score"] for item in result["evaluations"]} == {75, 90}
    assert {item["production_gate_status"] for item in result["evaluations"]} == {
        "disabled_uncalibrated"
    }
    diagnostics = result["evaluations"][0]["review_diagnostics"]
    assert diagnostics["inconclusive_domain_ids"] == ["canon_references"]
    assert diagnostics["gate_results"] == [
        {
            "id": "safety",
            "status": "inconclusive",
            "error_code": "GATE_TIMEOUT",
        }
    ]
    assert diagnostics["audit_calls"] == 8
    assert diagnostics["provider_errors"] == [
        {"domain": "canon_references", "code": "MALFORMED_OUTPUT"}
    ]
    assert store.load()["routes"] == routes_before
    assert manuscript.read_text(encoding="utf-8") == original
    artifact = Path(result["artifact_path"])
    serialized = artifact.read_text(encoding="utf-8")
    assert "secret-a" not in serialized
    assert "secret-b" not in serialized
    assert "secret-review" not in serialized
    assert "synthetic provider detail must not persist" not in serialized
    assert "synthetic response detail must not persist" not in serialized
    assert json.loads(serialized)["context_hash"] == result["context_hash"]


def test_benchmark_provider_failure_is_not_a_quality_score(tmp_path: Path):
    store = ModelProfileStore(tmp_path / "profiles")
    store.save_profile(profile("writer", "broken-model"), api_key="secret")
    store.save_profile(profile("critic", "critic-model"), api_key="critic-secret")

    def fail_generation(*_args):
        raise RuntimeError("provider unavailable")

    service = ModelBenchmarkService(
        tmp_path,
        "book",
        store,
        generation_executor=fail_generation,
        review_executor=lambda *_args: {},
    )
    result = service.run(
        {
            "writer_profile_ids": ["writer"],
            "reviewer_profile_ids": ["critic"],
            "repeats": 1,
            "execution_mode": "creative",
        },
        {
            "chapter_id": "ch_001",
            "target_words": 1000,
            "packet": {"outline": "固定大纲"},
        },
    )

    assert result["status"] == "failed"
    assert result["candidates"][0]["reliability_status"] == "failed"
    assert result["evaluations"] == []


def test_benchmark_usage_summary_distinguishes_free_from_unknown_cost(tmp_path: Path):
    store = ModelProfileStore(tmp_path / "profiles")
    store.save_profile(profile("writer", "free-model"), api_key="secret")
    store.save_profile(profile("critic", "critic-model"), api_key="critic-secret")

    def generate(*_args):
        return {
            "content": "正文",
            "word_count": 2,
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 20,
                "total_tokens": 30,
                "cost": 0,
            },
        }

    def review(*_args):
        return {
            "score": 80,
            "passed": True,
            "issue_details": [],
            "token_usage": {
                "prompt_tokens": 5,
                "completion_tokens": 7,
                "total_tokens": 12,
                "completion_tokens_details": {"reasoning_tokens": 2},
            },
            "review_v2": {
                "execution_status": "completed",
                "quality_score": 80,
                "coverage": 1,
                "gate_status": "pass",
                "delivery_status": "pass",
            },
        }

    result = ModelBenchmarkService(
        tmp_path,
        "book",
        store,
        generation_executor=generate,
        review_executor=review,
    ).run(
        {
            "writer_profile_ids": ["writer"],
            "reviewer_profile_ids": ["critic"],
            "execution_mode": "creative",
        },
        {"chapter_id": "ch_001", "packet": {"outline": "固定大纲"}},
    )

    assert result["candidates"][0]["cost_usd"] == 0
    assert result["candidates"][0]["cost_reported"] is True
    assert result["evaluations"][0]["cost_reported"] is False
    assert result["summary"] == {
        "requested_candidates": 1,
        "completed_candidates": 1,
        "requested_evaluations": 1,
        "completed_evaluations": 1,
        "average_quality_score": 80.0,
        "prompt_tokens": 15,
        "completion_tokens": 27,
        "reasoning_tokens": 2,
        "total_tokens": 42,
        "total_cost_usd": 0.0,
        "cost_reported_items": 1,
        "cost_item_count": 2,
        "cost_complete": False,
    }


def test_production_write_failure_returns_run_v2_provenance(tmp_path: Path, monkeypatch):
    init_project(tmp_path, "book")

    async def fail_write(*_args, **_kwargs):
        raise ProviderResponseError(
            "MODEL_OUTPUT_TRUNCATED",
            "provider detail must stay out of benchmark artifacts",
        )

    monkeypatch.setattr("tools.agent.WriterAgent.write_chapter", fail_write)

    result = execute_write_chapter(
        tmp_path,
        {"chapter_id": "ch_001", "target_words": 1000},
    )

    assert result["ok"] is False
    assert result["code"] == "MODEL_OUTPUT_TRUNCATED"
    assert result["run_id_v2"].startswith("runv2_")
    manifest = ChapterRunV2Store(tmp_path, "book").load(result["run_id_v2"])
    assert manifest is not None
    assert manifest.stages["draft"].status == "failed"
    assert manifest.stages["draft"].error_code == "MODEL_OUTPUT_TRUNCATED"


def test_framework_mode_runs_public_pipeline_in_per_candidate_workspace(
    tmp_path: Path,
    monkeypatch,
):
    init_project(tmp_path, "book")
    store = ModelProfileStore(tmp_path / "profiles")
    store.save_profile(profile("writer-a", "model-a"), api_key="secret-a")
    store.save_profile(profile("writer-b", "model-b"), api_key="secret-b")
    store.save_profile(profile("critic", "review-model"), api_key="secret-review")
    store.save_profile(profile("search", "search-model"), api_key="secret-search")
    store.save_routes({"chapter_write": "critic", "review": "critic", "search": "search"})
    routes_before = dict(store.load()["routes"])
    manuscript = (
        tmp_path / "data" / "novels" / "book" / "data" / "manuscript" / "arc_001" / "ch_001.md"
    )
    manuscript.write_text("# 原始章节\n\n不得改写", encoding="utf-8")
    original = manuscript.read_text(encoding="utf-8")
    legacy_benchmark = tmp_path / "data" / "novels" / "book" / "data" / "benchmarks" / "legacy.json"
    legacy_benchmark.parent.mkdir(parents=True)
    legacy_benchmark.write_text('{"must_not_copy": true}', encoding="utf-8")
    write_calls: list[tuple[str, Path]] = []
    review_calls: list[tuple[str, Path]] = []

    def framework_write(project_root, args):
        active = active_model_profile() or {}
        active_search = active_search_model_profile() or {}
        profile_id = str(active.get("id") or "")
        assert active_search.get("id") == "search"
        root = Path(project_root).resolve()
        assert root != tmp_path.resolve()
        assert args["context_packet"]["outline"] == "固定大纲"
        sandbox_chapter = (
            root / "data" / "novels" / "book" / "data" / "manuscript" / "arc_001" / "ch_001.md"
        )
        assert sandbox_chapter.read_text(encoding="utf-8") == original
        sandbox_chapter.write_text(f"# 候选-{profile_id}\n\n{profile_id}正文", encoding="utf-8")
        run_store = ChapterRunV2Store(root, "book")
        manifest = run_store.create(
            "ch_001",
            requested_target_words=1000,
            effective_target_words=1000,
            provider="openai",
            model=f"reported-{profile_id}",
        )
        for stage in ("context", "plan", "draft", "fact_extract", "settle", "validate", "commit"):
            run_store.start_stage(manifest, stage)
            run_store.complete_stage(manifest, stage, output={"stage": stage})
        write_calls.append((profile_id, root))
        return {
            "ok": True,
            "chapter_id": "ch_001",
            "title": f"候选-{profile_id}",
            "word_count": 1000,
            "run_id_v2": manifest.run_id,
            "finish_reason": "stop",
            "model": f"reported-{profile_id}",
            "provider": "openai",
            "usage": {"total_tokens": 30},
        }

    def framework_review(project_root, args):
        active = active_model_profile() or {}
        active_search = active_search_model_profile() or {}
        root = Path(project_root).resolve()
        assert str(active.get("id") or "") == "critic"
        assert active_search.get("id") == "search"
        assert args["run_id_v2"].startswith("runv2_")
        assert (root / "data" / "novels" / "book").is_dir()
        run_store = ChapterRunV2Store(root, "book")
        manifest = run_store.load(args["run_id_v2"])
        assert manifest is not None
        run_store.start_stage(manifest, "review")
        run_store.complete_stage(manifest, "review", output={"score": 86})
        review_calls.append((str(active.get("id") or ""), root))
        return {
            "ok": True,
            "score": 86,
            "passed": True,
            "issue_details": [],
            "token_usage": {"total_tokens": 40},
            "review_v2": {
                "execution_status": "completed",
                "quality_score": 86,
                "coverage": 1,
                "gate_status": "pass",
                "delivery_status": "pass",
                "production_gate_status": "disabled_uncalibrated",
                "domains": [],
                "gates": [],
            },
        }

    monkeypatch.setattr("tools.chapter_pipeline.execute_write_chapter", framework_write)
    monkeypatch.setattr("tools.chapter_pipeline.execute_review_chapter", framework_review)
    service = ModelBenchmarkService(tmp_path, "book", store)
    result = service.run(
        {
            "writer_profile_ids": ["writer-a", "writer-b"],
            "reviewer_profile_ids": ["critic"],
            "repeats": 1,
            "target_words": 1000,
            "concurrency": 2,
        },
        {
            "chapter_id": "ch_001",
            "target_words": 1000,
            "packet": {"outline": "固定大纲", "target_words": 1000},
        },
    )

    assert result["status"] == "completed", result
    assert {item[0] for item in write_calls} == {"writer-a", "writer-b"}
    assert len({item[1] for item in write_calls}) == 2
    assert len(review_calls) == 2
    assert all(item["execution_mode"] == "framework" for item in result["candidates"])
    assert all(
        item["framework"]["write_entrypoint"] == "execute_write_chapter"
        for item in result["candidates"]
    )
    assert all(
        item["framework"]["review_entrypoint"] == "execute_review_chapter"
        for item in result["evaluations"]
    )
    assert all(
        item["framework"]["search_profile"]["id"] == "search"
        for item in [*result["candidates"], *result["evaluations"]]
    )
    assert all(Path(item["workspace_path"]).is_dir() for item in result["candidates"])
    assert {item["response_model"] for item in result["candidates"]} == {
        "reported-writer-a",
        "reported-writer-b",
    }
    assert {item["response_provider"] for item in result["candidates"]} == {"openai"}
    assert all(
        not (Path(item["workspace_path"]) / "data/novels/book/data/benchmarks").exists()
        for item in result["candidates"]
    )
    assert manuscript.read_text(encoding="utf-8") == original
    assert store.load()["routes"] == routes_before
    artifact = json.loads(Path(result["artifact_path"]).read_text(encoding="utf-8"))
    assert artifact["config"]["execution_mode"] == "framework"
    assert "secret-a" not in json.dumps(artifact, ensure_ascii=False)
    assert "secret-search" not in json.dumps(artifact, ensure_ascii=False)


def test_benchmark_rejects_invalid_execution_mode(tmp_path: Path):
    store = ModelProfileStore(tmp_path / "profiles")
    store.save_profile(profile("writer", "model"), api_key="secret")
    store.save_profile(profile("critic", "critic"), api_key="review-secret")
    service = ModelBenchmarkService(tmp_path, "book", store)

    with pytest.raises(ValueError, match="execution_mode"):
        service.run(
            {
                "writer_profile_ids": ["writer"],
                "reviewer_profile_ids": ["critic"],
                "execution_mode": "shortcut",
            },
            {"chapter_id": "ch_001", "packet": {"outline": "固定大纲"}},
        )


def test_framework_write_failure_has_no_quality_score(tmp_path: Path, monkeypatch):
    init_project(tmp_path, "book")
    store = ModelProfileStore(tmp_path / "profiles")
    store.save_profile(profile("writer", "model"), api_key="secret")
    store.save_profile(profile("critic", "critic"), api_key="review-secret")

    def failed_write(project_root, _args):
        run_store = ChapterRunV2Store(Path(project_root), "book")
        manifest = run_store.create("ch_001")
        run_store.start_stage(manifest, "context")
        run_store.complete_stage(manifest, "context", output={})
        run_store.start_stage(manifest, "plan")
        run_store.complete_stage(manifest, "plan", output={})
        run_store.start_stage(manifest, "draft")
        run_store.fail_stage(
            manifest,
            "draft",
            code="PROVIDER_UNAVAILABLE",
            message="provider detail must not be persisted",
        )
        return {
            "ok": False,
            "code": "PROVIDER_UNAVAILABLE",
            "run_id_v2": manifest.run_id,
        }

    monkeypatch.setattr("tools.chapter_pipeline.execute_write_chapter", failed_write)
    service = ModelBenchmarkService(tmp_path, "book", store)

    result = service.run(
        {"writer_profile_ids": ["writer"], "reviewer_profile_ids": ["critic"]},
        {"chapter_id": "ch_001", "packet": {"outline": "固定大纲"}},
    )

    assert result["status"] == "failed"
    assert result["candidates"][0]["reliability_status"] == "failed"
    assert result["candidates"][0]["error"]["code"] == "PROVIDER_UNAVAILABLE"
    framework = result["candidates"][0]["framework"]
    assert framework["write_entrypoint"] == "execute_write_chapter"
    assert framework["run_id_v2"].startswith("runv2_")
    assert framework["stage_statuses"]["draft"] == "failed"
    assert framework["failed_stage"] == "draft"
    assert framework["stage_error_code"] == "PROVIDER_UNAVAILABLE"
    assert framework["chapter_committed"] is False
    assert "provider detail must not be persisted" not in json.dumps(result, ensure_ascii=False)
    assert result["evaluations"] == []
    assert result["summary"]["average_quality_score"] is None


def test_framework_review_failure_has_no_quality_score(tmp_path: Path, monkeypatch):
    init_project(tmp_path, "book")
    store = ModelProfileStore(tmp_path / "profiles")
    store.save_profile(profile("writer", "model"), api_key="secret")
    store.save_profile(profile("critic", "critic"), api_key="review-secret")

    def successful_write(project_root, args):
        root = Path(project_root)
        chapter = root / "data/novels/book/data/manuscript/arc_001/ch_001.md"
        chapter.write_text("# 候选\n\n正文", encoding="utf-8")
        run_store = ChapterRunV2Store(root, "book")
        manifest = run_store.create("ch_001")
        for stage in ("context", "plan", "draft", "fact_extract", "settle", "validate", "commit"):
            run_store.start_stage(manifest, stage)
            run_store.complete_stage(manifest, stage, output={"stage": stage})
        return {"ok": True, "run_id_v2": manifest.run_id, "word_count": 2}

    monkeypatch.setattr("tools.chapter_pipeline.execute_write_chapter", successful_write)

    def failed_review(project_root, args):
        run_store = ChapterRunV2Store(Path(project_root), "book")
        manifest = run_store.load(args["run_id_v2"])
        assert manifest is not None
        run_store.start_stage(manifest, "review")
        run_store.fail_stage(
            manifest,
            "review",
            code="REVIEW_PROVIDER_TIMEOUT",
            message="review detail must not be persisted",
        )
        return {
            "ok": False,
            "code": "REVIEW_PROVIDER_TIMEOUT",
            "run_id_v2": manifest.run_id,
        }

    monkeypatch.setattr("tools.chapter_pipeline.execute_review_chapter", failed_review)
    service = ModelBenchmarkService(tmp_path, "book", store)

    result = service.run(
        {"writer_profile_ids": ["writer"], "reviewer_profile_ids": ["critic"]},
        {"chapter_id": "ch_001", "packet": {"outline": "固定大纲"}},
    )

    assert result["status"] == "partial"
    assert result["candidates"][0]["reliability_status"] == "completed"
    assert result["evaluations"][0]["execution_status"] == "failed"
    assert result["evaluations"][0]["quality_score"] is None
    assert result["evaluations"][0]["error"]["code"] == "REVIEW_PROVIDER_TIMEOUT"
    framework = result["evaluations"][0]["framework"]
    assert framework["review_entrypoint"] == "execute_review_chapter"
    assert framework["stage_statuses"]["review"] == "failed"
    assert framework["failed_stage"] == "review"
    assert framework["stage_error_code"] == "REVIEW_PROVIDER_TIMEOUT"
    assert framework["review_committed"] is False
    assert "review detail must not be persisted" not in json.dumps(result, ensure_ascii=False)
    assert result["summary"]["average_quality_score"] is None


def test_framework_review_rejects_workspace_not_owned_by_candidate(tmp_path: Path):
    init_project(tmp_path, "book")
    store = ModelProfileStore(tmp_path / "profiles")
    service = ModelBenchmarkService(tmp_path, "book", store)
    wrong_workspace = service.store.root / "other" / "project"
    wrong_workspace.mkdir(parents=True)

    with pytest.raises(BenchmarkFrameworkError) as error:
        service._review_framework(
            profile("critic", "critic"),
            {
                "benchmark_run_id": "bench_20260825000000_deadbeef00",
                "candidate_id": "bench_20260825000000_deadbeef00_writer_1",
                "workspace_path": str(wrong_workspace),
                "chapter_id": "ch_001",
                "framework": {"run_id_v2": "runv2_missing"},
            },
            None,
        )

    assert error.value.code == "BENCHMARK_WORKSPACE_INVALID"
