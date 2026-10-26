"""TOML front matter helpers for shared source documents."""

from __future__ import annotations

import json
from typing import Any

from .toml_compat import tomllib


def has_toml_front_matter(text: str) -> bool:
    """Return True when text starts with a TOML front matter block."""
    return text.startswith("+++\n") or text.startswith("+++\r\n")


def parse_toml_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """Parse TOML front matter and return ``(metadata, body)``.

    Invalid or missing front matter is treated as plain body text.
    """
    if not has_toml_front_matter(text):
        return {}, text

    newline = "\r\n" if text.startswith("+++\r\n") else "\n"
    delimiter = f"{newline}+++{newline}"
    closing = text.find(delimiter, 3)
    if closing == -1:
        return {}, text

    raw_meta = text[len("+++") + len(newline):closing]
    body = text[closing + len(delimiter):]

    try:
        meta = tomllib.loads(raw_meta)
    except Exception:
        return {}, body

    if not isinstance(meta, dict):
        return {}, body
    return meta, body


def render_toml_front_matter(metadata: dict[str, Any]) -> str:
    """Render a limited TOML front matter block."""
    lines = ["+++"]

    # TOML has no syntax to return from a table header to the root. Root fields
    # must precede every table, regardless of the incoming mapping's order.
    def is_table(value: Any) -> bool:
        return isinstance(value, dict) or (
            isinstance(value, list)
            and bool(value)
            and all(isinstance(item, dict) for item in value)
        )

    for key, value in sorted(metadata.items(), key=lambda item: is_table(item[1])):
        if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
            for item in value:
                lines.append("")
                lines.append(f"[[{key}]]")
                for child_key, child_value in item.items():
                    lines.append(f"{child_key} = {_render_toml_value(child_value)}")
            continue

        if isinstance(value, dict):
            lines.append("")
            lines.append(f"[{key}]")
            for child_key, child_value in value.items():
                lines.append(f"{child_key} = {_render_toml_value(child_value)}")
            continue

        lines.append(f"{key} = {_render_toml_value(value)}")

    lines.append("+++")
    return "\n".join(lines)


def compose_toml_document(metadata: dict[str, Any], body: str) -> str:
    """Compose a shared source document with TOML front matter."""
    clean_body = body.lstrip("\r\n")
    if not metadata:
        return clean_body
    return f"{render_toml_front_matter(metadata)}\n\n{clean_body}"


def strip_front_matter_padding(body: str) -> str:
    """Remove the blank line introduced between front matter and Markdown body."""
    return body.lstrip("\r\n")


def _render_toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        rendered = ", ".join(_render_toml_value(item) for item in value)
        return f"[{rendered}]"
    return json.dumps("" if value is None else str(value), ensure_ascii=False)
