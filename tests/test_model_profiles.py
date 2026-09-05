from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.context_builder import ContextBuilder
from tools.llm.client import LLMConfig
from tools.model_profiles import (
    ModelProfileError,
    ModelProfileStore,
    activate_model_profile,
)
from tools.studio_preferences import StudioModelSettingsStore


def profile(profile_id: str, model: str, *, context_tokens: int = 64000) -> dict:
    return {
        "id": profile_id,
        "label": profile_id.title(),
        "provider": "openai",
        "base_url": "https://models.example/v1",
        "model": model,
        "api_format": "chat",
        "context_tokens": context_tokens,
        "max_output_tokens": 4096,
        "temperature": 0,
        "timeout_seconds": 45,
    }


def embedding_profile(profile_id: str, model: str, *, provider: str = "openai") -> dict:
    return {
        "id": profile_id,
        "label": profile_id.title(),
        "provider": provider,
        "base_url": "" if provider == "local" else "https://embeddings.example/v1",
        "model": model,
        "dimension": 512 if provider == "local" else 3072,
        "max_tokens": 512 if provider == "local" else 8192,
    }


def test_legacy_single_model_maps_to_default_without_exposing_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    legacy = StudioModelSettingsStore(tmp_path)
    legacy.save_settings(
        {
            "provider": "openai",
            "base_url": "https://legacy.example/v1",
            "model": "legacy-prose",
            "api_format": "chat",
            "context_tokens": 32000,
            "max_tokens": 2048,
        }
    )
    legacy.save_credential("legacy-secret")

    surface = ModelProfileStore(tmp_path).surface()

    assert surface["legacy_mapped"] is True
    assert surface["profiles"][0]["id"] == "default"
    assert surface["profiles"][0]["model"] == "legacy-prose"
    assert surface["profiles"][0]["configured"] is True
    assert "legacy-secret" not in json.dumps(surface, ensure_ascii=False)


def test_three_named_profiles_route_independently_and_keep_credentials_private(tmp_path: Path):
    store = ModelProfileStore(tmp_path)
    store.save_profile(profile("balanced", "planner"), api_key="plan-secret")
    store.save_profile(profile("prose", "writer"), api_key="write-secret")
    store.save_profile(profile("critic", "reviewer"), api_key="review-secret")
    store.save_routes(
        {
            "goethe": "balanced",
            "dante": "prose",
            "chapter_write": "prose",
            "review": "critic",
            "research": "balanced",
        }
    )

    assert store.resolve("goethe")["model"] == "planner"
    assert store.resolve("chapter_write")["api_key"] == "write-secret"
    assert store.resolve("review")["model"] == "reviewer"
    assert store.resolve("research")["model"] == "planner"
    surface_text = json.dumps(store.surface(), ensure_ascii=False)
    assert "plan-secret" not in surface_text
    assert "write-secret" not in surface_text
    assert "review-secret" not in surface_text


def test_named_profile_override_does_not_mutate_routes(tmp_path: Path):
    store = ModelProfileStore(tmp_path)
    store.save_profile(profile("writer-a", "writer-a-model"), api_key="a-secret")
    store.save_profile(profile("writer-b", "writer-b-model"), api_key="b-secret")
    store.save_routes({"chapter_write": "writer-a"})

    before = store.load()["routes"]
    resolved = store.resolve_profile("writer-b", operation="chapter_write")

    assert resolved["id"] == "writer-b"
    assert resolved["api_key"] == "b-secret"
    assert store.load()["routes"] == before


def test_profile_persists_task_scoped_thinking_modes(tmp_path: Path):
    store = ModelProfileStore(tmp_path)
    candidate = {
        **profile("critic", "deepseek-v4-flash"),
        "thinking_modes": {
            "review": "disabled",
            "revision": "disabled",
            "chapter_write": "omit",
            "unknown": "enabled",
        },
    }

    saved = store.save_profile(candidate, api_key="secret")
    store.save_routes({"review": "critic"})

    assert saved["thinking_modes"] == {
        "review": "disabled",
        "revision": "disabled",
        "chapter_write": "omit",
    }
    resolved = store.resolve("review")
    assert resolved["thinking_modes"]["review"] == "disabled"
    with activate_model_profile(resolved):
        config = LLMConfig.from_env()
    assert config.extra["thinking_modes"]["review"] == "disabled"


def test_search_profile_keeps_embedding_credentials_private(tmp_path: Path):
    store = ModelProfileStore(tmp_path)
    store.save_profile(profile("search", "graph-extractor"), api_key="llm-secret")
    store.save_embedding_profile(
        embedding_profile("search-embedding", "text-embedding-3-large"),
        api_key="embedding-secret",
    )
    store.select_embedding_profile("search-embedding")
    store.save_routes({"search": "search"})

    resolved_chat = store.resolve("search")
    resolved_embedding = store.resolve_embedding()
    surface_text = json.dumps(store.surface(), ensure_ascii=False)

    assert resolved_chat["api_key"] == "llm-secret"
    assert resolved_embedding["api_key"] == "embedding-secret"
    assert resolved_embedding["model"] == "text-embedding-3-large"
    assert resolved_embedding["dimension"] == 3072
    assert "llm-secret" not in surface_text
    assert "embedding-secret" not in surface_text


def test_local_embedding_profile_is_ready_without_embedding_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    store = ModelProfileStore(tmp_path)
    local_profile = embedding_profile("local-search", "BAAI/bge-small-zh-v1.5", provider="local")
    store.save_embedding_profile(local_profile)

    surface = store.surface()["embedding_profiles"][0]
    candidate = store.test_embedding_candidate(local_profile)

    assert surface["configured"] is True
    assert surface["active"] is True
    assert candidate["provider"] == "local"
    assert candidate["api_key"] == ""


def test_id_only_probe_hydrates_stored_chat_and_local_embedding_profiles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    store = ModelProfileStore(tmp_path)
    store.save_profile(profile("critic", "reviewer-model"), api_key="stored-chat-secret")
    store.save_embedding_profile(
        embedding_profile("local-search", "BAAI/bge-small-zh-v1.5", provider="local")
    )

    chat = store.test_candidate({"id": "critic"})
    embedding = store.test_embedding_candidate({"id": "local-search"})

    assert chat["model"] == "reviewer-model"
    assert chat["base_url"] == "https://models.example/v1"
    assert chat["api_key"] == "stored-chat-secret"
    assert embedding["provider"] == "local"
    assert embedding["model"] == "BAAI/bge-small-zh-v1.5"
    assert embedding["api_key"] == ""


def test_probe_merges_partial_explicit_fields_over_stored_profile(tmp_path: Path) -> None:
    store = ModelProfileStore(tmp_path)
    store.save_profile(profile("writer", "stored-model"), api_key="stored-secret")

    candidate = store.test_candidate({"id": "writer", "model": "candidate-model"})

    assert candidate["model"] == "candidate-model"
    assert candidate["provider"] == "openai"
    assert candidate["base_url"] == "https://models.example/v1"
    assert candidate["api_key"] == "stored-secret"


@pytest.mark.parametrize("kind", ["chat", "embedding"])
def test_id_only_probe_rejects_unknown_profile_with_stable_error(
    tmp_path: Path, kind: str
) -> None:
    store = ModelProfileStore(tmp_path)
    probe = store.test_candidate if kind == "chat" else store.test_embedding_candidate

    with pytest.raises(ModelProfileError) as error:
        probe({"id": "missing"})

    assert error.value.code == "MODEL_PROFILE_NOT_FOUND"


def test_vector_search_profile_resolves_without_chat_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    store = ModelProfileStore(tmp_path)
    chat_profile = {**profile("local-search", "unused-in-vector-mode"), "search_mode": "vector"}
    store.save_profile(chat_profile)
    store.save_embedding_profile(
        embedding_profile("local-vector", "BAAI/bge-small-zh-v1.5", provider="local")
    )
    store.save_routes({"search": "local-search"})

    resolved_chat = store.resolve("search")
    resolved_embedding = store.resolve_embedding()

    assert resolved_chat["api_key"] == ""
    assert resolved_embedding["provider"] == "local"
    assert resolved_embedding["api_key"] == ""
    store.save_profile({**chat_profile, "search_mode": "graph"})
    with pytest.raises(ModelProfileError) as error:
        store.resolve("search")
    assert error.value.code == "MODEL_CREDENTIAL_MISSING"


def test_session_only_credential_is_not_written_to_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    store = ModelProfileStore(tmp_path)
    store.save_profile(
        profile("temporary", "session-model"),
        api_key="session-secret",
        remember_api_key=False,
    )

    assert store.resolve("goethe")["api_key"] == "session-secret"
    assert "session-secret" not in store.credentials_path.read_text(encoding="utf-8")


def test_disabling_credential_persistence_clears_an_existing_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    store = ModelProfileStore(tmp_path)
    store.save_profile(profile("prose", "writer"), api_key="persisted-secret")
    store.save_profile(profile("prose", "writer"), remember_api_key=False)

    assert store.surface()["profiles"][0]["configured"] is False
    assert store.credentials_path.read_text(encoding="utf-8").strip() == "{}"


def test_credential_update_timestamps_are_server_managed_and_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    store = ModelProfileStore(tmp_path)
    first_timestamp = "2026-08-25T08:00:00Z"
    second_timestamp = "2026-08-25T09:30:00Z"
    monkeypatch.setattr(
        ModelProfileStore,
        "_utc_timestamp",
        staticmethod(lambda: first_timestamp),
    )

    saved = store.save_profile(
        {**profile("prose", "writer"), "credential_updated_at": "2099-01-01T00:00:00Z"},
        api_key="test-chat-credential-a",
    )
    saved_embedding = store.save_embedding_profile(
        {
            **embedding_profile("prose-vector", "text-embedding-3-large"),
            "credential_updated_at": "2099-01-01T00:00:00Z",
        },
        api_key="test-embedding-credential-a",
    )

    assert saved["credential_updated_at"] == first_timestamp
    assert saved_embedding["credential_updated_at"] == first_timestamp

    metadata_only = store.save_profile({**profile("prose", "writer"), "label": "Updated label"})
    embedding_metadata_only = store.save_embedding_profile(
        {**embedding_profile("prose-vector", "text-embedding-3-large"), "label": "Updated vector"}
    )
    assert metadata_only["credential_updated_at"] == first_timestamp
    assert embedding_metadata_only["credential_updated_at"] == first_timestamp

    monkeypatch.setattr(
        ModelProfileStore,
        "_utc_timestamp",
        staticmethod(lambda: second_timestamp),
    )
    rotated = store.save_profile(profile("prose", "writer"), api_key="test-chat-credential-b")
    assert rotated["credential_updated_at"] == second_timestamp
    store.select_embedding_profile("prose-vector")
    embedding_after = store.resolve_embedding()
    assert embedding_after["credential_updated_at"] == first_timestamp

    surface_text = json.dumps(store.surface(), ensure_ascii=False)
    profile_text = store.profiles_path.read_text(encoding="utf-8")
    assert second_timestamp in surface_text
    assert "test-chat-credential-a" not in surface_text
    assert "test-chat-credential-b" not in surface_text
    assert "test-embedding-credential-a" not in surface_text
    assert "test-chat-credential-a" not in profile_text
    assert "test-chat-credential-b" not in profile_text
    assert "test-embedding-credential-a" not in profile_text


def test_clearing_credentials_clears_update_timestamps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setattr(
        ModelProfileStore,
        "_utc_timestamp",
        staticmethod(lambda: "2026-08-25T08:00:00Z"),
    )
    store = ModelProfileStore(tmp_path)
    store.save_profile(profile("prose", "writer"), api_key="test-chat-credential")
    store.save_embedding_profile(
        embedding_profile("prose-vector", "text-embedding-3-large"),
        api_key="test-embedding-credential",
    )

    cleared = store.save_profile(profile("prose", "writer"), remember_api_key=False)
    cleared_embedding = store.save_embedding_profile(
        embedding_profile("prose-vector", "text-embedding-3-large"),
        remember_api_key=False,
    )
    surface_profile = next(item for item in store.surface()["profiles"] if item["id"] == "prose")
    surface_embedding = next(
        item for item in store.surface()["embedding_profiles"] if item["id"] == "prose-vector"
    )

    assert "credential_updated_at" not in cleared
    assert "credential_updated_at" not in surface_profile
    assert surface_profile["configured"] is False
    assert "credential_updated_at" not in cleared_embedding
    assert "credential_updated_at" not in surface_embedding
    assert surface_embedding["configured"] is False


def test_existing_credential_without_timestamp_does_not_invent_one(tmp_path: Path):
    store = ModelProfileStore(tmp_path)
    saved = store.save_profile(profile("prose", "writer"))
    store._write_json(
        store.credentials_path,
        {saved["credential_ref"]: "pre-upgrade-test-credential"},
    )

    surface_profile = store.surface()["profiles"][0]

    assert surface_profile["configured"] is True
    assert "credential_updated_at" not in surface_profile


def test_delete_profile_in_use_requires_and_applies_fallback(tmp_path: Path):
    store = ModelProfileStore(tmp_path)
    store.save_profile(profile("prose", "writer"), api_key="one")
    store.save_profile(profile("fallback", "backup"), api_key="two")
    store.save_routes({"chapter_write": "prose", "dante": "prose"})

    with pytest.raises(ModelProfileError) as error:
        store.delete_profile("prose")
    assert error.value.code == "MODEL_PROFILE_IN_USE"

    result = store.delete_profile("prose", fallback_id="fallback")
    assert result["routes"]["chapter_write"] == "fallback"
    assert result["routes"]["dante"] == "fallback"


def test_active_profile_drives_llm_config_and_context_budget(tmp_path: Path):
    active = {
        **profile("prose", "writer-large", context_tokens=128000),
        "api_key": "active-secret",
    }

    with activate_model_profile(active):
        config = LLMConfig.from_env()
        builder = ContextBuilder(tmp_path, "demo")

    assert config.model == "writer-large"
    assert config.api_key == "active-secret"
    assert config.temperature == 0
    assert config.max_tokens == 4096
    assert config.context_tokens == 128000
    assert builder.CONTEXT_WINDOW_TOKENS == 128000
    assert builder.MAX_OUTPUT_TOKENS == 4096
    assert builder.MAX_TOKENS == 120064


@pytest.mark.parametrize(
    ("context_tokens", "max_output_tokens"),
    (
        (1_050_000, 128_000),
        (2_000_000, 131_072),
        (10_000_000, 32_768),
        (1_000_000, 384_000),
        (2_000_000, 750_000),
    ),
)
def test_long_context_profiles_are_valid_and_drive_context_budget(
    tmp_path: Path,
    context_tokens: int,
    max_output_tokens: int,
):
    store = ModelProfileStore(tmp_path)
    saved = store.save_profile(
        {
            **profile("long-context", "long-context-model"),
            "context_tokens": context_tokens,
            "max_output_tokens": max_output_tokens,
        },
        api_key="long-context-secret",
    )

    with activate_model_profile(saved):
        builder = ContextBuilder(tmp_path, "demo")

    assert saved["context_tokens"] == context_tokens
    assert saved["max_output_tokens"] == max_output_tokens
    assert builder.CONTEXT_WINDOW_TOKENS == context_tokens
    assert builder.MAX_OUTPUT_TOKENS == max_output_tokens
    assert builder.MAX_TOKENS < context_tokens
    assert builder.MAX_TOKENS > context_tokens // 2


def test_model_profile_rejects_output_that_leaves_no_input_budget(tmp_path: Path):
    store = ModelProfileStore(tmp_path)

    with pytest.raises(ModelProfileError, match="最大输出必须小于上下文预算"):
        store.save_profile(
            {
                **profile("invalid-output", "custom-model"),
                "context_tokens": 500_000,
                "max_output_tokens": 500_000,
            }
        )


def test_model_profile_surface_exposes_presets_without_credentials(tmp_path: Path):
    store = ModelProfileStore(tmp_path)
    store.save_profile(profile("prose", "writer"), api_key="private-secret")

    surface = store.surface()
    serialized = json.dumps(surface, ensure_ascii=False)

    assert len(surface["presets"]) >= 20
    assert "openai-gpt-5.6-sol" in {preset["id"] for preset in surface["presets"]}
    assert "xiaomi-mimo-v2.5-pro" in {preset["id"] for preset in surface["presets"]}
    assert "private-secret" not in serialized
    assert all("api_key" not in preset for preset in surface["presets"])


def test_unknown_route_and_last_profile_deletion_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    store = ModelProfileStore(tmp_path)
    store.save_profile(profile("only", "single"), api_key="one")

    with pytest.raises(ModelProfileError) as route_error:
        store.resolve("unknown")
    assert route_error.value.code == "INVALID_MODEL_ROUTE"

    with pytest.raises(ModelProfileError) as delete_error:
        store.delete_profile("only")
    assert delete_error.value.code == "MODEL_PROFILE_LAST_PROFILE"


def test_surface_exposes_credential_free_profile_state_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    store = ModelProfileStore(tmp_path)
    store.save_profile(profile("prose", "writer-model"), api_key="surface-secret")
    store.save_profile(profile("critic", "review-model"), api_key="critic-secret")
    store.save_routes({"chapter_write": "prose", "review": "critic"})

    surface = store.surface({"review": "prose"})
    serialized = json.dumps(surface, ensure_ascii=False)
    entries = {item["id"]: item for item in surface["profiles"]}

    prose = entries["prose"]
    assert prose["schema_version"] == "openwrite.model-profile.v1"
    assert prose["capabilities"] == {"chat": True}
    # Effective routes include project overrides and the default-profile
    # fallback (prose is the default): every route resolves to prose here.
    assert prose["used_by_routes"] == [
        "goethe",
        "dante",
        "chapter_write",
        "review",
        "source_extract",
        "revision",
        "search",
        "research",
    ]
    assert entries["critic"]["used_by_routes"] == []
    assert prose["last_test"] is None
    assert "last_embedding_test" not in prose
    assert "surface-secret" not in serialized
    assert "critic-secret" not in serialized


def test_surface_keeps_chat_and_embedding_capabilities_independent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    store = ModelProfileStore(tmp_path)
    bare = profile("bare", "chat-only")
    saved = store.save_profile(bare, api_key="secret")
    embedding = store.save_embedding_profile(
        embedding_profile("vector", "BAAI/bge-small-zh-v1.5", provider="local")
    )
    surface = store.surface()
    entry = surface["profiles"][0]
    embedding_entry = surface["embedding_profiles"][0]
    assert "embedding_model" not in saved
    assert entry["capabilities"] == {"chat": True}
    assert embedding["model"] == "BAAI/bge-small-zh-v1.5"
    assert embedding_entry["configured"] is True
    assert embedding_entry["active"] is True


def test_record_test_result_persists_without_touching_config_or_routes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    store = ModelProfileStore(tmp_path)
    store.save_profile(profile("prose", "writer-model"), api_key="test-credential-xyz")
    store.save_routes({"chapter_write": "prose"})
    credentials_before = store.credentials_path.read_bytes()
    routes_before = dict(store.load()["routes"])
    profile_before = {
        key: value for key, value in store.load()["profiles"][0].items() if key != "last_test"
    }

    store.record_test_result(
        "prose",
        "last_test",
        {
            "status": "failed",
            "tested_at": "2026-09-01T08:00:00Z",
            "latency_ms": 17,
            "provider": "openai",
            "resolved_model": "writer-model",
            "error_code": "MODEL_TEST_TIMEOUT",
            "failed_stage": None,
        },
    )

    entry = store.surface()["profiles"][0]
    assert entry["last_test"] == {
        "status": "failed",
        "tested_at": "2026-09-01T08:00:00Z",
        "latency_ms": 17,
        "provider": "openai",
        "resolved_model": "writer-model",
        "error_code": "MODEL_TEST_TIMEOUT",
        "failed_stage": None,
    }
    assert "last_embedding_test" not in entry
    assert store.credentials_path.read_bytes() == credentials_before
    assert store.load()["routes"] == routes_before
    profile_after = {
        key: value for key, value in store.load()["profiles"][0].items() if key != "last_test"
    }
    assert profile_after == profile_before
    assert "test-credential-xyz" not in store.profiles_path.read_text(encoding="utf-8")


def test_save_profile_preserves_test_records_and_rejects_forged_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    store = ModelProfileStore(tmp_path)
    store.save_profile(profile("prose", "writer-model"), api_key="secret")
    store.record_test_result(
        "prose",
        "last_test",
        {
            "status": "ok",
            "tested_at": "2026-09-01T08:00:00Z",
            "latency_ms": 5,
            "provider": "openai",
            "resolved_model": "writer-model",
            "error_code": None,
            "failed_stage": None,
        },
    )

    forged = {
        **profile("prose", "writer-model"),
        "label": "Renamed",
        "last_test": {"status": "ok", "tested_at": "1999-01-01T00:00:00Z"},
    }
    saved = store.save_profile(forged)

    assert saved["label"] == "Renamed"
    assert saved["last_test"]["tested_at"] == "2026-09-01T08:00:00Z"
    assert saved["last_test"]["latency_ms"] == 5


def test_delete_profile_preview_reports_impact_without_mutating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    store = ModelProfileStore(tmp_path)
    store.save_profile(profile("prose", "writer"), api_key="one")
    store.save_profile(profile("fallback", "backup"), api_key="two")
    store.save_routes({"chapter_write": "prose", "dante": "prose", "review": "fallback"})
    before = store.profiles_path.read_bytes()

    blocked = store.delete_profile_preview("prose")
    assert blocked["deletable"] is False
    assert blocked["blocking_reasons"] == ["MODEL_PROFILE_IN_USE"]
    assert blocked["used_by_routes"] == ["dante", "chapter_write"]
    assert blocked["routes_that_would_fail"] == ["dante", "chapter_write"]
    assert blocked["resulting_routes"] is None
    assert {item["id"] for item in blocked["fallback_candidates"]} == {"fallback"}
    assert blocked["fallback_candidates"][0]["configured"] is True

    allowed = store.delete_profile_preview("prose", fallback_id="fallback")
    assert allowed["deletable"] is True
    assert allowed["blocking_reasons"] == []
    assert allowed["routes_that_would_fail"] == []
    assert allowed["resulting_routes"]["chapter_write"] == "fallback"
    assert allowed["resulting_routes"]["dante"] == "fallback"
    assert allowed["resulting_routes"]["review"] == "fallback"

    # The preview is read-only: the store file is byte-identical afterwards.
    assert store.profiles_path.read_bytes() == before


def test_delete_profile_preview_blocking_reasons(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    store = ModelProfileStore(tmp_path)
    store.save_profile(profile("prose", "writer"), api_key="one")
    store.save_profile(profile("raw", "backup"))
    store.save_routes({"chapter_write": "prose"})

    same = store.delete_profile_preview("prose", fallback_id="prose")
    assert same["blocking_reasons"] == ["MODEL_PROFILE_FALLBACK_INVALID"]
    missing = store.delete_profile_preview("prose", fallback_id="ghost")
    assert missing["blocking_reasons"] == ["MODEL_PROFILE_FALLBACK_INVALID"]
    unconfigured = store.delete_profile_preview("prose", fallback_id="raw")
    assert unconfigured["blocking_reasons"] == ["MODEL_PROFILE_FALLBACK_UNCONFIGURED"]
    assert unconfigured["fallback_candidates"] == [
        {"id": "raw", "label": "Raw", "configured": False}
    ]

    store.delete_profile("raw")
    last = store.delete_profile_preview("prose", fallback_id="raw")
    assert last["deletable"] is False
    assert last["blocking_reasons"] == ["MODEL_PROFILE_LAST_PROFILE"]
    assert last["fallback_candidates"] == []

    with pytest.raises(ModelProfileError) as error:
        store.delete_profile_preview("ghost")
    assert error.value.code == "MODEL_PROFILE_NOT_FOUND"


def test_delete_profile_enforces_fallback_validity(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    store = ModelProfileStore(tmp_path)
    store.save_profile(profile("prose", "writer"), api_key="one")
    store.save_profile(profile("raw", "backup"))
    store.save_routes({"chapter_write": "prose"})

    with pytest.raises(ModelProfileError) as same:
        store.delete_profile("prose", fallback_id="prose")
    assert same.value.code == "MODEL_PROFILE_FALLBACK_INVALID"
    with pytest.raises(ModelProfileError) as missing:
        store.delete_profile("prose", fallback_id="ghost")
    assert missing.value.code == "MODEL_PROFILE_FALLBACK_INVALID"
    with pytest.raises(ModelProfileError) as unconfigured:
        store.delete_profile("prose", fallback_id="raw")
    assert unconfigured.value.code == "MODEL_PROFILE_FALLBACK_UNCONFIGURED"
    # Rejected deletes never rewrite the routes.
    assert store.load()["routes"]["chapter_write"] == "prose"


def test_save_routes_validates_entire_map_before_swapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    store = ModelProfileStore(tmp_path)
    store.save_profile(profile("prose", "writer"), api_key="one")
    store.save_profile(profile("critic", "reviewer"), api_key="two")
    store.save_routes({"chapter_write": "prose"})

    saved = store.save_routes({"review": "critic", "dante": "critic"})
    assert saved["routes"]["chapter_write"] == "prose"
    assert saved["impact"]["changed_routes"] == [
        {"route": "dante", "from": None, "to": "critic"},
        {"route": "review", "from": None, "to": "critic"},
    ]
    assert saved["impact"]["profiles_affected"] == ["critic"]

    before = dict(store.load()["routes"])
    with pytest.raises(ModelProfileError) as unknown_key:
        store.save_routes({"polishing": "prose"})
    assert unknown_key.value.code == "INVALID_MODEL_ROUTE"
    with pytest.raises(ModelProfileError) as unknown_profile:
        store.save_routes({"review": "ghost"})
    assert unknown_profile.value.code == "MODEL_PROFILE_NOT_FOUND"
    # A rejected save never partially applies.
    assert store.load()["routes"] == before


def test_save_routes_concurrent_swaps_never_mix(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    store = ModelProfileStore(tmp_path)
    store.save_profile(profile("alpha", "model-a"), api_key="a")
    store.save_profile(profile("beta", "model-b"), api_key="b")
    map_alpha = {
        key: "alpha"
        for key in (
            "goethe",
            "dante",
            "chapter_write",
            "review",
            "source_extract",
            "revision",
            "search",
            "research",
        )
    }
    map_beta = {key: "beta" for key in map_alpha}

    from concurrent.futures import ThreadPoolExecutor

    for _ in range(10):
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(store.save_routes, dict(map_alpha))
            second = pool.submit(store.save_routes, dict(map_beta))
            first.result()
            second.result()
        final = store.load()["routes"]
        assert final == map_alpha or final == map_beta
