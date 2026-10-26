"""Author-visible regressions from the 5.8.12 serial-writing report."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.agent.base import AgentContext
from tools.agent.tool_runtime import _replace_document_text_range, project_document_change_plan
from tools.agent.writer import WriterAgent
from tools.arc_audit import ArcAuditService
from tools.chapter_assembler import ChapterAssemblerV2
from tools.chapter_pipeline import _style_profile
from tools.init_project import init_project
from tools.llm.client import LLMClient, LLMConfig, Message
from tools.llm.response import ProviderResponseError
from tools.manuscript_acceptance import ManuscriptAcceptanceError, ManuscriptAcceptanceService
from tools.novel_service import NovelApplicationService
from tools.outline_tree import build_outline_structure
from tools.structured_assets import StructuredAssetService
from tools.studio_application import StudioApplication
from tools.studio_contracts import StudioError, studio_error_payload
from tools.writing_assets import join_segment


def project(tmp_path: Path) -> Path:
    init_project(tmp_path, "demo")
    root = tmp_path / "data/novels/demo"
    (root / "src/outline.md").write_text(
        "# 作品\n\n## 第1篇：篇\n\n### 第1节：节\n\n#### 第1章：门\n\n开门。\n\n"
        "> 预估字数: 1000\n> 未知键: 保留原值\n"
    )
    return root


def response(content):
    return SimpleNamespace(
        content=content, usage={"total_tokens": 10}, total_tokens=10, finish_reason="stop"
    )


def test_style_text_is_not_silently_capped_per_file():
    docs = {"craft.dialogue_craft": "甲" * 1100, "source.voice": "乙" * 1000}
    rendered = _style_profile(docs, 4000)
    assert "甲" * 1100 in rendered
    assert "乙" * 1000 in rendered


def test_document_allocation_is_proportional_and_never_exceeds_bucket():
    assembler = ChapterAssemblerV2.__new__(ChapterAssemblerV2)
    kept, truncated, dropped = assembler._limit_document_map(
        {"short": "甲" * 100, "long": "乙" * 900}, total_chars=500, per_document=1000
    )
    assert {key: len(value) for key, value in kept.items()} == {"long": 450, "short": 50}
    assert len(truncated) == 2 and not dropped
    kept, _, dropped = assembler._limit_document_map(
        {"a": "甲" * 100, "b": "乙" * 100}, total_chars=1, per_document=1000
    )
    assert sum(map(len, kept.values())) == 1
    assert len(dropped) == 1


def test_repair_segment_target_and_final_hook_agree(tmp_path):
    calls = []

    def chat(**kwargs):
        calls.append(kwargs)
        return response("乙" * 2000)

    writer = WriterAgent(AgentContext(SimpleNamespace(chat=chat), "fake", str(tmp_path)))
    initial = response("# 第一章\n\n" + "甲" * 3000)
    result = asyncio.run(
        writer._segmented_write(
            {"chapter_beats": ["起", "承", "转", "合"], "chapter_hooks": ["门后是谁"]},
            1,
            0.7,
            5000,
            initial_response=initial,
        )
    )
    assert result["word_count"] == 5000
    assert len(calls) == 1
    prompt = calls[0]["messages"][-1].content
    assert "本段约 2000 字" in prompt and "本段完成章末钩子" in prompt
    assert "从上述前文尾部之后直接续写" in prompt


def test_near_duplicate_prose_is_removed_but_changed_numbers_and_short_dialogue_survive():
    old = (
        "他沿着雨中的石阶缓缓走到门口，抬头看了一眼天色，"
        "又仔细擦干钥匙上的水珠，随后推开那扇沉重的木门。"
    )
    changed = old.replace("缓缓", "缓慢")
    assert changed not in join_segment(old, changed + "\n\n好。\n\n好。")
    assert join_segment(old, changed + "\n\n好。\n\n好。").count("好。") == 2
    first = old + "钟敲了12声。"
    second = old + "钟敲了13声。"
    assert second in join_segment(first, second)


@pytest.mark.parametrize("code", ["MODEL_OUTPUT_TRUNCATED", "PROVIDER_NETWORK_ERROR"])
def test_transient_generation_retry_is_bounded_and_uses_exponential_delays(
    monkeypatch, tmp_path, code
):
    calls, waits = [], []

    def chat(**kwargs):
        calls.append(kwargs)
        if len(calls) < 3:
            raise ProviderResponseError(code, "transient")
        return response("# 第一章\n\n" + "甲" * 1000)

    async def wait(seconds):
        waits.append(seconds)

    monkeypatch.setattr("tools.agent.writer.asyncio.sleep", wait)
    writer = WriterAgent(AgentContext(SimpleNamespace(chat=chat), "fake", str(tmp_path)))
    result = asyncio.run(writer._creative_write({}, 1, 0.7, 1000))
    assert result["word_count"] == 1000
    assert len(calls) == 3 and waits == [1, 2]
    assert calls[0]["messages"] == calls[2]["messages"]
    assert result["usage"]["cost_reported"] is False


def test_unrelated_errors_are_not_retried(tmp_path):
    calls = []

    def chat(**kwargs):
        calls.append(kwargs)
        raise ProviderResponseError("MODEL_REASONING_ONLY", "no visible response")

    writer = WriterAgent(AgentContext(SimpleNamespace(chat=chat), "fake", str(tmp_path)))
    with pytest.raises(ProviderResponseError):
        asyncio.run(writer._creative_write({}, 1, 0.7, 1000))
    assert len(calls) == 1


def test_world_documents_are_in_full_bridge_context_with_read_inventory(tmp_path):
    root = project(tmp_path)
    (root / "src/world/terminology.md").write_text("专名：雨钥只能写成雨钥。")
    (root / "src/world/timeline.md").write_text("故事始于第三纪元第十八年。")
    result = NovelApplicationService(tmp_path).context_preview("ch_001", include_agent_payload=True)
    messages = str(result["writer_messages"])
    assert "雨钥只能写成雨钥" in messages
    assert "第三纪元第十八年" in messages
    assert result["agent_payload"]["target_words"] == 1000
    assert any(
        row["document"] == "world.timeline" and row["fully_in_writer_messages"]
        for row in result["document_inventory"]
    )


def test_unknown_outline_metadata_reports_original_key_value_and_line(tmp_path):
    root = project(tmp_path)
    report = build_outline_structure(root)["parse_report"]
    assert report["recognized_count"] == 1
    assert report["ignored"][0]["key"] == "未知键"
    assert report["ignored"][0]["value"] == "保留原值"
    assert report["ignored"][0]["node_id"] == "ch_001"


def test_related_mapping_is_preserved_on_create_raw_update_and_explicit_replace(tmp_path):
    project(tmp_path)
    service = StructuredAssetService(tmp_path, "demo")
    created = service.create("character", {"id": "lin", "name": "林", "related": {"zhou": "旧友"}})
    assert created["data"]["related"] == [{"target": "zhou", "note": "旧友"}]
    updated = service.update(
        "character",
        "lin",
        {"raw_text": '+++\nid = "lin"\nname = "林"\n+++\n\n# 林\n\n新正文。'},
        expected_revision=created["revision"],
    )
    assert updated["data"]["related"] == created["data"]["related"]
    cleared = service.update(
        "character",
        "lin",
        {"data": {"related": []}, "related_mode": "replace"},
        expected_revision=updated["revision"],
    )
    assert cleared["data"]["related"] == []


def test_range_can_preserve_end_heading_and_reports_literal_inline_quote_anchor():
    text = "## 旧节\n旧正文\n## 下一节\n保留正文"
    result = _replace_document_text_range(
        text, "## 旧节", "## 下一节", "## 新节\n新正文\n", end_inclusive=False
    )
    assert result["source"] == "## 新节\n新正文\n## 下一节\n保留正文"
    assert _replace_document_text_range("行中 > 这段原文\n结尾", "> 这段原文", "结尾", "替换")["ok"]


def test_consumed_preview_tokens_can_be_rejected_but_never_replayed(tmp_path):
    root = project(tmp_path)
    path = root / "src/world/rules.md"
    path.write_text("行中 > 唯一原文\n")
    preview = project_document_change_plan(
        tmp_path,
        "demo",
        {"path": "src/world/rules.md", "edits": [{"old_text": "> 唯一原文", "new_text": "新原文"}]},
    )
    token = preview["preview_token"]
    assert project_document_change_plan(
        tmp_path, "demo", {"action": "apply", "confirm": True, "preview_token": token}
    )["ok"]
    assert not project_document_change_plan(
        tmp_path, "demo", {"action": "apply", "confirm": True, "preview_token": token}
    )["ok"]
    assert (
        project_document_change_plan(
            tmp_path, "demo", {"action": "reject", "preview_token": token}
        )["status"]
        == "rejected"
    )
    assert path.read_text() == "行中 新原文\n"


def test_project_busy_returns_retry_hint():
    payload = studio_error_payload(StudioError("busy", 409, code="PROJECT_BUSY"), "test")
    assert payload["recoverable"]
    assert payload["details"]["retry_after_seconds"] == 30


@pytest.mark.parametrize(
    "base", ["https://opencode.ai/zen/go/v1", "https://opencode.ai/inference/go/openai/v1"]
)
def test_opencode_go_uses_chat_root_raw_model_and_stable_truthful_headers(base):
    calls = []

    def completion(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content="完成"), finish_reason="stop")
            ],
            usage={},
            model=kwargs["model"],
        )

    client = LLMClient(
        LLMConfig(
            provider="openai",
            api_key="fake",
            base_url=base + "/chat/completions",
            model="deepseek-v4.1-flash",
        ),
        client=completion,
    )
    client.chat([Message("user", "test")])
    client.chat([Message("user", "next")])
    assert calls[0]["base_url"] == base
    assert calls[0]["model"] == "deepseek-v4.1-flash"
    assert calls[0]["custom_llm_provider"] == "openai"
    assert calls[0]["extra_headers"]["User-Agent"].startswith("OpenWrite/")
    assert (
        calls[0]["extra_headers"]["x-opencode-session"]
        == calls[1]["extra_headers"]["x-opencode-session"]
    )


def test_unknown_payoff_reference_is_an_audit_error(tmp_path):
    root = project(tmp_path)
    path = root / "src/outline.md"
    path.write_text(path.read_text() + "\n> 回收伏笔: 第一次埋下的名字\n")
    errors = ArcAuditService(tmp_path, "demo").audit("arc_001")["errors"]
    assert errors[0]["code"] == "UNKNOWN_PAYOFF_REFERENCE"
    assert errors[0]["reference"] == "第一次埋下的名字"


def test_fast_acceptance_is_partial_with_next_action_and_chapter_alias(tmp_path):
    root = project(tmp_path)
    (root / "data/manuscript/arc_001/ch_001.md").write_text("# 第一章\n\n正文。")
    service = ManuscriptAcceptanceService(tmp_path, "demo")
    operation = service.establish_baseline(confirm=True)
    operation = service.accept_without_model(operation["operation_id"])
    app = StudioApplication(tmp_path)
    try:
        result = app._manuscript_acceptance_result(service, operation)
        assert result["completed"] is False and result["blocking"] is True
        assert result["status"] == "partial"
        assert result["next_action"]["action"] == "resume"
        assert app._acceptance_operation_id({"chapter_id": "ch_001"}) == operation["operation_id"]
        with pytest.raises(ManuscriptAcceptanceError) as failure:
            service.require_current("ch_002")
        assert failure.value.details["next_action"] == "resume"
        assert failure.value.details["model_called"] is False
    finally:
        if app._task_runner is not None:
            app._task_runner.shutdown(wait=True)


def test_retry_superseded_preview_can_be_rejected_without_affecting_new_preview(tmp_path):
    root = project(tmp_path)
    path = root / "src/world/rules.md"
    path.write_text("原文。")
    first = project_document_change_plan(
        tmp_path,
        "demo",
        {"path": "src/world/rules.md", "edits": [{"old_text": "原文", "new_text": "新文"}]},
    )
    path.write_text("原文。\n额外一句。")
    second = project_document_change_plan(
        tmp_path, "demo", {"action": "retry", "preview_token": first["preview_token"]}
    )
    assert second["preview_token"] != first["preview_token"]
    assert project_document_change_plan(
        tmp_path, "demo", {"action": "reject", "preview_token": first["preview_token"]}
    )["ok"]
    applied = project_document_change_plan(
        tmp_path,
        "demo",
        {"action": "apply", "confirm": True, "preview_token": second["preview_token"]},
    )
    assert applied["ok"] and path.read_text() == "新文。\n额外一句。"
