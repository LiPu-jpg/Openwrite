"""Project-configured previous-chapter context shared by both assemblers."""

from pathlib import Path

import yaml


def select_previous_context(project_root: Path, novel_id: str, chapter_id: str, text: str) -> str:
    config_path = project_root / "novel_config.yaml"
    config = (
        (yaml.safe_load(config_path.read_text(encoding="utf-8")) or {})
        if config_path.is_file()
        else {}
    )
    mode = config.get("previous_chapter_mode", "full")
    if mode not in {"full", "tail", "summary"}:
        raise ValueError("previous_chapter_mode must be full, tail, or summary")
    if mode == "full":
        return text
    if mode == "tail":
        limit = config.get("previous_chapter_tail_chars", 800)
        if type(limit) is not int or not 1 <= limit <= 50000:
            raise ValueError("previous_chapter_tail_chars must be an integer between 1 and 50000")
        return text[-limit:]
    number = int(chapter_id.split("_")[-1])
    if number <= 1:
        return ""
    from tools.chapter_memory import ChapterMemoryStore

    memory = ChapterMemoryStore(project_root, novel_id).load(f"ch_{number - 1:03d}")
    if not memory or memory.get("freshness_status") != "current" or not memory.get("summary"):
        raise ValueError(
            "previous_chapter_mode=summary requires a current previous-chapter memory; "
            "run settle backfill first"
        )
    return str(memory["summary"])
