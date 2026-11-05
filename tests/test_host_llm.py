"""The host's own model directory, reached through its loopback relay."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from tools.host_llm import (
    clear_host_llm,
    configure_host_llm,
    fetch_host_models,
    host_llm,
    host_llm_available,
)
from tools.llm.client import LLMConfig
from tools.model_profiles import ModelProfileError, ModelProfileStore


class _RelayHandler(BaseHTTPRequestHandler):
    """A stand-in for the host relay: it answers the model directory."""

    payload = {
        "object": "list",
        "data": [
            {
                "id": "deepseek-official/deepseek-flash",
                "object": "model",
                "owned_by": "deepseek-official",
                "provider": "deepseek-official",
                "model": "deepseek-flash",
                "label": "DeepSeek Flash",
                "description": "",
                "context_tokens": 131072,
            },
            {
                "id": "our-free-model/vendor/Model-X",
                "object": "model",
                "owned_by": "our-free-model",
                "provider": "our-free-model",
                "model": "vendor/Model-X",
                "label": "Model X",
                "description": "free",
                "context_tokens": 0,
            },
        ],
    }

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path != "/v1/models":
            self.send_response(404)
            self.end_headers()
            return
        body = json.dumps(self.payload).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        return


@pytest.fixture
def relay() -> str:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RelayHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture(autouse=True)
def _no_relay():
    clear_host_llm()
    yield
    clear_host_llm()


def test_the_relay_coordinates_are_kept_in_memory_only():
    assert host_llm() is None
    assert host_llm_available() is False
    configure_host_llm("http://127.0.0.1:9/v1", "token-value")
    assert host_llm() == {"url": "http://127.0.0.1:9/v1", "token": "token-value"}
    clear_host_llm()
    assert host_llm() is None


def test_an_incomplete_handshake_does_not_arm_the_relay():
    configure_host_llm("", "token-value")
    assert host_llm() is None
    configure_host_llm("http://127.0.0.1:9/v1", "")
    assert host_llm() is None


def test_the_model_directory_is_read_through_the_relay(relay: str):
    configure_host_llm(relay, "token-value")
    catalog = fetch_host_models()
    assert catalog["available"] is True
    ids = [entry["id"] for entry in catalog["models"]]
    assert "deepseek-official/deepseek-flash" in ids
    # A model id that itself contains a slash survives the provider/model split.
    assert "our-free-model/vendor/Model-X" in ids
    entry = next(item for item in catalog["models"] if item["id"] == "deepseek-official/deepseek-flash")
    assert entry["context_tokens"] == 131072


def test_a_missing_relay_reports_itself_instead_of_raising():
    catalog = fetch_host_models()
    assert catalog["available"] is False
    assert catalog["models"] == []


def test_a_host_relay_profile_resolves_against_the_live_relay(tmp_path: Path, relay: str):
    configure_host_llm(relay, "token-value")
    store = ModelProfileStore(tmp_path)
    store.save_profile(
        {
            "id": "host-model",
            "label": "宿主模型",
            "provider": "custom",
            "base_url": "",
            "model": "our-free-model/vendor/Model-X",
            "api_format": "chat",
            "auth_source": "host_relay",
        },
        api_key="",
        remember_api_key=False,
    )
    resolved = store.resolve("chapter_write")
    assert resolved["base_url"] == relay
    assert resolved["api_key"] == "token-value"
    assert resolved["model"] == "our-free-model/vendor/Model-X"


def test_a_host_relay_profile_never_stores_a_credential(tmp_path: Path, relay: str):
    configure_host_llm(relay, "token-value")
    store = ModelProfileStore(tmp_path)
    store.save_profile(
        {
            "id": "host-model",
            "label": "宿主模型",
            "provider": "custom",
            "base_url": "",
            "model": "our-free-model/vendor/Model-X",
            "api_format": "chat",
            "auth_source": "host_relay",
        },
        # A client that posts a key anyway must not have it kept.
        api_key="client-supplied-secret",
        remember_api_key=True,
    )
    credentials = store.credentials_path
    if credentials.exists():
        assert "client-supplied-secret" not in credentials.read_text(encoding="utf-8")
    assert "client-supplied-secret" not in json.dumps(
        store.surface(), ensure_ascii=False
    )


def test_a_host_relay_profile_is_unconfigured_without_the_relay(tmp_path: Path, relay: str):
    configure_host_llm(relay, "token-value")
    store = ModelProfileStore(tmp_path)
    store.save_profile(
        {
            "id": "host-model",
            "label": "宿主模型",
            "provider": "custom",
            "base_url": "",
            "model": "our-free-model/vendor/Model-X",
            "api_format": "chat",
            "auth_source": "host_relay",
        },
        api_key="",
        remember_api_key=False,
    )
    assert store.surface()["profiles"][0]["configured"] is True
    clear_host_llm()
    assert store.surface()["profiles"][0]["configured"] is False


def test_resolving_a_host_relay_profile_without_the_relay_fails_loudly(tmp_path: Path):
    store = ModelProfileStore(tmp_path)
    store.save_profile(
        {
            "id": "host-model",
            "label": "宿主模型",
            "provider": "custom",
            "base_url": "",
            "model": "our-free-model/vendor/Model-X",
            "api_format": "chat",
            "auth_source": "host_relay",
        },
        api_key="",
        remember_api_key=False,
    )
    with pytest.raises(ModelProfileError) as excinfo:
        store.resolve("chapter_write")
    assert excinfo.value.code == "MODEL_HOST_RELAY_UNAVAILABLE"


def test_a_host_relay_profile_may_not_use_an_auto_model(tmp_path: Path):
    store = ModelProfileStore(tmp_path)
    with pytest.raises(ModelProfileError):
        store.save_profile(
            {
                "id": "host-model",
                "label": "宿主模型",
                "provider": "custom",
                "base_url": "",
                "model": "auto:cheapest",
                "api_format": "chat",
                "auth_source": "host_relay",
            },
            api_key="",
            remember_api_key=False,
        )


def test_an_operation_runs_on_the_host_model(tmp_path: Path, relay: str):
    """A routed operation must reach the host model, not a guessed default."""
    from tools.studio_application import StudioApplication

    configure_host_llm(relay, "token-value")
    store = ModelProfileStore(tmp_path / "config")
    store.save_profile(
        {
            "id": "host-model",
            "label": "宿主模型",
            "provider": "custom",
            "base_url": "",
            "model": "deepseek-official/deepseek-flash",
            "api_format": "chat",
            "auth_source": "host_relay",
        },
        api_key="",
        remember_api_key=False,
    )
    store.save_routes({key: "host-model" for key in ("goethe", "dante", "chapter_write")})
    seen: list[dict] = []

    def chat_executor(root, novel_id, agent, message):
        # The executor runs inside the operation's model context: this is the
        # configuration the real agent would build its client from.
        from tools.llm.client import LLMConfig

        config = LLMConfig.from_env()
        seen.append(
            {
                "agent": agent,
                "base_url": config.base_url,
                "api_key": config.api_key,
                "auth_source": config.auth_source,
                "model": config.model,
            }
        )
        return {"content": "ok"}

    app = StudioApplication(
        tmp_path,
        model_profile_store=store,
        chat_executor=chat_executor,
    )
    app.chat_turn({"agent": "dante", "message": "写一句开场白"})
    assert seen and seen[0]["agent"] == "dante"
    assert seen[0]["base_url"] == relay
    assert seen[0]["api_key"] == "token-value"
    assert seen[0]["auth_source"] == "host_relay"
    assert seen[0]["model"] == "deepseek-official/deepseek-flash"


def test_an_unconfigured_backend_falls_back_to_the_host_model(monkeypatch: pytest.MonkeyPatch):
    for name in ("LLM_MODEL", "LLM_API_KEY", "LLM_BASE_URL", "LLM_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    configure_host_llm("http://127.0.0.1:9/v1", "token-value")
    config = LLMConfig.from_env()
    assert config.auth_source == "host_relay"
    assert config.base_url == "http://127.0.0.1:9/v1"
    assert config.api_key == "token-value"
    assert config.model == "host/current"


def test_a_legacy_environment_outranks_the_host_model(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_MODEL", "legacy-model")
    monkeypatch.setenv("LLM_API_KEY", "legacy-key")
    configure_host_llm("http://127.0.0.1:9/v1", "token-value")
    config = LLMConfig.from_env()
    assert config.auth_source == "api_key"
    assert config.model == "legacy-model"


def test_a_host_relay_config_without_a_base_url_is_refused():
    with pytest.raises(ValueError):
        LLMConfig(provider="custom", api_key="token", base_url="", model="host/current", auth_source="host_relay")
