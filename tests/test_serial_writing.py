import asyncio
from types import SimpleNamespace

import pytest

from tools.agent.base import AgentContext
from tools.agent.writer import WriterAgent
from tools.arc_audit import ArcAuditService
from tools.init_project import init_project
from tools.llm.client import _plain_usage
from tools.manuscript_acceptance import ManuscriptAcceptanceError, ManuscriptAcceptanceService
from tools.outline_parser import OutlineMdParser
from tools.outline_tree import build_outline_structure, mutate_outline_structure
from tools.writing_assets import (
    WritingAssets,
    join_segment,
    manuscript_metrics,
    overlap_report,
    term_findings,
)


def project(tmp_path):
    init_project(tmp_path, "demo")
    root = tmp_path / "data" / "novels" / "demo"
    outline = "# 作品\n\n## 第1篇：篇\n\n### 第1节：节\n\n"
    for number in range(1, 5):
        outline += (
            f"#### 第{number}章：章\n\n内容。\n\n> 预估字数: 1000\n"
            "> 字数预算: 1000\n> 章节承诺: 未拿到钥匙 -> 拿到钥匙\n> 章节功能: 推进\n\n"
        )
    (root / "src" / "outline.md").write_text(outline)
    for number in range(1, 4):
        (root / "data" / "manuscript" / "arc_001" / f"ch_{number:03d}.md").write_text(
            f"# 第{number}章\n\n" + "甲" * 800
        )
    return root


def test_metrics_and_overlap_offsets_are_explicit_and_nonoverlapping():
    text = "# 第一章\n\n他说：“这是雨中的一把钥匙。”\n\n这是雨中的一把钥匙。"
    result = manuscript_metrics(text, ["钥匙"])
    assert result["paragraph_count"] == 2
    assert 0 < result["dialogue_ratio"] < 1
    assert result["concrete_nouns"]["count"] == 2
    assert manuscript_metrics(text)["concrete_nouns"]["count"] is None
    report = overlap_report(text, {"anchor": "这是雨中的一把钥匙这里还有足够长的句子。"}, window=6)
    match = report["references"][0]
    assert 0 < match["ratio"] <= 1
    for span in match["spans"]:
        assert text[span["start"] : span["end"]] == span["text"]
    assert term_findings(text, [{"term": "钥匙", "forbidden": True}])[0]["line"] == 3
    assert term_findings(text, [{"term": "锁", "min_occurrences": 1}])[0]["kind"] == "missing_term"


def test_join_removes_overlap_and_duplicate_paragraphs_preserves_short_dialogue():
    paragraph = "这是一段足够长的重复段落，不应当出现两次。"
    previous = "# 第一章\n\n" + paragraph
    result = join_segment(previous, "# 第一章\n\n" + paragraph + "\n\n下一场。\n\n好。\n\n好。")
    assert result.count(paragraph) == 1
    assert result.count("好。") == 2


def test_assets_validate_rotation_sampling_and_optimistic_revision(tmp_path):
    project(tmp_path)
    assets = WritingAssets(tmp_path, "demo")
    data = {
        "terms": [{"term": "钥匙", "min_occurrences": 2, "example": "他收好钥匙。"}],
        "character_groups": {"林": [{"id": str(i), "text": f"可选细节{i}"} for i in range(7)]},
    }
    saved = assets.save(data, "")
    assert len(assets.context("ch_001")["character_group_selection"]["林"]) == 3
    assert assets.context("ch_001") != assets.context("ch_002")
    with pytest.raises(ValueError, match="revision"):
        assets.save(data, "")
    data["terms"][0]["forbidden"] = True
    with pytest.raises(ValueError, match="forbidden"):
        assets.save(data, saved["revision"])


def test_long_chapter_segments_follow_beats_keep_tail_and_account_usage(tmp_path):
    calls, drafts = [], []
    replies = iter(["# 第一章\n\n" + "甲" * 2500, "乙" * 2500, "丙" * 2500, "丁" * 2500])

    def chat(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            content=next(replies),
            usage={"total_tokens": 100, "reasoning_tokens": 10},
            finish_reason="stop",
            total_tokens=100,
        )

    ctx = AgentContext(SimpleNamespace(chat=chat), "fake", str(tmp_path))
    ctx.on_draft = drafts.append
    writer = WriterAgent(ctx)
    result = asyncio.run(
        writer._creative_write({"chapter_beats": ["起", "承", "转", "合"]}, 1, 0.7, 10000)
    )
    assert result["word_count"] == 10000
    assert result["usage"]["reasoning_tokens"] == 40
    assert result["usage"]["total_tokens"] == 400
    assert len(drafts) == 4
    assert len(calls[1]["messages"][1].content) == 1500
    assert "承" in calls[1]["messages"][-1].content
    assert "甲" * 2500 in result["content"]


def test_fast_acceptance_never_claims_facts_current_and_can_resume(tmp_path):
    project(tmp_path)
    service = ManuscriptAcceptanceService(tmp_path, "demo")
    operation = service.establish_baseline(confirm=True)
    result = service.accept_without_model(operation["operation_id"])
    assert result["facts_pending"] is True
    assert all(
        ch["accepted_revision"] == ch["current_revision"] for ch in service.inspect()["chapters"]
    )
    with pytest.raises(ManuscriptAcceptanceError) as error:
        service.require_current("ch_004")
    assert error.value.code == "MANUSCRIPT_FACTS_PENDING"
    completed = service.resume(
        operation["operation_id"],
        analyzer=lambda *args: {"chapter_summary": "接纳", "legacy_updates": {}},
    )
    assert completed["status"] == "completed"
    assert completed["facts_pending"] is False


def test_audit_drifts_freeze_and_absorb_with_baseline(tmp_path):
    root = project(tmp_path)
    service = ArcAuditService(tmp_path, "demo")
    audit = service.audit("sec_001")
    assert audit["words"]["planned"] == 4000
    assert audit["words"]["actual"] == 2400
    assert audit["functions"]["streaks"]["推进"] == [["ch_001", "ch_002", "ch_003", "ch_004"]]
    assert audit["progression"]["declared_changes"] == 4
    for i in range(3):
        audit = service.change(
            {
                "action": "drift_entry",
                "group_id": "sec_001",
                "chapter_id": "ch_001",
                "kind": "growth",
                "impact": "section",
                "note": "作者改变了方向",
                "expected_revision": i,
            }
        )
    assert audit["ledger"]["groups"]["sec_001"]["frozen"]
    with pytest.raises(ValueError, match="frozen"):
        service.require_unfrozen("ch_002")
    entry_ids = [entry["id"] for entry in audit["ledger"]["entries"]]
    old_outline = (root / "src" / "outline.md").read_text()
    final = service.change(
        {
            "action": "arc_reconcile",
            "decision": "absorb",
            "confirm": True,
            "group_id": "sec_001",
            "expected_revision": 3,
            "entry_ids": entry_ids,
            "resume": True,
            "outline_revision": build_outline_structure(root)["revision"],
            "outline_updates": [{"node_id": "ch_001", "metadata": {"promise": "没有盟友 -> 结盟"}}],
        }
    )
    assert not final["ledger"]["groups"]["sec_001"]["frozen"]
    assert all(e["outline_written"] for e in final["ledger"]["entries"])
    baseline = final["ledger"]["entries"][0]["reconciliation_baseline"]
    assert (
        root / "data" / "arc_audit" / "baselines" / baseline / "src" / "outline.md"
    ).read_text() == old_outline


def test_outline_metadata_budget_is_one_source(tmp_path):
    root = project(tmp_path)
    changed = mutate_outline_structure(
        root,
        operation="set_meta",
        node_id="ch_001",
        revision=build_outline_structure(root)["revision"],
        metadata={"word_budget": 2000, "payoff_of": ["f001"], "function": ["揭示", "代价"]},
    )
    chapter = OutlineMdParser().parse(changed["content"], "demo").chapters[0]
    assert chapter.word_budget == chapter.estimated_words == 2000
    assert chapter.payoff_of == ["f001"]
    with pytest.raises(ValueError, match="match"):
        mutate_outline_structure(
            root,
            operation="set_meta",
            node_id="ch_001",
            revision=build_outline_structure(root)["revision"],
            metadata={"word_budget": 2000, "target_words": 3000},
        )


def test_reasoning_usage_preserves_zero_and_unknown():
    assert (
        _plain_usage({"completion_tokens_details": {"reasoning_tokens": 0}})["reasoning_tokens"]
        == 0
    )
    assert (
        _plain_usage({"output_tokens_details": {"reasoning_tokens": 100}})["reasoning_tokens"]
        == 100
    )
    assert "reasoning_tokens" not in _plain_usage({"completion_tokens": 100})


def test_interrupted_absorption_can_finish_its_approved_transaction(tmp_path, monkeypatch):
    import tools.arc_audit as module

    root = project(tmp_path)
    service = ArcAuditService(tmp_path, "demo")
    first = service.change(
        {
            "action": "drift_entry",
            "group_id": "sec_001",
            "chapter_id": "ch_001",
            "kind": "growth",
            "impact": "local",
            "note": "改变承诺",
            "expected_revision": 0,
        }
    )
    real_write = module.atomic_write

    def fail_ledger(path, content):
        if path == service.ledger_path:
            raise OSError("simulated interruption")
        return real_write(path, content)

    monkeypatch.setattr(module, "atomic_write", fail_ledger)
    with pytest.raises(OSError):
        service.change(
            {
                "action": "arc_reconcile",
                "decision": "absorb",
                "confirm": True,
                "group_id": "sec_001",
                "expected_revision": 1,
                "entry_ids": [first["ledger"]["entries"][0]["id"]],
                "outline_revision": build_outline_structure(root)["revision"],
                "outline_updates": [{"node_id": "ch_001", "metadata": {"promise": "A -> C"}}],
            }
        )
    with pytest.raises(ValueError, match="recover_transaction"):
        service.audit()
    monkeypatch.setattr(module, "atomic_write", real_write)
    recovered = service.change({"action": "recover_transaction", "confirm": True})
    assert recovered["ledger"]["entries"][0]["outline_written"] is True
    assert not service.transaction_path.exists()
    assert recovered["chapters"][0]["promise"] == "A -> C"


def test_historical_rewrite_requires_explicit_opt_in_and_labels_current_canon(tmp_path):
    from tools.benchmark_tasks import BenchmarkInputError, benchmark_target

    project(tmp_path)
    with pytest.raises(BenchmarkInputError) as unavailable:
        benchmark_target(tmp_path, "demo", {"chapter_id": "ch_001"})
    assert unavailable.value.code == "BENCHMARK_HISTORICAL_CONTEXT_UNAVAILABLE"
    target = benchmark_target(tmp_path, "demo", {"chapter_id": "ch_001", "allow_historical": True})
    assert target["historical"] is True
    assert target["baseline_kind"] == "current_canon_rewrite"


def test_stream_total_timeout_preserves_received_draft(tmp_path, monkeypatch):
    from tools.llm.client import LLMClient, LLMConfig
    from tools.llm.errors import LLMTimeoutError

    monkeypatch.setenv("OW_LLM_TOTAL_TIMEOUT", "1")
    times = iter([0, 0.2, 2])
    monkeypatch.setattr("tools.llm.client.time.monotonic", lambda: next(times))
    client = LLMClient(LLMConfig(model="fake"))
    stream = iter([{"choices": [{"delta": {"content": "已有草稿"}}]}, {"choices": []}])
    with pytest.raises(LLMTimeoutError) as timeout:
        client._stream_response(stream, None)
    assert timeout.value.code == "PROVIDER_TIMEOUT"
    assert timeout.value.partial_content == "已有草稿"


def test_personal_archive_keeps_gate_report_and_does_not_require_delivery_approval(tmp_path):
    import json

    from tools.novel_service import NovelApplicationService

    root = project(tmp_path)
    service = NovelApplicationService(tmp_path)
    path = service.export_book(tmp_path / "archive.md", purpose="personal_archive")
    assert path.is_file()
    (receipt_path,) = list((root / "data" / "exports").glob("archive_*.json"))
    receipt = json.loads(receipt_path.read_text())
    assert receipt["status"] == "completed"
    assert receipt["preflight"]["purpose"] == "personal_archive"
    assert receipt["preflight"]["warnings"]


def test_planning_conversion_preserves_serial_metadata():
    import json

    from tools.architect import ArchitectAgent
    from tools.outline_benchmark import _render

    chapter = {
        "number": 1,
        "title": "章",
        "summary": "拿到钥匙。",
        "dramatic_position": "起",
        "content_focus": "拿钥匙",
        "goals": ["拿钥匙"],
        "estimated_words": 1000,
        "involved_characters": ["林"],
        "involved_settings": ["门"],
        "emotional_arc": "戒备",
        "beats": ["取钥匙"],
        "hooks": ["门后有什么"],
        "promise": "未拿到 -> 已拿到",
        "payoff_of": ["hook_001"],
        "word_budget": 1000,
        "function": ["推进", "代价"],
    }
    agent = ArchitectAgent.__new__(ArchitectAgent)
    parsed = agent._parse_chapter_outline(json.dumps([chapter]), 1)[0]
    assert parsed.promise == chapter["promise"]
    assert parsed.payoff_of == ["hook_001"]
    assert parsed.word_budget == 1000
    assert parsed.function == ["推进", "代价"]
    markdown = "# 作品\n\n## 第1篇：篇\n\n### 第1节：节\n\n" + _render([chapter])
    node = OutlineMdParser().parse(markdown, "demo").chapters[0]
    assert node.promise == parsed.promise
    assert node.payoff_of == parsed.payoff_of
    assert node.function == parsed.function
    assert node.word_budget == parsed.word_budget


@pytest.mark.parametrize("value", ["inf", "nan", "0", "-1"])
def test_stream_timeout_configuration_cannot_disable_deadline(monkeypatch, value):
    from tools.llm.client import LLMClient, LLMConfig

    monkeypatch.setenv("OW_LLM_TOTAL_TIMEOUT", value)
    with pytest.raises(ValueError, match="finite positive"):
        LLMClient(LLMConfig(model="fake"))._stream_response(iter([]), None)
