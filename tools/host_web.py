"""Coordinates of the host's loopback web search/fetch relay.

The relay is started by the dsh host plugin and handed to this process over its
private stdio handshake. Coordinates are held in memory only: the port is
ephemeral and the token is a machine secret.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

_host_web_url = ""
_host_web_token = ""


def configure_host_web(url: str, token: str) -> None:
    """Install relay coordinates from the startup handshake."""
    global _host_web_url, _host_web_token
    clean_url = str(url or "").strip().rstrip("/")
    clean_token = str(token or "").strip()
    parsed = urlparse(clean_url)
    # A malformed handshake must not become a half-configured provider that
    # every research run fails on with a network error.
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or not clean_token
    ):
        _host_web_url = ""
        _host_web_token = ""
        return
    _host_web_url = clean_url
    _host_web_token = clean_token


def host_web_available() -> bool:
    """Whether the managed host relay was configured for this process."""
    return _host_web_url != "" and _host_web_token != ""


def host_web_environment() -> dict[str, str]:
    """Environment the DeepResearch child uses to reach the relay."""
    if not host_web_available():
        raise ValueError("DSH 搜索仅在托管运行时可用，请选择其他搜索提供方")
    return {
        "OPENWRITE_WEB_RELAY_URL": _host_web_url,
        "OPENWRITE_WEB_RELAY_TOKEN": _host_web_token,
    }


def reset_host_web() -> None:
    """Clear state (tests and managed-runtime restarts)."""
    global _host_web_url, _host_web_token
    _host_web_url = ""
    _host_web_token = ""
