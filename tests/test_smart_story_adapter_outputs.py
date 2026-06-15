from __future__ import annotations

from pathlib import Path

from tools.smart_story_adapter.outputs import collect_private_drafts


def test_collect_private_drafts_from_manuscript_tree(tmp_path: Path) -> None:
    root = tmp_path
    chapter = root / "data" / "novels" / "demo" / "data" / "manuscript" / "arc_001" / "ch_001.md"
    chapter.parent.mkdir(parents=True)
    chapter.write_text("# Chương 1\n\nNội dung bản nháp tiếng Việt.", encoding="utf-8")

    drafts = collect_private_drafts(root, "demo", "abc123", "main")

    assert len(drafts) == 1
    assert drafts[0]["output_key"] == "chapter-number-1"
    assert drafts[0]["source_path"] == "data/novels/demo/data/manuscript/arc_001/ch_001.md"
    assert drafts[0]["commit_sha"] == "abc123"
    assert drafts[0]["branch"] == "main"
