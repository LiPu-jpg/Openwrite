"""Keep all automated QA out of the user's recent-project registry."""

import pytest


@pytest.fixture(autouse=True)
def isolated_project_registry(tmp_path, monkeypatch):
    # Automated regressions must never consume the developer's model credentials.
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("OPENWRITE_STUDIO_CONFIG_DIR", str(tmp_path / "test-preferences"))
    from tools import model_profiles
    profile_token = model_profiles._ACTIVE_PROFILE.set(None)
    from tools import project_registry, studio_application

    path = tmp_path / "test-registry.yaml"
    monkeypatch.setattr(project_registry, "default_registry_path", lambda: path)
    monkeypatch.setattr(studio_application, "default_registry_path", lambda: path)
    original = project_registry.ProjectRegistry.__init__

    def initialize(self, supplied_path=None, *, allow_ephemeral=False, **kwargs):
        # Explicitly supplied paths and policy remain the test's responsibility.
        original(self, kwargs.get("path", supplied_path) or path, allow_ephemeral=allow_ephemeral)

    monkeypatch.setattr(project_registry.ProjectRegistry, "__init__", initialize)
    yield
    model_profiles._ACTIVE_PROFILE.reset(profile_token)
