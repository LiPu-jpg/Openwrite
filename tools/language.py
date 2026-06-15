from __future__ import annotations

import os
from pathlib import Path

from tools.resource_resolver import ResourceResolver


def current_language(default: str = "zh") -> str:
    return os.getenv("OPENWRITE_LANGUAGE", default).strip() or default


def load_language_prompt(language: str, name: str, workspace: Path) -> str:
    return ResourceResolver(workspace).read_text("language_packs", f"{language}/{name}.md")
