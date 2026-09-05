from __future__ import annotations

from pathlib import Path

import pytest

from tools.reading_order import ReadingOrderError, ReadingOrderService


def _outline(*chapters: tuple[int, str]) -> str:
    by_volume: dict[int, list[str]] = {}
    for volume, chapter_id in chapters:
        number = int(chapter_id.removeprefix("ch_"))
        by_volume.setdefault(volume, []).append(
            f"#### 第{number}章：{chapter_id}\n\n{chapter_id} 的大纲。\n"
        )
    blocks = []
    for volume, items in by_volume.items():
        blocks.append(
            f"# 第{volume}卷\n\n## 第{volume}幕\n\n### 第{volume}节\n\n" + "\n".join(items)
        )
    return "\n".join(blocks)


def _project(
    root: Path,
    *,
    novel_id: str = "demo",
    outline_chapters: tuple[tuple[int, str], ...] = (
        (1, "ch_001"),
        (1, "ch_002"),
        (2, "ch_003"),
        (2, "ch_004"),
    ),
    files: tuple[tuple[str, str, str], ...] = (
        ("arc_001", "ch_001", "第一章正文"),
        ("arc_001", "ch_002", "第二章正文"),
        ("arc_002", "ch_003", "第三章正文"),
        ("arc_002", "ch_004", "第四章正文"),
    ),
) -> Path:
    novel = root / "data" / "novels" / novel_id
    outline = novel / "src" / "outline.md"
    outline.parent.mkdir(parents=True, exist_ok=True)
    outline.write_text(_outline(*outline_chapters), encoding="utf-8")
    for arc_id, chapter_id, content in files:
        path = novel / "data" / "manuscript" / arc_id / f"{chapter_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {chapter_id}\n\n{content}\n", encoding="utf-8")
    return novel


def _by_chapter(surface: dict, chapter_id: str) -> list[dict]:
    return [item for item in surface["documents"] if item["chapter_id"] == chapter_id]


def test_duplicate_chapter_ids_and_missing_files_are_visible_and_block_mutation(
    tmp_path: Path,
) -> None:
    novel = _project(
        tmp_path,
        outline_chapters=((1, "ch_001"), (1, "ch_002")),
        files=(
            ("arc_001", "ch_001", "原始正文 A"),
            ("arc_002", "ch_001", "重复正文 B"),
        ),
    )
    service = ReadingOrderService(tmp_path, "demo")

    surface = service.surface()

    duplicates = _by_chapter(surface, "ch_001")
    assert len(duplicates) == 2
    assert len({item["document_id"] for item in duplicates}) == 2
    assert len({item["occurrence_id"] for item in surface["documents"]}) == len(
        surface["documents"]
    )
    assert {item["path"] for item in duplicates} == {
        "data/manuscript/arc_001/ch_001.md",
        "data/manuscript/arc_002/ch_001.md",
    }
    assert _by_chapter(surface, "ch_002")[0]["status"] == "missing"
    assert {item["code"] for item in surface["issues"]} >= {
        "DUPLICATE_CHAPTER_ID",
        "MISSING_CHAPTER_FILE",
    }
    assert surface["mutation_allowed"] is False
    assert all(
        {
            "document_id",
            "occurrence_id",
            "reading_index",
            "revision",
            "writing_units",
            "updated_at",
        }
        <= item.keys()
        for item in surface["documents"]
    )
    assert all(item["revision"] == item["content_sha256"] for item in surface["documents"])
    assert all(item["updated_at"] for item in surface["documents"] if item["status"] != "missing")

    before = {path: path.read_bytes() for path in novel.rglob("*.md")}
    with pytest.raises(ReadingOrderError) as rejected:
        service.move(
            document_id=duplicates[0]["document_id"],
            target_volume_id=surface["volumes"][0]["volume_id"],
            target_index=0,
            expected_revision=surface["revision"],
        )
    assert rejected.value.code == "AMBIGUOUS_READING_ORDER"
    assert {path: path.read_bytes() for path in novel.rglob("*.md")} == before


def test_duplicate_outline_occurrences_keep_same_document_visible_twice(
    tmp_path: Path,
) -> None:
    _project(
        tmp_path,
        outline_chapters=((1, "ch_001"), (1, "ch_001")),
        files=(("arc_001", "ch_001", "唯一正文"),),
    )

    surface = ReadingOrderService(tmp_path, "demo").surface()
    occurrences = _by_chapter(surface, "ch_001")

    assert len(occurrences) == 2
    assert occurrences[0]["path"] == occurrences[1]["path"]
    assert occurrences[0]["document_id"] == occurrences[1]["document_id"]
    assert occurrences[0]["occurrence_id"] != occurrences[1]["occurrence_id"]
    assert occurrences[0]["revision"] == occurrences[1]["revision"]
    issue = next(
        item for item in surface["issues"] if item["code"] == "DUPLICATE_OUTLINE_CHAPTER_ID"
    )
    assert issue["occurrence_ids"] == [item["occurrence_id"] for item in occurrences]
    assert "MISSING_CHAPTER_FILE" not in {item["code"] for item in surface["issues"]}
    assert surface["mutation_allowed"] is False

    with pytest.raises(ReadingOrderError) as ambiguous:
        ReadingOrderService(tmp_path, "demo").packet(occurrences[0]["document_id"])
    assert ambiguous.value.code == "READING_DOCUMENT_AMBIGUOUS"
    packet = ReadingOrderService(tmp_path, "demo").packet(
        occurrences[1]["occurrence_id"], before=0, after=0
    )
    assert packet["anchor_occurrence_id"] == occurrences[1]["occurrence_id"]


def test_planned_unwritten_chapters_remain_visible_without_blocking_safe_moves(
    tmp_path: Path,
) -> None:
    _project(
        tmp_path,
        outline_chapters=((1, "ch_001"), (1, "ch_002")),
        files=(("arc_001", "ch_001", "已写正文"),),
    )
    service = ReadingOrderService(tmp_path, "demo")
    surface = service.surface()

    planned = _by_chapter(surface, "ch_002")[0]
    missing = next(
        item
        for item in surface["issues"]
        if item["code"] == "MISSING_CHAPTER_FILE"
    )
    assert planned["status"] == "missing"
    assert missing["blocking"] is False
    assert surface["mutation_allowed"] is True

    written = _by_chapter(surface, "ch_001")[0]
    moved = service.move(
        document_id=written["document_id"],
        target_volume_id=surface["volumes"][0]["volume_id"],
        target_index=1,
        expected_revision=surface["revision"],
    )["reading_order"]
    assert [item["chapter_id"] for item in moved["documents"]] == [
        "ch_002",
        "ch_001",
    ]


def test_cross_volume_move_preserves_identity_content_and_navigation(tmp_path: Path) -> None:
    novel = _project(tmp_path)
    service = ReadingOrderService(tmp_path, "demo")
    before = service.surface()
    moved = _by_chapter(before, "ch_002")[0]
    target_volume = before["volumes"][1]
    original = (novel / moved["path"]).read_bytes()

    result = service.move(
        document_id=moved["document_id"],
        target_volume_id=target_volume["volume_id"],
        target_index=1,
        expected_revision=before["revision"],
    )

    after = result["reading_order"]
    moved_after = _by_chapter(after, "ch_002")[0]
    assert moved_after["document_id"] == moved["document_id"]
    assert moved_after["path"] == "data/manuscript/arc_002/ch_002.md"
    assert (novel / moved_after["path"]).read_bytes() == original
    assert not (novel / moved["path"]).exists()
    assert [item["chapter_id"] for item in after["documents"]] == [
        "ch_001",
        "ch_003",
        "ch_002",
        "ch_004",
    ]
    assert moved_after["previous_document_id"] == _by_chapter(after, "ch_003")[0]["document_id"]
    assert moved_after["next_document_id"] == _by_chapter(after, "ch_004")[0]["document_id"]

    packet = service.packet(moved_after["document_id"], before=1, after=1)
    assert packet["revision"] == after["revision"]
    assert [item["chapter_id"] for item in packet["documents"]] == [
        "ch_003",
        "ch_002",
        "ch_004",
    ]
    assert packet["documents"][1]["content"].endswith("第二章正文\n")


def test_cross_volume_move_into_empty_volume_uses_target_section(tmp_path: Path) -> None:
    novel = _project(
        tmp_path,
        outline_chapters=((1, "ch_001"),),
        files=(("arc_001", "ch_001", "不可丢失的正文"),),
    )
    outline = novel / "src" / "outline.md"
    outline.write_text(
        _outline((1, "ch_001")) + "\n# 第2卷\n\n## 第2幕\n\n### 第2节\n",
        encoding="utf-8",
    )
    service = ReadingOrderService(tmp_path, "demo")
    before = service.surface()
    document = before["documents"][0]

    result = service.move(
        document_id=document["occurrence_id"],
        target_volume_id=before["volumes"][1]["volume_id"],
        target_index=0,
        expected_revision=before["revision"],
    )

    after = result["reading_order"]
    moved = after["documents"][0]
    assert moved["volume"]["volume_id"] == before["volumes"][1]["volume_id"]
    assert moved["path"] == "data/manuscript/arc_002/ch_001.md"
    assert (novel / moved["path"]).read_text(encoding="utf-8").endswith("不可丢失的正文\n")
    final_outline = outline.read_text(encoding="utf-8")
    assert final_outline.index("### 第2节") < final_outline.index("#### 第1章")


def test_same_volume_noop_accepts_occurrence_id(tmp_path: Path) -> None:
    novel = _project(tmp_path)
    service = ReadingOrderService(tmp_path, "demo")
    before = service.surface()
    document = _by_chapter(before, "ch_002")[0]
    source = novel / document["path"]
    content = source.read_bytes()

    result = service.move(
        document_id=document["occurrence_id"],
        target_volume_id=document["volume"]["volume_id"],
        target_index=1,
        expected_revision=before["revision"],
    )

    assert result["result_revision"] == before["revision"]
    assert source.read_bytes() == content
    assert not (novel / "data/workflows/reading_order_identities.json").exists()


def test_move_rejects_stale_revision_without_touching_files(tmp_path: Path) -> None:
    novel = _project(tmp_path)
    service = ReadingOrderService(tmp_path, "demo")
    surface = service.surface()
    document = _by_chapter(surface, "ch_002")[0]
    outline = novel / "src" / "outline.md"
    outline.write_text(
        outline.read_text(encoding="utf-8") + "\n<!-- external edit -->\n", encoding="utf-8"
    )
    before = {path: path.read_bytes() for path in novel.rglob("*.md")}

    with pytest.raises(ReadingOrderError) as rejected:
        service.move(
            document_id=document["document_id"],
            target_volume_id=surface["volumes"][1]["volume_id"],
            target_index=0,
            expected_revision=surface["revision"],
        )

    assert rejected.value.code == "READING_ORDER_CONFLICT"
    assert rejected.value.details["current_revision"] != surface["revision"]
    assert {path: path.read_bytes() for path in novel.rglob("*.md")} == before


@pytest.mark.parametrize(
    "failed_stage",
    ["document_copied", "outline_replaced", "registry_replaced", "source_removed"],
)
def test_move_rolls_back_every_file_after_transaction_failure(
    tmp_path: Path,
    failed_stage: str,
) -> None:
    novel = _project(tmp_path)
    service = ReadingOrderService(tmp_path, "demo")
    surface = service.surface()
    document = _by_chapter(surface, "ch_002")[0]
    before = {
        path.relative_to(novel): path.read_bytes() for path in novel.rglob("*") if path.is_file()
    }

    def fail(stage: str) -> None:
        if stage == failed_stage:
            raise OSError(f"injected failure at {stage}")

    with pytest.raises(ReadingOrderError) as rejected:
        service.move(
            document_id=document["document_id"],
            target_volume_id=surface["volumes"][1]["volume_id"],
            target_index=0,
            expected_revision=surface["revision"],
            fault_injector=fail,
        )

    assert rejected.value.code == "READING_ORDER_TRANSACTION_FAILED"
    after = {
        path.relative_to(novel): path.read_bytes() for path in novel.rglob("*") if path.is_file()
    }
    assert after == before
    assert service.surface()["revision"] == surface["revision"]


def test_services_are_isolated_by_workspace_root(tmp_path: Path) -> None:
    root_a = tmp_path / "workspace-a"
    root_b = tmp_path / "workspace-b"
    novel_a = _project(
        root_a,
        files=(
            ("arc_001", "ch_001", "A1"),
            ("arc_001", "ch_002", "A2"),
            ("arc_002", "ch_003", "A3"),
            ("arc_002", "ch_004", "A4"),
        ),
    )
    novel_b = _project(
        root_b,
        files=(
            ("arc_001", "ch_001", "B1"),
            ("arc_001", "ch_002", "B2"),
            ("arc_002", "ch_003", "B3"),
            ("arc_002", "ch_004", "B4"),
        ),
    )
    service_a = ReadingOrderService(root_a, "demo")
    service_b = ReadingOrderService(root_b, "demo")
    before_b = {
        path.relative_to(novel_b): path.read_bytes()
        for path in novel_b.rglob("*")
        if path.is_file()
    }
    surface_a = service_a.surface()

    service_a.move(
        document_id=_by_chapter(surface_a, "ch_002")[0]["document_id"],
        target_volume_id=surface_a["volumes"][1]["volume_id"],
        target_index=0,
        expected_revision=surface_a["revision"],
    )

    assert (novel_a / "data/manuscript/arc_002/ch_002.md").is_file()
    assert {
        path.relative_to(novel_b): path.read_bytes()
        for path in novel_b.rglob("*")
        if path.is_file()
    } == before_b
    assert service_b.packet(
        _by_chapter(service_b.surface(), "ch_002")[0]["document_id"], before=0, after=0
    )["documents"][0]["content"].endswith("B2\n")


def test_legacy_project_without_outline_has_deterministic_navigation(tmp_path: Path) -> None:
    novel = tmp_path / "data" / "novels" / "legacy"
    for arc_id, chapter_id in (("arc_001", "ch_002"), ("arc_001", "ch_001"), ("arc_002", "ch_003")):
        path = novel / "data" / "manuscript" / arc_id / f"{chapter_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {chapter_id}\n\n正文\n", encoding="utf-8")

    service = ReadingOrderService(tmp_path, "legacy")
    first = service.surface()
    second = service.surface()

    assert first["mode"] == "legacy_disk_order"
    assert first["revision"] == second["revision"]
    assert first["actual_order"] == second["actual_order"]
    assert [item["chapter_id"] for item in first["documents"]] == [
        "ch_001",
        "ch_002",
        "ch_003",
    ]
    assert first["documents"][1]["previous_document_id"] == first["documents"][0]["document_id"]
