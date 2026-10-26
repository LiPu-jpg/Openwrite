"""Helpers for canonical human/AI shared source documents."""

from __future__ import annotations

import re
from pathlib import Path

from .frontmatter import compose_toml_document, parse_toml_front_matter, strip_front_matter_padding

DEFAULT_CHARACTER_DETAIL_REFS = ["基本信息", "背景", "外貌", "性格", "关系"]
DEFAULT_ENTITY_DETAIL_REFS = ["规则", "特征", "关联"]

CHARACTER_MARKDOWN_CONTRACT = """## OpenWrite 角色文档契约

创建完整角色资产时，`content` 必须包含 TOML front matter 与 Markdown 正文。front matter 至少包含
`id`、`name`、`tier`、`summary`、`tags`，关系引用放在 `related`。正文必须使用一级角色名标题，
并填写 `## 基本信息`、`## 背景`、`## 外貌`、`## 性格`、`## 与主角关系`、
`## 说话风格`、`## 当前戏剧用途`；有能力体系时再填写 `## 特殊能力`。
未知信息写“待作者确认”，不能省略结构，也不能只传一句 description 充当完整角色卡。"""


def normalize_character_document(
    content: str,
    *,
    fallback_id: str = "",
    fallback_name: str = "",
    fallback_description: str = "",
) -> str:
    """Normalize a character source document into TOML + Markdown form."""

    meta, body = parse_toml_front_matter(content or "")
    clean_body = strip_front_matter_padding(body if meta else (content or "")).strip()

    name = (
        str(meta.get("name", "")).strip()
        or _extract_heading(clean_body)
        or fallback_name.strip()
        or fallback_id.strip()
        or "未命名角色"
    )
    summary = (
        str(meta.get("summary", "")).strip()
        or _extract_summary(clean_body)
        or fallback_description.strip()
        or f"{name}的角色档案。"
    )

    normalized_meta = dict(meta)
    normalized_meta["id"] = str(meta.get("id", "")).strip() or _safe_identifier(
        fallback_id or name
    )
    normalized_meta["name"] = name
    normalized_meta["tier"] = str(meta.get("tier", "")).strip() or "普通配角"
    normalized_meta["summary"] = summary
    normalized_meta["tags"] = _normalize_str_list(meta.get("tags"))
    normalized_meta["detail_refs"] = _normalize_str_list(
        meta.get("detail_refs"), default=DEFAULT_CHARACTER_DETAIL_REFS
    )
    normalized_meta["related"] = _normalize_related(meta.get("related"))

    normalized_body = _normalize_character_body(
        clean_body,
        name=name,
        fallback_description=fallback_description.strip() or summary,
    )
    return compose_toml_document(normalized_meta, normalized_body)


def normalize_world_entity_document(
    content: str,
    *,
    fallback_id: str = "",
    fallback_name: str = "",
    fallback_summary: str = "",
    default_type: str = "concept",
    default_subtype: str = "emergent",
) -> str:
    """Normalize a world entity source document into TOML + Markdown form."""

    meta, body = parse_toml_front_matter(content or "")
    clean_body = strip_front_matter_padding(body if meta else (content or "")).strip()

    name = (
        str(meta.get("name", "")).strip()
        or _extract_heading(clean_body)
        or fallback_name.strip()
        or fallback_id.strip()
        or "未命名概念"
    )
    summary = (
        str(meta.get("summary", "")).strip()
        or _extract_summary(clean_body)
        or fallback_summary.strip()
        or f"{name}的概念条目。"
    )

    normalized_meta = dict(meta)
    normalized_meta["id"] = str(meta.get("id", "")).strip() or _safe_identifier(
        fallback_id or name
    )
    normalized_meta["name"] = name
    normalized_meta["type"] = str(meta.get("type", "")).strip() or default_type
    normalized_meta["subtype"] = str(meta.get("subtype", "")).strip() or default_subtype
    normalized_meta["status"] = str(meta.get("status", "")).strip() or "active"
    normalized_meta["summary"] = summary
    normalized_meta["tags"] = _normalize_str_list(meta.get("tags"))
    normalized_meta["detail_refs"] = _normalize_str_list(
        meta.get("detail_refs"), default=DEFAULT_ENTITY_DETAIL_REFS
    )
    normalized_meta["related"] = _normalize_related(meta.get("related"))

    normalized_body = _normalize_entity_body(
        clean_body,
        name=name,
        fallback_summary=summary,
    )
    return compose_toml_document(normalized_meta, normalized_body)


def render_indexed_document(
    content: str,
    *,
    default_meta: dict[str, object] | None = None,
    max_chars: int = 0,
    max_sections: int = 3,
) -> str:
    """Render a shared document into an AI-friendly indexed view."""

    meta, body = parse_toml_front_matter(content or "")
    clean_body = strip_front_matter_padding(body if meta else (content or "")).strip()
    merged_meta = _merge_meta(default_meta or {}, meta)

    title = str(merged_meta.get("name", "")).strip() or _extract_heading(clean_body)
    summary = str(merged_meta.get("summary", "")).strip() or _extract_summary(clean_body)
    tags = _normalize_str_list(merged_meta.get("tags"))
    detail_refs = _normalize_str_list(merged_meta.get("detail_refs"))
    related = _normalize_related(merged_meta.get("related"))

    parts: list[str] = []
    if title:
        parts.append(f"标题: {title}")
    if summary:
        parts.append(f"摘要: {summary}")
    if tags:
        parts.append(f"标签: {'、'.join(tags)}")
    if detail_refs:
        parts.append(f"细节索引: {'、'.join(detail_refs)}")
    if related:
        relation_bits: list[str] = []
        for item in related[:5]:
            target = str(item.get("target", "")).strip()
            if not target:
                continue
            detail = (
                str(item.get("note", "")).strip()
                or str(item.get("description", "")).strip()
                or str(item.get("kind", "")).strip()
            )
            relation_bits.append(f"{target}（{detail}）" if detail else target)
        if relation_bits:
            parts.append(f"关联: {'；'.join(relation_bits)}")

    sections = _extract_sections(clean_body)
    section_refs = detail_refs[:max_sections] if detail_refs else list(sections.keys())[:max_sections]
    rendered_sections: list[str] = []
    for ref in section_refs:
        match = _match_section(ref, sections)
        if not match:
            continue
        section_title, section_body = match
        rendered_sections.append(f"## {section_title}\n{section_body}")

    if rendered_sections:
        parts.extend(rendered_sections)
    else:
        excerpt = _strip_leading_heading(clean_body)
        if excerpt:
            parts.append(excerpt[:800])

    text = "\n".join(part for part in parts if part).strip()
    if max_chars and len(text) > max_chars:
        return text[:max_chars] + "..."
    return text


def resolve_shared_document_path(directory: Path, reference: str) -> Path | None:
    """Resolve a human-readable reference to a canonical Markdown source file."""

    ref_key = _normalize_lookup_key(reference)
    if not ref_key or not directory.exists():
        return None

    for path in sorted(directory.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        for candidate in shared_document_lookup_keys(path, content=text):
            if _normalize_lookup_key(candidate) == ref_key:
                return path
    return None


def shared_document_lookup_keys(
    path: Path,
    *,
    content: str | None = None,
) -> list[str]:
    """Return canonical IDs, display names, headings, and aliases for a document."""

    if content is None:
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            return []
    meta, body = parse_toml_front_matter(content)
    return _iter_document_lookup_keys(path, meta, body)


def _normalize_character_body(body: str, *, name: str, fallback_description: str) -> str:
    if not body:
        return f"# {name}\n\n## 背景\n\n{fallback_description or '（待补充）'}\n"
    if re.search(r"^#\s+.+$", body, re.MULTILINE):
        return body
    if re.search(r"^##\s+.+$", body, re.MULTILINE):
        return f"# {name}\n\n{body}"
    return f"# {name}\n\n## 背景\n\n{body}\n"


def _normalize_entity_body(body: str, *, name: str, fallback_summary: str) -> str:
    if not body:
        return (
            f"# {name}\n\n"
            f"{fallback_summary or '（待补充）'}\n\n"
            "## 规则\n\n- （待补充）\n\n"
            "## 特征\n\n- （待补充）\n\n"
            "## 关联\n\n- （待补充）\n"
        )
    if re.search(r"^#\s+.+$", body, re.MULTILINE):
        return body
    if re.search(r"^##\s+.+$", body, re.MULTILINE):
        return f"# {name}\n\n{body}"
    return (
        f"# {name}\n\n"
        f"{body}\n\n"
        "## 规则\n\n- （待补充）\n\n"
        "## 特征\n\n- （待补充）\n\n"
        "## 关联\n\n- （待补充）\n"
    )


def _iter_document_lookup_keys(path: Path, meta: dict, body: str) -> list[str]:
    keys: list[str] = [path.stem]

    doc_id = str(meta.get("id", "")).strip()
    if doc_id:
        keys.append(doc_id)

    doc_name = str(meta.get("name", "")).strip() or _extract_heading(body)
    if doc_name:
        keys.append(doc_name)

    aliases = meta.get("aliases", [])
    if isinstance(aliases, list):
        keys.extend(str(alias).strip() for alias in aliases if str(alias).strip())

    expanded: list[str] = []
    for key in keys:
        if not key:
            continue
        expanded.append(key)
        stripped = _strip_parenthetical_suffix(key)
        if stripped and stripped != key:
            expanded.append(stripped)

    deduped: list[str] = []
    seen = set()
    for key in expanded:
        norm = _normalize_lookup_key(key)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        deduped.append(key)
    return deduped


def _normalize_str_list(value: object, *, default: list[str] | None = None) -> list[str]:
    if not isinstance(value, list):
        return list(default or [])
    normalized: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            normalized.append(text)
    return normalized or list(default or [])


def _normalize_lookup_key(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _normalize_related(value: object) -> list[dict[str, object]]:
    if isinstance(value, dict):
        value = [
            {**(details if isinstance(details, dict) else {"note": details}), "target": target}
            for target, details in value.items()
        ]
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        target = str(item.get("target", "")).strip()
        if not target:
            continue
        entry = {"target": target}
        for key in ("kind", "weight", "note", "description"):
            if key not in item:
                continue
            child = item.get(key)
            if child in (None, ""):
                continue
            entry[key] = child
        normalized.append(entry)
    return normalized


def _merge_meta(base: dict[str, object], overlay: dict[str, object]) -> dict[str, object]:
    merged = dict(base)
    for key, value in overlay.items():
        if value in (None, "", []):
            continue
        merged[key] = value
    return merged


def _extract_sections(body: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    current_title = ""
    buffer: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        heading = re.match(r"^##\s+(.+)$", stripped)
        if heading:
            if current_title and buffer:
                sections[current_title] = "\n".join(buffer).strip()
            current_title = heading.group(1).strip()
            buffer = []
            continue
        if current_title:
            buffer.append(line)
    if current_title and buffer:
        sections[current_title] = "\n".join(buffer).strip()
    return {title: text for title, text in sections.items() if text}


def _match_section(ref: str, sections: dict[str, str]) -> tuple[str, str] | None:
    needle = ref.strip().lower()
    for title, text in sections.items():
        if title.strip().lower() == needle:
            return title, text
    for title, text in sections.items():
        lowered = title.strip().lower()
        if needle in lowered or lowered in needle:
            return title, text
    return None


def _strip_leading_heading(body: str) -> str:
    lines = body.splitlines()
    if lines and re.match(r"^#\s+.+$", lines[0].strip()):
        return "\n".join(lines[1:]).strip()
    return body.strip()


def _extract_heading(text: str) -> str:
    match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _extract_summary(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#") or stripped.startswith(">"):
            continue
        if stripped.startswith(("- ", "* ")):
            stripped = stripped[2:].strip()
        if stripped:
            return stripped[:160]
    return ""


def _strip_parenthetical_suffix(value: str) -> str:
    return re.sub(r"\s*[（(][^()（）]+[)）]\s*$", "", value).strip()


def _safe_identifier(value: str) -> str:
    text = (value or "").strip()
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]", "", text)
    return text[:64] or "untitled"
