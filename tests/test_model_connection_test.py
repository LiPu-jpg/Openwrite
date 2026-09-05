"""Connection-test taxonomy, persistence, and payload contract tests."""

from __future__ import annotations

import asyncio
import json
from http import HTTPStatus
from pathlib import Path

import pytest

from tools.contracts_generated import validate_model_connection_test_v1
from tools.embedding_runtime import EmbeddingRuntimeError
from tools.init_project import init_project
from tools.llm.errors import (
    APIError,
    AuthenticationError,
    ContextLengthError,
    InvalidRequestError,
    LLMTimeoutError,
    NetworkError,
    RateLimitError,
)
from tools.llm.response import ProviderResponseError
from tools.llm.test_errors import connection_test_failure
from tools.model_profiles import ModelProfileError, ModelProfileStore
from tools.project_registry import ProjectRegistry
from tools.studio import StudioApplication
from tools.studio_contracts import StudioError
from tools.studio_preferences import StudioModelSettingsStore


def _profile(profile_id: str, model: str) -> dict:
    return {
        "id": profile_id,
        "label": profile_id,
        "provider": "openai",
        "base_url": "https://models.invalid/v1",
        "model": model,
        "api_format": "chat",
        "context_tokens": 64000,
        "max_output_tokens": 4096,
    }


def _embedding_profile(profile_id: str, model: str) -> dict:
    return {
        "id": profile_id,
        "label": profile_id,
        "provider": "openai",
        "base_url": "https://models.invalid/v1",
        "model": model,
        "dimension": 1536,
        "max_tokens": 8192,
    }


def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Legacy env mapping must never leak a phantom default profile into tests."""
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)


def _app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    executor=None,
    profiles: ModelProfileStore | None = None,
) -> StudioApplication:
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    init_project(tmp_path, "demo")
    return StudioApplication(
        tmp_path,
        model_test_executor=executor,
        project_registry=ProjectRegistry(
            tmp_path / "registry" / "recent.yaml", allow_ephemeral=True
        ),
        model_settings_store=StudioModelSettingsStore(tmp_path / "studio-settings"),
        model_profile_store=profiles or ModelProfileStore(tmp_path / "model-profiles"),
    )


class _FakeProviderHTTPError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


TAXONOMY_CASES = [
    ("invalid_configuration", ContextLengthError("context too long"), 412, False),
    ("authentication_failed", AuthenticationError("bad credential"), 401, False),
    ("permission_denied", _FakeProviderHTTPError(403, "forbidden"), 403, False),
    ("model_not_found", _FakeProviderHTTPError(404, "missing"), 404, False),
    ("rate_limited", RateLimitError("slow down"), 502, True),
    ("timeout", LLMTimeoutError("timed out"), 502, True),
    ("network_error", NetworkError("dns failed"), 502, True),
    ("provider_rejected", APIError("provider boom"), 502, True),
    ("provider_rejected", InvalidRequestError("bad request"), 502, True),
    ("provider_rejected", _FakeProviderHTTPError(503, "unavailable"), 502, True),
    ("unsupported_parameter", _FakeProviderHTTPError(400, "bad param"), 400, False),
    (
        "empty_response",
        ProviderResponseError("MODEL_EMPTY_RESPONSE", "模型返回了空内容"),
        502,
        True,
    ),
    (
        "invalid_response",
        ProviderResponseError("MALFORMED_STRUCTURED_OUTPUT", "无法解析"),
        502,
        True,
    ),
    ("timeout", TimeoutError("socket timeout"), 502, True),
    ("network_error", ConnectionError("connection reset"), 502, True),
    ("internal_error", ValueError("totally unexpected"), 500, False),
]


@pytest.mark.parametrize(
    ("kind", "exc", "http_status", "recoverable"),
    TAXONOMY_CASES,
    ids=[case[0] + "_" + type(case[1]).__name__ for case in TAXONOMY_CASES],
)
def test_chat_test_taxonomy_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    exc: Exception,
    http_status: int,
    recoverable: bool,
):
    def fail(_settings):
        raise exc

    app = _app(tmp_path, monkeypatch, executor=fail)
    with pytest.raises(StudioError) as captured:
        app.test_model_connection(
            {
                "provider": "openai",
                "base_url": "https://models.invalid/v1",
                "model": "candidate-model",
                "api_key": "candidate-secret",
            }
        )

    assert captured.value.code == f"MODEL_TEST_{kind.upper()}"
    assert captured.value.status == http_status
    assert captured.value.recoverable is recoverable
    assert "candidate-secret" not in str(captured.value)


def test_structured_signal_beats_message_inspection():
    # Message screams 401, but the structured provider status wins.
    exc = _FakeProviderHTTPError(429, "401 unauthorized: invalid api key")
    failure = connection_test_failure(exc)
    assert failure.kind == "rate_limited"
    assert failure.code == "MODEL_TEST_RATE_LIMITED"
    assert failure.http_status == HTTPStatus.BAD_GATEWAY
    assert failure.recoverable is True


def test_structured_status_on_cause_beats_message():
    cause = _FakeProviderHTTPError(404, "not found")
    wrapper = EmbeddingRuntimeError("云端 Embedding 请求失败: APIError")
    wrapper.__cause__ = cause
    assert connection_test_failure(wrapper).kind == "model_not_found"


def test_unrecognized_errors_degrade_by_exception_type():
    assert connection_test_failure(ValueError("weird")).kind == "internal_error"
    assert connection_test_failure(APIError("???")).kind == "provider_rejected"
    assert connection_test_failure(EmbeddingRuntimeError("???")).kind == "provider_rejected"
    assert connection_test_failure(asyncio.CancelledError()).kind == "cancelled"
    missing = ModelProfileError("缺少 API Key", code="MODEL_CREDENTIAL_MISSING")
    credential_failure = connection_test_failure(missing)
    assert credential_failure.kind == "credential_missing"
    assert credential_failure.http_status == HTTPStatus.PRECONDITION_FAILED
    invalid = ModelProfileError("配置无效", code="INVALID_MODEL_PROFILE")
    assert connection_test_failure(invalid).kind == "invalid_configuration"
    unknown = ModelProfileError("模型档案不存在", code="MODEL_PROFILE_NOT_FOUND")
    unknown_failure = connection_test_failure(unknown)
    assert unknown_failure.kind == "model_not_found"
    assert unknown_failure.http_status == HTTPStatus.NOT_FOUND


def test_chat_test_success_payload_and_last_test_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _isolate_env(monkeypatch)
    profiles = ModelProfileStore(tmp_path / "model-profiles")
    profiles.save_profile(_profile("writer", "writer-model"), api_key="test-credential-xyz")
    app = _app(tmp_path, monkeypatch, executor=lambda _settings: {"reply": "OK"})
    credentials_before = profiles.credentials_path.read_bytes()
    routes_before = dict(profiles.load()["routes"])

    result = app.test_model_connection({**_profile("writer", "writer-model")})

    assert result["ok"] is True
    assert result["status"] == "ok"
    assert result["provider"] == "openai"
    assert result["model"] == "writer-model"
    assert result["reply"] == "OK"
    assert result["latency_ms"] >= 1
    assert result["tested_at"].endswith("Z")
    validate_model_connection_test_v1(result)
    assert "test-credential-xyz" not in json.dumps(result, ensure_ascii=False)

    entry = profiles.surface()["profiles"][0]
    assert entry["last_test"]["status"] == "ok"
    assert entry["last_test"]["error_code"] is None
    assert entry["last_test"]["resolved_model"] == "writer-model"
    assert "last_embedding_test" not in entry
    # A successful test never rewrites config, credentials, or routes.
    assert profiles.credentials_path.read_bytes() == credentials_before
    assert profiles.load()["routes"] == routes_before
    saved_profile = profiles.load()["profiles"][0]
    assert saved_profile["model"] == "writer-model"
    assert saved_profile["base_url"] == "https://models.invalid/v1"


def test_id_only_connection_endpoints_use_stored_chat_and_local_embedding_profiles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _isolate_env(monkeypatch)
    profiles = ModelProfileStore(tmp_path / "model-profiles")
    profiles.save_profile(_profile("writer", "stored-writer"), api_key="stored-secret")
    profiles.save_embedding_profile(
        {
            **_embedding_profile("local-vector", "BAAI/bge-small-zh-v1.5"),
            "provider": "local",
            "base_url": "",
            "dimension": 512,
            "max_tokens": 512,
        }
    )
    observed: dict[str, object] = {}

    def chat_probe(settings):
        observed["chat_model"] = settings["model"]
        observed["chat_base_url"] = settings["base_url"]
        return {"reply": "OK"}

    def embedding_probe(settings):
        observed["embedding_provider"] = settings.provider
        observed["embedding_model"] = settings.model
        return {
            "ok": True,
            "provider": settings.provider,
            "provider_label": "本地 FastEmbed",
            "model": settings.model,
            "dimension": settings.dimension,
            "max_tokens": settings.max_tokens,
            "base_url": settings.base_url,
            "vectors": 2,
            "latency_ms": 1,
        }

    monkeypatch.setattr("tools.embedding_runtime.run_embedding_probe", embedding_probe)
    app = _app(tmp_path, monkeypatch, executor=chat_probe, profiles=profiles)

    chat = app.test_model_connection({"id": "writer"})
    embedding = app.test_embedding_connection({"id": "local-vector"})

    assert chat["status"] == "ok"
    assert embedding["status"] == "ok"
    assert observed == {
        "chat_model": "stored-writer",
        "chat_base_url": "https://models.invalid/v1",
        "embedding_provider": "local",
        "embedding_model": "BAAI/bge-small-zh-v1.5",
    }


@pytest.mark.parametrize(
    "method",
    ["test_model_connection", "test_embedding_connection"],
)
def test_id_only_unknown_connection_profile_returns_model_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method: str
):
    _isolate_env(monkeypatch)
    app = _app(tmp_path, monkeypatch)

    with pytest.raises(StudioError) as captured:
        getattr(app, method)({"id": "missing"})

    assert captured.value.code == "MODEL_TEST_MODEL_NOT_FOUND"
    assert captured.value.status == HTTPStatus.NOT_FOUND
    assert captured.value.recoverable is False


def test_chat_test_failure_persists_last_test_and_leaves_everything_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _isolate_env(monkeypatch)
    profiles = ModelProfileStore(tmp_path / "model-profiles")
    profiles.save_profile(_profile("writer", "writer-model"), api_key="test-credential-xyz")
    profiles.save_routes({"chapter_write": "writer"})
    credentials_before = profiles.credentials_path.read_bytes()
    profiles_file_before = profiles.profiles_path.read_text(encoding="utf-8")

    def fail(_settings):
        raise RateLimitError("429 quota exhausted; key test-credential-xyz rejected")

    app = _app(tmp_path, monkeypatch, executor=fail)
    novel_files_before = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file() and "model-profiles" not in path.parts
    }
    with pytest.raises(StudioError) as captured:
        app.test_model_connection({**_profile("writer", "writer-model")})

    assert captured.value.code == "MODEL_TEST_RATE_LIMITED"
    assert captured.value.status == 502
    assert captured.value.recoverable is True
    assert "test-credential-xyz" not in str(captured.value)

    entry = profiles.surface()["profiles"][0]
    assert entry["last_test"]["status"] == "failed"
    assert entry["last_test"]["error_code"] == "MODEL_TEST_RATE_LIMITED"
    assert entry["last_test"]["failed_stage"] is None
    assert "test-credential-xyz" not in json.dumps(entry, ensure_ascii=False)

    # Config fields, credentials, and routes are byte-identical after a
    # failed test; only the last_test key was added to the profiles file.
    assert profiles.credentials_path.read_bytes() == credentials_before
    after_text = profiles.profiles_path.read_text(encoding="utf-8")
    assert json.loads(after_text)["routes"] == json.loads(profiles_file_before)["routes"]
    before_profile = json.loads(profiles_file_before)["profiles"][0]
    after_profile = json.loads(after_text)["profiles"][0]
    assert after_profile.pop("last_test") is not None
    assert after_profile == before_profile
    # Nothing was written into the novel workspace.
    novel_files_after = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file() and "model-profiles" not in path.parts
    }
    assert novel_files_after == novel_files_before


def test_chat_test_credential_missing_is_taxonomy_and_persisted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _isolate_env(monkeypatch)
    profiles = ModelProfileStore(tmp_path / "model-profiles")
    profiles.save_profile(_profile("writer", "writer-model"))
    app = _app(tmp_path, monkeypatch, executor=lambda _settings: {"reply": "OK"})

    with pytest.raises(StudioError) as captured:
        app.test_model_connection({**_profile("writer", "writer-model")})

    assert captured.value.code == "MODEL_TEST_CREDENTIAL_MISSING"
    assert captured.value.status == 412
    assert captured.value.recoverable is False
    entry = profiles.surface()["profiles"][0]
    assert entry["last_test"]["status"] == "failed"
    assert entry["last_test"]["error_code"] == "MODEL_TEST_CREDENTIAL_MISSING"


def test_untested_profile_reads_back_as_null(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    profiles = ModelProfileStore(tmp_path / "model-profiles")
    profiles.save_profile(_profile("writer", "writer-model"), api_key="secret")
    profiles.save_embedding_profile(
        _embedding_profile("writer-vector", "text-embedding-3-small"), api_key="vector-secret"
    )

    surface = profiles.surface()
    entry = surface["profiles"][0]
    embedding_entry = surface["embedding_profiles"][0]

    assert entry["last_test"] is None
    assert embedding_entry["last_test"] is None


def test_embedding_test_success_payload_and_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _isolate_env(monkeypatch)
    profiles = ModelProfileStore(tmp_path / "model-profiles")
    profiles.save_embedding_profile(
        _embedding_profile("writer-vector", "text-embedding-3-small"),
        api_key="test-credential-xyz",
    )

    def fake_probe(settings):
        return {
            "ok": True,
            "provider": settings.provider,
            "provider_label": "云端 API",
            "model": settings.model,
            "dimension": settings.dimension,
            "max_tokens": settings.max_tokens,
            "base_url": settings.base_url,
            "vectors": 2,
            "latency_ms": 9,
        }

    monkeypatch.setattr("tools.embedding_runtime.run_embedding_probe", fake_probe)
    app = _app(tmp_path, monkeypatch)

    result = app.test_embedding_connection(
        {**_embedding_profile("writer-vector", "text-embedding-3-small")}
    )

    assert result["ok"] is True
    assert result["status"] == "ok"
    assert result["provider_label"] == "云端 API"
    assert result["dimension"] == 1536
    assert result["vectors"] == 2
    assert result["tested_at"].endswith("Z")
    validate_model_connection_test_v1(result)
    assert "test-credential-xyz" not in json.dumps(result, ensure_ascii=False)

    entry = profiles.surface()["embedding_profiles"][0]
    assert entry["last_test"]["status"] == "ok"
    assert entry["last_test"]["resolved_model"] == "text-embedding-3-small"


def test_embedding_test_failure_uses_same_taxonomy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _isolate_env(monkeypatch)
    profiles = ModelProfileStore(tmp_path / "model-profiles")
    profiles.save_embedding_profile(
        _embedding_profile("writer-vector", "text-embedding-3-small"),
        api_key="test-credential-xyz",
    )

    def fake_probe(_settings):
        raise EmbeddingRuntimeError("云端 Embedding 请求失败: AuthenticationError")

    monkeypatch.setattr("tools.embedding_runtime.run_embedding_probe", fake_probe)
    app = _app(tmp_path, monkeypatch)

    with pytest.raises(StudioError) as captured:
        app.test_embedding_connection(
            {**_embedding_profile("writer-vector", "text-embedding-3-small")}
        )

    assert captured.value.code == "MODEL_TEST_AUTHENTICATION_FAILED"
    assert captured.value.status == 401
    assert captured.value.recoverable is False
    assert "test-credential-xyz" not in str(captured.value)
    entry = profiles.surface()["embedding_profiles"][0]
    assert entry["last_test"]["status"] == "failed"
    assert entry["last_test"]["error_code"] == "MODEL_TEST_AUTHENTICATION_FAILED"
