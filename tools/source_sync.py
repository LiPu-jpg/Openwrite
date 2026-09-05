"""Shared source/runtime sync freshness helpers.

`src/` 是人工和 agent 共读的 canonical 真源，`data/` 里有一部分文件只是派生缓存。
这个模块只做两件事：
- 判断这些派生文件是否已经落后于 `src/`
- 在运行时读取前尽量自动修复，修不好就硬失败
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict


def collect_sync_status(project_root: Path, novel_id: str) -> Dict[str, Any]:
    """Collect freshness status between ``src`` and derived ``data`` files."""
    novel_root = Path(project_root) / "data" / "novels" / novel_id
    src_root = novel_root / "src"
    data_root = novel_root / "data"

    outline_src = src_root / "outline.md"
    hierarchy = data_root / "hierarchy.yaml"

    # outline/hierarchy 和 characters/cards 都属于从 src 派生的缓存，因此这里检查的是“新鲜度”，不是“业务完整度”。
    outline_pending = False
    if outline_src.exists():
        outline_pending = (not hierarchy.exists()) or (
            hierarchy.exists() and outline_src.stat().st_mtime > hierarchy.stat().st_mtime
        )

    profiles_dir = src_root / "characters"
    cards_dir = data_root / "characters" / "cards"
    profile_paths = {p.stem: p for p in profiles_dir.glob("*.md")} if profiles_dir.exists() else {}
    card_paths = {p.stem: p for p in cards_dir.glob("*.yaml")} if cards_dir.exists() else {}

    profile_stems = set(profile_paths)
    card_stems = set(card_paths)
    missing_cards = sorted(profile_stems - card_stems)
    extra_cards = sorted(card_stems - profile_stems)
    stale_cards = sorted(
        stem
        for stem in sorted(profile_stems & card_stems)
        if profile_paths[stem].stat().st_mtime > card_paths[stem].stat().st_mtime
    )

    # 章节记忆/真相属于“写章管线结算产物”，不是 src 派生缓存：既有/导入章节
    # 若从未结算会一直缺记忆。这里只做信息性统计（不进入 needs_sync，避免
    # ensure_runtime_fresh 因无法自动修复而硬失败）；真正的回填见
    # tools/settle_backfill.py（任务类型 settle_backfill）。
    manuscript_dir = data_root / "manuscript"
    drafted_stems = (
        sorted({p.stem for p in manuscript_dir.rglob("ch_*.md")})
        if manuscript_dir.is_dir()
        else []
    )
    memory_dir = data_root / "memory" / "chapters"
    memory_stems = (
        {p.stem for p in memory_dir.glob("ch_*.yaml")} if memory_dir.is_dir() else set()
    )
    memory_missing = sorted(set(drafted_stems) - memory_stems)

    return {
        "novel_id": novel_id,
        "outline_pending": outline_pending,
        "profiles": len(profile_stems),
        "cards": len(card_stems),
        "missing_cards": missing_cards,
        "extra_cards": extra_cards,
        "stale_cards": stale_cards,
        "drafted_chapters": len(drafted_stems),
        "memory_count": len(memory_stems),
        "memory_missing": memory_missing,
        "memory_missing_count": len(memory_missing),
        "needs_sync": outline_pending or bool(missing_cards) or bool(stale_cards),
    }


def run_sync(
    project_root: Path,
    novel_id: str,
    *,
    sync_outline: bool = True,
    sync_characters: bool = True,
) -> None:
    """Execute src -> data synchronization."""
    from tools.outline_sync import sync_outline_to_hierarchy
    from tools.character_sync import sync_all_profiles_to_cards

    novel_root = Path(project_root) / "data" / "novels" / novel_id
    src_root = novel_root / "src"
    data_root = novel_root / "data"
    data_root.mkdir(parents=True, exist_ok=True)

    # 只同步存在且已请求的派生物，避免无关目录被意外创建或刷新。
    outline_src = src_root / "outline.md"
    if sync_outline and outline_src.exists():
        sync_outline_to_hierarchy(src_root, data_root)

    if sync_characters:
        sync_all_profiles_to_cards(src_root, data_root)


def ensure_runtime_fresh(project_root: Path, novel_id: str) -> Dict[str, Any]:
    """Auto-sync stale derived files before runtime readers consume them.

    Returns the final status and whether an auto-sync occurred.
    Raises RuntimeError when files are still stale after attempting sync.
    """
    # 运行时优先尝试“自动纠偏一次”，让普通读取链不必手工先跑 sync。
    before = collect_sync_status(project_root, novel_id)
    if not before["needs_sync"]:
        return {**before, "auto_synced": False}

    run_sync(
        project_root,
        novel_id,
        sync_outline=before["outline_pending"],
        sync_characters=bool(before["missing_cards"] or before["stale_cards"]),
    )
    # 如果自动同步后仍然陈旧，就说明不是简单 freshness 问题，而是源文件/格式本身异常。
    after = collect_sync_status(project_root, novel_id)
    if after["needs_sync"]:
        raise RuntimeError(
            "检测到未同步或格式异常的源文件，请先运行 `openwrite sync --check` 排查后再继续。"
        )
    return {**after, "auto_synced": True}
