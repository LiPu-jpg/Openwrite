"""Silent-loss and ambiguity defects in the context builder, outline editor and
task surface.

Each of these used to drop or mis-route author data with no signal.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tools.init_project import init_project


@pytest.fixture()
def project(tmp_path: Path):
    init_project(tmp_path, "demo", template="demo_short")
    return tmp_path


# ── M5: the banned-phrase list must be deterministic ────────────────────────
def test_banned_phrases_are_deterministic(project: Path):
    from tools.context_builder import ContextBuilder

    craft = project / "craft"
    craft.mkdir(parents=True, exist_ok=True)
    (craft / "humanization.yaml").write_text(
        yaml.safe_dump(
            {"banned_phrases": [{"phrase": f"短语{i}"} for i in range(25)]},
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    builder = ContextBuilder(project, "demo")
    runs = {tuple(builder._load_banned_phrases()) for _ in range(6)}
    assert len(runs) == 1, "the banned-phrase order must not vary between runs"


# ── M6: a chapter's tasks must survive a large task store ───────────────────
def test_a_chapters_tasks_survive_a_large_task_store(project: Path):
    from tools.task_store import TaskStore

    store = TaskStore(project, "demo")
    # The chapter's tasks are the OLDEST ones and the store holds more tasks
    # than the limit, so a store that applied the limit before the filter
    # would return nothing at all. Interleaving the chapters instead — as an
    # earlier revision of this test did — let a limit-then-filter
    # implementation pass, because the chapter's tasks were still inside the
    # newest window.
    for _ in range(6):
        store.create("chapter_review", {}, chapter_id="ch_001")
    for index in range(40):
        store.create("chapter_review", {}, chapter_id=f"ch_{index % 2 + 2:03d}")
    # Filtering happens inside the store, before the limit is applied.
    found = store.list(limit=10, chapter_id="ch_001")
    assert len(found) == 6, "the chapter's tasks must not be lost to the limit"
    assert all(store._task_chapter(item) == "ch_001" for item in found)


# ── M7a: a duplicate node id must not silently target the wrong node ────────
def test_a_duplicate_node_id_is_refused_not_guessed(project: Path):
    from tools.outline_tree import OutlineEditError, build_outline_structure, mutate_outline_structure

    outline = project / "data/novels/demo/src/outline.md"
    # `####` is the chapter level in this format.
    outline.write_text(
        "# 第一卷\n\n## 第一幕\n\n#### 第一章：晴日\n\n甲\n\n#### 第一章：雨夜\n\n乙\n",
        encoding="utf-8",
    )
    structure = build_outline_structure(project / "data/novels/demo")
    chapters = [node for node in _walk(structure["roots"][0]) if node["kind"] == "chapter"]
    ids = [node["id"] for node in chapters]
    assert len(ids) == 2 and ids[0] == ids[1], f"fixture must produce a duplicate id, got {ids}"
    with pytest.raises(OutlineEditError) as refused:
        mutate_outline_structure(
            project / "data/novels/demo",
            operation="set_meta",
            revision=structure["revision"],
            node_id=ids[0],
            metadata={"summary": "改第一个"},
        )
    assert refused.value.code == "conflict"


# ── M7b: promote must renumber rather than leave a gap ──────────────────────
def test_promote_renumbers_instead_of_leaving_a_gap(project: Path):
    from tools.outline_tree import build_outline_structure, mutate_outline_structure

    root = project / "data/novels/demo"
    (root / "src/outline.md").write_text(
        "# 第一卷\n\n## 第一幕\n\n#### 第一章：起点\n\n甲\n\n"
        "# 第二卷\n\n## 第二幕\n\n#### 第二章：转折\n\n乙\n",
        encoding="utf-8",
    )
    before = build_outline_structure(root)
    volume = next(node for node in before["roots"] if node["kind"] == "volume")
    result = mutate_outline_structure(
        root, operation="promote", revision=before["revision"], node_id=volume["id"]
    )
    after = build_outline_structure(root)
    chapters = [
        node["id"]
        for node in after["roots"]
        for node in _walk(node)
    ]
    assert "ch_001" in chapters, f"numbering must be contiguous: {chapters}"
    assert result["renumbered"], "promote must report the renumbering it did"


def _walk(node: dict) -> list[dict]:
    yield node
    for child in node.get("children") or []:
        yield from _walk(child)
