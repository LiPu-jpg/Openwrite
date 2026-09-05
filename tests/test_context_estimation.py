from pathlib import Path

import pytest

from models.context_package import GenerationContext, estimate_text_tokens
from tools.chapter_assembler import ChapterAssemblerV2, ChapterAssemblyPacket
from tools.context_builder import ContextBuilder
from tools.context_manifest import build_context_manifest
from tools.llm.context import ContextBudgetPolicy


@pytest.mark.parametrize(
    "text",
    [
        "中" * 1500,
        "The rain crossed the old clock tower at midnight. " * 40,
        "雨落 clock tower 17，林岑说 keep moving。" * 80,
    ],
)
def test_manifest_and_execution_sections_use_one_estimator(
    tmp_path: Path, text: str
):
    manifest = build_context_manifest(tmp_path, {"creative_focus": text})
    item = manifest["items"][0]
    context = GenerationContext(creative_focus=text)
    report = context.token_estimate_report()
    packet = ChapterAssemblyPacket(
        novel_id="demo", chapter_id="ch_001", creative_focus=text
    )

    assert item["estimated_tokens"] == estimate_text_tokens(text)
    assert report["section_content_estimated_tokens"] == estimate_text_tokens(text)
    assert ChapterAssemblerV2._packet_token_count(packet) == estimate_text_tokens(text)
    assert item["measurement"]["estimator"] == report["estimator"]


def test_chinese_manifest_no_longer_understates_execution_by_150_percent(
    tmp_path: Path,
):
    text = "中" * 1500

    manifest = build_context_manifest(tmp_path, {"creative_focus": text})
    report = GenerationContext(creative_focus=text).token_estimate_report()

    assert manifest["estimated_tokens"] == 2250
    assert report["section_content_estimated_tokens"] == 2250


def test_estimate_breakdown_explains_total_and_keeps_actual_usage_unknown():
    context = GenerationContext(
        creative_focus="雨夜不能改变林岑的选择。",
        current_state="钟楼仍然封闭。",
        relationships="林岑信任周远。",
    )

    report = context.token_estimate_report()

    assert report["total_estimated_tokens"] == (
        report["section_content_estimated_tokens"]
        + report["wrapper_estimated_tokens"]
        + report["separate_truth_estimated_tokens"]
    )
    assert report["includes_wrapper_overhead"] is True
    assert report["actual_usage"] == {
        "reported": False,
        "prompt_tokens": None,
        "total_tokens": None,
    }


def test_manifest_labels_scope_and_does_not_render_unknown_actual_usage_as_zero(
    tmp_path: Path,
):
    manifest = build_context_manifest(tmp_path, {"creative_focus": "保留雨夜意象"})

    assert manifest["measurement"] == {
        "kind": "estimate",
        "estimator": "mixed-script-conservative-v1",
        "text_scope": "rendered_section_values",
        "includes_wrapper_overhead": False,
    }
    assert manifest["section_estimated_tokens"] == manifest["estimated_tokens"]
    assert manifest["wrapper_estimated_tokens"] is None
    assert manifest["actual_usage"] == {
        "reported": False,
        "prompt_tokens": None,
        "total_tokens": None,
    }


def test_execution_budget_report_declares_scope_and_unknown_provider_usage():
    builder = object.__new__(ContextBuilder)
    builder.COMPRESSION_STRATEGY = "test-strategy"
    plan = ContextBudgetPolicy(64000, 24000).plan(120)

    report = builder._compression_report(
        applied=False,
        level=0,
        original_tokens=120,
        final_tokens=120,
        actions=[],
        plan=plan,
    )

    assert report["measurement"] == {
        "kind": "estimate",
        "estimator": "mixed-script-conservative-v1",
        "text_scope": "rendered_prompt_and_separate_truth_values",
        "includes_wrapper_overhead": True,
    }
    assert report["actual_usage"]["reported"] is False
    assert report["actual_usage"]["total_tokens"] is None
