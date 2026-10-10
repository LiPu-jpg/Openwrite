"""Regression tests for ``auto:cheapest`` / ``auto:popular`` model selection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import tools.model_profiles as model_profiles
from tools.model_profiles import ModelProfileError, ModelProfileStore

OPENROUTER_BASE = "https://openrouter.ai/api/v1"


def _seed_store(tmp_path: Path, model: str, base_url: str = OPENROUTER_BASE) -> ModelProfileStore:
    (tmp_path / "model-profiles.json").write_text(
        json.dumps(
            {
                "version": 1,
                "default_profile_id": "auto-p",
                "profiles": [
                    {
                        "id": "auto-p",
                        "label": "auto",
                        "provider": "openai",
                        "base_url": base_url,
                        "model": model,
                        "api_format": "chat",
                        "context_tokens": 128000,
                        "max_output_tokens": 32000,
                        "temperature": 0.7,
                        "timeout_seconds": 120.0,
                        "credential_ref": "key_or",
                    }
                ],
                "routes": {},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / ".model-credentials.json").write_text(
        json.dumps({"key_or": "sk-test"}), encoding="utf-8"
    )
    return ModelProfileStore(directory=tmp_path)


class _Resp:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_Resp":
        return self

    def __exit__(self, *args: object) -> bool:
        return False


def _catalog(*models: dict) -> dict:
    return {"data": list(models)}


def _model(
    model_id: str,
    prompt: str,
    completion: str,
    *,
    modality: str = "text->text",
    context: int = 131072,
    max_completion: int = 16384,
) -> dict:
    return {
        "id": model_id,
        "context_length": context,
        "architecture": {"modality": modality},
        "pricing": {"prompt": prompt, "completion": completion},
        "top_provider": {"max_completion_tokens": max_completion},
    }


def test_cheapest_picks_lowest_priced_valid_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _seed_store(tmp_path, "auto:cheapest")
    catalog = _catalog(
        _model("vendor/good", "0.5", "0.5"),
        _model("vendor/best", "0.1", "0.2"),
        _model("vendor/free:free", "0", "0"),
        _model("vendor/zero-priced", "0", "0"),
        _model("vendor/batch:batch", "0.01", "0.01"),
        _model("vendor/image", "0.01", "0.01", modality="text+image->image"),
        _model("vendor/tiny-context", "0.01", "0.01", context=8000),
        _model("vendor/tiny-output", "0.01", "0.01", max_completion=2048),
        _model("vendor/dynamic", "-1", "-1"),
    )
    monkeypatch.setattr(
        model_profiles.urllib.request, "urlopen", lambda *a, **k: _Resp(catalog)
    )
    resolved = store.resolve_profile("auto-p", operation="search")
    assert resolved["model"] == "vendor/best"
    assert resolved["auto_select"] == {"strategy": "cheapest", "resolved": "vendor/best"}


def test_cheapest_uses_openrouter_live_rules(tmp_path: Path) -> None:
    """With the real on-disk cache from a previous fetch, no network is needed."""
    store = _seed_store(tmp_path, "auto:cheapest")
    cache_path = tmp_path / ".model-auto-select-cache.json"
    cache_path.write_text(
        json.dumps(
            {
                OPENROUTER_BASE: {
                    "fetched_at": 9999999999.0,  # far future: never expires
                    "models": [_model("vendor/cached-best", "0.2", "0.3")],
                }
            }
        ),
        encoding="utf-8",
    )
    resolved = store.resolve_profile("auto-p", operation="search")
    assert resolved["model"] == "vendor/cached-best"


def test_cheapest_caches_catalog_between_resolves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _seed_store(tmp_path, "auto:cheapest")
    calls = {"count": 0}

    def fake_urlopen(*args: object, **kwargs: object) -> _Resp:
        calls["count"] += 1
        return _Resp(_catalog(_model("vendor/only", "0.3", "0.3")))

    monkeypatch.setattr(model_profiles.urllib.request, "urlopen", fake_urlopen)
    first = store.resolve_profile("auto-p", operation="search")
    second = store.resolve_profile("auto-p", operation="search")
    assert calls["count"] == 1
    assert first["model"] == second["model"] == "vendor/only"
    cache = json.loads((tmp_path / ".model-auto-select-cache.json").read_text())
    assert OPENROUTER_BASE in cache


def test_cheapest_falls_back_to_stale_cache_on_fetch_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _seed_store(tmp_path, "auto:cheapest")
    (tmp_path / ".model-auto-select-cache.json").write_text(
        json.dumps(
            {OPENROUTER_BASE: {"fetched_at": 1.0, "models": [_model("vendor/stale", "0.9", "0.9")]}}
        ),
        encoding="utf-8",
    )

    def boom(*args: object, **kwargs: object) -> _Resp:
        raise OSError("network down")

    monkeypatch.setattr(model_profiles.urllib.request, "urlopen", boom)
    resolved = store.resolve_profile("auto-p", operation="search")
    assert resolved["model"] == "vendor/stale"


def test_cheapest_raises_when_catalog_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _seed_store(tmp_path, "auto:cheapest")

    def boom(*args: object, **kwargs: object) -> _Resp:
        raise OSError("network down")

    monkeypatch.setattr(model_profiles.urllib.request, "urlopen", boom)
    with pytest.raises(ModelProfileError) as excinfo:
        store.resolve_profile("auto-p", operation="search")
    assert excinfo.value.code == "MODEL_CATALOG_UNAVAILABLE"


def test_popular_resolves_to_openrouter_auto(tmp_path: Path) -> None:
    store = _seed_store(tmp_path, "auto:popular")
    resolved = store.resolve_profile("auto-p", operation="search")
    assert resolved["model"] == "openrouter/auto"
    assert resolved["auto_select"]["strategy"] == "popular"


def test_popular_rejects_non_openrouter_base_url(tmp_path: Path) -> None:
    store = _seed_store(tmp_path, "auto:popular", base_url="https://api.deepseek.com")
    with pytest.raises(ModelProfileError) as excinfo:
        store.resolve_profile("auto-p", operation="search")
    assert excinfo.value.code == "AUTO_SELECT_UNSUPPORTED"


def test_unknown_strategy_rejected(tmp_path: Path) -> None:
    store = _seed_store(tmp_path, "auto:bogus")
    with pytest.raises(ModelProfileError) as excinfo:
        store.resolve_profile("auto-p", operation="search")
    assert excinfo.value.code == "INVALID_AUTO_SELECT_STRATEGY"


def test_static_model_profiles_unaffected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _seed_store(tmp_path, "deepseek/deepseek-chat")
    monkeypatch.setattr(
        model_profiles.urllib.request,
        "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not fetch")),
    )
    resolved = store.resolve_profile("auto-p", operation="search")
    assert resolved["model"] == "deepseek/deepseek-chat"
    assert "auto_select" not in resolved
