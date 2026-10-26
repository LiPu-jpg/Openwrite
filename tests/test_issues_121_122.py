"""Regressions for delivery diagnostics and the 5.8.14 follow-up report."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from tools.agent.base import AgentContext
from tools.agent.reviewer import ReviewerAgent
from tools.chapter_pipeline import _apply_canon_gate
from tools.init_project import init_project
from tools.manuscript_acceptance import ManuscriptAcceptanceService
from tools.review_rubric import resolve_review_dimensions, selected_domains


def test_accepting_identical_revision_is_idempotent_without_invalidating_new_runs(tmp_path):
    init_project(tmp_path, "demo")
    root = tmp_path / "data/novels/demo"
    path = root / "data/manuscript/arc_001/ch_001.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# 门\n\n门外下雨。\n")
    service = ManuscriptAcceptanceService(tmp_path, "demo")
    first = service.start_acceptance("ch_001", source="manual")
    before = {p: p.read_bytes() for p in (root / "data").rglob("*") if p.is_file()}
    repeated = service.start_acceptance("ch_001", source="manual")
    assert repeated["operation_id"] == first["operation_id"]
    assert before == {p: p.read_bytes() for p in (root / "data").rglob("*") if p.is_file()}
    state = json.loads(service.state_path.read_text())
    path.write_text("# 门\n\n雨停了。\n")
    changed = service.start_acceptance(
        "ch_001",
        source="manual",
        expected_previous_revision=state["chapters"]["ch_001"]["pending_revision"],
    )
    assert changed["operation_id"] != first["operation_id"]


def test_quick_scope_is_explicit_and_does_not_claim_full_delivery(tmp_path, monkeypatch):
    reviewer = ReviewerAgent(AgentContext(SimpleNamespace(), "fake", str(tmp_path)))
    dimensions = resolve_review_dimensions(depth="quick")
    assert {d.id for d in selected_domains(dimensions)} == {"coherence", "canon", "prose"}

    async def domains(_content, _context, specs, _signals):
        return [
            {
                "id": d.id,
                "criteria": [
                    {
                        "id": c.id,
                        "status": "evaluated",
                        "earned": c.max_points,
                        "evidence": ["原文证据"],
                        "rationale": "符合",
                    }
                    for c in d.criteria
                ],
            }
            for d in specs
        ], []

    monkeypatch.setattr(reviewer, "_llm_review_domains", domains)
    monkeypatch.setattr(reviewer, "_rule_based_check", lambda *_a, **_kw: [])
    monkeypatch.setattr(reviewer, "_detect_ai_tells", lambda *_: [])
    monkeypatch.setattr(
        reviewer,
        "_llm_review_gate",
        lambda *_: ({"id": "safety", "status": "pass", "findings": []}, []),
    )
    result = asyncio.run(reviewer.review("门外的雨停了，他收起雨伞。", {}, dimensions=dimensions))
    v2 = result.review_v2
    assert v2["scope_status"] == "partial"
    assert v2["scope_quality_score"] == 100
    assert v2["scope_passed"] is True
    assert v2["quality_score"] is None and result.score is None
    assert result.passed is False and v2["delivery_status"] == "inconclusive"
    assert v2["delivery_diagnostics"]["code"] == "partial_review"
    assert v2["unreviewed_dimensions"]


@pytest.mark.parametrize(
    "scope",
    [
        {"depth": "unknown"},
        {"domains": []},
        {"domains": ["unknown"]},
        {"dimensions": []},
        {"dimensions": [True]},
        {"depth": "quick", "dimensions": [1]},
    ],
)
def test_invalid_review_scope_fails_before_calling_a_model(scope):
    with pytest.raises(ValueError):
        resolve_review_dimensions(**scope)


def test_canon_diagnostics_report_actual_missing_inputs_and_invalidate_score():
    v2 = {
        "domains": [{"id": "canon", "status": "inconclusive", "criteria": []}],
        "gates": [],
        "delivery_status": "pass",
        "quality_score": 80,
    }
    info = _apply_canon_gate(
        v2, strict=False, context={"chapter_summaries": "前章事实", "current_state": "现状"}
    )
    assert info["missing"] == ["ledger", "relationships"]
    assert v2["delivery_status"] == "inconclusive"
    assert v2["quality_score"] is None and v2["score_valid"] is False
    assert v2["delivery_diagnostics"]["reasons"][0]["missing"] == ["ledger", "relationships"]
    v2["delivery_status"] = "blocked"
    _apply_canon_gate(v2, strict=True, context={})
    assert v2["delivery_status"] == "blocked"
    assert v2["delivery_diagnostics"]["code"] == "hard_gate_blocked"


def test_stream_cancellation_closes_transport_and_preserves_partial_text():
    from tools.chapter_pipeline import _model_cancellation_scope
    from tools.llm.cancellation import ModelCancelledError
    from tools.llm.client import LLMClient, LLMConfig

    stopped = False

    class Stream:
        closed = False

        def __iter__(self):
            yield {"choices": [{"delta": {"content": "门外的雨停了。"}}]}
            yield {"choices": [{"delta": {"content": "不应再被接收。"}}]}
            raise AssertionError("transport should have closed")

        def close(self):
            self.closed = True

    def progress(_):
        nonlocal stopped
        stopped = True

    stream = Stream()
    with _model_cancellation_scope({"_cancel_requested": lambda: stopped}):
        with pytest.raises(ModelCancelledError) as raised:
            LLMClient(LLMConfig(model="fake"))._stream_response(stream, progress)
    assert raised.value.partial_content == "门外的雨停了。"
    assert stream.closed is True


def test_blocked_write_attempts_are_retained_in_both_run_stores(tmp_path):
    from tools.chapter_run_store import ChapterRunStore
    from tools.chapter_run_v2 import ChapterRunV2Store
    from tools.novel_service import NovelApplicationService, NovelServiceError

    init_project(tmp_path, "demo")
    path = tmp_path / "data/novels/demo/data/manuscript/arc_001/ch_001.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# 门\n\n已存在正文。\n")
    service = NovelApplicationService(tmp_path)
    for _ in range(3):
        with pytest.raises(NovelServiceError) as raised:
            service.write_chapter({"chapter_id": "ch_001"})
        assert raised.value.details["run_id_v2"]
        assert raised.value.details["model_call_count"] == 0
    assert len(ChapterRunStore(tmp_path, "demo").list()) == 3
    assert len(ChapterRunV2Store(tmp_path, "demo").list()) == 3


def test_cancelled_partial_draft_resumes_in_new_run_and_rejects_changed_inputs(
    tmp_path, monkeypatch
):
    import tools.llm as llm
    from tools.chapter_run_store import ChapterRunStore
    from tools.chapter_run_v2 import ChapterRunV2Store
    from tools.llm.cancellation import ModelCancelledError
    from tools.llm.client import LLMConfig, LLMResponse
    from tools.novel_service import NovelApplicationService, NovelServiceError

    init_project(tmp_path, "demo")
    novel = tmp_path / "data/novels/demo"
    outline = novel / "src/outline.md"
    original_outline = (
        "# 作品\n\n## 第1篇：篇\n\n### 第1节：节\n\n#### 第1章：门\n\n开门。\n\n> 预估字数: 1000\n"
    )
    outline.write_text(original_outline)
    cancelled = False
    calls = []

    class Client:
        def __init__(self, config):
            self.config = config

        def chat(self, **kwargs):
            nonlocal cancelled
            calls.append(kwargs)
            if len(calls) == 1:
                cancelled = True
                error = ModelCancelledError("MODEL_CANCELLED")
                error.partial_content = "# 第1章 门\n\n" + "甲" * 300
                raise error
            content = {
                2: "乙" * 700,
                3: "门被打开。",
                4: "state_updates: {}\nchapter_summary: 门被打开。",
            }[len(calls)]
            return LLMResponse(
                content=content,
                model="fake",
                usage={
                    "completion_tokens": 20,
                    "reasoning_tokens": 10,
                    "total_tokens": 20,
                    "cost_usd": 0.01,
                    "cost_reported": True,
                },
            )

    monkeypatch.setattr(
        llm.LLMConfig,
        "from_env",
        classmethod(lambda cls: LLMConfig(model="fake", api_key="test-only")),
    )
    monkeypatch.setattr(llm, "LLMClient", Client)
    service = NovelApplicationService(tmp_path)
    with pytest.raises(NovelServiceError) as raised:
        service.write_chapter(
            {"chapter_id": "ch_001", "target_words": 1000, "_cancel_requested": lambda: cancelled}
        )
    assert raised.value.code == "TASK_CANCELLED"
    cancelled_id = raised.value.details["run_id_v2"]
    store = ChapterRunV2Store(tmp_path, "demo")
    assert store.load(cancelled_id).status == "cancelled"
    assert (
        (store.root / "artifacts" / cancelled_id / "uncommitted.md")
        .read_text()
        .endswith("甲" * 300)
    )
    cancelled = False
    outline.write_text(original_outline.replace("开门。", "改成另一条故事线。"))
    with pytest.raises(NovelServiceError) as stale:
        service.write_chapter({"chapter_id": "ch_001", "resume_from_draft": True})
    assert stale.value.code == "RESUME_INPUT_STALE"
    assert len(calls) == 1
    outline.write_text(original_outline)
    result = service.write_chapter({"chapter_id": "ch_001", "resume_from_draft": True})
    resumed = store.load(result["run_id_v2"])
    assert resumed.run_id != cancelled_id and resumed.resumed_from_run_id == cancelled_id
    assert store.load(cancelled_id).status == "cancelled"
    assert "甲" * 300 in str(calls[1]["messages"]) and "直接续写" in str(calls[1]["messages"])
    assert resumed.stages["draft"].usage["usage_calls"] == 1
    assert resumed.stages["fact_extract"].usage["usage_calls"] == 1
    assert resumed.stages["settle"].usage["usage_calls"] == 1
    assert result["usage"]["reasoning_tokens"] == 30
    assert result["usage"]["cost_summary"] == {
        "reported_usd": 0.03,
        "complete": True,
        "missing_calls": 0,
    }
    assert len(ChapterRunStore(tmp_path, "demo").list()) == 3


def test_each_segment_checkpoint_keeps_latest_text_and_usage(tmp_path):
    from tools.chapter_pipeline import _preserve_failed_draft
    from tools.chapter_run_v2 import ChapterRunV2Store

    init_project(tmp_path, "demo")
    store = ChapterRunV2Store(tmp_path, "demo")
    run = store.create("ch_001")
    for text in ["第一段。", "第一段。\n\n第二段。"]:
        result = _preserve_failed_draft(
            tmp_path, "demo", "ch_001", store, run, partial_content=text, usage={"total_tokens": 50}
        )
    from pathlib import Path

    assert Path(result["draft_path"]).read_text() == "第一段。\n\n第二段。"
    assert (
        json.loads(Path(result["draft_path"]).with_suffix(".usage.json").read_text())[
            "total_tokens"
        ]
        == 50
    )


def test_context_options_and_custom_outline_metadata_reach_writer_preview(
    tmp_path, monkeypatch, caplog
):
    import yaml

    from tools.context_builder import ContextBuilder
    from tools.novel_service import NovelApplicationService
    from tools.outline_cache import deserialize_outline_hierarchy
    from tools.outline_sync import sync_outline_to_hierarchy

    init_project(tmp_path, "demo")
    novel = tmp_path / "data/novels/demo"
    (novel / "src/outline.md").write_text(
        "# 作品\n\n## 第1篇：篇\n\n### 第1节：节\n\n"
        "#### 第1章：门\n\n> 预估字数: 1000\n\n"
        "#### 第2章：信\n\n> 预估字数: 1000\n"
        "> 故事线: 雨钥线\n> 未登记字段: 不应静默丢失\n"
    )
    previous = novel / "data/manuscript/arc_001/ch_001.md"
    previous.write_text("# 第1章 门\n\n" + "旧文" * 2000 + "结尾八字雨停开门")
    config_path = tmp_path / "novel_config.yaml"
    config = yaml.safe_load(config_path.read_text())
    config.update(
        previous_chapter_mode="tail", previous_chapter_tail_chars=8, outline_extra_keys=["故事线"]
    )
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True))
    sync_outline_to_hierarchy(novel / "src", novel / "data")
    cached = deserialize_outline_hierarchy(
        yaml.safe_load((novel / "data/hierarchy.yaml").read_text()), "demo"
    )
    assert cached.chapters[1].extra_metadata == {"故事线": "雨钥线"}
    assert "未登记字段" in caplog.text
    preview = NovelApplicationService(tmp_path).context_preview(
        "ch_002", include_agent_payload=True
    )
    assert preview["agent_payload"]["recent_chapters"] == "结尾八字雨停开门"
    assert (
        ContextBuilder(tmp_path, "demo").build_generation_context("ch_002").recent_text
        == "结尾八字雨停开门"
    )
    assert "故事线: 雨钥线" in preview["agent_payload"]["outline"]
    assert preview["packet"]["chapter_requirements"]["extra_metadata"] == {"故事线": "雨钥线"}


def test_document_manifest_reports_each_compressed_craft_file(tmp_path, monkeypatch):
    from dataclasses import asdict

    from tools.chapter_assembler import ChapterAssemblerV2
    from tools.context_manifest import build_context_manifest
    from tools.llm.context import ContextBudgetPolicy

    init_project(tmp_path, "demo")
    assembler = ChapterAssemblerV2(tmp_path, "demo")
    assembler._context_policy = ContextBudgetPolicy(12000, 4000)
    monkeypatch.setattr(
        assembler,
        "_load_all_style_documents",
        lambda **_: {"craft.a": "甲" * 30000, "craft.b": "乙" * 20000},
    )
    packet = assembler.assemble("ch_001")
    docs = build_context_manifest(assembler.novel_root, asdict(packet))["documents"]
    craft = [d for d in docs if d["document"].startswith("craft.")]
    assert len(craft) == 2
    assert all(
        d["compressed"] and d["assembled_characters"] < d["original_characters"] for d in craft
    )
    assert {d["document"]: d["assembled_characters"] for d in craft} == {
        k: len(v) for k, v in packet.style_documents.items()
    }


def test_write_dry_run_includes_requested_guidance_without_task_or_model(tmp_path):
    from tools.project_registry import ProjectRegistry
    from tools.studio_application import StudioApplication

    init_project(tmp_path, "demo")
    app = StudioApplication(
        tmp_path,
        project_registry=ProjectRegistry(tmp_path / "registry.yaml", allow_ephemeral=True),
        writer_executor=lambda *_: pytest.fail("dry-run must not invoke writer"),
    )
    try:
        result = app.submit_write_chapter(
            {
                "dry_run": True,
                "chapter_id": "ch_001",
                "target_words": 2000,
                "guidance": "雨停之后再开门。",
            }
        )
        assert result["dry_run"] and result["model_call_count"] == 0
        assert result["context"]["agent_payload"]["target_words"] == 2000
        assert "雨停之后再开门。" in str(result["context"]["writer_messages"])
        assert "task_id" not in result
    finally:
        app._task_runner.shutdown(wait=True)


def test_archived_runs_remain_discoverable_with_their_original_artifacts(tmp_path):
    from tools.chapter_lifecycle import archive_chapter_artifacts
    from tools.chapter_run_v2 import ChapterRunV2Store, chapter_run_v2_action

    init_project(tmp_path, "demo")
    store = ChapterRunV2Store(tmp_path, "demo")
    run = store.create("ch_001")
    store.start_stage(run, "context")
    artifact = store.write_artifact(
        run, "context", {"chapter_id": "ch_001", "original": "原始上下文"}
    )
    store.complete_stage(run, "context", artifact=artifact)
    archive_chapter_artifacts(tmp_path / "data/novels/demo", "ch_001", "delete_test")
    assert store.list() == []
    result = chapter_run_v2_action(tmp_path, "demo", {"action": "list", "include_archived": True})
    assert result["count"] == 1
    old = result["runs"][0]
    assert old["archived"] and old["next_stage"] is None
    from pathlib import Path

    assert (
        json.loads(Path(old["stages"]["context"]["artifact"]).read_text())["original"]
        == "原始上下文"
    )


def test_usage_ledger_retains_segment_reasoning_and_unknown_failed_call_cost(tmp_path):
    from tools.agent.writer import WriterAgent
    from tools.llm.client import LLMResponse
    from tools.llm.response import ProviderResponseError

    calls = []

    def chat(**kwargs):
        calls.append(kwargs)
        if len(calls) == 3:
            raise ProviderResponseError("PROVIDER_NETWORK_ERROR", "connection lost")
        return LLMResponse(
            content="门外下雨。",
            model="fake",
            usage={
                "completion_tokens": 20,
                "reasoning_tokens": 12,
                "completion_tokens_details": {"reasoning_tokens": 12},
                "cost_usd": 0.02,
                "cost_reported": True,
            },
        )

    writer = WriterAgent(AgentContext(SimpleNamespace(chat=chat), "fake", str(tmp_path)))
    writer.chat(messages=[], segment_index=1)
    writer.chat(messages=[], segment_index=2)
    with pytest.raises(ProviderResponseError):
        writer.chat(messages=[], usage_stage="fact_extract")
    usage = writer.usage_summary()
    assert usage["reasoning_tokens"] == 24
    assert usage["completion_tokens_details"]["reasoning_tokens"] == 24
    assert [c["segment_index"] for c in usage["calls"]] == [1, 2, None]
    assert usage["calls"][-1]["stage"] == "fact_extract"
    assert usage["cost_reported"] is False
    assert usage["cost_summary"] == {"reported_usd": 0.04, "complete": False, "missing_calls": 1}
