"""Machine-local named model profiles and operation routing."""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from tools.embedding_runtime import (
    DEFAULT_CLOUD_MODEL,
    DEFAULT_LOCAL_DIMENSION,
    DEFAULT_LOCAL_MAX_TOKENS,
    DEFAULT_LOCAL_MODEL,
    EmbeddingRuntimeError,
    normalize_embedding_provider,
)
from tools.llm.model_catalog import (
    MAX_CONTEXT_TOKENS,
    MAX_OUTPUT_TOKENS,
    model_preset_catalog,
)
from tools.studio_preferences import StudioModelSettingsStore, default_studio_preferences_dir

PROFILE_VERSION = 1
ROUTE_KEYS = (
    "goethe",
    "dante",
    "chapter_write",
    "review",
    "source_extract",
    "revision",
    "search",
    "research",
)
PROFILE_FIELDS = (
    "id",
    "label",
    "provider",
    "base_url",
    "model",
    "api_format",
    "context_tokens",
    "max_output_tokens",
    "temperature",
    "timeout_seconds",
    "thinking_modes",
    "credential_ref",
    "credential_updated_at",
    "embedding_provider",
    "embedding_base_url",
    "embedding_model",
    "embedding_dimension",
    "embedding_max_tokens",
    "embedding_credential_ref",
    "embedding_credential_updated_at",
    "search_mode",
)

_ACTIVE_PROFILE: ContextVar[dict[str, Any] | None] = ContextVar(
    "openwrite_active_model_profile",
    default=None,
)
_ACTIVE_SEARCH_PROFILE: ContextVar[dict[str, Any] | None] = ContextVar(
    "openwrite_active_search_model_profile",
    default=None,
)


class ModelProfileError(RuntimeError):
    def __init__(self, message: str, *, code: str = "MODEL_PROFILE_FAILED"):
        super().__init__(message)
        self.code = code


class ModelProfileStore:
    """Persist profile metadata and credentials outside every project."""

    def __init__(self, directory: Path | None = None):
        self.directory = (directory or default_studio_preferences_dir()).resolve()
        self.profiles_path = self.directory / "model-profiles.json"
        self.credentials_path = self.directory / ".model-credentials.json"
        self.legacy = StudioModelSettingsStore(self.directory)
        self._session_credentials: dict[str, str] = {}

    def load(self) -> dict[str, Any]:
        payload = self._read_json(self.profiles_path)
        if payload:
            profiles = payload.get("profiles")
            routes = payload.get("routes")
            return {
                "version": PROFILE_VERSION,
                "default_profile_id": str(payload.get("default_profile_id") or "default"),
                "profiles": [
                    self._profile_metadata(item) for item in profiles if isinstance(item, dict)
                ]
                if isinstance(profiles, list)
                else [],
                "routes": self._routes(routes),
            }
        legacy = self.legacy.load_settings()
        if (
            not legacy
            and not os.environ.get("LLM_MODEL", "").strip()
            and not os.environ.get("LLM_API_KEY", "").strip()
        ):
            return {
                "version": PROFILE_VERSION,
                "default_profile_id": "default",
                "profiles": [],
                "routes": {},
            }
        profile = {
            "id": "default",
            "label": "默认模型",
            "provider": str(legacy.get("provider") or os.environ.get("LLM_PROVIDER") or "openai"),
            "base_url": str(legacy.get("base_url") or os.environ.get("LLM_BASE_URL") or ""),
            "model": str(legacy.get("model") or os.environ.get("LLM_MODEL") or "gpt-4o-mini"),
            "api_format": str(
                legacy.get("api_format") or os.environ.get("LLM_API_FORMAT") or "chat"
            ),
            "context_tokens": int(
                legacy.get("context_tokens") or os.environ.get("OPENWRITE_CONTEXT_TOKENS") or 64000
            ),
            "max_output_tokens": int(
                legacy.get("max_tokens") or os.environ.get("LLM_MAX_TOKENS") or 24000
            ),
            "temperature": float(os.environ.get("LLM_TEMPERATURE", "0.7")),
            "timeout_seconds": float(os.environ.get("LLM_TIMEOUT_SECONDS", "120")),
            "credential_ref": "key_default",
            "embedding_provider": os.environ.get(
                "OPENWRITE_LIGHTRAG_EMBEDDING_PROVIDER", "openai"
            ).strip(),
            "embedding_base_url": os.environ.get(
                "OPENWRITE_LIGHTRAG_EMBEDDING_BASE_URL", ""
            ).strip(),
            "embedding_model": os.environ.get(
                "OPENWRITE_LIGHTRAG_EMBEDDING_MODEL", DEFAULT_CLOUD_MODEL
            ).strip(),
            "embedding_dimension": 1536,
            "embedding_max_tokens": 8192,
            "embedding_credential_ref": "embedding_key_default",
            "search_mode": "vector",
        }
        credential = self.legacy.load_credential()
        if credential:
            self._session_credentials["key_default"] = credential
        return {
            "version": PROFILE_VERSION,
            "default_profile_id": "default",
            "profiles": [profile],
            "routes": {key: "default" for key in ROUTE_KEYS},
        }

    def surface(self, project_routes: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = self.load()
        persisted_credentials = self._credentials()
        profiles = []
        for profile in payload["profiles"]:
            credential_ref = str(profile.get("credential_ref") or "")
            configured = bool(
                self._session_credentials.get(credential_ref)
                or persisted_credentials.get(credential_ref)
                or (profile["id"] == "default" and os.environ.get("LLM_API_KEY", "").strip())
            )
            embedding_credential_ref = str(profile.get("embedding_credential_ref") or "")
            separate_embedding_key = bool(
                self._session_credentials.get(embedding_credential_ref)
                or persisted_credentials.get(embedding_credential_ref)
                or (
                    profile["id"] == "default"
                    and os.environ.get("OPENWRITE_LIGHTRAG_EMBEDDING_API_KEY", "").strip()
                )
            )
            profiles.append(
                {
                    **profile,
                    "configured": configured,
                    "embedding_configured": (
                        profile.get("embedding_provider") == "local"
                        or separate_embedding_key
                        or configured
                    ),
                    "embedding_key_configured": separate_embedding_key,
                }
            )
        routes = dict(payload["routes"])
        routes.update(self._routes(project_routes))
        default_id = str(payload.get("default_profile_id") or "default")
        for key in ROUTE_KEYS:
            routes.setdefault(key, default_id)
        return {
            "schema_version": "openwrite.model-profile.v1",
            "profiles": profiles,
            "presets": model_preset_catalog(),
            "routes": routes,
            "default_profile_id": default_id,
            "legacy_mapped": not self.profiles_path.is_file() and bool(profiles),
        }

    def save_profile(
        self,
        profile: dict[str, Any],
        *,
        api_key: str = "",
        embedding_api_key: str = "",
        remember_api_key: bool = True,
    ) -> dict[str, Any]:
        payload = self.load()
        metadata = self._profile_metadata(profile)
        profile_id = metadata["id"]
        existing = next(
            (item for item in payload["profiles"] if item["id"] == profile_id),
            {},
        )
        metadata.pop("credential_updated_at", None)
        metadata.pop("embedding_credential_updated_at", None)
        credential_ref = str(metadata.get("credential_ref") or f"key_{profile_id}")
        metadata["credential_ref"] = credential_ref
        embedding_credential_ref = str(
            metadata.get("embedding_credential_ref") or f"embedding_key_{profile_id}"
        )
        metadata["embedding_credential_ref"] = embedding_credential_ref
        secret = str(api_key or "").strip()
        if existing.get("credential_ref") == credential_ref and existing.get(
            "credential_updated_at"
        ):
            metadata["credential_updated_at"] = existing["credential_updated_at"]
        if secret:
            metadata["credential_updated_at"] = self._utc_timestamp()
            self._session_credentials[credential_ref] = secret
            credentials = self._credentials()
            if remember_api_key:
                credentials[credential_ref] = secret
            else:
                credentials.pop(credential_ref, None)
            self._write_json(self.credentials_path, credentials)
        elif not remember_api_key:
            self._session_credentials.pop(credential_ref, None)
            credentials = self._credentials()
            credentials.pop(credential_ref, None)
            self._write_json(self.credentials_path, credentials)
            metadata.pop("credential_updated_at", None)
        embedding_secret = str(embedding_api_key or "").strip()
        if existing.get("embedding_credential_ref") == embedding_credential_ref and existing.get(
            "embedding_credential_updated_at"
        ):
            metadata["embedding_credential_updated_at"] = existing[
                "embedding_credential_updated_at"
            ]
        if embedding_secret:
            metadata["embedding_credential_updated_at"] = self._utc_timestamp()
            self._session_credentials[embedding_credential_ref] = embedding_secret
            credentials = self._credentials()
            if remember_api_key:
                credentials[embedding_credential_ref] = embedding_secret
            else:
                credentials.pop(embedding_credential_ref, None)
            self._write_json(self.credentials_path, credentials)
        elif not remember_api_key:
            self._session_credentials.pop(embedding_credential_ref, None)
            credentials = self._credentials()
            credentials.pop(embedding_credential_ref, None)
            self._write_json(self.credentials_path, credentials)
            metadata.pop("embedding_credential_updated_at", None)
        profiles = [item for item in payload["profiles"] if item["id"] != profile_id]
        profiles.append(metadata)
        payload["profiles"] = sorted(profiles, key=lambda item: item["id"])
        if str(payload.get("default_profile_id") or "") not in {item["id"] for item in profiles}:
            payload["default_profile_id"] = profile_id
        self._write_payload(payload)
        return metadata

    def save_routes(self, routes: dict[str, Any]) -> dict[str, str]:
        payload = self.load()
        profile_ids = {item["id"] for item in payload["profiles"]}
        normalized = self._routes(routes)
        missing = sorted(set(normalized.values()) - profile_ids)
        if missing:
            raise ModelProfileError(
                f"模型档案不存在: {', '.join(missing)}",
                code="MODEL_PROFILE_NOT_FOUND",
            )
        payload["routes"] = {**payload["routes"], **normalized}
        self._write_payload(payload)
        return payload["routes"]

    def test_candidate(self, profile: dict[str, Any], *, api_key: str = "") -> dict[str, Any]:
        """Resolve a connection-test candidate without exposing stored credentials."""
        metadata = self._profile_metadata(profile)
        credential_ref = str(metadata.get("credential_ref") or "")
        secret = (
            str(api_key or "").strip()
            or self._session_credentials.get(credential_ref, "")
            or self._credentials().get(credential_ref, "")
            or (os.environ.get("LLM_API_KEY", "").strip() if metadata["id"] == "default" else "")
        )
        if not secret:
            raise ModelProfileError(
                f"模型档案 {metadata['label']} 缺少 API Key",
                code="MODEL_CREDENTIAL_MISSING",
            )
        return {**metadata, "api_key": secret}

    def test_embedding_candidate(
        self,
        profile: dict[str, Any],
        *,
        api_key: str = "",
        embedding_api_key: str = "",
    ) -> dict[str, Any]:
        """Resolve an embedding probe without requiring a chat-model request."""
        metadata = self._profile_metadata(profile)
        if metadata["embedding_provider"] == "local":
            return {**metadata, "embedding_api_key": ""}

        credential_ref = str(metadata.get("credential_ref") or "")
        embedding_credential_ref = str(metadata.get("embedding_credential_ref") or "")
        secret = (
            str(embedding_api_key or "").strip()
            or str(api_key or "").strip()
            or self._session_credentials.get(embedding_credential_ref, "")
            or self._credentials().get(embedding_credential_ref, "")
            or self._session_credentials.get(credential_ref, "")
            or self._credentials().get(credential_ref, "")
            or (
                os.environ.get("OPENWRITE_LIGHTRAG_EMBEDDING_API_KEY", "").strip()
                or os.environ.get("LLM_API_KEY", "").strip()
                if metadata["id"] == "default"
                else ""
            )
        )
        if not secret:
            raise ModelProfileError(
                f"模型档案 {metadata['label']} 缺少 Embedding API Key",
                code="MODEL_CREDENTIAL_MISSING",
            )
        return {**metadata, "embedding_api_key": secret}

    def delete_profile(
        self,
        profile_id: str,
        *,
        fallback_id: str = "",
        project_routes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = self.load()
        profile_ids = {item["id"] for item in payload["profiles"]}
        if profile_id not in profile_ids:
            raise ModelProfileError("模型档案不存在", code="MODEL_PROFILE_NOT_FOUND")
        if len(profile_ids) == 1:
            raise ModelProfileError(
                "至少保留一个模型档案",
                code="MODEL_PROFILE_LAST_PROFILE",
            )
        routes = {**payload["routes"], **self._routes(project_routes)}
        referenced = sorted(key for key, value in routes.items() if value == profile_id)
        if referenced:
            if not fallback_id or fallback_id == profile_id or fallback_id not in profile_ids:
                raise ModelProfileError(
                    "档案正在被任务路由引用，请选择回退档案",
                    code="MODEL_PROFILE_IN_USE",
                )
            routes = {
                key: fallback_id if value == profile_id else value for key, value in routes.items()
            }
        removed = next(item for item in payload["profiles"] if item["id"] == profile_id)
        payload["profiles"] = [item for item in payload["profiles"] if item["id"] != profile_id]
        if payload.get("default_profile_id") == profile_id:
            payload["default_profile_id"] = fallback_id or (
                payload["profiles"][0]["id"] if payload["profiles"] else "default"
            )
        payload["routes"] = {key: value for key, value in routes.items() if key in ROUTE_KEYS}
        credential_ref = str(removed.get("credential_ref") or "")
        self._session_credentials.pop(credential_ref, None)
        embedding_credential_ref = str(removed.get("embedding_credential_ref") or "")
        self._session_credentials.pop(embedding_credential_ref, None)
        credentials = self._credentials()
        credentials.pop(credential_ref, None)
        credentials.pop(embedding_credential_ref, None)
        self._write_json(self.credentials_path, credentials)
        self._write_payload(payload)
        return {"deleted": profile_id, "routes": payload["routes"]}

    def resolve(
        self,
        operation: str,
        project_routes: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if operation not in ROUTE_KEYS:
            raise ModelProfileError("模型任务路由无效", code="INVALID_MODEL_ROUTE")
        surface = self.surface(project_routes)
        routes = surface["routes"]
        profile_id = str(routes.get(operation) or surface["default_profile_id"])
        profile = next(
            (item for item in surface["profiles"] if item["id"] == profile_id),
            None,
        )
        if profile is None:
            profile = next(
                (
                    item
                    for item in surface["profiles"]
                    if item["id"] == surface["default_profile_id"]
                ),
                None,
            )
        if profile is None:
            raise ModelProfileError("尚未配置模型档案", code="MODEL_PROFILE_NOT_CONFIGURED")
        credential_ref = str(profile.get("credential_ref") or "")
        api_key = (
            self._session_credentials.get(credential_ref)
            or self._credentials().get(credential_ref)
            or (os.environ.get("LLM_API_KEY", "").strip() if profile["id"] == "default" else "")
        )
        vector_search_without_chat = (
            operation == "search" and profile.get("search_mode") == "vector"
        )
        if not api_key and not vector_search_without_chat:
            raise ModelProfileError(
                f"模型档案 {profile['label']} 缺少 API Key",
                code="MODEL_CREDENTIAL_MISSING",
            )
        embedding_credential_ref = str(profile.get("embedding_credential_ref") or "")
        embedding_api_key = (
            self._session_credentials.get(embedding_credential_ref)
            or self._credentials().get(embedding_credential_ref)
            or (
                os.environ.get("OPENWRITE_LIGHTRAG_EMBEDDING_API_KEY", "").strip()
                if profile["id"] == "default"
                else ""
            )
        )
        return {
            **profile,
            "api_key": api_key,
            "embedding_api_key": embedding_api_key,
            "operation": operation,
        }

    def resolve_profile(self, profile_id: str, *, operation: str) -> dict[str, Any]:
        """Resolve one named profile for a run-scoped operation without changing routes."""
        if operation not in ROUTE_KEYS:
            raise ModelProfileError("模型任务路由无效", code="INVALID_MODEL_ROUTE")
        clean_id = str(profile_id or "").strip()
        surface = self.surface()
        profile = next(
            (item for item in surface["profiles"] if item["id"] == clean_id),
            None,
        )
        if profile is None:
            raise ModelProfileError(
                f"模型档案不存在: {clean_id}",
                code="MODEL_PROFILE_NOT_FOUND",
            )
        credential_ref = str(profile.get("credential_ref") or "")
        api_key = (
            self._session_credentials.get(credential_ref)
            or self._credentials().get(credential_ref)
            or (os.environ.get("LLM_API_KEY", "").strip() if profile["id"] == "default" else "")
        )
        if not api_key:
            raise ModelProfileError(
                f"模型档案 {profile['label']} 缺少 API Key",
                code="MODEL_CREDENTIAL_MISSING",
            )
        return {**profile, "api_key": api_key, "operation": operation}

    @staticmethod
    def _profile_metadata(value: dict[str, Any]) -> dict[str, Any]:
        profile_id = str(value.get("id") or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}", profile_id):
            raise ModelProfileError("模型档案 ID 格式无效", code="INVALID_MODEL_PROFILE")
        provider = str(value.get("provider") or "openai").strip().lower()
        if provider not in {"openai", "anthropic", "custom"}:
            raise ModelProfileError("模型提供方无效", code="INVALID_MODEL_PROFILE")
        api_format = str(value.get("api_format") or "chat").strip().lower()
        if api_format not in {"chat", "responses"}:
            raise ModelProfileError("API 格式无效", code="INVALID_MODEL_PROFILE")
        model = str(value.get("model") or "").strip()
        if not model or len(model) > 120:
            raise ModelProfileError(
                "模型名称不能为空且不能超过 120 字",
                code="INVALID_MODEL_PROFILE",
            )
        base_url = str(value.get("base_url") or "").strip().rstrip("/")
        if provider == "custom" and not base_url:
            raise ModelProfileError(
                "自定义模型必须填写 Base URL",
                code="INVALID_MODEL_PROFILE",
            )
        if not base_url:
            base_url = (
                "https://api.anthropic.com"
                if provider == "anthropic"
                else "https://api.openai.com/v1"
            )
        parsed_url = urlparse(base_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise ModelProfileError(
                "Base URL 必须是有效的 HTTP(S) 地址",
                code="INVALID_MODEL_PROFILE",
            )
        context_tokens = ModelProfileStore._bounded_number(
            value.get("context_tokens"),
            64000,
            12000,
            MAX_CONTEXT_TOKENS,
            int,
            "上下文预算",
        )
        max_output_tokens = ModelProfileStore._bounded_number(
            value.get("max_output_tokens", value.get("max_tokens")),
            24000,
            256,
            MAX_OUTPUT_TOKENS,
            int,
            "最大输出",
        )
        if max_output_tokens >= context_tokens:
            raise ModelProfileError(
                "最大输出必须小于上下文预算，以便为输入保留空间",
                code="INVALID_MODEL_PROFILE",
            )
        temperature = ModelProfileStore._bounded_number(
            value.get("temperature"), 0.7, 0, 2, float, "温度"
        )
        timeout_seconds = ModelProfileStore._bounded_number(
            value.get("timeout_seconds"), 120, 1, 1800, float, "超时"
        )
        try:
            embedding_provider = normalize_embedding_provider(
                value.get("embedding_provider") or "openai"
            )
        except EmbeddingRuntimeError as exc:
            raise ModelProfileError(str(exc), code="INVALID_MODEL_PROFILE") from exc
        embedding_base_url = str(value.get("embedding_base_url") or "").strip().rstrip("/")
        if embedding_provider == "openai" and embedding_base_url:
            parsed_embedding_url = urlparse(embedding_base_url)
            if (
                parsed_embedding_url.scheme not in {"http", "https"}
                or not parsed_embedding_url.netloc
            ):
                raise ModelProfileError(
                    "Embedding Base URL 必须是有效的 HTTP(S) 地址",
                    code="INVALID_MODEL_PROFILE",
                )
        embedding_model = str(
            value.get("embedding_model")
            or (DEFAULT_LOCAL_MODEL if embedding_provider == "local" else DEFAULT_CLOUD_MODEL)
        ).strip()
        if not embedding_model or len(embedding_model) > 120:
            raise ModelProfileError(
                "Embedding 模型名称不能为空且不能超过 120 字",
                code="INVALID_MODEL_PROFILE",
            )
        embedding_dimension = ModelProfileStore._bounded_number(
            value.get("embedding_dimension"),
            DEFAULT_LOCAL_DIMENSION if embedding_provider == "local" else 1536,
            1,
            65536,
            int,
            "Embedding 维度",
        )
        embedding_max_tokens = ModelProfileStore._bounded_number(
            value.get("embedding_max_tokens"),
            DEFAULT_LOCAL_MAX_TOKENS if embedding_provider == "local" else 8192,
            256,
            131072,
            int,
            "Embedding Token 上限",
        )
        search_mode = str(value.get("search_mode") or "vector").strip().lower()
        if search_mode not in {"vector", "graph"}:
            raise ModelProfileError("检索策略无效", code="INVALID_MODEL_PROFILE")
        raw_thinking_modes = value.get("thinking_modes")
        if raw_thinking_modes is None:
            thinking_modes: dict[str, str] = {}
        elif isinstance(raw_thinking_modes, dict):
            thinking_modes = {
                str(operation): str(mode).strip().lower()
                for operation, mode in raw_thinking_modes.items()
                if str(operation) in {"chapter_write", "review", "revision"}
                and str(mode).strip().lower() in {"enabled", "disabled", "omit"}
            }
        else:
            raise ModelProfileError("thinking_modes 必须是对象", code="INVALID_MODEL_PROFILE")
        metadata = {
            "id": profile_id,
            "label": str(value.get("label") or profile_id).strip()[:80],
            "provider": provider,
            "base_url": base_url,
            "model": model,
            "api_format": api_format,
            "context_tokens": context_tokens,
            "max_output_tokens": max_output_tokens,
            "temperature": temperature,
            "timeout_seconds": timeout_seconds,
            "thinking_modes": thinking_modes,
            "credential_ref": str(value.get("credential_ref") or f"key_{profile_id}"),
            "embedding_provider": embedding_provider,
            "embedding_base_url": embedding_base_url,
            "embedding_model": embedding_model,
            "embedding_dimension": embedding_dimension,
            "embedding_max_tokens": embedding_max_tokens,
            "embedding_credential_ref": str(
                value.get("embedding_credential_ref") or f"embedding_key_{profile_id}"
            ),
            "search_mode": search_mode,
        }
        for field in ("credential_updated_at", "embedding_credential_updated_at"):
            timestamp = ModelProfileStore._normalized_timestamp(value.get(field))
            if timestamp:
                metadata[field] = timestamp
        return metadata

    @staticmethod
    def _utc_timestamp() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

    @staticmethod
    def _normalized_timestamp(value: Any) -> str:
        timestamp = str(value or "").strip()
        if not timestamp or len(timestamp) > 40 or not timestamp.endswith("Z"):
            return ""
        try:
            parsed = datetime.fromisoformat(timestamp[:-1] + "+00:00")
        except ValueError:
            return ""
        if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
            return ""
        return timestamp

    @staticmethod
    def _bounded_number(
        value: Any,
        default: int | float,
        minimum: int | float,
        maximum: int | float,
        parser: type[int] | type[float],
        label: str,
    ) -> int | float:
        try:
            parsed = parser(default if value in {None, ""} else value)
        except (TypeError, ValueError) as exc:
            raise ModelProfileError(f"{label}格式无效", code="INVALID_MODEL_PROFILE") from exc
        if not minimum <= parsed <= maximum:
            raise ModelProfileError(
                f"{label}必须在 {minimum}-{maximum} 之间",
                code="INVALID_MODEL_PROFILE",
            )
        return parsed

    @staticmethod
    def _routes(value: Any) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        return {
            key: str(value[key]).strip() for key in ROUTE_KEYS if str(value.get(key) or "").strip()
        }

    def _write_payload(self, payload: dict[str, Any]) -> None:
        self._write_json(
            self.profiles_path,
            {
                "version": PROFILE_VERSION,
                "default_profile_id": payload.get("default_profile_id") or "default",
                "profiles": payload.get("profiles") or [],
                "routes": payload.get("routes") or {},
            },
        )

    def _credentials(self) -> dict[str, str]:
        payload = self._read_json(self.credentials_path)
        return {str(key): str(value) for key, value in payload.items() if str(key) and str(value)}

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self.directory,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            temp_path = Path(handle.name)
        temp_path.chmod(0o600)
        temp_path.replace(path)
        path.chmod(0o600)


@contextmanager
def activate_model_profile(
    profile: dict[str, Any],
    *,
    search_profile: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    token = _ACTIVE_PROFILE.set(dict(profile))
    search_token = _ACTIVE_SEARCH_PROFILE.set(dict(search_profile) if search_profile else None)
    try:
        yield profile
    finally:
        _ACTIVE_SEARCH_PROFILE.reset(search_token)
        _ACTIVE_PROFILE.reset(token)


def active_model_profile() -> dict[str, Any] | None:
    profile = _ACTIVE_PROFILE.get()
    return dict(profile) if profile else None


def active_search_model_profile() -> dict[str, Any] | None:
    profile = _ACTIVE_SEARCH_PROFILE.get()
    return dict(profile) if profile else None
