"""Opt-in credentials from the locally authenticated official OpenCode CLI."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from .errors import AuthenticationError


class ConsoleAuthenticationError(AuthenticationError):
    def __init__(self, reason: str = "login"):
        messages = {
            "missing": "未找到 OpenCode CLI；请在 Studio 所在电脑安装并登录 OpenCode Console",
            "login": (
                "无法读取 OpenCode Go 登录；请在 Studio 所在电脑"
                "完成 OpenCode Console CLI 登录后重试"
            ),
            "workspace": (
                "OpenCode CLI 当前工作区与档案不一致；请切换 CLI 工作区或更新档案的工作区 ID"
            ),
        }
        super().__init__(messages.get(reason, messages["login"]))


GO_BASE_URL = "https://opencode.ai/inference/go/openai/v1"


def is_go_url(value: str) -> bool:
    try:
        url = urlsplit(value.rstrip("/"))
        return (
            url.scheme == "https"
            and url.hostname == "opencode.ai"
            and url.port in {None, 443}
            and not (url.username or url.password or url.query or url.fragment)
            and url.path
            in {
                "/inference/go/openai/v1",
                "/inference/go/openai/v1/chat/completions",
                "/zen/go/v1",
                "/zen/go/v1/chat/completions",
            }
        )
    except ValueError:
        return False


def console_available() -> bool:
    return shutil.which("opencode") is not None


def console_credentials(workspace_id: str = "") -> tuple[str, dict[str, str]]:
    """Resolve on each request so the CLI refreshes expiring Console tokens.

    The CLI owns authentication and refresh. Never copy its access/refresh tokens
    into an OpenWrite profile, DTO, log, or named temporary file.
    """
    executable = shutil.which("opencode")
    if not executable:
        raise ConsoleAuthenticationError("missing")
    try:
        # A regular anonymous file also avoids the CLI's truncated stdout when
        # a large resolved model catalog is written to a pipe.
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as error:
            result = subprocess.run(
                [executable, "debug", "config", "--pure"],
                cwd=Path.home(),
                stdout=output,
                stderr=error,
                timeout=20,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if result.returncode or output.tell() > 8 * 1024 * 1024:
                raise ValueError("unavailable config")
            output.seek(0)
            config = json.load(output)
        options = config["provider"]["opencode-go"]["options"]
        key = options["apiKey"]
        org = options["headers"]["x-opencode-org-id"]
        if not isinstance(key, str) or not key.strip():
            raise ValueError("missing credential")
        if not isinstance(org, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", org):
            raise ValueError("missing workspace")
    except (OSError, ValueError, TypeError, KeyError, subprocess.TimeoutExpired):
        # CLI output can contain credentials: deliberately do not echo it or
        # attach a raw exception/traceback containing its parsed values.
        raise ConsoleAuthenticationError("login") from None
    if workspace_id and org != workspace_id:
        raise ConsoleAuthenticationError("workspace")
    return key, {"x-opencode-org-id": org}
