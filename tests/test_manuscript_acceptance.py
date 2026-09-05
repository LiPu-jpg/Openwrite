from __future__ import annotations

from pathlib import Path

import pytest

from tools.chapter_memory import ChapterMemoryStore
from tools.chapter_run_v2 import ChapterRunV2Store
from tools.init_project import init_project
from tools.manuscript_acceptance import (
    ManuscriptAcceptanceError,
    ManuscriptAcceptanceService,
)
from tools.review_store import ReviewStore
from tools.rolling_planning import RollingPlanningError, RollingPlanningService


def _chapter(root: Path, chapter_id: str, text: str) -> Path:
    path = root / "data" / "novels" / "demo" / "data" / "manuscript" / "arc_001"
    path.mkdir(parents=True, exist_ok=True)
    target = path / f"{chapter_id}.md"
    target.write_text(f"# {chapter_id}\n\n{text}\n", encoding="utf-8")
    return target


def _analyze(chapter_id: str, title: str, content: str, prior_context: str) -> dict:
    del title, prior_context
    if chapter_id == "ch_001":
        fact = "林岑已死" if "死去" in content else "林岑仍活着"
    else:
        fact = "旧信已被找到"
    return {
        "chapter_summary": f"{chapter_id}摘要：{fact}",
        "observations": fact,
        "legacy_updates": {"current_state": fact},
        "state_delta": {},
    }


def _baseline(root: Path) -> ManuscriptAcceptanceService:
    service = ManuscriptAcceptanceService(root, "demo")
    operation = service.establish_baseline(confirm=True)
    service.resume(operation["operation_id"], analyzer=_analyze)
    return service


def test_legacy_manuscript_requires_explicit_baseline_and_inspection_is_read_only(
    tmp_path: Path,
):
    init_project(tmp_path, "demo")
    _chapter(tmp_path, "ch_001", "林岑仍活着。")
    service = ManuscriptAcceptanceService(tmp_path, "demo")

    surface = service.inspect()

    assert surface["status"] == "baseline_required"
    assert surface["chapters"][0]["status"] == "baseline_required"
    assert surface["chapters"][0]["accepted_revision"] == ""
    assert not service.state_path.exists()
    with pytest.raises(ManuscriptAcceptanceError) as raised:
        service.require_current("ch_002")
    assert raised.value.code == "ACCEPTANCE_BASELINE_REQUIRED"


def test_rewrite_invalidates_old_memory_then_rebuilds_facts_from_frozen_content(
    tmp_path: Path,
):
    init_project(tmp_path, "demo")
    changed = _chapter(tmp_path, "ch_001", "林岑仍活着。")
    _chapter(tmp_path, "ch_002", "林岑继续寻找旧信。")
    service = _baseline(tmp_path)
    memory = ChapterMemoryStore(tmp_path, "demo")
    assert "林岑仍活着" in memory.render_context("ch_003")

    before = service.fingerprint(changed.read_text(encoding="utf-8"))
    changed.write_text("# ch_001\n\n林岑在钟楼死去。\n", encoding="utf-8")
    operation = service.start_acceptance(
        "ch_001",
        source="manual",
        expected_previous_revision=before,
    )

    assert service.inspect()["status"] == "pending"
    pending_head = service.inspect()["chapters"][0]
    assert pending_head["accepted_revision"] == before
    assert pending_head["pending_revision"] == service.fingerprint(
        changed.read_text(encoding="utf-8")
    )
    assert "林岑仍活着" not in memory.render_context("ch_003")
    with pytest.raises(ManuscriptAcceptanceError) as raised:
        service.require_current("ch_003")
    assert raised.value.code == "MANUSCRIPT_FACTS_PENDING"
    with pytest.raises(RollingPlanningError) as planning_blocked:
        RollingPlanningService(tmp_path, "demo").create()
    assert planning_blocked.value.code == "MANUSCRIPT_FACTS_PENDING"

    service.resume(operation["operation_id"], analyzer=_analyze)
    current_head = service.inspect()["chapters"][0]
    assert current_head["accepted_revision"] == current_head["current_revision"]
    assert current_head["pending_revision"] == ""
    rebuilt = (
        tmp_path
        / "data"
        / "novels"
        / "demo"
        / "data"
        / "world"
        / "current_state.md"
    ).read_text(encoding="utf-8")
    assert "林岑已死" in rebuilt
    assert "林岑仍活着" not in rebuilt
    assert service.inspect()["status"] == "needs_review"

    service.acknowledge(
        operation["operation_id"],
        domains=["outline", "foreshadowing"],
        confirm=True,
    )
    assert service.inspect()["status"] == "current"
    service.require_current("ch_003")
    assert "林岑已死" in memory.render_context("ch_003")


def test_analysis_result_is_rejected_if_manuscript_changes_during_model_call(
    tmp_path: Path,
):
    init_project(tmp_path, "demo")
    chapter = _chapter(tmp_path, "ch_001", "林岑仍活着。")
    service = ManuscriptAcceptanceService(tmp_path, "demo")
    operation = service.establish_baseline(confirm=True)

    def changing_analyzer(*args):
        result = _analyze(*args)
        chapter.write_text("# ch_001\n\n分析期间正文再次变化。\n", encoding="utf-8")
        return result

    with pytest.raises(ManuscriptAcceptanceError) as raised:
        service.resume(operation["operation_id"], analyzer=changing_analyzer)

    assert raised.value.code == "ACCEPTED_SOURCE_CHANGED"
    assert service.operation(operation["operation_id"])["status"] == "stale"
    assert not service.fact_path("ch_001").exists()
    assert service.inspect()["chapters"][0]["status"] == "external_change"


def test_failed_resume_reuses_frozen_payload_and_does_not_duplicate_runtime_facts(
    tmp_path: Path,
):
    init_project(tmp_path, "demo")
    _chapter(tmp_path, "ch_001", "林岑仍活着。")
    service = ManuscriptAcceptanceService(tmp_path, "demo")
    operation = service.establish_baseline(confirm=True)
    seen: list[str] = []

    def flaky(chapter_id: str, title: str, content: str, prior_context: str) -> dict:
        seen.append(content)
        if len(seen) == 1:
            raise RuntimeError("transient")
        return _analyze(chapter_id, title, content, prior_context)

    with pytest.raises(RuntimeError, match="transient"):
        service.resume(operation["operation_id"], analyzer=flaky)
    assert service.operation(operation["operation_id"])["stages"]["analyze"]["status"] == "failed"

    completed = service.resume(operation["operation_id"], analyzer=flaky)

    assert completed["status"] == "completed"
    assert seen[0] == seen[1]
    runtime = (
        tmp_path
        / "data"
        / "novels"
        / "demo"
        / "data"
        / "world"
        / "runtime_state.json"
    ).read_text(encoding="utf-8")
    assert runtime.count("林岑仍活着") == 1
    assert completed["stages"]["analyze"]["attempts"] == 2


def test_acceptance_marks_reviews_plans_and_runs_stale_before_analysis(
    tmp_path: Path,
):
    init_project(tmp_path, "demo")
    chapter = _chapter(tmp_path, "ch_001", "林岑仍活着。")
    service = _baseline(tmp_path)
    review_store = ReviewStore(tmp_path, "demo")
    review_store.save("ch_001", {"passed": True, "score": 90, "issue_details": []})
    candidate = RollingPlanningService(tmp_path, "demo").create()
    run_store = ChapterRunV2Store(tmp_path, "demo")
    run = run_store.create("ch_001", input_revisions={"context": "old"})
    run_store.start_stage(run, "context")
    run_store.complete_stage(run, "context", output={"old": True})

    before = service.fingerprint(chapter.read_text(encoding="utf-8"))
    chapter.write_text("# ch_001\n\n林岑在钟楼死去。\n", encoding="utf-8")
    operation = service.start_acceptance(
        "ch_001",
        source="revision",
        expected_previous_revision=before,
    )

    assert review_store.load("ch_001")["stale"] is True
    assert RollingPlanningService(tmp_path, "demo").load(candidate.candidate_id).state == "stale"
    assert run_store.load(run.run_id).stages["context"].status == "stale"
    impacts = service.operation(operation["operation_id"])["impacts"]
    assert {item["domain"] for item in impacts if item["status"] == "stale"} >= {
        "outline",
        "foreshadowing",
    }


def test_external_edit_is_detected_and_must_enter_the_same_acceptance_protocol(
    tmp_path: Path,
):
    init_project(tmp_path, "demo")
    chapter = _chapter(tmp_path, "ch_001", "林岑仍活着。")
    service = _baseline(tmp_path)

    chapter.write_text("# ch_001\n\n林岑在钟楼死去。\n", encoding="utf-8")
    surface = service.inspect()

    assert surface["status"] == "external_change"
    assert surface["chapters"][0]["status"] == "external_change"
    with pytest.raises(ManuscriptAcceptanceError) as raised:
        service.require_current("ch_002")
    assert raised.value.code == "EXTERNAL_MANUSCRIPT_CHANGE"

    operation = service.accept_external("ch_001", confirm=True)
    service.resume(operation["operation_id"], analyzer=_analyze)
    assert service.operation(operation["operation_id"])["source"] == "external_editor"


def test_rapid_saves_keep_last_completed_revision_until_latest_facts_are_accepted(
    tmp_path: Path,
):
    init_project(tmp_path, "demo")
    chapter = _chapter(tmp_path, "ch_001", "林岑仍活着。")
    service = _baseline(tmp_path)
    completed_revision = service.inspect()["chapters"][0]["accepted_revision"]

    chapter.write_text("# ch_001\n\n林岑走下钟楼。\n", encoding="utf-8")
    first_pending_revision = service.fingerprint(chapter.read_text(encoding="utf-8"))
    first = service.start_acceptance(
        "ch_001",
        source="autosave",
        expected_previous_revision=completed_revision,
    )
    chapter.write_text("# ch_001\n\n林岑离开钟楼。\n", encoding="utf-8")
    latest_revision = service.fingerprint(chapter.read_text(encoding="utf-8"))
    latest = service.start_acceptance(
        "ch_001",
        source="autosave",
        expected_previous_revision=first_pending_revision,
    )

    head = service.inspect()["chapters"][0]
    assert head["status"] == "pending"
    assert head["accepted_revision"] == completed_revision
    assert head["pending_revision"] == latest_revision
    with pytest.raises(ManuscriptAcceptanceError) as superseded:
        service.resume(first["operation_id"], analyzer=_analyze)
    assert superseded.value.code == "ACCEPTED_SOURCE_CHANGED"

    completed = service.resume(latest["operation_id"], analyzer=_analyze)
    assert completed["accepted_revision"] == latest_revision
    assert service.inspect()["chapters"][0]["accepted_revision"] == latest_revision
