"""Reproduce the deterministic data, task and contract failures from issue #76."""

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.agent.reviewer import ReviewerAgent
from tools.agent.tool_runtime import project_document_change_plan
from tools.agent.writer import WriterAgent
from tools.chapter_pipeline import execute_write_chapter
from tools.chapter_run_v2 import ChapterRunV2Error, ChapterRunV2Store, chapter_run_v2_action
from tools.init_project import init_project
from tools.manuscript_acceptance import ManuscriptAcceptanceError, ManuscriptAcceptanceService
from tools.novel_service import NovelApplicationService, NovelServiceError
from tools.outline_tree import build_outline_structure, mutate_outline_structure
from tools.review_rubric import aggregate_review, selected_domains
from tools.review_store import ReviewStore
from tools.runtime_diagnostics import RuntimeDiagnosticsService
from tools.structured_assets import StructuredAssetService
from tools.task_runner import PersistentTaskRunner
from tools.writing_policy import resolve_target_words


@pytest.fixture
def novel(tmp_path):
    init_project(tmp_path, "demo")
    root = tmp_path / "data" / "novels" / "demo"
    (root / "src" / "outline.md").write_text(
        "# 第一卷\n## 第一幕\n### 第一节\n#### 第1章 起点\n> 预估字数: 15000\n旧摘要\n"
        "#### 第2章 终点\n> 预估字数: 3000\n",
        encoding="utf-8",
    )
    return tmp_path, root


def _wait(runner, task_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        task = runner.store.load(task_id)
        if task["status"] in {"completed", "failed", "cancelled"}:
            return task
        time.sleep(0.01)
    raise AssertionError("task did not terminate")


def _evaluated(domain):
    return {
        "id": domain.id,
        "criteria": [
            {
                "id": criterion.id,
                "status": "evaluated",
                "earned": criterion.max_points,
                "evidence": ["quoted prose"],
            }
            for criterion in domain.criteria
        ],
    }


def _reviewer(monkeypatch):
    reviewer = ReviewerAgent.__new__(ReviewerAgent)
    reviewer.ctx = SimpleNamespace(client=SimpleNamespace(config=SimpleNamespace(model="test")))
    reviewer._audit_usage_summary = lambda: {}
    calls = []

    async def audit(content, context, domains, issues):
        return [_evaluated(domain) for domain in domains], []

    def gate(*args):
        calls.append(True)
        return {"id": "safety", "status": "pass", "findings": []}, []

    reviewer._llm_review_domains = audit
    reviewer._llm_review_gate = gate
    return reviewer, calls


def test_commit_failure_preserves_prose_handle_and_resumes_without_generation(novel, monkeypatch):
    import tools.agent as agents
    import tools.llm as llm

    project, root = novel
    monkeypatch.setattr(
        llm.LLMConfig, "from_env", classmethod(lambda cls: SimpleNamespace(model="requested"))
    )
    monkeypatch.setattr(llm, "LLMClient", lambda config: object())
    monkeypatch.setattr(agents, "AgentContext", lambda *args: SimpleNamespace())
    calls = []

    class Writer:
        def __init__(self, context):
            pass

        async def write_chapter(self, **kwargs):
            calls.append(True)
            return SimpleNamespace(
                title="回声",
                content="昂贵的完整草稿。",
                word_count=8,
                state_updates={},
                state_delta={},
                token_usage={"total_tokens": 157997},
                model="gateway-actual",
                provider="test",
            )

    monkeypatch.setattr(agents, "WriterAgent", Writer)
    original = ManuscriptAcceptanceService.record_precomputed

    def fail(*args, **kwargs):
        raise ManuscriptAcceptanceError("stale ghost", code="STALE_ACCEPTED_REVISION")

    monkeypatch.setattr(ManuscriptAcceptanceService, "record_precomputed", fail)
    result = execute_write_chapter(project, {"chapter_id": "ch_001", "target_words": 15000})
    assert not result["ok"] and result["uncommitted"]
    assert Path(result["draft_path"]).read_text().endswith("昂贵的完整草稿。")
    assert (root / "data/manuscript/arc_001/ch_001.md").exists()
    assert (root / "data/manuscript/arc_001/ch_001.uncommitted.json").exists()
    store = ChapterRunV2Store(project, "demo")
    assert store.load(result["run_id_v2"]).status == "drafted"
    monkeypatch.setattr(ManuscriptAcceptanceService, "record_precomputed", original)
    resumed = NovelApplicationService(project).write_chapter(
        {"chapter_id": "ch_001", "run_id_v2": result["run_id_v2"]}
    )
    assert resumed["ok"] and len(calls) == 1
    assert resumed["model"] == "gateway-actual"
    assert store.load(result["run_id_v2"]).model == "gateway-actual"
    assert not (root / "data/manuscript/arc_001/ch_001.uncommitted.json").exists()


def test_target_precedence_and_preview_agree(novel):
    project, _ = novel
    assert resolve_target_words(800, 15000)["target_words_source"] == "explicit"
    assert resolve_target_words(None, 15000)["target_words"] == 15000
    assert resolve_target_words()["target_words"] == 3000
    preview = NovelApplicationService(project).context_preview("ch_001")
    assert preview["target_words"] == 15000
    assert preview["target_words_source"] == "outline"
    with pytest.raises(ValueError):
        resolve_target_words(50001)


def test_document_batch_preserves_crlf_requires_confirmation_and_undo(novel):
    project, root = novel
    path = root / "src/story/background.md"
    original = b"first\r\nsecond\r\nthird\r\n"
    path.write_bytes(original)
    preview = project_document_change_plan(
        project,
        "demo",
        {
            "action": "preview",
            "path": "src/story/background.md",
            "edits": [
                {"old_text": "first", "new_text": "one"},
                {"old_text": "third", "new_text": "three"},
            ],
        },
    )
    assert preview["edit_count"] == 2
    token = preview["preview_token"]
    assert (
        project_document_change_plan(project, "demo", {"action": "apply", "preview_token": token})[
            "error"
        ]
        == "CONFIRMATION_REQUIRED"
    )
    assert path.read_bytes() == original
    applied = project_document_change_plan(
        project, "demo", {"action": "apply", "preview_token": token, "confirm": True}
    )
    assert applied["applied"]
    assert path.read_bytes() == b"one\r\nsecond\r\nthree\r\n"
    assert applied["normalizations"] == {"count": 0, "kinds": []}
    undone = project_document_change_plan(
        project,
        "demo",
        {"action": "undo", "preview_token": applied["undo_preview_token"], "confirm": True},
    )
    assert undone["applied"] and path.read_bytes() == original


def test_range_rejects_each_ambiguous_endpoint_even_when_only_one_pair_orders(novel):
    project, root = novel
    path = root / "src/story/background.md"
    path.write_text("END\nSTART\nbody\nEND\n", encoding="utf-8")
    result = project_document_change_plan(
        project,
        "demo",
        {
            "action": "preview",
            "path": "src/story/background.md",
            "edits": [{"start_text": "START", "end_text": "END", "new_text": "replacement"}],
        },
    )
    assert result["error"] == "ambiguous_text_range"
    assert "body" in path.read_text()


def test_outline_summary_replaces_metadata_block_and_promote_keeps_chapter_ids(novel):
    _, root = novel
    outline = root / "src/outline.md"
    structure = build_outline_structure(root)
    result = mutate_outline_structure(
        root,
        operation="update_summary",
        revision=structure["revision"],
        node_id="ch_001",
        summary="> 预估字数: 8000\n新摘要",
    )
    assert result["content"].count("> 预估字数: 8000") == 1
    assert "15000" not in result["content"] and "旧摘要" not in result["content"]
    outline.write_text(result["content"], encoding="utf-8")
    structure = build_outline_structure(root)
    result = mutate_outline_structure(
        root,
        operation="delete",
        cascade=False,
        revision=structure["revision"],
        node_id="section_001",
    )
    outline.write_text(result["content"], encoding="utf-8")
    assert result["renumbered"] == []
    tree = build_outline_structure(root)

    def ids(nodes):
        return [item["id"] for node in nodes for item in [node]] + [
            i for node in nodes for i in ids(node["children"])
        ]

    assert {"ch_001", "ch_002"}.issubset(ids(tree["roots"]))


def test_asset_list_revision_can_be_used_for_update(novel):
    project, _ = novel
    assets = StructuredAssetService(project, "demo")
    assets.create("character", {"id": "hero", "name": "Hero", "body_markdown": "# Hero\nA writer."})
    listing = assets.list("character")
    hero = next(item for item in listing if item["id"] == "hero")
    assert hero["revision"] == assets.read("character", "hero")["revision"]
    updated = assets.update(
        "character", "hero", {"name": "Writer"}, expected_revision=hero["revision"]
    )
    assert updated["revision"] != hero["revision"]


def test_partial_review_keeps_full_denominator_and_runs_safety_gate(monkeypatch):
    reviewer, calls = _reviewer(monkeypatch)
    result = asyncio.run(reviewer.review("# 第1章 回声\n\n一阵风。", {}, dimensions=[7]))
    assert len(calls) == 1
    assert result.review_v2["potential_max"] == 100
    assert result.review_v2["coverage"] < 1
    assert result.review_v2["delivery_status"] == "inconclusive"
    assert len(result.review_v2["domains"]) == 6


def test_structure_failure_cannot_be_approved_even_with_dimension_filter(monkeypatch):
    reviewer, _ = _reviewer(monkeypatch)
    result = asyncio.run(
        reviewer.review("I should write a chapter now.\n# 第1章 正文\n正文", {}, dimensions=[7])
    )
    assert result.review_v2["delivery_status"] == "blocked"
    assert any(issue.category == "structure" for issue in result.issues)


def test_reasoning_is_removed_and_unclosed_reasoning_is_rejected():
    writer = WriterAgent.__new__(WriterAgent)
    parsed = writer._parse_creative_output(
        "<think>private reasoning</think>\n# 第1章 回声\n正文", 1, {}
    )
    assert parsed["content"] == "正文"
    with pytest.raises(Exception, match="reasoning"):
        writer._parse_creative_output("<think>unclosed reasoning\n正文", 1, {})


def test_busy_task_is_deferred_and_does_not_count_as_failure(novel):
    project, _ = novel
    calls = []

    def handler(payload, context):
        calls.append(True)
        if len(calls) == 1:
            raise NovelServiceError("busy", code="PROJECT_BUSY")
        return {"ok": True}

    runner = PersistentTaskRunner(project, "demo", handlers={"chapter_write": handler})
    try:
        task = runner.submit("chapter_write", {"chapter_id": "ch_001"})
        finished = _wait(runner, task["task_id"])
        assert finished["status"] == "completed" and len(calls) == 2
        events = runner.store.events(task["task_id"])
        assert any(event["event"] == "task_deferred" for event in events)
        assert not any(event["event"] == "task_failed" for event in events)
    finally:
        runner.shutdown(wait=True)


def test_completed_partial_task_can_retry_and_reuses_draft(novel):
    project, _ = novel
    runs = ChapterRunV2Store(project, "demo")
    run = runs.create("ch_001")
    run.status = "drafted"
    run.stages["draft"].status = "completed"
    runs.save(run)
    captured = []
    runner = PersistentTaskRunner(
        project,
        "demo",
        handlers={"continuous_write": lambda payload, ctx: captured.append(payload) or {}},
    )
    try:
        old = runner.store.create("continuous_write", {"max_chapters": 1})
        runner.store.transition(
            old["task_id"],
            status="completed",
            updates={
                "result": {
                    "failed_chapters": [{"chapter_id": "ch_001"}],
                    "stop_reason": "max_failures_reached",
                }
            },
        )
        retry = runner.retry(old["task_id"])
        assert _wait(runner, retry["task_id"])["status"] == "completed"
        assert captured[0]["_resume_runs"]["ch_001"] == run.run_id
    finally:
        runner.shutdown(wait=True)


def test_running_cancel_is_a_request_and_late_result_is_rejected(novel):
    project, _ = novel
    store = ChapterRunV2Store(project, "demo")
    run = store.create("ch_001")
    store.start_stage(run, "context")
    result = chapter_run_v2_action(
        project, "demo", {"action": "cancel", "run_id": run.run_id, "revision": store.revision(run)}
    )
    assert result["cancel_requested"] and not result["cancelled"]
    with pytest.raises(ChapterRunV2Error):
        store.assert_accepts_result(run)
    store.save(run)
    assert store.load(run.run_id).cancel_requested


def test_review_history_retains_prior_bytes_and_compares(novel):
    project, _ = novel
    reviews = ReviewStore(project, "demo")
    first = {
        "score": 70,
        "passed": True,
        "issue_details": [],
        "reviewed_at": "2026-10-12T01:00:00Z",
    }
    reviews.save("ch_001", first)
    revision = reviews.versions("ch_001")[0]["revision"]
    reviews.save("ch_001", {**first, "score": 90, "reviewed_at": "2026-10-13T01:00:00Z"})
    assert len(reviews.versions("ch_001")) == 2
    compared = reviews.compare("ch_001", revision)
    assert compared["before"]["score"] == 70 and compared["after"]["score"] == 90


def test_archive_keeps_artifacts_but_removes_noise_from_lists(novel):
    project, _ = novel
    store = ChapterRunV2Store(project, "demo")
    run = store.create("ch_001")
    run.status = "failed"
    store.save(run)
    result = chapter_run_v2_action(
        project,
        "demo",
        {"action": "archive", "run_id": run.run_id, "revision": store.revision(run)},
    )
    assert result["archived"] and store.list() == []
    assert store.load(run.run_id).archived


def test_transport_errors_appear_in_diagnostics_without_model_text(novel):
    project, _ = novel
    directory = project / ".openwrite/transport-errors"
    directory.mkdir(parents=True)
    (directory / "error.json").write_text(
        json.dumps({"code": "NETWORK_ERROR", "path": "/api/tasks", "tool_call_id": "call_lost"})
    )
    report = RuntimeDiagnosticsService(project, "demo").run()
    finding = next(item for item in report.findings if item.code == "transport_error")
    assert any(item.source == "transport" for item in finding.evidence)


def test_uncalibrated_gate_is_not_exposed_and_inconclusive_canon_cannot_pass():
    raw = [_evaluated(domain) for domain in selected_domains(None)]
    raw[0]["criteria"][0]["status"] = "inconclusive"
    result = aggregate_review(raw, [], min_coverage=0.1)
    assert result["delivery_status"] == "inconclusive"
    assert "production_gate_status" not in result


def test_metadata_batch_is_atomic_revision_gated_and_reads_chapter_ids(novel):
    from tools.project_registry import ProjectRegistry
    from tools.studio_application import StudioApplication

    project, root = novel
    app = StudioApplication(
        project, project_registry=ProjectRegistry(project / "registry.yaml", allow_ephemeral=True)
    )
    revision = app.outline_structure()["revision"]
    result = app.edit_outline_structure(
        {
            "operation": "set_meta",
            "revision": revision,
            "updates": [
                {"chapter_id": "ch_001", "metadata": {"target_words": 16000, "beats": "Arrival"}},
                {"chapter_id": "ch_002", "metadata": {"target_words": 4200, "hooks": "The letter"}},
            ],
        }
    )
    assert result["metadata"]["ch_001"]["beats"] == "Arrival"
    fresh = app.outline_structure()["revision"]
    read = app.edit_outline_structure(
        {
            "operation": "get_meta",
            "revision": fresh,
            "updates": [{"chapter_id": "ch_001"}, {"chapter_id": "ch_002"}],
        }
    )
    assert read["metadata"]["ch_002"]["target_words"] == 4200
    before = (root / "src/outline.md").read_bytes()
    with pytest.raises(Exception):
        app.edit_outline_structure(
            {
                "operation": "set_meta",
                "revision": fresh,
                "updates": [
                    {"chapter_id": "ch_001", "metadata": {"target_words": 3300}},
                    {"chapter_id": "ch_002", "metadata": {"target_words": 100000}},
                ],
            }
        )
    assert (root / "src/outline.md").read_bytes() == before
    with pytest.raises(Exception):
        app.edit_outline_structure(
            {
                "operation": "set_meta",
                "revision": revision,
                "chapter_id": "ch_001",
                "metadata": {"target_words": 500},
            }
        )


def test_abandon_missing_manuscript_releases_pending_head_but_keeps_audit(novel):
    project, root = novel
    chapter = root / "data/manuscript/arc_001/ch_001.md"
    chapter.write_text("# 第1章 草稿\n\n正文", encoding="utf-8")
    service = ManuscriptAcceptanceService(project, "demo")
    operation = service.establish_baseline(confirm=True)
    chapter.unlink()
    with pytest.raises(ManuscriptAcceptanceError):
        service.abandon(operation["operation_id"])
    abandoned = service.abandon(operation["operation_id"], confirm=True)
    assert abandoned["status"] == "abandoned"
    assert service.operation(operation["operation_id"])["frozen_chapters"]
    assert service.inspect()["blocking"] is False
    service.require_current("ch_001")


def test_acknowledgement_supports_canon_memory_and_character_domains(novel):
    project, root = novel
    chapter = root / "data/manuscript/arc_001/ch_001.md"
    chapter.write_text("# 第1章 起点\n\n正文", encoding="utf-8")
    service = ManuscriptAcceptanceService(project, "demo")
    operation = service.establish_baseline(confirm=True)
    operation["impacts"] = [
        {"domain": domain, "status": "needs_review"}
        for domain in ("canon", "chapter_memory", "character_state")
    ]
    service._write_operation(operation)
    result = service.acknowledge(
        operation["operation_id"],
        domains=["canon", "chapter_memory", "character_state"],
        confirm=True,
    )
    assert all(item["status"] == "acknowledged" for item in result["impacts"])


def test_english_heading_is_preserved_and_unstructured_reasoning_is_rejected():
    writer = WriterAgent.__new__(WriterAgent)
    parsed = writer._parse_creative_output("# Chapter 1: The Letter\n\nThe letter arrived.", 1, {})
    assert parsed["title"] == "Chapter 1: The Letter"
    with pytest.raises(Exception, match="chapter heading"):
        writer._parse_creative_output(
            "I should think about the plot first.\nThe letter arrived.", 1, {}
        )
