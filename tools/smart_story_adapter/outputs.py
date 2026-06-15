from __future__ import annotations

import re
from pathlib import Path


def collect_private_drafts(workspace: Path, novel_id: str, commit_sha: str, branch: str) -> list[dict]:
    manuscript_root = workspace / "data" / "novels" / novel_id / "data" / "manuscript"
    drafts: list[dict] = []
    if not manuscript_root.exists():
        return drafts

    for path in sorted(manuscript_root.glob("**/ch_*.md")):
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            continue
        rel = path.relative_to(workspace).as_posix()
        number = _chapter_number(path.stem)
        drafts.append(
            {
                "output_key": f"chapter-number-{number}" if number is not None else f"path-{path.stem}",
                "source_path": rel,
                "commit_sha": commit_sha,
                "branch": branch,
                "content": content,
                "chapter_number": number,
                "title": _title(content),
                "summary": None,
                "word_count": len(re.findall(r"\S+", content)),
                "metadata": {"runtime": "openwrite", "collector": "manuscript"},
            }
        )
    return drafts


def _chapter_number(stem: str) -> int | None:
    match = re.search(r"(\d+)", stem)
    return int(match.group(1)) if match else None


def _title(content: str) -> str | None:
    for line in content.splitlines():
        if line.startswith("#"):
            return line.lstrip("#").strip()
    return None
