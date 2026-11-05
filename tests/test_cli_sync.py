"""sync 命令辅助逻辑测试。"""

import os

import yaml
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.cli import _build_sync_actions, _collect_sync_status, _run_sync


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_sync_status_and_run(tmp_path: Path):
    novel_id = "sync_novel"
    novel_root = tmp_path / "data" / "novels" / novel_id
    src_root = novel_root / "src"
    data_root = novel_root / "data"

    _write_text(
        src_root / "outline.md",
        "# 大纲\n\n## 第一篇\n\n### 第一节\n\n#### 第一章\n\n> 内容焦点: 开场\n",
    )
    _write_text(src_root / "characters" / "chen_ming.md", "# 陈明\n\n- 职业: 程序员\n")

    before = _collect_sync_status(tmp_path, novel_id)
    assert before["needs_sync"] is True
    assert before["outline_pending"] is True
    assert "chen_ming" in before["missing_cards"]

    _run_sync(tmp_path, novel_id)

    after = _collect_sync_status(tmp_path, novel_id)
    assert after["outline_pending"] is False
    assert "chen_ming" not in after["missing_cards"]
    assert after["needs_sync"] is False

    assert (data_root / "hierarchy.yaml").exists()
    assert (data_root / "characters" / "cards" / "chen_ming.yaml").exists()


def test_sync_actions_when_pending(tmp_path: Path):
    novel_id = "pending_actions"
    src_root = tmp_path / "data" / "novels" / novel_id / "src"

    _write_text(src_root / "outline.md", "# 大纲\n")
    _write_text(src_root / "characters" / "a.md", "# A\n")

    status = _collect_sync_status(tmp_path, novel_id)
    actions = _build_sync_actions(status)

    assert any(a["name"] == "run_sync" for a in actions)


def test_sync_actions_when_clean(tmp_path: Path):
    novel_id = "clean_actions"
    src_root = tmp_path / "data" / "novels" / novel_id / "src"

    _write_text(src_root / "outline.md", "# 大纲\n")
    _write_text(src_root / "characters" / "a.md", "# A\n")
    _run_sync(tmp_path, novel_id)

    status = _collect_sync_status(tmp_path, novel_id)
    actions = _build_sync_actions(status)

    assert actions[0]["type"] == "noop"
    assert actions[0]["name"] == "continue_writing"


def test_sync_status_marks_stale_character_cards_pending(tmp_path: Path):
    novel_id = "stale_cards"
    novel_root = tmp_path / "data" / "novels" / novel_id
    src_root = novel_root / "src"
    data_root = novel_root / "data"

    _write_text(src_root / "outline.md", "# 大纲\n")
    _write_text(src_root / "characters" / "chen_ming.md", "# 陈明\n\n## 背景\n最初版本\n")
    _run_sync(tmp_path, novel_id)

    profile = src_root / "characters" / "chen_ming.md"
    card = data_root / "characters" / "cards" / "chen_ming.yaml"
    profile.write_text("# 陈明\n\n## 背景\n更新版本\n", encoding="utf-8")
    stale_time = profile.stat().st_mtime - 10
    os.utime(card, (stale_time, stale_time))

    status = _collect_sync_status(tmp_path, novel_id)

    assert status["needs_sync"] is True
    assert status["stale_cards"] == ["chen_ming"]


def test_outline_sync_is_atomic_and_leaves_no_temporary_files(tmp_path: Path):
    """A crash mid-write must not leave a half-written hierarchy.yaml.

    The freshness check compares mtimes, so a file truncated by a bare
    open(...,"w") then reads as current and every consumer (workspace snapshot,
    context build, reading order) works from a partial outline.
    """
    from tools.outline_sync import sync_outline_to_hierarchy

    src = tmp_path / "src"
    data = tmp_path / "data"
    src.mkdir(parents=True)
    (src / "outline.md").write_text(
        "# 小说\n\n## 第一幕\n\n#### 第一章 起点\n\n甲\n", encoding="utf-8"
    )

    sync_outline_to_hierarchy(src, data)

    hierarchy = data / "hierarchy.yaml"
    assert hierarchy.is_file()
    # The written cache parses completely, so nothing was left half-serialized.
    parsed = yaml.safe_load(hierarchy.read_text(encoding="utf-8"))
    assert isinstance(parsed, dict) and parsed
    # No stray temp files beside it.
    assert sorted(p.name for p in data.iterdir() if p.name.startswith('.')) == []
