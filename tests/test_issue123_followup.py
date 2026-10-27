"""Regression evidence supplied in the follow-up comments on #123."""

import asyncio
import json
from pathlib import Path

import pytest

from tools.agent.base import AgentContext
from tools.agent.tool_runtime import project_document_change_plan
from tools.agent.writer import WriterAgent
from tools.init_project import init_project
from tools.llm.client import LLMClient, LLMConfig, Message
from tools.project_registry import ProjectRegistry
from tools.revision_service import RevisionError, RevisionService
from tools.studio_application import StudioApplication
from tools.studio_contracts import StudioError


def provider_response(text):
    return {
        "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


@pytest.mark.parametrize("mode", ["disabled", "enabled", "omit"])
def test_writer_stages_send_the_selected_thinking_mode(tmp_path, monkeypatch, mode):
    sent = []
    outputs = iter(["正文", "观察", "invalid: [yaml", "state_updates: {}\nchapter_summary: 雨停"])
    config = LLMConfig(
        model="fake",
        max_tokens=8192,
        extra={
            "thinking_modes": {
                "chapter_write": mode,
                "review": "enabled",
                "revision": "enabled",
            }
        },
    )
    client = LLMClient(config)

    def completion(**params):
        sent.append(params)
        return provider_response(next(outputs))

    monkeypatch.setattr(client, "_completion", completion)
    monkeypatch.setattr("tools.agent.base.long_generation_stream", lambda: False)
    writer = WriterAgent(AgentContext(client, "fake", str(tmp_path)))
    asyncio.run(writer._creative_chat(messages=[Message("user", "写作")]))
    asyncio.run(writer._observe_facts({}, 1, "门", "正文"))
    asyncio.run(writer._settle({}, 1, "门", "正文", "观察"))
    assert len(sent) == 4
    for params in sent:
        assert params["max_tokens"] == 8192
        if mode == "omit":
            assert "thinking" not in params.get("extra_body", {})
        else:
            assert params["extra_body"]["thinking"] == {"type": mode}
    assert [c["stage"] for c in writer._usage_history] == [
        "draft",
        "fact_extract",
        "settle",
        "settle",
    ]


def test_revision_generation_uses_revision_thinking_mode(tmp_path, monkeypatch):
    sent = []
    config = LLMConfig(
        model="fake",
        extra={
            "thinking_modes": {
                "chapter_write": "enabled",
                "revision": "disabled",
            }
        },
    )
    monkeypatch.setattr(LLMConfig, "from_env", lambda: config)
    monkeypatch.setattr("tools.revision_service.long_generation_stream", lambda: False)

    client = LLMClient(config)

    def completion(**params):
        sent.append(params)
        return provider_response(
            json.dumps(
                {"replacement_text": "雨停", "rationale": "精简", "risk_flags": []},
                ensure_ascii=False,
            )
        )

    monkeypatch.setattr(client, "_completion", completion)
    monkeypatch.setattr("tools.llm.LLMClient", lambda _config: client)
    service = RevisionService(tmp_path, "demo")
    result = service._default_generator({"request": {}, "selection": "雨终于停了"})
    assert result["replacement_text"] == "雨停"
    assert sent[0]["extra_body"]["thinking"] == {"type": "disabled"}


def test_selection_mismatch_is_not_reported_as_a_version_conflict(tmp_path):
    init_project(tmp_path, "demo")
    path = tmp_path / "data/novels/demo/data/manuscript/arc_001/ch_001.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "# 门\r\n\r\n行中 > 悬念: 雨声\r\n第二行\n尾部"
    path.write_bytes(content.encode())
    selected = "> 悬念: 雨声\r\n第二行"
    start = content.index(selected)
    service = RevisionService(tmp_path, "demo", generator=lambda _: pytest.fail("no model"))
    with pytest.raises(RevisionError) as failed:
        service.create_selection(
            chapter_id="ch_001",
            start=start,
            end=start + len(selected),
            original_text=selected.replace("\r\n", "\n"),
        )
    assert failed.value.code == "OLD_TEXT_NOT_FOUND"
    assert failed.value.details["suggested_old_text"] == selected
    assert failed.value.details["mismatch_kind"] == "whitespace"
    assert failed.value.details["retry_revision"] == service.fingerprint(content)
    assert StudioApplication._translate_revision_error(failed.value).status == 400
    assert path.read_bytes() == content.encode()


def test_missing_range_anchor_explains_exact_whitespace_without_changing_bytes(tmp_path):
    init_project(tmp_path, "demo")
    path = tmp_path / "data/novels/demo/src/world/rules.md"
    content = "# 规则\r\n行中 > 悬念:\u00a0雨声\n第二行\r\n## 尾部"
    path.write_bytes(content.encode())
    result = project_document_change_plan(
        tmp_path,
        "demo",
        {
            "path": "src/world/rules.md",
            "edits": [{"start_text": "> 悬念: 雨声", "end_text": "## 尾部", "new_text": "替换"}],
        },
    )
    assert result["error"] == "text_range_not_found"
    hint = result["details"]["anchor_diagnostics"]["start_text"]
    assert hint["suggested_old_text"] == "> 悬念:\u00a0雨声"
    assert hint["mismatch_kind"] == "whitespace"
    assert path.read_bytes() == content.encode()


def test_existing_manuscript_preflight_names_the_chapter_and_recovery(tmp_path):
    init_project(tmp_path, "demo")
    path = tmp_path / "data/novels/demo/data/manuscript/arc_001/ch_001.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes("# 门\n\n已有正文".encode())
    app = StudioApplication(
        tmp_path,
        project_registry=ProjectRegistry(tmp_path / "registry.json", allow_ephemeral=True),
        writer_executor=lambda *_: pytest.fail("no model"),
    )
    try:
        with pytest.raises(StudioError) as failed:
            app.write_next_chapter({"chapter_id": "ch_001"})
        assert failed.value.code == "CHAPTER_ALREADY_EXISTS"
        assert failed.value.details["chapter_id"] == "ch_001"
        assert "已有正文" in str(failed.value)
    finally:
        app._task_runner.shutdown(wait=True)


def test_health_workspace_and_package_metadata_have_one_version(tmp_path):
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib
    from tools.studio_http import health_payload
    from tools.version import __version__

    init_project(tmp_path, "demo")
    app = StudioApplication(
        tmp_path, project_registry=ProjectRegistry(tmp_path / "registry.json", allow_ephemeral=True)
    )
    try:
        project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
        assert health_payload()["core_version"] == app.workspace()["version"]
        assert __version__ == project["project"]["version"] == app.workspace()["version"]
    finally:
        app._task_runner.shutdown(wait=True)
