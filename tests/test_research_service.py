from __future__ import annotations

import json
from pathlib import Path
from threading import Thread
from urllib.request import ProxyHandler, build_opener

import pytest

from tools.init_project import init_project
from tools.research_service import (
    MAX_PROCESS_OUTPUT_BYTES,
    ResearchService,
    ResearchServiceError,
    normalize_report_metadata,
)
from tools.studio import create_server
from tools.studio_preferences import StudioResearchSettingsStore


def test_research_service_archives_and_reads_report(tmp_path: Path):
    novel_root = tmp_path / "novel"
    reports = novel_root / "data" / "research" / "reports"
    reports.mkdir(parents=True)
    (reports / "episode_1.md").write_text("# 研究结果\n\n正文", encoding="utf-8")
    (reports / "episode_1.json").write_text(
        json.dumps(
            {
                "title": "叙事视角",
                "status": "succeeded",
                "episode_id": "episode_1",
                "created_at": "2026-08-03T00:00:00Z",
                "metrics": {"sources": 3},
            }
        ),
        encoding="utf-8",
    )
    service = ResearchService(novel_root)
    assert service.list_reports()[0]["id"] == "episode_1"
    assert service.read_report("episode_1")["content"].startswith("# 研究结果")


def test_research_service_maps_openwrite_model_environment(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "local-model")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    service = ResearchService(tmp_path)
    env = service._research_environment({"search": "none"})
    assert env["AGENT_PROVIDER"] == "openai"
    assert env["OPENAI_API_KEY"] == "test-key"
    assert env["AGENT_MODEL"] == "local-model"
    assert env["OPENAI_BASE_URL"] == "https://example.test/v1"


def test_research_settings_keep_search_credentials_private(tmp_path: Path):
    store = StudioResearchSettingsStore(tmp_path / "preferences")

    surface = store.save(
        {
            "search_provider": "bocha",
            "search_api_key": "private-bocha-key",
            "remember_api_key": True,
        }
    )

    bocha = next(item for item in surface["search_providers"] if item["id"] == "bocha")
    assert bocha["configured"] is True
    assert bocha["credential_configured"] is True
    assert "private-bocha-key" not in json.dumps(surface, ensure_ascii=False)
    assert store.credential("bocha") == "private-bocha-key"
    assert (store.credentials_path.stat().st_mode & 0o777) == 0o600


def test_research_environment_uses_routed_model_and_saved_search_key(tmp_path: Path):
    store = StudioResearchSettingsStore(tmp_path / "preferences")
    store.save(
        {
            "search_provider": "jina",
            "search_api_key": "jina-secret",
            "remember_api_key": False,
        }
    )
    service = ResearchService(tmp_path / "novel", settings_store=store)

    env = service._research_environment(
        {"search": "jina"},
        model_profile={
            "provider": "openai",
            "api_key": "model-secret",
            "base_url": "https://models.example/v1",
            "model": "research-model",
            "api_format": "responses",
        },
    )

    assert env["AGENT_PROVIDER"] == "openai"
    assert env["OPENAI_API_KEY"] == "model-secret"
    assert env["OPENAI_BASE_URL"] == "https://models.example/v1"
    assert env["AGENT_MODEL"] == "research-model"
    assert env["OPENAI_WIRE_API"] == "responses"
    assert env["JINA_API_KEY"] == "jina-secret"
    assert "jina-secret" not in store.credentials_path.read_text(encoding="utf-8")


def test_research_environment_uses_saved_jina_key_as_bing_fetch_fallback(tmp_path: Path):
    store = StudioResearchSettingsStore(tmp_path / "preferences")
    store.save(
        {
            "search_provider": "jina",
            "search_api_key": "jina-reader-secret",
            "remember_api_key": True,
        }
    )
    service = ResearchService(tmp_path / "novel", settings_store=store)

    env = service._research_environment({"search": "bing"})

    assert env["JINA_API_KEY"] == "jina-reader-secret"
    assert env["FETCH_MODE"] == "fallback"


def test_research_environment_reports_missing_search_key(tmp_path: Path):
    service = ResearchService(
        tmp_path / "novel",
        settings_store=StudioResearchSettingsStore(tmp_path / "preferences"),
    )

    with pytest.raises(ResearchServiceError, match="博查 API Key") as exc_info:
        service._research_environment({"search": "bocha"})

    assert exc_info.value.code == "RESEARCH_SEARCH_CREDENTIAL_MISSING"


def test_research_status_does_not_expose_machine_paths(tmp_path: Path):
    framework = tmp_path / "private-install" / "deepresearch"
    framework.mkdir(parents=True)
    (framework / "package.json").write_text("{}", encoding="utf-8")

    status = ResearchService(tmp_path / "novel", framework_root=framework).status()

    assert "framework_root" not in status
    assert "node" not in status
    assert "pnpm" not in status
    assert str(tmp_path) not in json.dumps(status, ensure_ascii=False)


def test_research_service_rejects_report_outside_artifact_root(tmp_path: Path):
    service = ResearchService(tmp_path / "novel", framework_root=tmp_path / "framework")
    outside = tmp_path / "outside.md"
    outside.write_text("private", encoding="utf-8")

    with pytest.raises(ResearchServiceError, match="产物目录之外") as exc_info:
        service._validated_report_path(outside)

    assert exc_info.value.code == "INVALID_REPORT_PATH"


def test_research_process_output_is_bounded():
    output = bytearray(b"old")
    ResearchService._append_process_output(output, b"x" * (MAX_PROCESS_OUTPUT_BYTES + 20))

    assert len(output) == MAX_PROCESS_OUTPUT_BYTES
    assert output == b"x" * MAX_PROCESS_OUTPUT_BYTES


def test_research_service_parses_pretty_summary():
    summary = ResearchService._parse_summary(
        '{\n  "status": "succeeded",\n  "episodeId": "ep_1",\n  "report": "/tmp/report.md"\n}'
    )
    assert summary["episodeId"] == "ep_1"


def test_research_service_rejects_failed_internal_episode_after_archiving(
    tmp_path: Path, monkeypatch
):
    framework = tmp_path / "framework"
    (framework / "node_modules").mkdir(parents=True)
    (framework / "package.json").write_text("{}", encoding="utf-8")
    service = ResearchService(tmp_path / "novel", framework_root=framework)
    source_report = service.artifact_root / "EP_failed" / "final-report.md"
    source_report.parent.mkdir(parents=True)
    source_report.write_text("# 失败研究产物\n\n预算门未通过。", encoding="utf-8")

    class FakeContext:
        def phase(self, phase: str, note: str = "") -> None:
            del phase, note

        def checkpoint(self) -> None:
            return None

        def cancellation_requested(self) -> bool:
            return False

    monkeypatch.setattr(service, "status", lambda: {"available": True})
    monkeypatch.setattr("tools.research_service.shutil.which", lambda name: "/bin/echo")
    monkeypatch.setattr(
        service,
        "_parse_summary",
        lambda output: {
            "status": "failed",
            "episodeId": "EP_failed",
            "report": str(source_report),
            "metrics": {"publishGatePassed": False},
        },
    )

    with pytest.raises(ResearchServiceError) as exc_info:
        service.run(
            {"prompt": "研究悬疑小说剧情设计", "search": "none"},
            FakeContext(),
        )

    assert exc_info.value.code == "RESEARCH_EPISODE_FAILED"
    archived = service.report_root / "EP_failed.json"
    assert archived.is_file()
    metadata = json.loads(archived.read_text(encoding="utf-8"))
    assert metadata["status"] == "failed"
    assert metadata["failure"] == {
        "code": "RESEARCH_EPISODE_FAILED",
        "message": "DeepResearch 未通过内部质量或预算门，失败产物已保留供诊断",
    }
    assert metadata["sources"] is None
    assert metadata["sources_status"] == "unavailable"
    assert metadata["usage"] == {"total_tokens": None, "reported": False}
    assert metadata["cost_usd"] == {"value": None, "reported": False}
    assert (service.report_root / "EP_failed.md").is_file()


class _FakeContext:
    task_id = "tsk_fake"

    def phase(self, phase: str, note: str = "") -> None:
        del phase, note

    def checkpoint(self) -> None:
        return None

    def cancellation_requested(self) -> bool:
        return False


def _stub_successful_run(service, monkeypatch, summary):
    monkeypatch.setattr(service, "status", lambda: {"available": True})
    monkeypatch.setattr("tools.research_service.shutil.which", lambda name: "/bin/echo")
    monkeypatch.setattr(service, "_parse_summary", lambda output: summary)


def test_research_service_archives_enriched_metadata(tmp_path: Path, monkeypatch):
    framework = tmp_path / "framework"
    (framework / "node_modules").mkdir(parents=True)
    (framework / "package.json").write_text("{}", encoding="utf-8")
    store = StudioResearchSettingsStore(tmp_path / "preferences")
    service = ResearchService(
        tmp_path / "novel", framework_root=framework, settings_store=store
    )
    episode_dir = service.artifact_root / "EP_ok"
    episode_dir.mkdir(parents=True)
    body = "# 研究结果\n\n引用 [C1] 的证据。\n"
    source_report = episode_dir / "report.md"
    source_report.write_text(body, encoding="utf-8")
    evidence_index = episode_dir / "evidence-index.json"
    evidence_index.write_text(
        json.dumps(
            [
                {
                    "citationId": "C1",
                    "title": "来源甲",
                    "url": "https://a.example/1",
                    "sourceTier": "primary",
                },
                {
                    "citationId": "C2",
                    "title": "来源乙",
                    "url": "https://b.example/2",
                    "sourceTier": "secondary",
                },
            ]
        ),
        encoding="utf-8",
    )
    _stub_successful_run(
        service,
        monkeypatch,
        {
            "status": "succeeded",
            "episodeId": "EP_ok",
            "report": str(source_report),
            "evidenceIndex": str(evidence_index),
            "metrics": {
                "citationCount": 2,
                "totalTokenCount": 0,
                "estimatedCostUsd": 0.0,
            },
        },
    )

    result = service.run(
        {"prompt": "研究叙事视角", "search": "none"},
        _FakeContext(),
        model_profile={
            "id": "default",
            "label": "默认档案",
            "model": "glm-4.7-flash",
            "provider": "openai",
            "api_key": "model-secret",
        },
        task_id="tsk_20260101_ab",
    )

    assert result["report_id"] == "EP_ok"
    metadata = json.loads((service.report_root / "EP_ok.json").read_text(encoding="utf-8"))
    # existing keys untouched
    assert metadata["prompt"] == "研究叙事视角"
    assert metadata["artifact_ref"].startswith("data/research/artifacts/")
    assert metadata["metrics"]["citationCount"] == 2
    # enrichment
    assert metadata["task_id"] == "tsk_20260101_ab"
    assert metadata["created_at"]
    assert metadata["completed_at"]
    assert metadata["model_profile"] == {
        "id": "default",
        "label": "默认档案",
        "model": "glm-4.7-flash",
        "provider": "openai",
    }
    assert "model-secret" not in json.dumps(metadata, ensure_ascii=False)
    assert metadata["search_provider"] == "none"
    assert isinstance(metadata["latency_ms"], int) and metadata["latency_ms"] >= 0
    assert metadata["word_count"] == len(body)
    assert metadata["sources_status"] == "ok"
    assert metadata["sources"] == [
        {
            "title": "来源甲",
            "url": "https://a.example/1",
            "source_type": "primary",
            "cited": True,
        },
        {
            "title": "来源乙",
            "url": "https://b.example/2",
            "source_type": "secondary",
            "cited": False,
        },
    ]
    # explicit 0 is reported, not absent
    assert metadata["usage"] == {"total_tokens": 0, "reported": True}
    assert metadata["cost_usd"] == {"value": 0.0, "reported": True}
    assert metadata["failure"] is None
    entry = service.list_reports()[0]
    assert entry["task_id"] == "tsk_20260101_ab"
    assert entry["source_count"] == 2


def test_research_service_normalizes_legacy_report_metadata(tmp_path: Path):
    novel_root = tmp_path / "novel"
    reports = novel_root / "data" / "research" / "reports"
    reports.mkdir(parents=True)
    body = "# 旧报告\n\n正文内容"
    (reports / "legacy.md").write_text(body, encoding="utf-8")
    (reports / "legacy.json").write_text(
        json.dumps(
            {
                "title": "旧研究",
                "prompt": "旧研究",
                "status": "succeeded",
                "episode_id": "legacy",
                "created_at": "2026-01-01T00:00:00Z",
                "artifact_ref": "data/research/artifacts/legacy",
                "metrics": {"citationCount": 2, "totalTokenCount": 1200},
            }
        ),
        encoding="utf-8",
    )
    service = ResearchService(novel_root)

    entry = service.list_reports()[0]
    assert entry["id"] == "legacy"
    assert entry["title"] == "旧研究"
    assert entry["status"] == "succeeded"
    assert entry["task_id"] is None
    assert entry["model_profile"] is None
    assert entry["search_provider"] is None
    assert entry["completed_at"] is None
    assert entry["latency_ms"] is None
    assert entry["word_count"] is None
    assert entry["sources"] is None
    assert entry["sources_status"] == "unavailable"
    assert entry["source_count"] is None
    assert entry["usage"] == {"total_tokens": 1200, "reported": True}
    assert entry["cost_usd"] == {"value": None, "reported": False}
    assert entry["failure"] is None
    assert entry["metrics"]["citationCount"] == 2

    detail = service.read_report("legacy")
    assert detail["content"] == body
    assert detail["metadata"]["word_count"] == len(body)
    assert detail["metadata"]["task_id"] is None


def test_research_metadata_preserves_prompt_completion_and_legacy_success_aliases():
    dto = normalize_report_metadata(
        {
            "title": "历史研究",
            "prompt": "核查旧报告",
            "status": "completed",
            "completed_at": "2026-08-23T10:25:37Z",
        },
        report_id="legacy-complete",
    )

    assert dto["prompt"] == "核查旧报告"
    assert dto["status"] == "succeeded"
    assert dto["completed_at"] == "2026-08-23T10:25:37Z"


def test_normalize_report_metadata_tolerates_garbage():
    dto = normalize_report_metadata("not-a-dict", report_id="broken")
    assert dto["id"] == "broken"
    assert dto["status"] == "unknown"
    assert dto["sources"] is None
    assert dto["sources_status"] == "unavailable"
    assert dto["usage"] == {"total_tokens": None, "reported": False}
    assert dto["metrics"] == {}


def test_research_settings_are_scoped_per_workspace(tmp_path: Path):
    global_store = StudioResearchSettingsStore(tmp_path / "preferences")
    service_a = ResearchService(tmp_path / "novel-a", settings_store=global_store)
    service_b = ResearchService(tmp_path / "novel-b", settings_store=global_store)

    service_a.save_settings({"search_provider": "bocha"})
    service_b.save_settings({"search_provider": "bing"})

    assert service_a.settings_store.load_settings()["search_provider"] == "bocha"
    assert service_b.settings_store.load_settings()["search_provider"] == "bing"
    workspace_file = tmp_path / "novel-a" / "data" / "research" / "settings.json"
    assert json.loads(workspace_file.read_text(encoding="utf-8")) == {
        "search_provider": "bocha",
        "remember_api_key": True,
    }
    # the machine-global settings file is not written by workspace saves
    assert not (tmp_path / "preferences" / "research-settings.json").exists()


def test_research_settings_fall_back_to_machine_global(tmp_path: Path):
    global_store = StudioResearchSettingsStore(tmp_path / "preferences")
    global_store.save(
        {
            "search_provider": "jina",
            "search_api_key": "jina-secret",
            "remember_api_key": True,
        }
    )
    service = ResearchService(tmp_path / "novel", settings_store=global_store)

    # no workspace file yet: legacy machine-global settings still apply
    assert service.settings_store.load_settings()["search_provider"] == "jina"
    assert service.settings_store.credential("jina") == "jina-secret"

    service.save_settings({"search_provider": "bing"})
    assert service.settings_store.load_settings()["search_provider"] == "bing"
    # the workspace save does not clobber the machine-global fallback
    assert global_store.load_settings()["search_provider"] == "jina"


def test_research_workspace_settings_never_store_credentials(tmp_path: Path):
    global_store = StudioResearchSettingsStore(tmp_path / "preferences")
    service = ResearchService(tmp_path / "novel", settings_store=global_store)

    surface = service.save_settings(
        {
            "search_provider": "bocha",
            "search_api_key": "super-secret-key",
            "remember_api_key": True,
        }
    )

    workspace_file = tmp_path / "novel" / "data" / "research" / "settings.json"
    assert workspace_file.is_file()
    assert "super-secret-key" not in workspace_file.read_text(encoding="utf-8")
    credentials = (tmp_path / "preferences" / ".research-search-credentials.json").read_text(
        encoding="utf-8"
    )
    assert "super-secret-key" in credentials
    bocha = next(item for item in surface["search_providers"] if item["id"] == "bocha")
    assert bocha["credential_configured"] is True
    assert "super-secret-key" not in json.dumps(surface, ensure_ascii=False)


def test_studio_exposes_research_status_and_report_route(tmp_path: Path):
    init_project(tmp_path, "demo")
    server = create_server(tmp_path, port=0)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        opener = build_opener(ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{server.server_port}/api/research") as response:
            payload = json.loads(response.read())
        assert payload["ok"] is True
        assert payload["data"]["schema_version"] == "openwrite.research-surface.v1"
        assert "available" in payload["data"]
        assert payload["data"]["reports"] == []
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
