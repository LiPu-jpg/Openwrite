from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tools.scene_structure import SceneStructureError, SceneStructureService


def _project(root: Path, *, novel_id: str = "demo") -> Path:
    novel = root / "data" / "novels" / novel_id
    outline = novel / "src" / "outline.md"
    outline.parent.mkdir(parents=True, exist_ok=True)
    outline.write_text(
        "# 第一卷\n\n## 第一幕\n\n### 第一节\n\n"
        "#### 第1章：开始\n\n开端。\n\n"
        "#### 第2章：继续\n\n推进。\n",
        encoding="utf-8",
    )
    chapters = {
        "ch_001": (
            "# 第一章\n\n序言。\n\n"
            "## 场景一：雨夜\n\n林岚进入车站。\n\n"
            "### Scene 2: departure\n\n周明离开海城。\n"
        ),
        "ch_002": "# 第二章\n\n没有显式场景标题的正文。\n",
    }
    for chapter_id, content in chapters.items():
        path = novel / "data" / "manuscript" / "arc_001" / f"{chapter_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return novel


def _files(root: Path) -> dict[Path, bytes]:
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def _migrate(service: SceneStructureService) -> dict:
    preview = service.migration_preview()
    return service.apply_migration(
        expected_preview_revision=preview["preview_revision"], confirm=True
    )


def test_migration_preview_is_read_only_and_segments_scene_headings(tmp_path: Path) -> None:
    novel = _project(tmp_path)
    service = SceneStructureService(tmp_path, "demo")
    before = _files(novel)

    first = service.migration_preview()
    second = service.migration_preview()

    assert service.surface()["status"] == "absent"
    assert first["schema_version"] == "openwrite.scene-migration-preview.v1"
    assert first["preview_revision"] == second["preview_revision"]
    assert first["input_chapters"] == second["input_chapters"]
    assert _files(novel) == before
    assert not (novel / "data/story_structure").exists()
    plans = {item["chapter_id"]: item for item in first["plan"]}
    assert len(plans["ch_001"]["scenes"]) == 2
    assert plans["ch_001"]["scenes"][0]["title"] == "场景一：雨夜"
    assert plans["ch_001"]["scenes"][1]["title"] == "Scene 2: departure"
    assert plans["ch_002"]["strategy"] == "fallback_single_scene"
    assert len(plans["ch_002"]["scenes"]) == 1
    assert all(
        item["anchor"]["offset_unit"] == "python_unicode_codepoint"
        and item["anchor"]["end_exclusive"] is True
        for plan in first["plan"]
        for item in plan["scenes"]
    )
    assert first["rollback_evidence"]["sidecar_exists"] is False


def test_apply_migration_requires_confirmation_and_exact_preview_revision(
    tmp_path: Path,
) -> None:
    novel = _project(tmp_path)
    service = SceneStructureService(tmp_path, "demo")
    preview = service.migration_preview()

    with pytest.raises(SceneStructureError) as confirmation:
        service.apply_migration(
            expected_preview_revision=preview["preview_revision"], confirm=False
        )
    assert confirmation.value.code == "CONFIRMATION_REQUIRED"

    chapter = novel / "data/manuscript/arc_001/ch_001.md"
    chapter.write_text(chapter.read_text(encoding="utf-8") + "\n外部修改。\n", encoding="utf-8")
    before = _files(novel)
    with pytest.raises(SceneStructureError) as stale:
        service.apply_migration(expected_preview_revision=preview["preview_revision"], confirm=True)
    assert stale.value.code == "SCENE_MIGRATION_CONFLICT"
    assert _files(novel) == before
    assert not (novel / "data/story_structure").exists()


def test_apply_migration_builds_current_surface_and_stable_project_copy(
    tmp_path: Path,
) -> None:
    novel = _project(tmp_path)
    service = SceneStructureService(tmp_path, "demo")
    preview = service.migration_preview()

    result = _migrate(service)
    surface = result["scene_structure"]

    assert surface["schema_version"] == "openwrite.scene-structure.v1"
    assert surface["status"] == "current"
    assert surface["mutation_allowed"] is True
    assert surface["reading_order"] == [item["scene_id"] for item in surface["scenes"]]
    assert [item["scene_id"] for item in surface["scenes"]] == [
        scene["scene_id"] for plan in preview["plan"] for scene in plan["scenes"]
    ]
    assert all(item["freshness"] == "current" for item in surface["scenes"])
    assert all(
        {
            "scene_id",
            "chapter",
            "order",
            "title",
            "story_time",
            "references",
            "anchor",
            "freshness",
        }
        <= item.keys()
        for item in surface["scenes"]
    )
    assert all(
        {"document_id", "occurrence_id", "chapter_id", "path", "reading_index"}
        <= item["chapter"].keys()
        for item in surface["scenes"]
    )
    copied_root = tmp_path / "copied"
    shutil.copytree(novel, copied_root / "data/novels/demo")
    copied = SceneStructureService(copied_root, "demo").surface()
    assert [item["scene_id"] for item in copied["scenes"]] == [
        item["scene_id"] for item in surface["scenes"]
    ]


def test_reanchor_after_ordinary_prose_edit_preserves_scene_identity(tmp_path: Path) -> None:
    novel = _project(tmp_path)
    service = SceneStructureService(tmp_path, "demo")
    before = _migrate(service)["scene_structure"]
    before = service.update_metadata(
        before["scenes"][0]["scene_id"],
        expected_revision=before["revision"],
        title="人工保留标题",
        characters=["林岚"],
    )["scene_structure"]
    path = novel / "data/manuscript/arc_001/ch_001.md"
    path.write_text(
        path.read_text(encoding="utf-8").replace("林岚进入车站。", "林岚缓步进入车站。"),
        encoding="utf-8",
    )

    preview = service.migration_preview()
    planned = [
        item["scene_id"]
        for chapter in preview["plan"]
        if chapter["chapter_id"] == "ch_001"
        for item in chapter["scenes"]
    ]
    original = [
        item["scene_id"] for item in before["scenes"] if item["chapter"]["chapter_id"] == "ch_001"
    ]
    assert planned == original
    reapplied = service.apply_migration(
        expected_preview_revision=preview["preview_revision"], confirm=True
    )["scene_structure"]
    assert [
        item["scene_id"]
        for item in reapplied["scenes"]
        if item["chapter"]["chapter_id"] == "ch_001"
    ] == original
    retained = next(item for item in reapplied["scenes"] if item["scene_id"] == original[0])
    assert retained["title"] == "人工保留标题"
    assert retained["references"]["characters"] == ["林岚"]


def test_planned_missing_chapters_do_not_block_written_scene_work(tmp_path: Path) -> None:
    novel = _project(tmp_path)
    outline = novel / "src/outline.md"
    outline.write_text(
        outline.read_text(encoding="utf-8") + "\n#### 第3章：计划章\n\n尚未写作。\n",
        encoding="utf-8",
    )
    service = SceneStructureService(tmp_path, "demo")
    surface = _migrate(service)["scene_structure"]

    planned = next(item for item in surface["chapters"] if item["chapter_id"] == "ch_003")
    assert planned["freshness"] == "planned_missing"
    assert surface["status"] == "current"
    assert surface["mutation_allowed"] is True
    missing_issue = next(
        item for item in surface["issues"] if item["code"] == "MISSING_CHAPTER_FILE"
    )
    assert missing_issue["blocking"] is False

    scene = next(item for item in surface["scenes"] if item["chapter"]["chapter_id"] == "ch_001")
    metadata = service.update_metadata(
        scene["scene_id"],
        expected_revision=surface["revision"],
        title="已写章场景",
    )["scene_structure"]
    chapter = next(item for item in metadata["chapters"] if item["chapter_id"] == "ch_001")
    moved = service.move(
        metadata["scenes"][1]["scene_id"],
        target_chapter_id="ch_001",
        target_index=0,
        expected_revision=metadata["revision"],
        expected_source_revision=chapter["revision"],
        expected_target_revision=chapter["revision"],
    )["scene_structure"]
    assert moved["status"] == "current"


def test_legacy_project_without_outline_can_migrate_deterministic_disk_order(
    tmp_path: Path,
) -> None:
    novel = tmp_path / "data/novels/legacy"
    chapter = novel / "data/manuscript/arc_001/ch_001.md"
    chapter.parent.mkdir(parents=True, exist_ok=True)
    chapter.write_text("# 第一章\n\n旧项目正文。\n", encoding="utf-8")
    service = SceneStructureService(tmp_path, "legacy")

    preview = service.migration_preview()
    assert preview["can_apply"] is True
    surface = service.apply_migration(
        expected_preview_revision=preview["preview_revision"], confirm=True
    )["scene_structure"]

    assert surface["status"] == "current"
    assert surface["mutation_allowed"] is True
    assert len(surface["scenes"]) == 1
    outline_issue = next(
        item for item in surface["issues"] if item["code"] == "OUTLINE_ORDER_UNAVAILABLE"
    )
    assert outline_issue["blocking"] is False


def test_metadata_update_is_cas_bound_and_controls_story_time_order(tmp_path: Path) -> None:
    _project(tmp_path)
    service = SceneStructureService(tmp_path, "demo")
    surface = _migrate(service)["scene_structure"]
    first, second = surface["scenes"][:2]

    updated = service.update_metadata(
        second["scene_id"],
        expected_revision=surface["revision"],
        story_time_sort_key="0010",
        story_time_label="十年前",
        characters=["周明", "周明", ""],
        locations=["海城"],
        events=["离站"],
    )
    current = updated["scene_structure"]
    changed = next(item for item in current["scenes"] if item["scene_id"] == second["scene_id"])
    assert changed["story_time"] == {"sort_key": "0010", "label": "十年前"}
    assert changed["references"] == {
        "characters": ["周明"],
        "locations": ["海城"],
        "events": ["离站"],
    }
    assert current["story_time_order"][0] == second["scene_id"]
    with pytest.raises(SceneStructureError) as stale:
        service.update_metadata(
            first["scene_id"],
            expected_revision=surface["revision"],
            title="过期修改",
        )
    assert stale.value.code == "SCENE_STRUCTURE_CONFLICT"


def test_same_chapter_reorder_preserves_scene_ids_and_all_text(tmp_path: Path) -> None:
    novel = _project(tmp_path)
    service = SceneStructureService(tmp_path, "demo")
    surface = _migrate(service)["scene_structure"]
    chapter = next(item for item in surface["chapters"] if item["chapter_id"] == "ch_001")
    scenes = [item for item in surface["scenes"] if item["chapter"]["chapter_id"] == "ch_001"]
    path = novel / chapter["path"]
    before = path.read_text(encoding="utf-8")
    blocks = {
        item["scene_id"]: before[item["anchor"]["start"] : item["anchor"]["end"]] for item in scenes
    }

    result = service.move(
        scenes[1]["scene_id"],
        target_chapter_id="ch_001",
        target_index=0,
        expected_revision=surface["revision"],
        expected_source_revision=chapter["revision"],
        expected_target_revision=chapter["revision"],
    )

    after = result["scene_structure"]
    reordered = [item for item in after["scenes"] if item["chapter"]["chapter_id"] == "ch_001"]
    assert [item["scene_id"] for item in reordered] == [
        scenes[1]["scene_id"],
        scenes[0]["scene_id"],
    ]
    content = path.read_text(encoding="utf-8")
    assert all(content.count(block) == 1 for block in blocks.values())
    assert all(item["freshness"] == "current" for item in reordered)


def test_cross_chapter_move_preserves_text_identity_and_invalidates_derivatives(
    tmp_path: Path,
) -> None:
    novel = _project(tmp_path)
    service = SceneStructureService(tmp_path, "demo")
    surface = _migrate(service)["scene_structure"]
    moving = surface["scenes"][1]
    target = next(item for item in surface["chapters"] if item["chapter_id"] == "ch_002")
    source = next(item for item in surface["chapters"] if item["chapter_id"] == "ch_001")
    source_path = novel / source["path"]
    target_path = novel / target["path"]
    source_before = source_path.read_text(encoding="utf-8")
    target_before = target_path.read_text(encoding="utf-8")
    moved_text = source_before[moving["anchor"]["start"] : moving["anchor"]["end"]]

    result = service.move(
        moving["scene_id"],
        target_chapter_id="ch_002",
        target_index=0,
        expected_revision=surface["revision"],
        expected_source_revision=source["revision"],
        expected_target_revision=target["revision"],
    )

    after = result["scene_structure"]
    moved = next(item for item in after["scenes"] if item["scene_id"] == moving["scene_id"])
    assert moved["chapter"]["chapter_id"] == "ch_002"
    assert moved["order"] == 0
    assert moved["freshness"] == "current"
    assert moved_text in target_path.read_text(encoding="utf-8")
    assert moved_text not in source_path.read_text(encoding="utf-8")
    assert target_before.split("\n", 1)[1].strip() in target_path.read_text(encoding="utf-8")
    assert result["acceptance"]["status"] in {"pending", "processing"}
    from tools.manuscript_acceptance import ManuscriptAcceptanceService

    acceptance = ManuscriptAcceptanceService(tmp_path, "demo").inspect()
    assert acceptance["blocking"] is True
    assert {item["chapter_id"] for item in acceptance["chapters"]} >= {"ch_001", "ch_002"}
    heads = {item["chapter_id"]: item for item in acceptance["chapters"]}
    changed = {item["chapter_id"]: item for item in after["chapters"]}
    assert heads["ch_001"]["pending_revision"] == changed["ch_001"]["revision"]
    assert heads["ch_002"]["pending_revision"] == changed["ch_002"]["revision"]


def test_move_rejects_stale_anchor_or_chapter_revision_without_writes(tmp_path: Path) -> None:
    novel = _project(tmp_path)
    service = SceneStructureService(tmp_path, "demo")
    surface = _migrate(service)["scene_structure"]
    scene = surface["scenes"][0]
    source = next(item for item in surface["chapters"] if item["chapter_id"] == "ch_001")
    target = next(item for item in surface["chapters"] if item["chapter_id"] == "ch_002")
    chapter = novel / source["path"]
    chapter.write_text(chapter.read_text(encoding="utf-8") + "\n旁路修改。\n", encoding="utf-8")
    stale_surface = service.surface()
    assert stale_surface["status"] == "stale"
    assert stale_surface["mutation_allowed"] is False
    assert (
        next(item for item in stale_surface["scenes"] if item["scene_id"] == scene["scene_id"])[
            "freshness"
        ]
        == "stale"
    )
    before = _files(novel)

    with pytest.raises(SceneStructureError) as rejected:
        service.move(
            scene["scene_id"],
            target_chapter_id="ch_002",
            target_index=0,
            expected_revision=stale_surface["revision"],
            expected_source_revision=source["revision"],
            expected_target_revision=target["revision"],
        )
    assert rejected.value.code in {"SCENE_STRUCTURE_STALE", "SOURCE_REVISION_CONFLICT"}
    assert _files(novel) == before


def test_move_rolls_back_both_chapters_and_sidecar_on_failure(tmp_path: Path) -> None:
    novel = _project(tmp_path)

    def fail(stage: str) -> None:
        if stage == "sidecar_replaced":
            raise OSError("injected scene transaction failure")

    normal = SceneStructureService(tmp_path, "demo")
    surface = _migrate(normal)["scene_structure"]
    service = SceneStructureService(tmp_path, "demo", fault_injector=fail)
    source = next(item for item in surface["chapters"] if item["chapter_id"] == "ch_001")
    target = next(item for item in surface["chapters"] if item["chapter_id"] == "ch_002")
    before = _files(novel)

    with pytest.raises(SceneStructureError) as rejected:
        service.move(
            surface["scenes"][1]["scene_id"],
            target_chapter_id="ch_002",
            target_index=0,
            expected_revision=surface["revision"],
            expected_source_revision=source["revision"],
            expected_target_revision=target["revision"],
        )
    assert rejected.value.code == "SCENE_TRANSACTION_FAILED"
    assert _files(novel) == before
    assert normal.surface()["revision"] == surface["revision"]


def test_rollback_migration_restores_exact_previous_sidecar(tmp_path: Path) -> None:
    novel = _project(tmp_path)
    service = SceneStructureService(tmp_path, "demo")
    first = _migrate(service)["scene_structure"]
    service.update_metadata(
        first["scenes"][0]["scene_id"],
        expected_revision=first["revision"],
        title="人工场景标题",
    )
    sidecar = novel / "data/story_structure/scenes.json"
    expected_bytes = sidecar.read_bytes()
    second = _migrate(service)

    restored = service.rollback_migration(
        second["migration_id"],
        expected_revision=second["scene_structure"]["revision"],
    )

    assert sidecar.read_bytes() == expected_bytes
    assert restored["scene_structure"]["status"] == "current"
    assert any(item["title"] == "人工场景标题" for item in restored["scene_structure"]["scenes"])


def test_corrupt_sidecar_is_explicit_and_blocks_mutation(tmp_path: Path) -> None:
    novel = _project(tmp_path)
    service = SceneStructureService(tmp_path, "demo")
    before = _migrate(service)["scene_structure"]
    sidecar = novel / "data/story_structure/scenes.json"
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    payload["scenes"][1]["scene_id"] = payload["scenes"][0]["scene_id"]
    sidecar.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    invalid = service.surface()

    assert invalid["status"] == "ambiguous"
    assert invalid["revision"] != before["revision"]
    assert invalid["mutation_allowed"] is False
    assert "DUPLICATE_SCENE_ID" in {item["code"] for item in invalid["issues"]}
    preview = service.migration_preview()
    assert preview["can_apply"] is False
    assert "DUPLICATE_SCENE_ID" in {item["code"] for item in preview["issues"]}
