"""Structured outline tree and next-chapter recommendation.

The Markdown file remains the only source of truth.  This module builds a
read-only projection for Studio and ReAct without introducing another cache.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from tools.frontmatter import parse_toml_front_matter
from tools.writing_targets import normalize_writing_targets

HEADING_RE = re.compile(r"^(#{1,4})\s+(.+?)\s*$")
NUMBER_TOKEN = r"[零〇一二三四五六七八九十百千万两\d]+"
CHAPTER_RE = re.compile(rf"第\s*({NUMBER_TOKEN})\s*章")
CHAPTER_ID_RE = re.compile(r"\bch[_-]?(\d+)\b", re.IGNORECASE)
OUTLINE_KINDS = ("volume", "act", "section", "chapter")
CHILD_KIND = {"volume": "act", "act": "section", "section": "chapter"}
NUMBERED_TITLE_RE = {
    kind: re.compile(rf"第\s*({NUMBER_TOKEN})\s*{label}")
    for kind, label in {
        "volume": "卷",
        "act": "幕",
        "section": "节",
        "chapter": "章",
    }.items()
}


class OutlineEditError(ValueError):
    """A safe, user-facing rejection of a structural outline edit."""

    def __init__(self, message: str, *, code: str = "invalid"):
        super().__init__(message)
        self.code = code


def build_outline_structure(
    novel_root: Path,
    *,
    chapter_id: str = "",
    writing_targets: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a bounded, human-readable volume/act/section/chapter tree."""
    root = Path(novel_root).resolve()
    outline_path = root / "src" / "outline.md"
    if not outline_path.is_file():
        return _empty_structure()

    text = outline_path.read_text(encoding="utf-8")
    metadata, body = parse_toml_front_matter(text)
    drafted = {path.stem for path in (root / "data" / "manuscript").rglob("ch_*.md")}
    targets = normalize_writing_targets(writing_targets) if writing_targets else None
    roots, flat = _parse_tree(
        body,
        drafted,
        writing_targets=targets,
        document_summary=str(metadata.get("summary") or "").strip(),
    )
    line_offset = text[: len(text) - len(body)].count("\n")
    for node in flat:
        node["line"] += line_offset
        node["end_line"] += line_offset
        for change in node.get("delete_renumber_preview", []):
            change["line"] += line_offset
    recommendation = _recommend_chapter(
        roots,
        flat,
        drafted,
        requested=chapter_id,
        target_words=(
            int(targets["chapter_words"])
            if targets
            else _smart_target_words(root)
        ),
    )
    counts = {kind: 0 for kind in ("volume", "act", "section", "chapter", "appendix")}
    for node in flat:
        counts[node["kind"]] = counts.get(node["kind"], 0) + 1

    return {
        "path": "src/outline.md",
        "revision": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
        "roots": roots,
        "counts": counts,
        "drafted_chapters": len(drafted),
        "recommendation": recommendation,
    }


def mutate_outline_structure(
    novel_root: Path,
    *,
    operation: str,
    revision: str,
    node_id: str = "",
    title: str = "",
    summary: str = "",
    kind: str = "",
) -> dict[str, Any]:
    """Prepare one revision-checked, local structural edit to ``outline.md``.

    The caller owns persistence.  Returning the new content instead of writing it
    here lets Studio reuse its atomic document writer and Git checkpoint policy.
    """
    root = Path(novel_root).resolve()
    outline_path = root / "src" / "outline.md"
    if not outline_path.is_file():
        raise OutlineEditError("当前没有可编辑的大纲")
    structure = build_outline_structure(root)
    if not revision or revision != structure["revision"]:
        raise OutlineEditError(
            "大纲已在其他位置变化，请刷新结构后重试",
            code="conflict",
        )

    nodes = _flatten_nodes(structure["roots"])
    by_id = {node["id"]: node for node in nodes}
    target = by_id.get(node_id)
    operation = str(operation or "").strip()
    kind = str(kind or "").strip()
    lines = outline_path.read_text(encoding="utf-8").splitlines(keepends=True)
    selection_hint: dict[str, Any] = {}

    if operation == "rename":
        target = _editable_target(target)
        clean_title = _validate_title(title, target["kind"])
        if target["kind"] == "chapter":
            next_chapter_id = _canonical_chapter_id(clean_title)
            if not next_chapter_id:
                raise OutlineEditError("章节标题必须包含章节号，例如“第12章：转折”")
            if target["status"] == "drafted" and next_chapter_id != target["id"]:
                raise OutlineEditError("已有正文的章节只能修改标题，不能更换章节编号")
            if next_chapter_id != target["id"] and any(
                node["id"] == next_chapter_id for node in nodes
            ):
                raise OutlineEditError(f"{next_chapter_id} 已存在，请使用新的章节号")
        line_index = int(target["line"]) - 1
        marker = "#" * int(target["level"])
        ending = "\n" if lines[line_index].endswith("\n") else ""
        lines[line_index] = f"{marker} {clean_title}{ending}"
        selection_hint = {"kind": target["kind"], "title": clean_title, "line": line_index + 1}
        message = f"已将{target['label']}重命名为“{clean_title}”"
    elif operation == "update_summary":
        target = _editable_target(target)
        clean_summary = _validate_summary(summary)
        start = int(target["line"])
        end = _direct_body_end(lines, start)
        summary_start, summary_end = _direct_summary_span(lines, start, end)
        lines[summary_start:summary_end] = _summary_block(
            clean_summary,
            has_following=summary_end < len(lines),
        )
        selection_hint = {
            "kind": target["kind"],
            "title": target["title"],
            "line": int(target["line"]),
        }
        message = f"已更新{target['label']}“{target['title']}”的内容"
    elif operation in {"add_child", "add_after"}:
        if operation == "add_child" and not node_id:
            expected_kind = "volume"
            insert_index = next(
                (int(node["line"]) - 1 for node in nodes if node["kind"] == "appendix"),
                len(lines),
            )
            parent_title = "大纲根节点"
        else:
            target = _editable_target(target)
            if operation == "add_child":
                expected_kind = str(target.get("child_kind") or "")
                if not expected_kind:
                    raise OutlineEditError("章节下面不能再新增结构层级")
                insert_index = int(target["end_line"])
                parent_title = target["title"]
            else:
                expected_kind = target["kind"]
                insert_index = int(target["end_line"])
                parent_title = target.get("path", [""])[-1] if target.get("path") else "大纲根节点"
        if kind and kind != expected_kind:
            raise OutlineEditError("新增层级与当前节点不匹配，请刷新后重试")
        clean_title = _validate_title(title, expected_kind)
        if expected_kind == "chapter":
            chapter_id = _canonical_chapter_id(clean_title)
            if not chapter_id:
                raise OutlineEditError("章节标题必须包含章节号，例如“第12章：转折”")
            if any(node["id"] == chapter_id for node in nodes):
                raise OutlineEditError(f"{chapter_id} 已存在，请使用新的章节号")
        level = OUTLINE_KINDS.index(expected_kind) + 1
        block, heading_offset = _heading_block(lines, insert_index, level, clean_title)
        lines[insert_index:insert_index] = block
        selection_hint = {
            "kind": expected_kind,
            "title": clean_title,
            "line": insert_index + heading_offset + 1,
        }
        message = f"已在“{parent_title}”新增{_kind_label(expected_kind)}“{clean_title}”"
    elif operation == "delete":
        target = _editable_target(target)
        if not target.get("can_delete"):
            raise OutlineEditError(
                str(target.get("delete_blocked_reason") or "该节点包含已有正文的章节，不能删除")
            )
        renumbered, skipped = _deletion_renumber_plan(nodes, target)
        for change in renumbered:
            line_index = int(change["line"]) - 1
            marker = "#" * int(change["level"])
            ending = "\n" if lines[line_index].endswith("\n") else ""
            lines[line_index] = f"{marker} {change['new_title']}{ending}"
        start = int(target["line"]) - 1
        end = int(target["end_line"])
        removed_lines = end - start
        del lines[start:end]
        selection_hint = {"parent_id": target.get("parent_id", "")}
        message = (
            f"已删除{target['label']}“{target['title']}”及其 "
            f"{target['descendant_count']} 个下级节点（{removed_lines} 行），"
            f"并连续重编号 {len(renumbered)} 个后续节点"
        )
        if skipped:
            message += f"；{len(skipped)} 个无可识别编号的标题保持不变"
    else:
        raise OutlineEditError("不支持的大纲编辑操作")

    return {
        "content": "".join(lines),
        "message": message,
        "selection_hint": selection_hint,
        "renumbered": renumbered if operation == "delete" else [],
        "skipped_renumbering": skipped if operation == "delete" else [],
    }


def _parse_tree(
    body: str,
    drafted: set[str],
    *,
    writing_targets: dict[str, int] | None = None,
    document_summary: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    lines = body.splitlines()
    headings: list[dict[str, Any]] = []
    counters = {1: 0, 2: 0, 3: 0, 4: 0}
    inside_appendix = False
    for index, raw in enumerate(lines):
        match = HEADING_RE.match(raw.strip())
        if not match:
            continue
        level = len(match.group(1))
        counters[level] += 1
        title = match.group(2).strip()
        if level == 1:
            inside_appendix = "附录" in title
        kind = _node_kind(level, title, inside_appendix)
        node_id = _node_id(kind, title, counters[level], level)
        headings.append(
            {
                "id": node_id,
                "kind": kind,
                "label": _kind_label(kind),
                "title": title,
                "line": index + 1,
                "end_line": index + 1,
                "level": level,
                "content": "",
                "summary": "",
                "status": "drafted" if node_id in drafted else "planned",
                "children": [],
                "parent_id": "",
                "path": [],
            }
        )

    roots: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []
    for position, node in enumerate(headings):
        next_line = headings[position + 1]["line"] - 1 if position + 1 < len(headings) else len(lines)
        body_lines = lines[node["line"] : next_line]
        node["content"] = _body_block(body_lines)
        node["summary"] = _summarize_block(
            body_lines,
            kind=node["kind"],
            fallback=document_summary if node["kind"] == "volume" and not roots else "",
        )
        node["content_units"] = _writing_units(node["content"])
        detail_key = f"outline_{node['kind']}_words"
        node["detail_target_words"] = int((writing_targets or {}).get(detail_key, 0))
        if node["kind"] == "chapter":
            node["chapter_target_words"] = _explicit_chapter_target(
                node["content"]
            ) or int((writing_targets or {}).get("chapter_words", 0))
        else:
            node["chapter_target_words"] = 0
        subtree_end = len(lines)
        for candidate in headings[position + 1 :]:
            if candidate["level"] <= node["level"]:
                subtree_end = candidate["line"] - 1
                break
        node["end_line"] = subtree_end
        while stack and stack[-1]["level"] >= node["level"]:
            stack.pop()
        if stack:
            parent = stack[-1]
            node["parent_id"] = parent["id"]
            node["path"] = [*parent["path"], parent["title"]]
            parent["children"].append(node)
        else:
            roots.append(node)
        stack.append(node)

    for node in reversed(headings):
        descendants = _flatten_nodes(node["children"])
        node["descendant_count"] = len(descendants)
        node["child_kind"] = CHILD_KIND.get(node["kind"], "")
        node["editable"] = node["kind"] in OUTLINE_KINDS
        subtree_has_draft = any(
            child["kind"] == "chapter" and child["status"] == "drafted"
            for child in [node, *descendants]
        )
        node["can_delete"] = node["editable"] and not subtree_has_draft
        node["delete_blocked_reason"] = (
            "该节点包含已有正文的章节，不能删除" if subtree_has_draft else ""
        )

    for node in headings:
        node["delete_renumber_count"] = 0
        node["delete_renumber_preview"] = []
        node["delete_renumber_skipped"] = 0
        if not node["can_delete"]:
            continue
        try:
            renumbered, skipped = _deletion_renumber_plan(headings, node)
        except OutlineEditError as exc:
            node["can_delete"] = False
            node["delete_blocked_reason"] = str(exc)
            continue
        node["delete_renumber_count"] = len(renumbered)
        node["delete_renumber_preview"] = renumbered[:5]
        node["delete_renumber_skipped"] = len(skipped)

    return roots, headings


def _flatten_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for node in nodes:
        result.append(node)
        result.extend(_flatten_nodes(node.get("children", [])))
    return result


def _deletion_renumber_plan(
    nodes: list[dict[str, Any]], target: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Describe the global numbering shifts caused by deleting one subtree."""
    start = int(target["line"])
    end = int(target["end_line"])
    removed = [
        node
        for node in nodes
        if start <= int(node["line"]) <= end and node["kind"] in OUTLINE_KINDS
    ]
    removed_numbers: dict[str, list[int]] = {kind: [] for kind in OUTLINE_KINDS}
    for node in removed:
        number = _title_number(str(node["title"]), str(node["kind"]))
        if number is not None:
            removed_numbers[str(node["kind"])].append(number)

    renumbered: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for node in nodes:
        kind = str(node["kind"])
        if kind not in OUTLINE_KINDS or int(node["line"]) <= end:
            continue
        deleted_before = removed_numbers[kind]
        if not deleted_before:
            continue
        old_number = _title_number(str(node["title"]), kind)
        if old_number is None:
            skipped.append(
                {
                    "kind": kind,
                    "id": node["id"],
                    "title": node["title"],
                    "line": node["line"],
                    "reason": "标题没有可识别的层级编号",
                }
            )
            continue
        shift = sum(number < old_number for number in deleted_before)
        if not shift:
            continue
        new_number = old_number - shift
        new_title = _replace_title_number(str(node["title"]), kind, new_number)
        change = {
            "kind": kind,
            "old_id": node["id"],
            "new_id": _shifted_node_id(
                node,
                sequence_shift=sum(item["kind"] == kind for item in removed),
                new_number=new_number,
            ),
            "old_title": node["title"],
            "new_title": new_title,
            "line": node["line"],
            "level": node["level"],
        }
        if kind == "chapter" and node.get("status") == "drafted":
            raise OutlineEditError(
                f"删除会将已有正文的“{node['title']}”改为“{new_title}”，"
                "为避免正文文件与章纲错位，本次操作已阻止"
            )
        renumbered.append(change)

    return renumbered, skipped


def _title_number(title: str, kind: str) -> int | None:
    pattern = NUMBERED_TITLE_RE.get(kind)
    match = pattern.search(title) if pattern else None
    return _chapter_token_number(match.group(1)) if match else None


def _replace_title_number(title: str, kind: str, number: int) -> str:
    pattern = NUMBERED_TITLE_RE[kind]
    match = pattern.search(title)
    if not match:
        return title
    token = match.group(1)
    replacement = str(number) if token.isdigit() else _number_to_chinese(number)
    return f"{title[:match.start(1)]}{replacement}{title[match.end(1):]}"


def _shifted_node_id(
    node: dict[str, Any], *, sequence_shift: int, new_number: int
) -> str:
    if node["kind"] == "chapter":
        return f"ch_{new_number:03d}"
    match = re.search(r"_(\d+)$", str(node["id"]))
    if not match:
        return str(node["id"])
    return f"{node['kind']}_{max(1, int(match.group(1)) - sequence_shift):03d}"


def _editable_target(target: dict[str, Any] | None) -> dict[str, Any]:
    if target is None:
        raise OutlineEditError("大纲节点不存在，请刷新结构后重试")
    if not target.get("editable"):
        raise OutlineEditError("附录节点请在 Markdown 原文中编辑")
    return target


def _validate_title(title: str, kind: str) -> str:
    clean = str(title or "").strip()
    if not clean or len(clean) > 160:
        raise OutlineEditError("标题不能为空且不能超过 160 字")
    if "\n" in clean or "\r" in clean or clean.startswith("#"):
        raise OutlineEditError("标题不能包含换行或 Markdown 标题符号")
    if kind not in OUTLINE_KINDS:
        raise OutlineEditError("无效的大纲层级")
    if kind == "volume" and "附录" in clean:
        raise OutlineEditError("附录请在 Markdown 原文中维护，卷标题不能命名为附录")
    return clean


def _validate_summary(summary: str) -> str:
    clean = str(summary or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if len(clean) > 20000:
        raise OutlineEditError("节点内容不能超过 20000 字")
    for line in clean.splitlines():
        if HEADING_RE.match(line.strip()):
            raise OutlineEditError("节点内容不能包含 Markdown 标题，请用新增或改名调整大纲层级")
    return clean


def _direct_body_end(lines: list[str], start: int) -> int:
    for index in range(start, len(lines)):
        if HEADING_RE.match(lines[index].strip()):
            return index
    return len(lines)


def _direct_summary_span(lines: list[str], start: int, end: int) -> tuple[int, int]:
    """Locate the prose synopsis before structured metadata in a node body."""
    cursor = start
    while cursor < end and not lines[cursor].strip():
        cursor += 1
    if cursor >= end or _is_structured_outline_line(lines[cursor]):
        return start, start

    cursor += 1
    while cursor < end and not _is_structured_outline_line(lines[cursor]):
        cursor += 1
    return start, cursor


def _is_structured_outline_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith(">") or bool(
        re.match(
            r"^\*\*(节拍|悬念|涉及人物|本章目标|beats|hooks)",
            stripped,
            re.IGNORECASE,
        )
    )


def _summary_block(summary: str, *, has_following: bool) -> list[str]:
    if not summary:
        return ["\n"] if has_following else []
    block = ["\n"]
    for line in summary.splitlines():
        block.append(f"{line.rstrip()}\n" if line.strip() else "\n")
    block.append("\n")
    return block


def _heading_block(
    lines: list[str], insert_index: int, level: int, title: str
) -> tuple[list[str], int]:
    before_blank = insert_index == 0 or not lines[insert_index - 1].strip()
    after_blank = insert_index < len(lines) and not lines[insert_index].strip()
    block: list[str] = []
    if not before_blank:
        block.append("\n")
    heading_offset = len(block)
    block.append(f"{'#' * level} {title}\n")
    if not after_blank:
        block.append("\n")
    return block, heading_offset


def _node_kind(level: int, title: str, inside_appendix: bool) -> str:
    if inside_appendix:
        return "appendix"
    if level == 1:
        return "appendix" if "附录" in title else "volume"
    return {2: "act", 3: "section", 4: "chapter"}[level]


def _node_id(kind: str, title: str, sequence: int, level: int) -> str:
    if kind == "chapter":
        match = CHAPTER_ID_RE.search(title) or CHAPTER_RE.search(title)
        if match:
            return f"ch_{_chapter_token_number(match.group(1)):03d}"
    if kind == "appendix":
        return f"appendix_l{level}_{sequence:03d}"
    return f"{kind}_{sequence:03d}"


def _kind_label(kind: str) -> str:
    return {
        "volume": "卷",
        "act": "幕",
        "section": "节",
        "chapter": "章",
        "appendix": "附",
    }.get(kind, "项")


def _summarize_block(
    lines: list[str],
    *,
    kind: str = "",
    fallback: str = "",
    limit: int = 720,
) -> str:
    content: list[str] = []
    metadata: dict[str, str] = {}
    in_structured_list = False
    for raw in lines:
        line = raw.strip()
        if not line or line == "---" or line.startswith("<!--"):
            continue
        if line.startswith(">"):
            cleaned = re.sub(r"^>\s*", "", line)
            cleaned = re.sub(r"[*_`]", "", cleaned).strip()
            match = re.match(r"^(.+?)\s*[:：]\s*(.+)$", cleaned)
            if match:
                metadata[match.group(1).strip()] = match.group(2).strip()
            continue
        if re.match(r"^\*\*(节拍|悬念|涉及人物|本章目标|beats|hooks)", line, re.IGNORECASE):
            in_structured_list = True
            continue
        if in_structured_list and re.match(r"^(?:[-*]|\d+\.)\s+", line):
            continue
        in_structured_list = False
        line = re.sub(r"^[-*\d.\s]+", "", line)
        line = re.sub(r"[*_`]", "", line).strip()
        if line:
            content.append(line)
        if sum(len(item) for item in content) >= limit:
            break
    summary = "\n".join(content).strip()
    if not summary:
        fallback_keys = {
            "volume": ("故事简介", "简介"),
            "act": ("摘要", "篇梗概", "篇主题", "主题"),
            "section": ("摘要", "节梗概", "目的"),
            "chapter": ("摘要", "章梗概", "内容焦点"),
        }
        summary = next(
            (metadata[key] for key in fallback_keys.get(kind, ()) if metadata.get(key)),
            fallback,
        )
    return summary[:limit]


def _body_block(lines: list[str]) -> str:
    start = 0
    end = len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return "\n".join(lines[start:end]).rstrip("\n")


def _recommend_chapter(
    roots: list[dict[str, Any]],
    flat: list[dict[str, Any]],
    drafted: set[str],
    *,
    requested: str,
    target_words: int,
) -> dict[str, Any] | None:
    del roots
    chapters = [node for node in flat if node["kind"] == "chapter"]
    requested_id = _canonical_chapter_id(requested)
    candidate = next((node for node in chapters if node["id"] == requested_id), None)
    if candidate is None:
        candidate = next((node for node in chapters if node["id"] not in drafted), None)
    if candidate is None:
        return None

    ancestors = _ancestor_nodes(candidate, flat)
    section = next((node for node in reversed(ancestors) if node["kind"] == "section"), None)
    act = next((node for node in reversed(ancestors) if node["kind"] == "act"), None)
    volume = next((node for node in reversed(ancestors) if node["kind"] == "volume"), None)
    focus = candidate["summary"] or (section or {}).get("summary", "")
    explicit_target = _explicit_chapter_target(str(candidate.get("content") or ""))
    guidance_parts = [f"按章纲推进「{_clean_planned(candidate['title'])}」。"]
    if section:
        guidance_parts.append(f"所属节：{section['title']}。")
    if focus:
        guidance_parts.append(f"大纲上下文：{focus[:900]}")
    guidance_parts.append("仅写本章正文，不提前透支后续章纲；完成后保持 truth、memory 与 workflow 同步。")
    return {
        "chapter_id": candidate["id"],
        "title": _clean_planned(candidate["title"]),
        "status": candidate["status"],
        "line": candidate["line"],
        "breadcrumb": [
            node["title"] for node in (volume, act, section, candidate) if node
        ],
        "target_words": explicit_target or target_words,
        "target_source": "outline" if explicit_target else "project_or_recent",
        "guidance": "\n".join(guidance_parts),
        "reason": "大纲中最早尚未生成正文的章纲" if not requested_id else "用户选择的章纲",
    }


def _ancestor_nodes(node: dict[str, Any], flat: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {item["id"]: item for item in flat}
    result: list[dict[str, Any]] = []
    parent_id = node.get("parent_id")
    while parent_id and parent_id in by_id:
        parent = by_id[parent_id]
        result.append(parent)
        parent_id = parent.get("parent_id")
    return list(reversed(result))


def _smart_target_words(root: Path) -> int:
    recent = sorted(
        (root / "data" / "manuscript").rglob("ch_*.md"),
        key=lambda path: _chapter_number(path.stem),
    )[-3:]
    counts = [_writing_units(path.read_text(encoding="utf-8")) for path in recent]
    if not counts:
        return 3000
    average = round((sum(counts) / len(counts)) / 100) * 100
    return max(1000, min(8000, average))


def _writing_units(text: str) -> int:
    without_headings = re.sub(r"^\s{0,3}#{1,6}\s+.*$", "", text, flags=re.MULTILINE)
    cjk = re.findall(r"[\u3400-\u4dbf\u4e00-\u9fff]", without_headings)
    latin = re.findall(
        r"[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*",
        re.sub(r"[\u3400-\u4dbf\u4e00-\u9fff]", " ", without_headings),
    )
    return len(cjk) + len(latin)


def _explicit_chapter_target(content: str) -> int:
    match = re.search(r"(?:预估字数|目标字数)\s*[:：]\s*([\d,]+)", content)
    if not match:
        return 0
    value = int(match.group(1).replace(",", ""))
    return value if 200 <= value <= 12_000 else 0


def _canonical_chapter_id(value: str) -> str:
    match = CHAPTER_ID_RE.search(str(value or "")) or CHAPTER_RE.search(str(value or ""))
    return f"ch_{_chapter_token_number(match.group(1)):03d}" if match else ""


def _chapter_token_number(value: str) -> int:
    if value.isdigit():
        return int(value)
    digits = {
        "零": 0,
        "〇": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    small_units = {"十": 10, "百": 100, "千": 1000}
    total = section = digit = 0
    for character in value:
        if character in digits:
            digit = digits[character]
        elif character in small_units:
            section += (digit or 1) * small_units[character]
            digit = 0
        elif character == "万":
            total += (section + digit) * 10_000
            section = digit = 0
    return total + section + digit


def _number_to_chinese(value: int) -> str:
    if value <= 0:
        return "零"
    digits = "零一二三四五六七八九"

    def below_ten_thousand(number: int) -> str:
        units = ("", "十", "百", "千")
        result = ""
        pending_zero = False
        for position in range(3, -1, -1):
            divisor = 10**position
            digit = number // divisor
            number %= divisor
            if digit:
                if pending_zero and result:
                    result += "零"
                if not (position == 1 and digit == 1 and not result):
                    result += digits[digit]
                result += units[position]
                pending_zero = False
            elif result and number:
                pending_zero = True
        return result

    high, low = divmod(value, 10_000)
    if not high:
        return below_ten_thousand(low)
    result = f"{below_ten_thousand(high)}万"
    if not low:
        return result
    if low < 1000:
        result += "零"
    return result + below_ten_thousand(low)


def _chapter_number(value: str) -> int:
    match = re.search(r"(\d+)", value)
    return int(match.group(1)) if match else 0


def _clean_planned(title: str) -> str:
    return re.sub(r"[（(]拟定[）)]", "", title).strip()


def _empty_structure() -> dict[str, Any]:
    return {
        "path": "src/outline.md",
        "revision": "",
        "roots": [],
        "counts": {"volume": 0, "act": 0, "section": 0, "chapter": 0, "appendix": 0},
        "drafted_chapters": 0,
        "recommendation": None,
    }
