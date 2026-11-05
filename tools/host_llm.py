"""The host's own model directory, reached through its OpenAI-compatible relay.

The host (dsh) owns the model adapters: its own providers and the ones other
plugins register into the same directory. OpenWrite's Core cannot call those
adapters directly — it is a separate process — so the host exposes a loopback
relay that speaks the OpenAI chat-completions protocol and performs the call
with the host's own credentials.

The relay address and its machine token arrive in Core's private stdio
handshake. They are held in memory only: the relay port is ephemeral, so a
persisted copy would be stale after the next host restart, and the token is a
machine secret that must never reach the browser or the disk.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from threading import Lock
from typing import Any

HOST_LLM_URL_KEY = "url"
HOST_LLM_TOKEN_KEY = "token"

# The relay answers on the loopback interface only; a request that leaves the
# machine would carry the machine token to a stranger.
_RELAY_TIMEOUT_SECONDS = 10.0

_lock = Lock()
_relay: dict[str, str] | None = None


def configure_host_llm(url: str, token: str) -> None:
    """Record the relay coordinates handed over by the host handshake."""
    global _relay
    clean_url = str(url or "").strip()
    clean_token = str(token or "").strip()
    if not clean_url or not clean_token:
        clear_host_llm()
        return
    with _lock:
        _relay = {HOST_LLM_URL_KEY: clean_url.rstrip("/"), HOST_LLM_TOKEN_KEY: clean_token}


def clear_host_llm() -> None:
    """Forget the relay (used by tests and by a standalone Core run)."""
    global _relay
    with _lock:
        _relay = None


def host_llm() -> dict[str, str] | None:
    """The live relay coordinates, or None when Core runs without a host."""
    with _lock:
        return dict(_relay) if _relay is not None else None


def host_llm_available() -> bool:
    return host_llm() is not None


def host_llm_url() -> str:
    relay = host_llm()
    return relay[HOST_LLM_URL_KEY] if relay is not None else ""


def fetch_host_models() -> dict[str, Any]:
    """Read the host's model directory through the relay.

    The directory is not a secret, but it is read through the machine channel
    anyway: the relay is the only addressable surface of the host's model
    service, and the browser never learns its token.
    """
    relay = host_llm()
    if relay is None:
        return {"available": False, "providers": [], "models": [], "current": None, "error": "宿主模型通道未连接"}
    url = f"{relay[HOST_LLM_URL_KEY]}/models"
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {relay[HOST_LLM_TOKEN_KEY]}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=_RELAY_TIMEOUT_SECONDS) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"available": False, "providers": [], "models": [], "current": None, "error": f"宿主模型目录读取失败: {exc}"}
    entries = payload.get("data") if isinstance(payload, dict) else None
    models: list[dict[str, str]] = []
    providers: list[dict[str, str]] = []
    seen: set[str] = set()
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        identifier = str(entry.get("id") or "").strip()
        if not identifier:
            continue
        provider = str(entry.get("provider") or identifier.split("/", 1)[0])
        model = str(entry.get("model") or identifier.split("/", 1)[-1])
        try:
            context_tokens = int(entry.get("context_tokens") or 0)
        except (TypeError, ValueError):
            context_tokens = 0
        models.append(
            {
                "id": identifier,
                "provider": provider,
                "model": model,
                "label": str(entry.get("label") or model),
                "description": str(entry.get("description") or ""),
                "context_tokens": context_tokens,
            }
        )
        if provider not in seen:
            seen.add(provider)
            providers.append({"id": provider, "name": provider})
    return {"available": True, "providers": providers, "models": models, "current": None, "error": ""}
