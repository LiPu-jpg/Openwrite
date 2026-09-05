"""Machine-local Studio preferences kept outside novel and framework repositories."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

MODEL_SETTING_KEYS = {
    "provider",
    "model",
    "api_format",
    "base_url",
    "context_tokens",
    "max_tokens",
    "remember_api_key",
}

MODEL_ENV_KEYS = {
    "provider": "LLM_PROVIDER",
    "model": "LLM_MODEL",
    "api_format": "LLM_API_FORMAT",
    "base_url": "LLM_BASE_URL",
    "context_tokens": "OPENWRITE_CONTEXT_TOKENS",
    "max_tokens": "LLM_MAX_TOKENS",
}

RESEARCH_SEARCH_PROVIDERS = ("bocha", "bing", "jina", "none")
RESEARCH_SEARCH_CREDENTIAL_ENV = {
    "bocha": "BOCHA_API_KEY",
    "jina": "JINA_API_KEY",
}


def default_studio_preferences_dir() -> Path:
    override = os.environ.get("OPENWRITE_STUDIO_CONFIG_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "posix" and Path("/System/Library/CoreServices").exists():
        return Path.home() / "Library" / "Application Support" / "OpenWrite"
    return Path.home() / ".config" / "openwrite"


class StudioModelSettingsStore:
    """Persist model metadata and a 0600 local credential outside all projects."""

    def __init__(self, directory: Path | None = None):
        self.directory = (directory or default_studio_preferences_dir()).resolve()
        self.settings_path = self.directory / "model-settings.json"
        self.credential_path = self.directory / ".model-api-key"

    def restore_environment(self) -> dict[str, Any]:
        settings = self.load_settings()
        for key, env_name in MODEL_ENV_KEYS.items():
            value = settings.get(key)
            if value not in {None, ""} and not os.environ.get(env_name, "").strip():
                os.environ[env_name] = str(value)
        if not os.environ.get("LLM_API_KEY", "").strip():
            credential = self.load_credential()
            if credential:
                os.environ["LLM_API_KEY"] = credential
        return settings

    def load_settings(self) -> dict[str, Any]:
        if not self.settings_path.is_file():
            return {}
        try:
            payload = json.loads(self.settings_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {key: value for key, value in payload.items() if key in MODEL_SETTING_KEYS}

    def save_settings(self, settings: dict[str, Any]) -> None:
        payload = {key: settings[key] for key in MODEL_SETTING_KEYS if key in settings}
        self._write_private(
            self.settings_path,
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        )

    def load_credential(self) -> str:
        if not self.credential_path.is_file():
            return ""
        try:
            return self.credential_path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            return ""

    def save_credential(self, api_key: str) -> None:
        secret = str(api_key or "").strip()
        if not secret:
            self.clear_credential()
            return
        self._write_private(self.credential_path, secret)

    def clear_credential(self) -> None:
        try:
            self.credential_path.unlink(missing_ok=True)
        except OSError:
            return

    @property
    def settings_persisted(self) -> bool:
        return self.settings_path.is_file()

    @property
    def credential_persisted(self) -> bool:
        return bool(self.load_credential())

    def _write_private(self, path: Path, content: str) -> None:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.directory.chmod(0o700)
        except OSError:
            pass
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.directory,
            delete=False,
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as handle:
            handle.write(content)
            temp_path = Path(handle.name)
        temp_path.chmod(0o600)
        temp_path.replace(path)
        path.chmod(0o600)


class StudioResearchSettingsStore:
    """Persist DeepResearch search settings and credentials.

    Credentials always stay in the machine-global prefs directory (0600 files,
    shared across workspaces). Non-secret settings (``search_provider``,
    ``remember_api_key``) may bind to a per-workspace file via
    :meth:`for_workspace`; reads then prefer the workspace file and fall back
    to the machine-global settings file, which keeps pre-workspace-scoping
    installs working unchanged.
    """

    def __init__(
        self, directory: Path | None = None, *, workspace_path: Path | None = None
    ):
        self.directory = (directory or default_studio_preferences_dir()).resolve()
        self.settings_path = self.directory / "research-settings.json"
        self.credentials_path = self.directory / ".research-search-credentials.json"
        self.workspace_path = (
            Path(workspace_path).resolve() if workspace_path is not None else None
        )
        self._session_credentials: dict[str, str] = {}

    def for_workspace(self, workspace_path: Path) -> StudioResearchSettingsStore:
        """Return a copy bound to a workspace settings file.

        The bound store shares the machine-global directory and session
        credentials; only non-secret settings reads/writes move to the
        workspace file.
        """
        bound = StudioResearchSettingsStore(self.directory, workspace_path=workspace_path)
        bound._session_credentials = self._session_credentials
        return bound

    def surface(self) -> dict[str, Any]:
        settings = self.load_settings()
        provider = str(settings.get("search_provider") or "bocha")
        providers = []
        for provider_id, label in (
            ("bocha", "博查"),
            ("bing", "Bing"),
            ("jina", "Jina"),
            ("none", "不联网"),
        ):
            requires_api_key = provider_id in RESEARCH_SEARCH_CREDENTIAL_ENV
            credential_configured = bool(self.credential(provider_id))
            providers.append(
                {
                    "id": provider_id,
                    "label": label,
                    "requires_api_key": requires_api_key,
                    "configured": not requires_api_key or credential_configured,
                    "credential_configured": credential_configured,
                }
            )
        return {"search_provider": provider, "search_providers": providers}

    def load_settings(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.workspace_path is not None:
            payload = self._read_json(self.workspace_path)
        if not payload:
            payload = self._read_json(self.settings_path)
        provider = str(payload.get("search_provider") or "").strip().lower()
        remember = payload.get("remember_api_key")
        return {
            "search_provider": (
                provider if provider in RESEARCH_SEARCH_PROVIDERS else "bocha"
            ),
            "remember_api_key": True if remember is None else bool(remember),
        }

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        provider = str(payload.get("search_provider") or "bocha").strip().lower()
        if provider not in RESEARCH_SEARCH_PROVIDERS:
            raise ValueError("深度研究搜索提供方无效")
        api_key = str(payload.get("search_api_key") or "").strip()
        remember = bool(payload.get("remember_api_key", True))
        clear_api_key = bool(payload.get("clear_api_key", False))
        credentials = self._credentials()
        if clear_api_key:
            self._session_credentials.pop(provider, None)
            credentials.pop(provider, None)
        elif api_key:
            self._session_credentials[provider] = api_key
            if remember:
                credentials[provider] = api_key
            else:
                credentials.pop(provider, None)
        elif not remember:
            self._session_credentials.pop(provider, None)
            credentials.pop(provider, None)
        self._write_private_json(self.credentials_path, credentials)
        self._write_private_json(
            self.workspace_path or self.settings_path,
            {"search_provider": provider, "remember_api_key": remember},
        )
        return self.surface()

    def credential(self, provider: str) -> str:
        normalized = str(provider or "").strip().lower()
        env_name = RESEARCH_SEARCH_CREDENTIAL_ENV.get(normalized, "")
        return (
            self._session_credentials.get(normalized, "")
            or self._credentials().get(normalized, "")
            or (os.environ.get(env_name, "").strip() if env_name else "")
        )

    def environment(self, provider: str) -> dict[str, str]:
        normalized = str(provider or "").strip().lower()
        if normalized not in RESEARCH_SEARCH_PROVIDERS:
            raise ValueError("深度研究搜索提供方无效")
        env_name = RESEARCH_SEARCH_CREDENTIAL_ENV.get(normalized, "")
        credential = self.credential(normalized)
        if env_name and not credential:
            label = "博查" if normalized == "bocha" else "Jina"
            raise ValueError(f"请先在深度研究 API 设置中配置 {label} API Key")
        return {env_name: credential} if env_name else {}

    def _credentials(self) -> dict[str, str]:
        payload = self._read_json(self.credentials_path)
        return {
            key: str(payload.get(key) or "").strip()
            for key in RESEARCH_SEARCH_CREDENTIAL_ENV
            if str(payload.get(key) or "").strip()
        }

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_private_json(self, path: Path, payload: dict[str, Any]) -> None:
        directory = path.parent
        directory.mkdir(parents=True, exist_ok=True)
        if directory == self.directory:
            try:
                self.directory.chmod(0o700)
            except OSError:
                pass
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=directory,
            delete=False,
            prefix=f".{path.name}.",
            suffix=".tmp",
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            temp_path = Path(handle.name)
        temp_path.chmod(0o600)
        temp_path.replace(path)
        path.chmod(0o600)
