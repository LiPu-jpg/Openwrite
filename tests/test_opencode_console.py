from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tools.llm import opencode_console as console
from tools.llm.client import LLMClient, LLMConfig, Message
from tools.llm.test_errors import connection_test_failure
from tools.model_profiles import ModelProfileError, ModelProfileStore, activate_model_profile
from tools.studio_application import StudioApplication


def fake_cli(monkeypatch, keys=("first-test-token", "renewed-test-token"), org="wrk_test"):
    calls = []
    monkeypatch.setattr(console.shutil, "which", lambda _: "/test/opencode")

    def run(args, **kwargs):
        calls.append((args, kwargs))
        key = keys[min(len(calls) - 1, len(keys) - 1)]
        data = {
            "padding": "x" * 70000,
            "provider": {
                "opencode-go": {
                    "options": {
                        "apiKey": key,
                        "headers": {"x-opencode-org-id": org, "Authorization": "ignored"},
                    }
                }
            },
        }
        kwargs["stdout"].write(json.dumps(data).encode())
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(console.subprocess, "run", run)
    return calls


def profile(**changes):
    return {
        "id": "go",
        "label": "Go",
        "provider": "openai",
        "model": "deepseek-v4.1-flash",
        "base_url": console.GO_BASE_URL,
        "api_format": "chat",
        "auth_source": "opencode_console",
        **changes,
    }


def test_each_request_refreshes_once_and_preserves_workspace_and_truthful_headers(monkeypatch):
    calls = fake_cli(monkeypatch)
    requests = []

    def completion(**params):
        requests.append(params)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="OK"), finish_reason="stop")],
            usage={},
        )

    client = LLMClient(
        LLMConfig(
            base_url=console.GO_BASE_URL,
            model="deepseek-v4.1-flash",
            auth_source="opencode_console",
            extra={"extra_headers": {"x-test": "kept"}},
        ),
        client=completion,
    )
    for _ in range(2):
        assert client.chat([Message("user", "test")]).content == "OK"
    assert len(calls) == 2
    assert [r["api_key"] for r in requests] == ["first-test-token", "renewed-test-token"]
    for r in requests:
        assert r["extra_headers"]["x-opencode-org-id"] == "wrk_test"
        assert r["extra_headers"]["User-Agent"].startswith("OpenWrite/")
        assert r["extra_headers"]["x-test"] == "kept"
        assert "Authorization" not in r["extra_headers"]
    assert (
        requests[0]["extra_headers"]["x-opencode-session"]
        == requests[1]["extra_headers"]["x-opencode-session"]
    )
    assert calls[0][0][-3:] == ["debug", "config", "--pure"]
    assert calls[0][1]["timeout"] == 20


@pytest.mark.parametrize(
    "url",
    [
        "http://opencode.ai/zen/go/v1",
        "https://evil.example/v1",
        "https://opencode.ai.evil.example/zen/go/v1",
        "https://opencode.ai/zen/go/v1?redirect=evil",
        "https://user@opencode.ai/zen/go/v1",
        "https://opencode.ai:444/zen/go/v1",
        "https://opencode.ai/console",
    ],
)
def test_console_credentials_cannot_be_sent_to_another_destination(url, monkeypatch):
    calls = fake_cli(monkeypatch)
    with pytest.raises(ValueError):
        LLMConfig(base_url=url, auth_source="opencode_console")
    with pytest.raises(ModelProfileError):
        ModelProfileStore._profile_metadata(profile(base_url=url))
    assert not calls


def test_missing_cli_and_workspace_mismatch_are_actionable_and_do_not_echo_secrets(monkeypatch):
    monkeypatch.setattr(console.shutil, "which", lambda _: None)
    with pytest.raises(console.ConsoleAuthenticationError) as missing:
        console.console_credentials()
    assert "Studio" in connection_test_failure(missing.value).message
    fake_cli(monkeypatch)
    with pytest.raises(console.ConsoleAuthenticationError) as mismatch:
        console.console_credentials("wrk_other")
    assert "工作区" in connection_test_failure(mismatch.value).message
    assert "first-test-token" not in str(mismatch.value)


def test_cli_failure_does_not_expose_stdout_or_stderr(monkeypatch):
    fake_cli(monkeypatch)

    def broken(args, **kwargs):
        kwargs["stderr"].write(b"super-private-token")
        kwargs["stdout"].write(b"not-json-super-private-token")
        return SimpleNamespace(returncode=1)

    monkeypatch.setattr(console.subprocess, "run", broken)
    with pytest.raises(console.ConsoleAuthenticationError) as error:
        console.console_credentials()
    assert "super-private-token" not in str(error.value)
    assert "super-private-token" not in connection_test_failure(error.value).message


def test_profiles_probe_and_runtime_use_console_without_persisting_tokens(tmp_path, monkeypatch):
    calls = fake_cli(monkeypatch)
    store = ModelProfileStore(tmp_path)
    store.save_profile(profile(), api_key="must-not-be-stored")
    assert not store.credentials_path.exists()
    assert store.surface()["profiles"][0]["configured"] is True
    for item in [
        store.test_candidate({"id": "go"}),
        store.resolve("chapter_write"),
        store.resolve_profile("go", operation="review"),
    ]:
        assert item["api_key"] == ""
        with activate_model_profile(item):
            cfg = LLMConfig.from_env()
        assert cfg.auth_source == "opencode_console"
    assert calls == []  # reads/saves never execute the CLI or consume credentials
    assert "first-test-token" not in store.profiles_path.read_text()
    assert "renewed-test-token" not in store.profiles_path.read_text()
    assert "must-not-be-stored" not in json.dumps(store.surface())


def test_connection_probe_and_manual_key_forward_workspace(monkeypatch):
    import tools.llm

    received = []

    class Client:
        def __init__(self, config):
            received.append(config)

        def chat(self, *args, **kwargs):
            return SimpleNamespace(content="OK")

    monkeypatch.setattr(tools.llm, "LLMClient", Client)
    result = StudioApplication._default_model_connection_test(
        {**profile(), "api_key": "", "workspace_id": "wrk_test", "max_tokens": 256}
    )
    assert result == {"reply": "OK"}
    assert received[0].auth_source == "opencode_console"
    assert received[0].workspace_id == "wrk_test"
    client = LLMClient(
        LLMConfig(base_url=console.GO_BASE_URL, api_key="manual", workspace_id="wrk_test"),
        client=lambda **p: None,
    )
    assert client._base_params()["extra_headers"]["x-opencode-org-id"] == "wrk_test"


def test_switching_auth_source_keeps_inactive_manual_key_and_clears_old_probe(
    tmp_path, monkeypatch
):
    fake_cli(monkeypatch)
    store = ModelProfileStore(tmp_path)
    store.save_profile(profile(auth_source="api_key"), api_key="manual-test-secret")
    saved = store.load()
    saved["profiles"][0]["last_test"] = {
        "status": "ok",
        "tested_at": "2026-10-26T00:00:00Z",
        "latency_ms": 1,
        "provider": "openai",
        "resolved_model": "deepseek-v4.1-flash",
    }
    store._write_payload(saved)
    store.save_profile(profile(), remember_api_key=False)
    assert store.surface()["profiles"][0]["last_test"] is None
    assert store.resolve("chapter_write")["api_key"] == ""
    store.save_profile(profile(auth_source="api_key"))
    assert store.resolve("chapter_write")["api_key"] == "manual-test-secret"


def test_graph_search_resolves_console_credentials_and_forwards_headers(tmp_path, monkeypatch):
    import asyncio
    import sys
    from types import ModuleType

    from tools.project_search import LightRAGConfiguration, LightRAGSearchBackend

    fake_cli(monkeypatch)
    store = ModelProfileStore()
    store.save_profile(profile(search_mode="graph"))
    store.save_embedding_profile(
        {"id": "embed", "model": "test-embed", "base_url": "https://example.invalid/v1"},
        api_key="embedding-test-secret",
    )
    store.select_embedding_profile("embed")
    resolved = store.resolve("search")
    with activate_model_profile(resolved, search_profile=resolved):
        config = LightRAGConfiguration.from_runtime()
    assert config.llm_auth_source == "opencode_console"
    assert "embedding-test-secret" not in json.dumps(config.public_payload())
    captured = {}
    requests = []
    fake = ModuleType("lightrag")

    def rag(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace()

    fake.LightRAG = rag
    monkeypatch.setitem(sys.modules, "lightrag", fake)
    openai = ModuleType("lightrag.llm.openai")

    async def complete(*args, **kwargs):
        requests.append(kwargs)
        return "{}"

    openai.openai_complete_if_cache = complete
    monkeypatch.setitem(sys.modules, "lightrag.llm.openai", openai)
    utils = ModuleType("lightrag.utils")
    utils.EmbeddingFunc = lambda **kwargs: kwargs
    monkeypatch.setitem(sys.modules, "lightrag.utils", utils)
    LightRAGSearchBackend(tmp_path, configuration=config)._create_rag()
    assert asyncio.run(captured["llm_model_func"]("extract keywords")) == "{}"
    assert requests[0]["api_key"] == "first-test-token"
    assert requests[0]["extra_headers"]["x-opencode-org-id"] == "wrk_test"
    assert requests[0]["extra_headers"]["User-Agent"].startswith("OpenWrite/")
