"""二阶段风格合成器。

这个模块把风格系统拆成两步：

1. `build_style_manifest()`
   先把 source pack、craft、fingerprint 和作品约束归一成结构化 manifest.toml。
2. `synthesize_style_document()`
   再基于 manifest 生成最终的 composed.md。
   优先尝试 LLM 合成；如果模型不可用或失败，则回退到确定性编译。

这样做的目标是把“来源信号整理”和“作品级风格输出”分开，
避免直接把零散文档硬拼成写作提示词。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import tomllib
import yaml

from .frontmatter import render_toml_front_matter
from .llm.client import LLMClient, LLMConfig, LLMResponse, Message
from .shared_documents import render_indexed_document
from .resource_resolver import ResourceResolver


def build_style_manifest(project_root: Path, novel_id: str, style_id: str) -> dict[str, Any]:
    """收集当前作品的风格来源，并写出 ``manifest.toml``。"""
    root = Path(project_root).resolve()
    style_dir = root / "data" / "novels" / novel_id / "data" / "style"
    style_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "novel_id": novel_id,
        "style_id": style_id,
        "created_at": datetime.now().isoformat(),
        "synthesis_strategy": "two_stage",
        "reusable_signals": _dedupe_preserve(
            _collect_summary_reusable(root, novel_id, style_id)
            + _collect_candidate_signals(root, novel_id, style_id, "voice.md")
            + _collect_candidate_signals(root, novel_id, style_id, "language.md")
            + _collect_candidate_signals(root, novel_id, style_id, "rhythm.md")
            + _collect_candidate_signals(root, novel_id, style_id, "dialogue.md")
        ),
        "source_bound_signals": _dedupe_preserve(
            _collect_summary_source_bound(root, novel_id, style_id)
            + _collect_consistency_source_bound(root, novel_id, style_id)
        ),
        "negative_rules": _dedupe_preserve(
            _collect_banned_phrases(root)
            + _collect_consistency_forbidden(root, novel_id, style_id)
        ),
        "narration_rules": _dedupe_preserve(
            _collect_fingerprint_rules(root, novel_id)
            + _collect_candidate_signals(root, novel_id, style_id, "voice.md")
        ),
        "dialogue_rules": _dedupe_preserve(
            _collect_candidate_signals(root, novel_id, style_id, "dialogue.md")
            + _collect_craft_headings(root, "dialogue_craft.md")
        ),
        "rhythm_rules": _dedupe_preserve(
            _collect_candidate_signals(root, novel_id, style_id, "rhythm.md")
            + _collect_craft_headings(root, "rhythm_craft.md")
        ),
        "craft_rules": _dedupe_preserve(
            _collect_craft_headings(root, "dialogue_craft.md")
            + _collect_craft_headings(root, "scene_craft.md")
            + _collect_craft_headings(root, "rhythm_craft.md")
        ),
        "work_constraints": _dedupe_preserve(_collect_work_constraints(root, novel_id)),
        "priority_order": [
            "work_constraints",
            "narration_rules",
            "dialogue_rules",
            "rhythm_rules",
            "reusable_signals",
            "craft_rules",
            "negative_rules",
        ],
    }

    (style_dir / "manifest.toml").write_text(_render_toml_file(manifest), encoding="utf-8")
    return manifest


def synthesize_style_document(
    project_root: Path,
    novel_id: str,
    style_id: str,
    *,
    llm_client: Any | None = None,
) -> dict[str, Any]:
    """执行二阶段风格合成，并写出 ``composed.md``。"""
    root = Path(project_root).resolve()
    style_dir = root / "data" / "novels" / novel_id / "data" / "style"
    style_dir.mkdir(parents=True, exist_ok=True)
    composed_path = style_dir / "composed.md"

    manifest = build_style_manifest(root, novel_id, style_id)

    mode = "fallback"
    if llm_client is None:
        llm_client = _build_optional_llm_client()

    if llm_client is not None:
        try:
            llm_text = _synthesize_with_llm(llm_client, manifest)
            sanitized = _remove_source_bound_signals(
                llm_text,
                manifest.get("source_bound_signals", []),
            )
            content = _normalize_synthesized_document(
                sanitized,
                novel_id=novel_id,
                style_id=style_id,
                mode="llm",
            )
            mode = "llm"
        except Exception as exc:
            content = _build_fallback_style_document(
                manifest,
                novel_id=novel_id,
                style_id=style_id,
                note=f"LLM 合成失败：{exc}",
            )
    else:
        content = _build_fallback_style_document(
            manifest,
            novel_id=novel_id,
            style_id=style_id,
            note="LLM 不可用，已使用确定性回退合成。",
        )

    composed_path.write_text(content, encoding="utf-8")
    return {
        "mode": mode,
        "content": content,
        "manifest": manifest,
        "manifest_path": style_dir / "manifest.toml",
        "composed_path": composed_path,
    }


def render_style_manifest_summary(manifest: dict[str, Any] | str, *, max_items: int = 6) -> str:
    """把 manifest 渲染成给 writer/reviewer 使用的安全摘要。

    注意：这里故意不输出 `source_bound_signals`，避免来源绑定内容重新泄漏到正文提示词。
    """
    if isinstance(manifest, str):
        try:
            manifest_data = tomllib.loads(manifest)
        except Exception:
            manifest_data = {}
    else:
        manifest_data = dict(manifest or {})

    sections = [
        ("可复用信号", manifest_data.get("reusable_signals", [])),
        ("叙述规则", manifest_data.get("narration_rules", [])),
        ("对话规则", manifest_data.get("dialogue_rules", [])),
        ("节奏规则", manifest_data.get("rhythm_rules", [])),
        ("作品约束", manifest_data.get("work_constraints", [])),
        ("禁止", manifest_data.get("negative_rules", [])),
    ]

    parts: list[str] = []
    for title, values in sections:
        normalized = [str(item).strip() for item in list(values or []) if str(item).strip()]
        if not normalized:
            continue
        parts.append(f"## {title}\n" + "\n".join(f"- {item}" for item in normalized[:max_items]))
    return "\n\n".join(parts).strip()


def _build_optional_llm_client() -> LLMClient | None:
    if not str(LLMConfig.from_env().api_key).strip():
        return None
    return LLMClient(LLMConfig.from_env())


def _synthesize_with_llm(client: Any, manifest: dict[str, Any]) -> str:
    prompt = (
        "你是一位小说风格总编。请基于给定 manifest 生成一份作品级风格文档。"
        "只保留可复用信号，绝对不要把 source_bound_signals 里的专有名词、组织名、桥段名写进最终文档。"
        "输出 Markdown，至少包含这些二级标题："
        "合成摘要、优先风格信号、叙述声音、对话规则、节奏规则、作品约束、通用技法、禁止。"
    )
    messages = [
        Message("system", prompt),
        Message("user", _render_manifest_for_prompt(manifest)),
    ]
    response = client.chat(messages, temperature=0.2, max_tokens=4000)
    content = str(getattr(response, "content", "") or "").strip()
    if not content:
        raise RuntimeError("empty llm synthesis output")
    return content


def _normalize_synthesized_document(text: str, *, novel_id: str, style_id: str, mode: str) -> str:
    body = text.strip()
    if not body.startswith("# "):
        body = f"# 最终风格文档：{novel_id}\n\n{body}"
    header = [
        f"> synthesis_mode: {mode}",
        f"> style_id: {style_id or '无'}",
    ]
    lines = body.splitlines()
    if len(lines) >= 2 and lines[1].startswith("> "):
        return body.rstrip() + "\n"
    return "\n".join([lines[0], "", *header, "", *lines[1:]]).rstrip() + "\n"


def _build_fallback_style_document(
    manifest: dict[str, Any],
    *,
    novel_id: str,
    style_id: str,
    note: str,
) -> str:
    reusable = list(manifest.get("reusable_signals", []))[:8]
    narration = list(manifest.get("narration_rules", []))[:8]
    dialogue = list(manifest.get("dialogue_rules", []))[:8]
    rhythm = list(manifest.get("rhythm_rules", []))[:8]
    work_constraints = list(manifest.get("work_constraints", []))[:8]
    craft_rules = list(manifest.get("craft_rules", []))[:8]
    negative = list(manifest.get("negative_rules", []))[:20]

    parts = [
        f"# 最终风格文档：{novel_id}",
        "",
        "> synthesis_mode: fallback",
        f"> style_id: {style_id or '无'}",
        "",
        "## 合成摘要",
        "",
        note,
        "",
        "## 优先风格信号",
        "",
        _render_bullets(reusable, "（待补充）"),
        "",
        "## 叙述声音",
        "",
        _render_bullets(narration, "（待补充）"),
        "",
        "## 对话规则",
        "",
        _render_bullets(dialogue, "（待补充）"),
        "",
        "## 节奏规则",
        "",
        _render_bullets(rhythm, "（待补充）"),
        "",
        "## 作品约束",
        "",
        _render_bullets(work_constraints, "（待补充）"),
        "",
        "## 通用技法",
        "",
        _render_bullets(craft_rules, "（待补充）"),
        "",
        "## 禁止",
        "",
        _render_bullets(negative, "（待补充）"),
        "",
    ]
    return "\n".join(parts).rstrip() + "\n"


def _render_manifest_for_prompt(manifest: dict[str, Any]) -> str:
    body = _render_toml_file(manifest).strip()
    return f"以下是 style manifest，请生成最终风格文档：\n\n```toml\n{body}\n```"


def _render_toml_file(data: dict[str, Any]) -> str:
    rendered = render_toml_front_matter(data).splitlines()
    if rendered and rendered[0] == "+++":
        rendered = rendered[1:]
    if rendered and rendered[-1] == "+++":
        rendered = rendered[:-1]
    return "\n".join(rendered).rstrip() + "\n"


def _remove_source_bound_signals(text: str, source_bound_signals: list[str]) -> str:
    result = text
    for item in source_bound_signals:
        signal = str(item).strip()
        if signal:
            result = result.replace(signal, "")
    return result


def _collect_summary_reusable(project_root: Path, novel_id: str, style_id: str) -> list[str]:
    path = _source_style_root(project_root, novel_id, style_id) / "summary.md"
    return _extract_markdown_list(_read_text(path), "reusable_signals")


def _collect_summary_source_bound(project_root: Path, novel_id: str, style_id: str) -> list[str]:
    path = _source_style_root(project_root, novel_id, style_id) / "summary.md"
    return _extract_markdown_list(_read_text(path), "source_bound_signals")


def _collect_candidate_signals(
    project_root: Path,
    novel_id: str,
    style_id: str,
    filename: str,
) -> list[str]:
    path = _source_style_root(project_root, novel_id, style_id) / filename
    return _extract_markdown_list(_read_text(path), "候选信号")


def _collect_consistency_forbidden(project_root: Path, novel_id: str, style_id: str) -> list[str]:
    path = _source_style_root(project_root, novel_id, style_id) / "consistency.md"
    return _extract_markdown_list(_read_text(path), "禁止直接搬运")


def _collect_consistency_source_bound(project_root: Path, novel_id: str, style_id: str) -> list[str]:
    path = _source_style_root(project_root, novel_id, style_id) / "consistency.md"
    return _extract_markdown_list(_read_text(path), "来源绑定内容")


def _collect_banned_phrases(project_root: Path) -> list[str]:
    text = ResourceResolver(project_root).read_text("craft", "humanization.yaml")
    if not text:
        return []
    try:
        data = yaml.safe_load(text) or {}
    except Exception:
        return []
    phrases = data.get("banned_phrases", [])
    results: list[str] = []
    for item in phrases:
        if isinstance(item, dict):
            value = str(item.get("phrase", "")).strip()
        else:
            value = str(item).strip()
        if value:
            results.append(value)
    return results


def _collect_fingerprint_rules(project_root: Path, novel_id: str) -> list[str]:
    path = Path(project_root) / "data" / "novels" / novel_id / "data" / "style" / "fingerprint.yaml"
    if not path.exists():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return []

    results = []
    voice = str(data.get("voice", "")).strip()
    language = str(data.get("language_style", "")).strip()
    rhythm = str(data.get("rhythm", "")).strip()
    if voice:
        results.append(voice)
    if language:
        results.append(language)
    if rhythm:
        results.append(rhythm)
    return results


def _collect_craft_headings(project_root: Path, filename: str) -> list[str]:
    text = ResourceResolver(project_root).read_text("craft", filename)
    if not text:
        return []
    results: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            results.append(stripped[3:].strip())
    return results


def _collect_work_constraints(project_root: Path, novel_id: str) -> list[str]:
    base = Path(project_root) / "data" / "novels" / novel_id / "src"
    results: list[str] = []
    for path, meta in (
        (
            base / "story" / "foundation.md",
            {"name": "基础设定", "summary": "作品基础设定", "detail_refs": ["核心前提", "限制", "禁忌"]},
        ),
        (
            base / "world" / "rules.md",
            {"name": "世界规则", "summary": "作品世界规则", "detail_refs": ["power_rules", "social_rules", "limits"]},
        ),
    ):
        if path.exists():
            rendered = render_indexed_document(
                path.read_text(encoding="utf-8"),
                default_meta=meta,
                max_chars=600,
            ).strip()
            if rendered:
                results.append(rendered)
    return results


def _source_style_root(project_root: Path, novel_id: str, style_id: str) -> Path:
    return Path(project_root) / "data" / "novels" / novel_id / "data" / "sources" / style_id / "style"


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _extract_markdown_list(text: str, heading: str) -> list[str]:
    if not text.strip():
        return []
    lines = text.splitlines()
    collecting = False
    results: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            title = stripped[3:].strip()
            if title == heading:
                collecting = True
                continue
            if collecting:
                break
        if collecting and stripped.startswith("- "):
            value = stripped[2:].strip()
            if value:
                results.append(value)
    return results


def _render_bullets(items: list[str], placeholder: str) -> str:
    if not items:
        return f"- {placeholder}"
    return "\n".join(f"- {item}" for item in items)


def _dedupe_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        normalized = str(item).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result
