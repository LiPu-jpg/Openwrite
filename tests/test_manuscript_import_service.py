from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.init_project import init_project
from tools.manuscript_acceptance import ManuscriptAcceptanceService
from tools.manuscript_import import ManuscriptImportError, ManuscriptImportService
from tools.novel_workspace import list_chapters


def _source(root: Path) -> Path:
    path = root / "legacy.md"
    path.write_text(
        "# 第一章 雨夜\n\n林岑听见钟声。\n\n# 第二章 旧宅\n\n她推开旧宅的门。\n",
        encoding="utf-8",
    )
    return path


def _analyze(chapter_id: str, title: str, content: str, prior_context: str) -> dict:
    del title, prior_context
    return {
        "chapter_summary": f"{chapter_id}：{content[:20]}",
        "observations": content[:40],
        "legacy_updates": {},
        "state_delta": {},
    }


def test_unconfirmed_preview_never_publishes_canonical_manuscript(tmp_path: Path):
    init_project(tmp_path, "demo")
    service = ManuscriptImportService(tmp_path, "demo")
    operation = service.start(_source(tmp_path), arc_id="arc_001", start_number=1)

    assert operation["status"] == "awaiting_confirmation"
    assert operation["stages"]["snapshot"]["status"] == "completed"
    assert operation["stages"]["split"]["status"] == "completed"
    assert operation["stages"]["snapshot"]["input_sha256"].startswith("sha256:")
    assert operation["stages"]["split"]["input_sha256"] == operation["source"]["sha256"]

    resumed = service.resume(operation["import_id"])

    assert resumed["status"] == "awaiting_confirmation"
    assert not list(
        (tmp_path / "data" / "novels" / "demo" / "data" / "manuscript").rglob("ch_*.md")
    )
    with pytest.raises(ManuscriptImportError) as rejected:
        service.confirm_structure(
            operation["import_id"],
            expected_preview_revision=operation["preview_revision"],
            confirm=False,
        )
    assert rejected.value.code == "CONFIRMATION_REQUIRED"

    listed = service.list_operations(limit=1)
    summary = listed["operations"][0]
    serialized = json.dumps(summary, ensure_ascii=False)
    assert summary["import_id"] == operation["import_id"]
    assert summary["preview_revision"] == operation["preview_revision"]
    assert summary["progress"] == {
        "current_stage": "structure_confirmed",
        "completed_stages": 2,
        "total_stages": 8,
        "published_chapters": 0,
        "total_chapters": 2,
    }
    assert summary["stages"]["snapshot"]["output_sha256"].startswith("sha256:")
    assert "original_path" not in serialized
    assert str(tmp_path) not in serialized

    with pytest.raises(ManuscriptImportError) as unconfirmed_discard:
        service.discard(operation["import_id"])
    assert unconfirmed_discard.value.code == "CONFIRMATION_REQUIRED"
    discarded = service.discard(operation["import_id"], confirm=True)
    assert discarded["status"] == "discarded"
    assert Path(operation["source"]["snapshot_path"]).is_file()
    assert service.resume(operation["import_id"])["status"] == "discarded"


def test_frozen_source_survives_later_edits_and_preview_edits_define_boundaries(
    tmp_path: Path,
):
    init_project(tmp_path, "demo")
    source = _source(tmp_path)
    service = ManuscriptImportService(tmp_path, "demo")
    operation = service.start(source, arc_id="arc_002", start_number=7)
    original_sha = operation["source"]["sha256"]

    source.write_text("# 被替换的源文件\n\n这段不应进入导入。\n", encoding="utf-8")
    preview = service.preview(operation["import_id"])
    edited = service.revise_preview(
        operation["import_id"],
        expected_preview_revision=preview["revision"],
        chapters=[
            {
                "chapter_id": "ch_007",
                "title": "雨夜来信",
                "content": "林岑听见钟声。\n\n她走到旧宅门前。",
            },
            {
                "chapter_id": "ch_008",
                "title": "门后",
                "content": "她推开旧宅的门。",
            },
        ],
    )
    service.confirm_structure(
        operation["import_id"],
        expected_preview_revision=edited["revision"],
        confirm=True,
    )

    published = service.resume(operation["import_id"])

    first = tmp_path / "data" / "novels" / "demo" / "data" / "manuscript" / "arc_002" / "ch_007.md"
    assert published["status"] == "awaiting_reconciliation"
    assert "雨夜来信" in first.read_text(encoding="utf-8")
    assert "走到旧宅门前" in first.read_text(encoding="utf-8")
    assert "被替换的源文件" not in first.read_text(encoding="utf-8")
    assert published["source"]["sha256"] == original_sha
    assert (
        Path(published["source"]["snapshot_path"])
        .read_text(encoding="utf-8-sig")
        .startswith("# 第一章 雨夜")
    )
    assert published["acceptance_operation_id"]
    acceptance = ManuscriptAcceptanceService(tmp_path, "demo").operation(
        published["acceptance_operation_id"]
    )
    assert acceptance["chapter_id"] == "ch_007"
    assert acceptance["source"] == "import"


def test_duplicate_chapter_ids_are_rejected_before_confirmation(tmp_path: Path):
    init_project(tmp_path, "demo")
    service = ManuscriptImportService(tmp_path, "demo")
    operation = service.start(_source(tmp_path), arc_id="arc_001", start_number=1)

    with pytest.raises(ManuscriptImportError) as duplicate_preview:
        service.revise_preview(
            operation["import_id"],
            expected_preview_revision=operation["preview_revision"],
            chapters=[
                {"chapter_id": "ch_001", "title": "一", "content": "甲"},
                {"chapter_id": "ch_001", "title": "二", "content": "乙"},
            ],
        )
    assert duplicate_preview.value.code == "DUPLICATE_CHAPTER_ID"

    existing = (
        tmp_path / "data" / "novels" / "demo" / "data" / "manuscript" / "arc_009" / "ch_001.md"
    )
    existing.parent.mkdir(parents=True, exist_ok=True)
    existing.write_text("# 已有章节\n\n不可覆盖。\n", encoding="utf-8")
    with pytest.raises(ManuscriptImportError) as duplicate_canonical:
        service.confirm_structure(
            operation["import_id"],
            expected_preview_revision=operation["preview_revision"],
            confirm=True,
        )
    assert duplicate_canonical.value.code == "DUPLICATE_CHAPTER_ID"
    assert duplicate_canonical.value.details["chapter_ids"] == ["ch_001"]


def test_publish_recovers_after_interruption_and_is_idempotent(tmp_path: Path):
    init_project(tmp_path, "demo")
    service = ManuscriptImportService(tmp_path, "demo")
    operation = service.start(_source(tmp_path), arc_id="arc_001", start_number=1)
    service.confirm_structure(
        operation["import_id"],
        expected_preview_revision=operation["preview_revision"],
        confirm=True,
    )
    interrupted = False

    def fail_after_first_publish(point: str) -> None:
        nonlocal interrupted
        if point == "publish:ch_001" and not interrupted:
            interrupted = True
            raise RuntimeError("simulated process interruption")

    with pytest.raises(RuntimeError, match="simulated process interruption"):
        service.resume(operation["import_id"], fault_injector=fail_after_first_publish)

    failed = service.operation(operation["import_id"])
    assert failed["status"] == "failed"
    assert failed["stages"]["published"]["status"] == "failed"
    manuscript_root = tmp_path / "data" / "novels" / "demo" / "data" / "manuscript"
    assert list(manuscript_root.rglob("ch_*.md")) == []
    assert list_chapters(tmp_path, "demo") == []
    assert failed["published_chapters"] == []
    assert failed["publication_transaction"]["swap_status"] == "preparing"
    staged = service.operation_root(operation["import_id"]) / "publication"
    assert (staged / "ch_001.md").is_file()
    assert not staged.is_relative_to(manuscript_root)
    failed_summary = service.list_operations()["operations"][0]
    assert failed_summary["status"] == "failed"
    assert failed_summary["progress"]["current_stage"] == "published"
    assert failed_summary["publication"]["committed"] is False
    assert failed_summary["failure"] == {
        "code": "RuntimeError",
        "stage": "published",
        "recoverable": True,
    }

    recovered = service.resume(operation["import_id"])
    assert recovered["status"] == "awaiting_reconciliation"
    assert recovered["stages"]["published"]["attempts"] == 2
    assert [item["chapter_id"] for item in recovered["published_chapters"]] == [
        "ch_001",
        "ch_002",
    ]
    first = Path(recovered["published_chapters"][0]["path"])
    second = Path(recovered["published_chapters"][1]["path"])
    before = (first.read_bytes(), second.read_bytes(), recovered["acceptance_operation_id"])

    repeated = service.resume(operation["import_id"])
    after = (first.read_bytes(), second.read_bytes(), repeated["acceptance_operation_id"])
    assert after == before

    acceptance = ManuscriptAcceptanceService(tmp_path, "demo")
    acceptance.resume(repeated["acceptance_operation_id"], analyzer=_analyze)
    completed = service.resume(operation["import_id"])

    assert completed["status"] == "completed"
    assert all(
        completed["stages"][name]["status"] == "completed"
        for name in (
            "snapshot",
            "split",
            "structure_confirmed",
            "published",
            "acceptance",
            "reconcile",
            "synthesis",
            "complete",
        )
    )
    synthesis_path = service.operation_root(operation["import_id"]) / "synthesis.json"
    synthesis = json.loads(synthesis_path.read_text(encoding="utf-8"))
    assert [item["chapter_id"] for item in synthesis["chapter_facts"]] == [
        "ch_001",
        "ch_002",
    ]
    assert all(item["title"] for item in synthesis["chapter_facts"])
    assert all(item["chapter_summary"] for item in synthesis["chapter_facts"])
    assert all(item["observations"] for item in synthesis["chapter_facts"])
    assert all(item["source_revision"] for item in synthesis["chapter_facts"])
    assert synthesis["runtime_revision"] >= 2
    assert synthesis["fact_coverage"] == {
        "covered": 2,
        "total": 2,
        "missing_chapters": [],
        "stale_chapters": [],
        "coverage_ratio": 1.0,
    }
    assert synthesis["input_sha256"] == completed["stages"]["synthesis"]["input_sha256"]
    assert synthesis_path.is_file()
    with pytest.raises(ManuscriptImportError) as published_discard:
        service.discard(operation["import_id"], confirm=True)
    assert published_discard.value.code == "IMPORT_DISCARD_FORBIDDEN"


def test_failed_uncommitted_publish_can_be_discarded(tmp_path: Path):
    init_project(tmp_path, "demo")
    service = ManuscriptImportService(tmp_path, "demo")
    operation = service.start(_source(tmp_path), arc_id="arc_001", start_number=1)
    service.confirm_structure(
        operation["import_id"],
        expected_preview_revision=operation["preview_revision"],
        confirm=True,
    )

    def fail_during_staging(point: str) -> None:
        if point == "publish:ch_001":
            raise RuntimeError("stop before canonical swap")

    with pytest.raises(RuntimeError, match="stop before canonical swap"):
        service.resume(operation["import_id"], fault_injector=fail_during_staging)

    staging = service.operation_root(operation["import_id"]) / "publication"
    assert staging.is_dir()
    discarded = service.discard(operation["import_id"], confirm=True)

    assert discarded["status"] == "discarded"
    assert not staging.exists()
    assert list_chapters(tmp_path, "demo") == []
    assert service.operation_path(operation["import_id"]).is_file()
    assert Path(operation["source"]["snapshot_path"]).is_file()


def test_list_operations_is_latest_first_and_bounded(tmp_path: Path):
    init_project(tmp_path, "demo")
    service = ManuscriptImportService(tmp_path, "demo")
    first = service.start(_source(tmp_path), arc_id="arc_001", start_number=1)
    second = service.start(_source(tmp_path), arc_id="arc_002", start_number=3)

    listed = service.list_operations(limit=1)

    assert [item["import_id"] for item in listed["operations"]] == [second["import_id"]]
    assert listed["counts"] == {"awaiting_confirmation": 1}
    assert first["created_at"] <= second["created_at"]
