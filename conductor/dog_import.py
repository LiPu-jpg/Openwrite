"""Materialize a smart-import run as a DoG integrity/query graph.

The importer remains the owner of chapter creation.  DoG only verifies the
immutable import manifest and the chapter files that the importer reports.
The manifest also records the next asset/outline/canonical-building actions so
an agentic root assertion can surface unfinished post-import setup without
silently modifying the project.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _source_digest(source: Path) -> str:
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_import_artifacts(
    project_root: Path,
    novel_id: str,
    import_id: str,
    source: Path,
    source_format: str,
    arc_id: str,
    imported: list[dict[str, Any]],
    ai_check: dict[str, Any],
    status: str = "completed",
    error: str = "",
) -> dict[str, Any]:
    """Write an import manifest and a DoG graph for one completed import."""
    if not project_root.is_dir() or not novel_id:
        raise ValueError("smart import lacks project root or novel id")
    if not source.is_file():
        raise ValueError(f"import source disappeared: {source}")
    if status not in {"completed", "partial", "failed"}:
        raise ValueError(f"invalid smart import status: {status}")
    if status == "completed" and not imported:
        raise ValueError("smart import produced no chapter records")

    relative_dir = Path("data") / "novels" / novel_id / "data" / "dog" / "imports" / import_id
    artifact_dir = project_root / relative_dir
    chapters: list[dict[str, Any]] = []
    for item in imported:
        chapter_id = str(item.get("chapter_id") or "").strip()
        title = str(item.get("title") or chapter_id).strip()
        if not chapter_id or not chapter_id.startswith("ch_"):
            raise ValueError(f"invalid imported chapter id: {chapter_id}")
        target = (Path("data") / "novels" / novel_id / "data" / "manuscript" / arc_id / f"{chapter_id}.md").as_posix()
        chapters.append({
            "chapterId": chapter_id,
            "title": title,
            "target": target,
            "writingUnits": int(item.get("writing_units") or 0),
        })

    manifest = {
        "schemaVersion": "dsh-novel.import.manifest.v1",
        "recordType": "smart-import",
        "importId": import_id,
        "novelId": novel_id,
        "status": status,
        "error": error[:2000],
        "source": {"name": source.name, "format": source_format, "sha256": _source_digest(source)},
        "arcId": arc_id,
        "chapterCount": len(chapters),
        "chapters": chapters,
        "aiCheck": {
            "status": str(ai_check.get("status") or "unknown"),
            "summary": str(ai_check.get("summary") or "")[:2000],
        },
        "construction": {
            "outline": "pending",
            "assets": "pending",
            "canonicalIndex": "pending",
            "nextActions": [
                "用 Goethe 根据导入章节建立/校准大纲",
                "从正文抽取角色、世界观、进度和正典事件资产",
                "运行跨章节六域评审并确认时间线与伏笔索引",
            ],
        },
    }
    _atomic_write_json(artifact_dir / "import.json", manifest)

    nodes: dict[str, dict[str, Any]] = {
        "root": {
            "kind": "composite",
            "title": f"{import_id} 拆书导入验收",
            "constraint": "hard",
            "target": (relative_dir / "import.json").as_posix(),
            "completion": {
                "op": "all",
                "items": [{"op": "ref", "id": "manifest"}] + [
                    {"op": "ref", "id": f"chapter-{item['chapterId']}"} for item in chapters
                ],
            },
            "verifier": {
                "mode": "agentic",
                "instruction": (
                    "只检查 smart-import manifest 的聚合一致性：确认 chapterCount 与 chapters 数量一致、"
                    "每个 target 都有对应章节记录，并报告 aiCheck 与 construction 中的待办。"
                    "不要修改文件，也不要重新审查全文。"
                ),
            },
        },
        "manifest": {
            "kind": "leaf",
            "title": "导入 manifest 完整性",
            "constraint": "hard",
            "target": (relative_dir / "import.json").as_posix(),
            "verifier": {"mode": "programmatic", "script": "import-record"},
        },
    }
    contains = [{"parent": "root", "child": "manifest", "required": True, "failure": "fatal"}]
    for item in chapters:
        node_id = f"chapter-{item['chapterId']}"
        nodes[node_id] = {
            "kind": "leaf",
            "title": f"{item['chapterId']} {item['title']}",
            "constraint": "hard",
            "target": item["target"],
            "verifier": {"mode": "programmatic", "script": "import-chapter"},
        }
        contains.append({"parent": "root", "child": node_id, "required": True, "failure": "fatal"})

    graph = {
        "schemaVersion": "0.9",
        "id": f"novel-import-{import_id}",
        "root": "root",
        "nodes": nodes,
        "contains": contains,
        "dependsOn": [],
    }
    graph_path = artifact_dir / "dog-graph.json"
    _atomic_write_json(graph_path, graph)
    return {
        "manifest": str(relative_dir / "import.json"),
        "graph_path": str(graph_path),
        "graph": graph,
        "chapters": len(chapters),
    }
