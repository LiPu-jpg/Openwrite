from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import tools.llm as llm_module
from models.source_analysis import EvidenceRef
from tools.init_project import init_project
from tools.source_analysis import SourceAnalysisError, SourceAnalysisService


def _service(tmp_path: Path) -> SourceAnalysisService:
    init_project(tmp_path, "demo", "证据测试")
    return SourceAnalysisService(tmp_path, "demo")


def _text(chapters: int = 8, body_size: int = 180) -> str:
    return "".join(
        f"第{index}章 测试\n\n" + (f"第{index}段潮声与钟声交替。" * body_size) + "\n\n"
        for index in range(1, chapters + 1)
    )


def _analyzer(
    text: str,
    context: dict,
    *,
    claim: str = "用重复物象建立递进节奏",
    source_bound: bool = False,
) -> dict:
    quote = text[: min(12, len(text))]
    return {
        "summary": f"第 {context['chunk_index']} 块摘要",
        "model": "fixture-model",
        "findings": [
            {
                "category": "method",
                "claim": claim,
                "confidence": 0.9,
                "reusable": not source_bound,
                "source_bound": source_bound,
                "evidence": [{"start": 0, "end": len(quote), "quote": quote}],
            }
        ],
    }


def test_source_analysis_models_forbid_unknown_fields():
    with pytest.raises(ValidationError):
        EvidenceRef.model_validate(
            {
                "source_id": "demo",
                "chunk_id": "chunk",
                "start": 0,
                "end": 1,
                "line_start": 1,
                "line_end": 1,
                "quote": "钟",
                "sha256": "0" * 64,
                "unexpected": True,
            }
        )


def test_budget_split_covers_long_chinese_text_without_loss():
    text = _text(chapters=12, body_size=240)
    ranges = SourceAnalysisService.split_text(text, 900)

    assert len(ranges) > 10
    assert ranges[0][0] == 0
    assert ranges[-1][1] == len(text)
    assert all(left[1] == right[0] for left, right in zip(ranges, ranges[1:]))
    assert "".join(text[start:end] for start, end in ranges) == text
    assert all(
        SourceAnalysisService.estimate_tokens(text[start:end]) <= 900
        for start, end in ranges
    )


def test_analysis_persists_evidence_and_unchanged_source_uses_zero_calls(tmp_path: Path):
    service = _service(tmp_path)
    text = _text(chapters=4, body_size=80)
    prepared = service.prepare(
        "reference_a",
        text,
        relative_name="reference-a.txt",
        input_budget_tokens=700,
    )
    calls: list[str] = []

    def analyze(text: str, context: dict) -> dict:
        calls.append(context["chunk_id"])
        return _analyzer(text, context)

    result = service.analyze("reference_a", analyzer=analyze)

    assert result["ok"] is True
    assert len(calls) == prepared["pending_chunks"]
    assert result["report"]["status"] == "completed"
    first_evidence = result["report"]["findings"][0]["evidence"][0]
    assert text[first_evidence["start"] : first_evidence["end"]] == first_evidence["quote"]

    repeated = service.prepare(
        "reference_a",
        text,
        relative_name="reference-a.txt",
        input_budget_tokens=700,
    )
    calls.clear()
    rerun = service.analyze("reference_a", analyzer=analyze)

    assert repeated["manifest"]["change_status"] == "unchanged"
    assert repeated["model_calls_needed"] == 0
    assert rerun["processed_chunks"] == 0
    assert calls == []


def test_source_snapshot_preserves_crlf_without_trailing_newline(tmp_path: Path):
    service = _service(tmp_path)
    text = "第一章\r\n\r\n钟声响了三次。\r\n没有末尾换行"

    prepared = service.prepare(
        "reference_crlf",
        text,
        relative_name="reference-crlf.txt",
        input_budget_tokens=500,
    )
    manifest = prepared["manifest"]
    snapshot = service.source_root("reference_crlf") / manifest["source_snapshot_ref"]

    assert snapshot.read_bytes() == text.encode("utf-8")
    assert service.analyze("reference_crlf", analyzer=_analyzer)["ok"] is True


@pytest.mark.parametrize("stream", ["0", "1"])
def test_deepseek_flash_source_analysis_disables_thinking(monkeypatch, tmp_path: Path, stream):
    monkeypatch.setenv("OW_AGENT_STREAM", stream)
    service = _service(tmp_path)
    service.prepare(
        "reference_flash",
        "第一章\n\n钟声响了三次。",
        relative_name="reference-flash.txt",
        input_budget_tokens=500,
    )
    config = SimpleNamespace(
        provider="openai",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        extra={},
    )

    class FakeClient:
        def __init__(self, received_config):
            assert received_config is config

        def chat(self, messages, **kwargs):
            assert messages and kwargs["stream"] is (stream == "1")
            return SimpleNamespace(
                content='{"summary":"测试摘要","findings":[]}',
                model="deepseek-v4-flash",
                finish_reason="stop",
                reasoning="",
            )

    monkeypatch.setattr(
        llm_module.LLMConfig,
        "from_env",
        classmethod(lambda cls: config),
    )
    monkeypatch.setattr(llm_module, "LLMClient", FakeClient)

    result = service.analyze("reference_flash")

    assert result["ok"] is True
    assert result["report"]["models"] == ["deepseek-v4-flash"]
    assert config.extra["extra_body"]["thinking"] == {"type": "disabled"}
    assert config.extra["response_format"] == {"type": "json_object"}


def test_generated_report_rejects_repeated_evidence_after_one_repair(
    monkeypatch, tmp_path: Path
):
    service = _service(tmp_path)
    text = "第一章\n\n钟声响了三次，雨也停了。"
    service.prepare(
        "reference_repeated",
        text,
        relative_name="reference-repeated.txt",
        input_budget_tokens=500,
    )
    quote = text[:4]
    payload = {
        "summary": "测试摘要",
        "findings": [
            {
                "category": category,
                "claim": f"结论 {index}",
                "confidence": 0.8,
                "reusable": True,
                "source_bound": False,
                "evidence": [{"start": 0, "end": 4, "quote": quote}],
            }
            for index, category in enumerate(("hook", "pacing", "method"), start=1)
        ],
    }
    config = SimpleNamespace(
        provider="openai",
        base_url="https://api.openai.com/v1",
        model="fixture-model",
        extra={},
    )
    calls = 0

    class FakeClient:
        def __init__(self, received_config):
            assert received_config is config

        def chat(self, messages, **kwargs):
            nonlocal calls
            calls += 1
            return SimpleNamespace(
                content=json.dumps(payload, ensure_ascii=False),
                model="fixture-model",
                finish_reason="stop",
                reasoning="",
            )

    monkeypatch.setattr(
        llm_module.LLMConfig,
        "from_env",
        classmethod(lambda cls: config),
    )
    monkeypatch.setattr(llm_module, "LLMClient", FakeClient)

    result = service.analyze("reference_repeated")

    assert result["ok"] is False
    assert result["failures"][0]["code"] == "INVALID_EVIDENCE"
    assert calls == 2


def test_generated_report_rejects_low_coverage_for_long_chunk():
    with pytest.raises(SourceAnalysisError, match="至少需要 3 条"):
        SourceAnalysisService._validate_generated_report_quality(
            SimpleNamespace(findings=[SimpleNamespace()]),
            chunk_chars=2000,
        )


def test_generated_report_rejects_more_than_eight_findings():
    with pytest.raises(SourceAnalysisError, match="8 条结论上限"):
        SourceAnalysisService._validate_generated_report_quality(
            SimpleNamespace(findings=[SimpleNamespace() for _ in range(9)]),
            chunk_chars=2000,
        )


def test_changed_source_reuses_unchanged_chunks(tmp_path: Path):
    service = _service(tmp_path)
    original = _text(chapters=7, body_size=80)
    first = service.prepare(
        "reference_b",
        original,
        relative_name="reference-b.txt",
        input_budget_tokens=650,
    )
    service.analyze("reference_b", analyzer=_analyzer)

    changed = original.replace("第7段潮声与钟声交替。", "第7段潮声忽然中断。")
    second = service.prepare(
        "reference_b",
        changed,
        relative_name="reference-b.txt",
        input_budget_tokens=650,
    )

    assert first["pending_chunks"] > 2
    assert second["manifest"]["change_status"] == "modified"
    assert 0 < second["pending_chunks"] < len(second["manifest"]["chunks"])
    assert second["reused_chunks"] > 0


def test_failed_chunk_never_marks_complete_and_can_retry_one_chunk(tmp_path: Path):
    service = _service(tmp_path)
    service.prepare(
        "reference_c",
        _text(chapters=4, body_size=100),
        relative_name="reference-c.txt",
        input_budget_tokens=600,
    )

    def flaky(text: str, context: dict) -> dict:
        if context["chunk_index"] == 1:
            raise RuntimeError("fixture failure")
        return _analyzer(text, context)

    failed = service.analyze("reference_c", analyzer=flaky)

    assert failed["ok"] is False
    assert failed["manifest"]["status"] == "failed"
    assert failed["report"]["status"] == "incomplete"
    assert len(failed["failures"]) == 1
    failed_chunk = failed["failures"][0]["chunk_id"]

    retried = service.retry("reference_c", failed_chunk, analyzer=_analyzer)

    assert retried["ok"] is True
    assert retried["processed_chunks"] == 1
    assert retried["manifest"]["status"] == "completed"


def test_invalid_evidence_is_bounded_failure(tmp_path: Path):
    service = _service(tmp_path)
    service.prepare(
        "reference_bad",
        "第一章\n\n钟声响了三次。",
        relative_name="bad.txt",
        input_budget_tokens=500,
    )

    def invalid(text: str, context: dict) -> dict:
        payload = _analyzer(text, context)
        payload["findings"][0]["evidence"][0]["quote"] = "不匹配"
        return payload

    result = service.analyze("reference_bad", analyzer=invalid)

    assert result["ok"] is False
    assert result["failures"][0]["code"] == "INVALID_EVIDENCE"
    assert len(result["failures"][0]["message"]) <= 800


def test_evidence_quote_repairs_incorrect_model_offsets(tmp_path: Path):
    service = _service(tmp_path)
    text = "第一章\n\n雨停之后，钟声响了三次。"
    service.prepare(
        "reference_offsets",
        text,
        relative_name="offsets.txt",
        input_budget_tokens=500,
    )

    def misplaced(chunk: str, context: dict) -> dict:
        payload = _analyzer(chunk, context)
        payload["findings"][0]["evidence"] = [
            {"start": 0, "end": 2, "quote": "钟声响了三次"}
        ]
        return payload

    result = service.analyze("reference_offsets", analyzer=misplaced)
    evidence = result["report"]["findings"][0]["evidence"][0]

    assert result["ok"] is True
    assert evidence["start"] == text.index("钟声响了三次")
    assert text[evidence["start"] : evidence["end"]] == evidence["quote"]


def test_evidence_quote_normalizes_quote_glyphs_but_persists_source_slice(
    tmp_path: Path,
):
    service = _service(tmp_path)
    text = '第一章\n\n他说："钟声响了三次。"'
    service.prepare(
        "reference_quote_glyphs",
        text,
        relative_name="quote-glyphs.txt",
        input_budget_tokens=500,
    )

    def normalized_quotes(chunk: str, context: dict) -> dict:
        payload = _analyzer(chunk, context)
        supplied = "他说：“钟声响了三次。”"
        payload["findings"][0]["evidence"] = [
            {"start": 0, "end": len(supplied), "quote": supplied}
        ]
        return payload

    result = service.analyze("reference_quote_glyphs", analyzer=normalized_quotes)
    evidence = result["report"]["findings"][0]["evidence"][0]

    assert result["ok"] is True
    assert evidence["quote"] == '他说："钟声响了三次。"'
    assert text[evidence["start"] : evidence["end"]] == evidence["quote"]


def test_invalid_extra_evidence_is_dropped_when_finding_keeps_valid_quote(
    tmp_path: Path,
):
    service = _service(tmp_path)
    text = "第一章\n\n钟声响了三次。"
    service.prepare(
        "reference_extra_evidence",
        text,
        relative_name="extra-evidence.txt",
        input_budget_tokens=500,
    )

    def extra_invalid(chunk: str, context: dict) -> dict:
        payload = _analyzer(chunk, context)
        payload["findings"][0]["evidence"].append(
            {"start": 0, "end": 0, "quote": ""}
        )
        return payload

    result = service.analyze("reference_extra_evidence", analyzer=extra_invalid)

    assert result["ok"] is True
    assert len(result["report"]["findings"][0]["evidence"]) == 1


def test_synthesis_excludes_bound_content_and_promotion_requires_confirmation(
    tmp_path: Path,
):
    service = _service(tmp_path)
    for source_id, title in (("alpha", "甲城钟楼"), ("beta", "乙城剧场")):
        text = f"第一章 {title}\n\n{title}每晚都会改变一次钟声。"
        service.prepare(
            source_id,
            text,
            relative_name=f"{source_id}.txt",
            input_budget_tokens=500,
        )

        def analyze(chunk: str, context: dict, *, bound=title) -> dict:
            common = _analyzer(chunk, context)
            bound_finding = _analyzer(
                chunk,
                context,
                claim=f"专属设定：{bound}",
                source_bound=True,
            )["findings"][0]
            common["findings"].append(bound_finding)
            copied_name = _analyzer(
                chunk,
                context,
                claim=f"{bound}每晚都会改变钟声",
            )["findings"][0]
            common["findings"].append(copied_name)
            return common

        service.analyze(source_id, analyzer=analyze)

    profile = service.synthesize(["alpha", "beta"])
    preview = service.preview_promotion(profile.profile_id, "style")

    assert profile.common_methods[0].claim == "用重复物象建立递进节奏"
    assert any("甲城钟楼" in item for item in profile.excluded_items)
    assert "甲城钟楼" not in preview.proposed_content
    assert "乙城剧场" not in preview.proposed_content
    with pytest.raises(SourceAnalysisError) as confirmation:
        service.apply_promotion(preview.preview_id, confirm=False)
    assert confirmation.value.code == "CONFIRMATION_REQUIRED"

    applied = service.apply_promotion(preview.preview_id, confirm=True)
    target = service.novel_root / applied["target_ref"]
    assert target.is_file()
    assert "用重复物象建立递进节奏" in target.read_text(encoding="utf-8")


def test_promotion_rejects_changed_baseline_and_deleted_source_becomes_stale(tmp_path: Path):
    service = _service(tmp_path)
    for source_id in ("one", "two"):
        content = f"第一章\n\n{source_id} 的钟声逐次加快。"
        service.prepare(
            source_id,
            content,
            relative_name=f"{source_id}.txt",
            input_budget_tokens=500,
        )
        service.analyze(source_id, analyzer=_analyzer)
    profile = service.synthesize(["one", "two"])
    preview = service.preview_promotion(profile.profile_id, "rules")
    target = service.novel_root / preview.target_ref
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("人工变更\n", encoding="utf-8")

    with pytest.raises(SourceAnalysisError) as conflict:
        service.apply_promotion(preview.preview_id, confirm=True)
    assert conflict.value.code == "DOCUMENT_CONFLICT"

    deleted = service.mark_deleted("one")
    assert deleted["manifest"]["change_status"] == "deleted"
    assert deleted["manifest"]["status"] == "stale"
    assert service.status("one")["complete"] is False
