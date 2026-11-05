"""A model route must never silently resolve to a different profile.

Project-level routes are read straight out of ``novel_config.yaml``, which
``save_routes`` never validated, so a restored archive or a hand edit can name a
profile that does not exist on this machine. Falling back to the default profile
would swap both the model and the API key with no signal to the author.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.model_profiles import ModelProfileError, ModelProfileStore


def _store(tmp_path: Path) -> ModelProfileStore:
    store = ModelProfileStore(tmp_path)
    store.save_profile(
        {"id": "alpha", "provider": "openai", "model": "alpha-model"}, api_key="alpha-secret"
    )
    store.save_profile(
        {"id": "beta", "provider": "openai", "model": "beta-model"}, api_key="beta-secret"
    )
    store.save_routes({"goethe": "beta"})
    return store


def test_a_configured_route_resolves_to_its_own_profile(tmp_path: Path):
    store = _store(tmp_path)
    resolved = store.resolve("goethe")
    assert resolved["id"] == "beta"
    assert resolved["model"] == "beta-model"
    assert resolved["api_key"] == "beta-secret"


def test_a_route_naming_a_missing_profile_is_refused_not_substituted(tmp_path: Path):
    store = _store(tmp_path)
    # What a restored archive or hand-edited novel_config.yaml can produce.
    ghost = {"goethe": "ghost-profile"}
    with pytest.raises(ModelProfileError) as refused:
        store.resolve("goethe", ghost)
    assert refused.value.code == "MODEL_PROFILE_NOT_FOUND"


def test_an_unresolvable_route_is_visible_in_the_surface(tmp_path: Path):
    store = _store(tmp_path)
    surface = store.surface({"goethe": "ghost-profile"})
    assert surface["unresolved_routes"] == {"goethe": "ghost-profile"}
    # `used_by_routes` must not claim the route belongs to a real profile.
    for profile in surface["profiles"]:
        assert "goethe" not in profile["used_by_routes"]


def test_a_healthy_surface_reports_no_unresolved_routes(tmp_path: Path):
    store = _store(tmp_path)
    assert store.surface()["unresolved_routes"] == {}
