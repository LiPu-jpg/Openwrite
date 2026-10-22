"""Chapter deletion archives and discoverable, byte-preserving draft recovery."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from tools.chapter_run_v2 import ChapterRunV2Store
from tools.manuscript_acceptance import ManuscriptAcceptanceService
from tools.novel_workspace import count_writing_units


def archive_chapter_artifacts(novel_root: Path, chapter_id: str, operation_id: str) -> str:
    """Move derived data out of active stores without discarding recovery history."""
    data = novel_root / "data"
    archive = data / "chapter_deletions" / operation_id
    token = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(chapter_id)}(?![A-Za-z0-9_])")
    run_ids: set[str] = set()

    def move(path: Path) -> None:
        target = archive / path.relative_to(data)
        target.parent.mkdir(parents=True, exist_ok=True)
        path.rename(target)

    for name in (
        "chapter_runs_v2",
        "chapter_runs",
        "dog",
        "reviews",
        "manuscript_versions",
        "snapshots",
        "workflows",
        "revisions",
        "annotations",
    ):
        directory = data / name
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*"), key=lambda p: len(p.parts)):
            if not path.exists() or path.is_symlink():
                continue
            if name == "chapter_runs_v2" and "artifacts" in path.relative_to(directory).parts:
                continue
            if path.name == chapter_id or token.search(path.name):
                move(path)
                continue
            if not path.is_file() or path.suffix not in {".json", ".yaml", ".yml", ".md"}:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            snapshot = re.match(r"snapshot_(\d+)_", path.name)
            if (
                token.search(text)
                or snapshot
                and int(snapshot[1]) >= int(chapter_id.split("_")[-1])
            ):
                if name == "chapter_runs_v2" and path.stem.startswith("runv2_"):
                    run_ids.add(path.stem)
                move(path)
    for run_id in run_ids:
        artifacts = data / "chapter_runs_v2" / "artifacts" / run_id
        if artifacts.is_dir():
            move(artifacts)
    return str(archive.relative_to(novel_root))


def list_drafts(project_root: Path, novel_id: str) -> list[dict[str, Any]]:
    store = ChapterRunV2Store(project_root, novel_id)
    candidates: dict[str, dict[str, Any]] = {}
    manuscript = store.root.parent / "manuscript"
    for pointer in manuscript.rglob("*.uncommitted.json"):
        try:
            record = json.loads(pointer.read_text(encoding="utf-8"))
            run_id = str(record.get("run_id_v2") or "")
            store.path_for(run_id)
        except (OSError, ValueError, AttributeError):
            continue
        candidates[run_id] = {"chapter_id": pointer.name.split(".")[0]}
    for path in (store.root / "artifacts").glob("runv2_*/uncommitted.md"):
        candidates.setdefault(path.parent.name, {})
    drafts = []
    for run_id, pointer in candidates.items():
        path = (store.root / "artifacts" / run_id / "uncommitted.md").resolve()
        if (path.parent / "restored.json").exists():
            continue
        if not path.is_relative_to(store.root.resolve()) or not path.is_file():
            continue
        try:
            run = store.load(run_id)
            content = path.read_text(encoding="utf-8")
        except (OSError, ValueError):
            continue
        drafts.append(
            {
                "chapter_id": run.chapter_id if run else pointer.get("chapter_id", ""),
                "run_id_v2": run_id,
                "draft_path": str(path),
                "draft_artifact": run.stages["draft"].artifact if run else "",
                "word_count": count_writing_units("\n".join(content.splitlines()[1:])),
                "created_at": run.created_at if run else "",
                "draft_revision": ManuscriptAcceptanceService.fingerprint(content),
                "uncommitted": True,
                "restorable": bool(
                    run and not run.archived and run.status not in {"committed", "reviewed"}
                ),
            }
        )
    return sorted(drafts, key=lambda item: item["created_at"], reverse=True)
