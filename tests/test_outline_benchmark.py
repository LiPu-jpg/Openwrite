"""Offline task-aware benchmark integration with isolated project registries."""

import hashlib
import json
import re
import time
from pathlib import Path
from threading import Thread
from types import SimpleNamespace
from urllib.request import ProxyHandler, build_opener

import pytest

from tools.benchmark_execution import BenchmarkExecution
from tools.benchmark_tasks import (
    OUTLINE_DIMENSIONS,
    BenchmarkInputError,
    benchmark_options,
    benchmark_pipeline,
    benchmark_target,
    outline_context_preview,
)
from tools.init_project import init_project
from tools.llm import LLMClient
from tools.model_benchmark import ModelBenchmarkService, _benchmark_comparison
from tools.model_profiles import ModelProfileStore
from tools.outline_benchmark import OutlineReviewerAgent, validate_outline_window
from tools.project_registry import ProjectRegistry
from tools.review_rubric import selected_domains
from tools.studio import StudioApplication, create_server

SUMMARY = "林霁发现旧港异常，决定进入灯塔调查。"


def chapter(number):
    return {
        "number": number,
        "title": "灯塔",
        "summary": SUMMARY,
        "dramatic_position": "承",
        "content_focus": "调查灯塔",
        "goals": ["找到线索"],
        "estimated_words": 3000,
        "involved_characters": ["林霁"],
        "involved_settings": ["旧港"],
        "emotional_arc": "犹疑 -> 决意",
        "beats": ["发现异常", "进入灯塔"],
        "hooks": ["门后是谁"],
    }


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    init_project(root, "book", "灯塔")
    novel = root / "data" / "novels" / "book"
    for name in ("author_intent", "current_focus", "background", "foundation"):
        (novel / "src" / "story" / f"{name}.md").write_text("# 已确认设定\n\n" + SUMMARY)
    (novel / "src" / "outline.md").write_text(
        "# 灯塔\n\n寻找异常来源。\n\n## 第1篇：旧港\n\n调查。\n\n### 第1节：灯塔\n\n前进。\n\n"
        + "\n\n".join(f"#### 第{number}章：灯塔\n\n{SUMMARY}" for number in range(1, 6))
    )
    profiles = ModelProfileStore(tmp_path / "profiles")
    for profile_id in ("writer", "writer-two", "critic", "critic-two"):
        profiles.save_profile(
            {
                "id": profile_id,
                "label": profile_id,
                "provider": "openai",
                "model": "offline-test",
                "base_url": "https://invalid.example/v1",
                "api_format": "chat",
                "context_tokens": 128000,
                "max_output_tokens": 16000,
                "temperature": 0.7,
                "timeout_seconds": 60,
            },
            api_key="isolated-unit-secret",
        )
    registry = ProjectRegistry(tmp_path / "registry.yaml", allow_ephemeral=True)
    return root, profiles, registry


@pytest.fixture
def model_calls(monkeypatch):
    calls = []

    def chat(self, *, messages, **kwargs):
        system, user = messages[0].content, messages[-1].content
        calls.append((system, user))
        if "大纲师" in system:
            start = int(re.search(r"起始章节（含）：第(\d+)章", user).group(1))
            end = int(re.search(r"结束章节（含）：第(\d+)章", user).group(1))
            payload = [chapter(number) for number in range(start, end + 1)]
        elif "硬门禁评审员" in system:
            payload = {"id": "safety", "status": "pass", "findings": []}
        else:
            domain = next(
                domain
                for domain in selected_domains(OUTLINE_DIMENSIONS)
                if f"“{domain.name}”" in system
            )
            payload = {
                "id": domain.id,
                "criteria": [
                    {
                        "id": criterion.id,
                        "status": "evaluated",
                        "earned": criterion.max_points,
                        "evidence": [SUMMARY],
                        "rationale": "规划证据完整",
                    }
                    for criterion in domain.criteria
                ],
                "issues": [],
            }
            assert "拟议章节大纲" in user
        return SimpleNamespace(
            content=json.dumps(payload, ensure_ascii=False),
            usage={"total_tokens": 20},
            total_tokens=20,
            finish_reason="stop",
            model="offline",
            provider="test",
        )

    monkeypatch.setattr(LLMClient, "chat", chat)
    return calls


def test_options_are_read_only_and_expose_task_specific_real_pipelines(project):
    root, profiles, registry = project
    app = StudioApplication(root, model_profile_store=profiles, project_registry=registry)
    try:
        before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
        options = app.benchmark_options()
        assert options["default_outline_start_chapter"] == 6
        assert all(
            task["readiness"] == {"ok": True, "code": "", "message": ""}
            for task in options["tasks"]
        )
        assert [item["chapter_id"] for item in options["chapters"]] == [
            f"ch_{number:03d}" for number in range(1, 6)
        ]
        outline = options["tasks"][1]["pipelines"][0]
        assert outline["execution_mode"] == "framework"
        assert "prose" not in {domain["id"] for domain in outline["review_domains"]}
        assert "safety" in {domain["id"] for domain in outline["review_domains"]}
        assert before == {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    finally:
        if app._task_runner is not None:
            app._task_runner.shutdown(wait=True)


def test_options_report_missing_acceptance_baseline_without_writes_or_models(project, model_calls):
    from tools.manuscript_acceptance import ManuscriptAcceptanceError, ManuscriptAcceptanceService

    root, profiles, registry = project
    path = root / "data/novels/book/data/manuscript/arc_001/ch_001.md"
    path.write_text("# 第一章\n已存在但尚未建立接纳基线的正文。")
    app = StudioApplication(root, model_profile_store=profiles, project_registry=registry)
    try:
        before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
        options = app.benchmark_options()
        for task in options["tasks"]:
            chapter_id = (
                options["next_chapter_id"] if task["task_type"] == "chapter"
                else f"ch_{options['default_outline_start_chapter']:03d}"
            )
            with pytest.raises(ManuscriptAcceptanceError) as raised:
                ManuscriptAcceptanceService(root, "book").require_current(chapter_id)
            assert task["readiness"] == {
                "ok": False,
                "code": "ACCEPTANCE_BASELINE_REQUIRED",
                "message": str(raised.value),
            }
        assert before == {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
        assert model_calls == []
    finally:
        if app._task_runner is not None:
            app._task_runner.shutdown(wait=True)


def test_options_readiness_distinguishes_missing_chapter_plan_from_outline_design(project):
    root, _profiles, _registry = project
    (root / "data/novels/book/src/outline.md").write_text("# 尚未设计章节\n\n" + SUMMARY)
    tasks = {item["task_type"]: item for item in benchmark_options(root, "book")["tasks"]}
    assert tasks["chapter"]["readiness"]["code"] == "TARGET_NOT_PLANNED"
    assert tasks["outline"]["readiness"] == {"ok": True, "code": "", "message": ""}


def test_options_http_is_available_without_model_calls(project, monkeypatch):
    root, profiles, registry = project
    monkeypatch.setattr(
        LLMClient, "chat", lambda *_args, **_kwargs: pytest.fail("read-only options called a model")
    )
    server = create_server(root, port=0, project_registry=registry, model_profile_store=profiles)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        opener = build_opener(ProxyHandler({}))
        with opener.open(
            f"http://127.0.0.1:{server.server_port}/api/benchmarks/options"
        ) as response:
            payload = json.loads(response.read())["data"]
        assert payload["default_outline_start_chapter"] == 6
        assert all(item["readiness"]["ok"] for item in payload["tasks"])
    finally:
        server.shutdown()
        server.server_close()
        if server.app._task_runner is not None:
            server.app._task_runner.shutdown(wait=True)
        thread.join()


def test_studio_outline_task_uses_planning_snapshot_and_validated_artifact(project, model_calls):
    root, profiles, registry = project
    app = StudioApplication(root, model_profile_store=profiles, project_registry=registry)
    try:
        created = app.create_benchmark(
            {
                "task_type": "outline",
                "outline_start_chapter": 8,
                "outline_chapter_count": 1,
                "writer_profile_ids": ["writer"],
                "reviewer_profile_ids": ["critic"],
            }
        )
        assert created["input_summary"] == "模型横评 · 大纲设计第8-8章"
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            task = app.get_task(created["task_id"])["task"]
            if task["status"] in {"completed", "failed"}:
                break
            time.sleep(0.01)
        assert task["status"] == "completed", task
        run = app.benchmark_run(task["result"]["run_id"])
        assert run["config"]["task_type"] == "outline"
        assert run["config"]["outline_start_chapter"] == 8
        assert run["candidates"][0]["outline_chapter_count"] == 1
    finally:
        if app._task_runner is not None:
            app._task_runner.shutdown(wait=True)


def test_outline_task_summary_resolves_default_inclusive_range(project, monkeypatch):
    root, profiles, registry = project
    app = StudioApplication(root, model_profile_store=profiles, project_registry=registry)
    captured = {}

    def submit(_task_type, task_input, **kwargs):
        captured.update(input=task_input, **kwargs)
        return {"task_id": "test"}

    monkeypatch.setattr(app, "_tasks", lambda: SimpleNamespace(submit=submit))
    try:
        app.create_benchmark({"task_type": "outline"})
        assert captured["input_summary"] == "模型横评 · 大纲设计第6-8章"
        assert captured["input"]["outline_start_chapter"] == 6
        assert captured["input"]["outline_end_chapter"] == 8
        assert captured["chapter_id"] == "ch_006"
    finally:
        if app._task_runner is not None:
            app._task_runner.shutdown(wait=True)


def test_outline_framework_runs_real_planner_and_scoped_reviewer_in_isolation(project, model_calls):
    root, profiles, _registry = project
    novel = root / "data" / "novels" / "book"
    before = {path: path.read_bytes() for path in novel.rglob("*") if path.is_file()}
    service = ModelBenchmarkService(root, "book", profiles)
    payload = {
        "task_type": "outline",
        "outline_start_chapter": 4,
        "outline_chapter_count": 2,
        "writer_profile_ids": ["writer", "writer-two"],
        "reviewer_profile_ids": ["critic", "critic-two"],
        "concurrency": 2,
    }
    target = service.target(payload)
    snapshot = outline_context_preview(root, "book", target)
    result = service.run(payload, snapshot)

    assert result["status"] == "completed"
    assert len(result["candidates"]) == 2 and len(result["evaluations"]) == 4
    for candidate in result["candidates"]:
        assert (
            candidate["outline_start_chapter"],
            candidate["outline_end_chapter"],
            candidate["outline_chapter_count"],
        ) == (4, 5, 2)
        assert candidate["framework"]["write_entrypoint"] == "ArchitectAgent.generate_outline"
        assert all(
            node["status"] == "completed"
            for node in candidate["framework"]["pipeline_execution"]["nodes"]
        )
        execution = json.loads(Path(candidate["framework"]["execution_path"]).read_text())
        assert execution["nodes"][-1]["status"] == "completed"
        assert len(execution["nodes"][-1]["evidence"]) == 2
        for evidence in execution["nodes"][-1]["evidence"]:
            path = Path(candidate["framework"]["execution_path"]).parent / evidence["path"]
            data = path.read_bytes()
            assert evidence["sha256"] == hashlib.sha256(data).hexdigest()
            assert evidence["bytes"] == len(data)
        assert Path(candidate["workspace_path"]) != root
    assert all(
        item["execution_status"] == "completed" and item["coverage"] == 1
        for item in result["evaluations"]
    )
    assert (
        len(model_calls) == 26
    )  # 2 planners + 4 reviews × (5 applicable quality domains + safety)
    assert all(path.read_bytes() == content for path, content in before.items())
    record = service.store.load(result["run_id"])
    assert record["config"]["pipeline"] == benchmark_pipeline("outline", "framework")
    assert record["rubric_version"] == "openwrite.outline-review.v1"
    assert "isolated-unit-secret" not in Path(result["artifact_path"]).read_text()


@pytest.mark.parametrize("numbers", [[4], [4, 4], [1, 2], [4, 6]])
def test_outline_range_never_silently_renumbers_or_accepts_missing_chapters(numbers):
    with pytest.raises(ValueError):
        validate_outline_window([chapter(number) for number in numbers], 4, 2)


@pytest.mark.parametrize(
    "field,value",
    [
        ("outline_start_chapter", 0),
        ("outline_start_chapter", True),
        ("outline_start_chapter", 1.5),
        ("outline_chapter_count", 0),
        ("outline_chapter_count", 21),
    ],
)
def test_outline_target_rejects_invalid_ranges(project, field, value):
    root, _profiles, _registry = project
    with pytest.raises(BenchmarkInputError):
        benchmark_target(root, "book", {"task_type": "outline", field: value})


def test_historical_context_is_explicitly_unavailable_but_future_non_next_is_valid(project):
    root, _profiles, _registry = project
    manuscript = root / "data/novels/book/data/manuscript/ch_002.md"
    manuscript.parent.mkdir(parents=True, exist_ok=True)
    manuscript.write_text("第2章正文")
    options = benchmark_options(root, "book")
    assert options["next_chapter_id"] == "ch_003"
    assert all(
        item["availability"] == "unavailable" and item["reason"] for item in options["chapters"][:2]
    )
    with pytest.raises(BenchmarkInputError) as error:
        benchmark_target(root, "book", {"chapter_id": "ch_001"})
    assert error.value.code == "BENCHMARK_HISTORICAL_CONTEXT_UNAVAILABLE"
    assert benchmark_target(root, "book", {"chapter_id": "ch_005"})["chapter_id"] == "ch_005"


def test_outline_failure_preserves_usage_and_skips_all_reviewer_branches(
    project, monkeypatch, model_calls
):
    from tools.architect import ArchitectAgent

    original = ArchitectAgent.generate_outline

    async def wrong_count(self, *args, **kwargs):
        chapters = await original(self, *args, **kwargs)
        return chapters[:1]

    monkeypatch.setattr(ArchitectAgent, "generate_outline", wrong_count)
    root, profiles, _registry = project
    service = ModelBenchmarkService(root, "book", profiles)
    payload = {
        "task_type": "outline",
        "outline_chapter_count": 2,
        "writer_profile_ids": ["writer"],
        "reviewer_profile_ids": ["critic"],
    }
    result = service.run(payload, outline_context_preview(root, "book", service.target(payload)))
    assert result["status"] == "failed" and result["evaluations"] == []
    candidate = result["candidates"][0]
    assert candidate["usage"]["total_tokens"] == 20
    assert candidate["framework"]["stage_statuses"]["validate"] == "failed"
    assert candidate["framework"]["stage_statuses"]["review"] == "skipped"
    assert len(model_calls) == 1


def test_execution_refuses_unfulfilled_dependencies_and_retains_failure(tmp_path):
    trace = BenchmarkExecution(
        tmp_path / "execution.json", benchmark_pipeline("outline", "framework")
    )
    with pytest.raises(ValueError, match="dependencies"):
        trace.start("review")
    trace.start("context")
    trace.fail("context", "MISSING_CONTEXT")
    assert trace.nodes["plan"]["status"] == "skipped"
    with pytest.raises(ValueError):
        trace.start("plan")


def test_outline_review_failure_is_persisted_per_reviewer(project, monkeypatch, model_calls):
    async def fail(*args, **kwargs):
        raise RuntimeError("offline review failure")

    monkeypatch.setattr(OutlineReviewerAgent, "review", fail)
    root, profiles, _registry = project
    service = ModelBenchmarkService(root, "book", profiles)
    payload = {
        "task_type": "outline",
        "outline_chapter_count": 1,
        "writer_profile_ids": ["writer"],
        "reviewer_profile_ids": ["critic"],
    }
    result = service.run(payload, outline_context_preview(root, "book", service.target(payload)))
    review = result["evaluations"][0]
    assert review["execution_status"] == "failed"
    assert Path(review["framework"]["artifact_path"]).is_file()
    assert review["framework"]["pipeline_execution"]["nodes"][-1]["status"] == "failed"


def test_comparison_key_separates_target_task_and_outline_range():
    base = {"context_hash": "same", "chapter_id": "ch_004", "config": {"task_type": "chapter"}}
    first = _benchmark_comparison(base)["key"]
    assert first != _benchmark_comparison({**base, "chapter_id": "ch_005"})["key"]
    assert (
        first
        != _benchmark_comparison(
            {
                **base,
                "config": {
                    "task_type": "outline",
                    "outline_start_chapter": 4,
                    "outline_chapter_count": 2,
                },
            }
        )["key"]
    )


def test_chapter_pipeline_dependencies_match_the_production_run_v2():
    from tools.chapter_run_v2 import V2_STAGE_DEPENDENCIES

    nodes = benchmark_pipeline("chapter", "framework")["nodes"]
    assert {node["id"]: tuple(node["depends_on"]) for node in nodes} == V2_STAGE_DEPENDENCIES


def test_chapter_review_evidence_hashes_artifact_bytes_not_logical_revision(tmp_path):
    artifact = tmp_path / "review.json"
    artifact.write_text('{\n  "score": 80\n}\n')
    stages = {
        node["id"]: SimpleNamespace(
            status="completed", artifact="", output_revision="sha256:logical-revision"
        )
        for node in benchmark_pipeline("chapter", "framework")["nodes"]
    }
    stages["review"].artifact = "review.json"
    framework = ModelBenchmarkService._framework_evidence(
        workspace=tmp_path,
        entrypoint="execute_review_chapter",
        run_id_v2="run-test",
        manifest=SimpleNamespace(stages=stages),
        committed_stage="review",
        committed_key="review_committed",
        search_profile=None,
    )
    node = next(n for n in framework["pipeline_execution"]["nodes"] if n["id"] == "review")
    assert node["evidence"] == [{
        "path": str(artifact),
        "output_revision": "sha256:logical-revision",
        "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "bytes": len(artifact.read_bytes()),
    }]


def test_outline_can_design_unplanned_range_but_still_requires_authored_foundation(project):
    root, _profiles, _registry = project
    target = benchmark_target(root, "book", {"task_type": "outline", "outline_start_chapter": 10})
    assert outline_context_preview(root, "book", target)["chapter_id"] == "ch_010"
    foundation = root / "data/novels/book/src/story/foundation.md"
    foundation.write_text("# 基础设定\n待填写")
    with pytest.raises(BenchmarkInputError) as raised:
        outline_context_preview(root, "book", target)
    assert raised.value.code == "PROJECT_NOT_READY"


@pytest.mark.parametrize("mode", ["creative", "framework"])
def test_all_chapter_modes_reject_prior_unaccepted_facts_before_any_model(
    project, model_calls, mode
):
    from tools.manuscript_acceptance import ManuscriptAcceptanceError

    root, profiles, _registry = project
    path = root / "data/novels/book/data/manuscript/arc_001/ch_001.md"
    path.write_text("# 第一章\n未接纳的正文。")
    service = ModelBenchmarkService(root, "book", profiles)
    with pytest.raises(ManuscriptAcceptanceError) as error:
        service.run(
            {
                "task_type": "chapter",
                "chapter_id": "ch_005",
                "execution_mode": mode,
                "writer_profile_ids": ["writer"],
                "reviewer_profile_ids": ["critic"],
            },
            {"chapter_id": "ch_005", "packet": {"outline": "第五章"}},
        )
    assert error.value.code == "ACCEPTANCE_BASELINE_REQUIRED"
    assert model_calls == []
