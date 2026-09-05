from __future__ import annotations

import json
from pathlib import Path

import yaml

from tools.chapter_work_brief import ChapterWorkBriefService
from tools.init_project import init_project
from tools.manuscript_acceptance import ManuscriptAcceptanceService
from tools.review_store import ReviewStore
from tools.revision_store import RevisionStore
from tools.task_store import TaskStore


def _chapter(root: Path, chapter_id: str, content: str) -> Path:
    path = (
        root
        / "data"
        / "novels"
        / "demo"
        / "data"
        / "manuscript"
        / "arc_001"
        / f"{chapter_id}.md"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _dag(root: Path, nodes: dict[str, dict]) -> None:
    path = (
        root
        / "data"
        / "novels"
        / "demo"
        / "data"
        / "foreshadowing"
        / "dag.yaml"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "nodes": nodes,
                "edges": [],
                "status": {
                    node_id: str(node.get("status") or "")
                    for node_id, node in nodes.items()
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _node(**updates) -> dict:
    result = {
        "content": "钟声的异常",
        "weight": 5,
        "layer": "支线",
        "status": "埋伏",
        "created_at": "ch_001",
        "target_chapter": None,
        "tags": [],
    }
    result.update(updates)
    return result


def _analyze(chapter_id: str, title: str, content: str, prior: str) -> dict:
    del title, content, prior
    return {
        "chapter_summary": f"{chapter_id} 摘要",
        "observations": "无新增事实",
        "legacy_updates": {},
        "state_delta": {},
    }


def test_foreshadowing_classification_boundaries_are_mutually_exclusive(
    tmp_path: Path,
) -> None:
    init_project(tmp_path, "demo")
    _chapter(tmp_path, "ch_005", "# 第五章\n\n钟声响起。\n")
    _dag(
        tmp_path,
        {
            "f_due": _node(target_chapter="ch_005", source_revision="sha256:due"),
            "f_overdue": _node(target_chapter="ch_004"),
            "f_upcoming": _node(target_chapter="ch_006", earliest_reveal="ch_005"),
            "f_early": _node(target_chapter="ch_008", earliest_reveal="ch_007"),
            "f_plant": _node(
                status="planned",
                planned=True,
                plant_anchor={"chapter_id": "ch_005", "line": 12},
            ),
            "f_closed": _node(status="已收", target_chapter="ch_005"),
        },
    )

    brief = ChapterWorkBriefService(tmp_path, "demo").get("ch_005")
    groups = brief["foreshadowing"]

    assert [item["id"] for item in groups["must_resolve"]] == ["f_due"]
    assert [item["id"] for item in groups["overdue"]] == ["f_overdue"]
    assert [item["id"] for item in groups["upcoming"]] == ["f_upcoming"]
    assert [item["id"] for item in groups["prohibited_early"]] == ["f_early"]
    assert [item["id"] for item in groups["to_plant"]] == ["f_plant"]
    all_ids = [
        item["id"]
        for category in ChapterWorkBriefService.FORESHADOW_CATEGORIES
        for item in groups[category]
    ]
    assert len(all_ids) == len(set(all_ids)) == 5
    assert groups["must_resolve"][0]["source_revision"] == "sha256:due"
    assert groups["to_plant"][0]["plant_anchor"]["line"] == 12
    assert groups["prohibited_early"][0]["earliest_reveal"] == "ch_007"


def test_brief_aggregates_stale_review_acceptance_revision_tasks_and_target(
    tmp_path: Path,
) -> None:
    init_project(tmp_path, "demo")
    novel_root = tmp_path / "data" / "novels" / "demo"
    chapter = _chapter(tmp_path, "ch_001", "# 第一章：雨夜\n\n林舟走进钟楼。\n")
    (novel_root / "src" / "outline.md").write_text(
        "# 第一卷\n## 第一幕\n### 第一节\n"
        "#### 第一章：雨夜\n> 预估字数: 4200\n进入钟楼。\n",
        encoding="utf-8",
    )
    acceptance = ManuscriptAcceptanceService(tmp_path, "demo")
    operation = acceptance.establish_baseline(confirm=True)
    acceptance.resume(operation["operation_id"], analyzer=_analyze)

    ReviewStore(tmp_path, "demo").save(
        "ch_001",
        {
            "review_v2": {
                "schema_version": "openwrite.review.v2",
                "execution_status": "completed",
                "quality_score": 82.5,
                "coverage": 1.0,
                "gate_status": "pass",
                "delivery_status": "pass",
                "production_gate_status": "disabled_uncalibrated",
            },
            "issue_details": [],
        },
    )
    revision_store = RevisionStore(tmp_path, "demo")
    revision_store.save(
        {
            "proposal_id": "rev_20260905010101_latest",
            "chapter_id": "ch_001",
            "kind": "review_fix",
            "status": "applied",
            "source_revision": acceptance.fingerprint(chapter.read_text(encoding="utf-8")),
            "applied_revision": "sha256:previous-apply",
            "selection": {},
            "request": {},
            "review_issue_ids": ["issue_1"],
            "replacement_text": "",
            "rationale": "",
            "risk_flags": [],
            "created_at": "2026-09-05T01:01:01+00:00",
            "applied_at": "2026-09-05T01:02:01+00:00",
        }
    )
    task_store = TaskStore(tmp_path, "demo")
    task = task_store.create(
        "chapter_review", {"chapter_id": "ch_001"}, chapter_id="ch_001"
    )
    task_store.transition(task["task_id"], status="running", phase="model")

    chapter.write_text("# 第一章：雨夜\n\n林舟在钟楼听见十三下钟声。\n", encoding="utf-8")
    brief = ChapterWorkBriefService(tmp_path, "demo").get(
        "ch_001", document_id="doc_ch_001_current"
    )

    assert brief["schema_version"] == "openwrite.chapter-work-brief.v1"
    assert brief["document_id"] == "doc_ch_001_current"
    assert brief["manuscript"]["title"] == "第一章：雨夜"
    assert brief["manuscript"]["save_status"] == "saved"
    assert brief["manuscript"]["current_revision"].startswith("sha256:")
    assert brief["manuscript"]["sha256"] == brief["manuscript"][
        "current_revision"
    ].removeprefix("sha256:")
    assert brief["acceptance"]["status"] == "external_change"
    assert brief["acceptance"]["blocking"] is True
    assert brief["review"]["freshness_status"] == "stale"
    assert brief["review"]["stale"] is True
    assert brief["review"]["review_revision"].startswith("sha256:")
    assert brief["review"]["source_revision"] != brief["review"][
        "current_source_revision"
    ]
    assert brief["review"]["gate_status"] == "pass"
    assert brief["review"]["delivery_status"] == "stale"
    assert brief["review"]["deliverable"] is False
    assert brief["latest_revision"]["proposal_id"] == "rev_20260905010101_latest"
    assert brief["latest_revision"]["apply_status"] == "applied"
    assert brief["tasks"][0]["task_id"] == task["task_id"]
    assert brief["tasks"][0]["phase"] == "model"
    assert brief["target"] == {
        "writing_units": 4200,
        "source": "outline",
        "actual_units": brief["manuscript"]["writing_units"],
        "remaining_units": 4200 - brief["manuscript"]["writing_units"],
        "progress": brief["manuscript"]["writing_units"] / 4200,
    }
    assert {item["kind"] for item in brief["recent_edits"]} >= {
        "manuscript_saved",
        "reviewed",
        "revision_applied",
        "task_updated",
        "acceptance_updated",
    }
    for item in brief["recent_edits"]:
        assert {
            "document_id",
            "path",
            "chapter_id",
            "revision",
            "updated_at",
            "writing_units_delta",
            "reason",
        } <= item.keys()
        assert item["document_id"] == "doc_ch_001_current"
        assert item["path"] == brief["manuscript"]["path"]
        assert item["chapter_id"] == "ch_001"
    manuscript_event = next(
        item for item in brief["recent_edits"] if item["kind"] == "manuscript_saved"
    )
    assert manuscript_event["revision"] == brief["manuscript"]["current_revision"]
    assert manuscript_event["writing_units_delta"] is None
    assert manuscript_event["reason"] is None


def test_brief_projects_latest_rereview_issue_closure(tmp_path: Path) -> None:
    init_project(tmp_path, "demo")
    chapter = _chapter(tmp_path, "ch_001", "# 第一章\n\n钟声停了。\n")
    source_revision = ManuscriptAcceptanceService.fingerprint(
        chapter.read_text(encoding="utf-8")
    )
    ReviewStore(tmp_path, "demo").save(
        "ch_001",
        {
            "source_revision": source_revision,
            "score": 82,
            "issue_details": [{"id": "issue_new", "summary": "新增冲突"}],
            "revision_closures": [
                {
                    "schema_version": "openwrite.review-closure.v1",
                    "closure_id": "closure_latest",
                    "proposal_id": "rev_latest",
                    "source_review_revision": "sha256:review-before",
                    "stale_review_revision": "sha256:review-stale",
                    "rereview_review_revision": "sha256:review-after",
                    "source_revision": "sha256:source-before",
                    "applied_revision": source_revision,
                    "rereview_source_revision": source_revision,
                    "selected_issue_ids": ["issue_fixed", "issue_kept"],
                    "issue_outcomes": [
                        {"issue_id": "issue_fixed", "outcome": "resolved"},
                        {"issue_id": "issue_kept", "outcome": "retained"},
                    ],
                    "regressions": [
                        {
                            "issue_id": "issue_new",
                            "outcome": "regressed",
                            "issue": {"id": "issue_new", "summary": "新增冲突"},
                        }
                    ],
                    "closed_at": "2026-09-05T02:00:00+00:00",
                }
            ],
        },
    )

    closure = ChapterWorkBriefService(tmp_path, "demo").get("ch_001")["review"][
        "latest_closure"
    ]

    assert closure["closure_id"] == "closure_latest"
    assert closure["issue_outcomes"] == [
        {"issue_id": "issue_fixed", "outcome": "resolved"},
        {"issue_id": "issue_kept", "outcome": "retained"},
    ]
    assert closure["regressions"][0]["outcome"] == "regressed"
    assert closure["rereview_source_revision"] == source_revision


def test_legacy_foreshadow_review_and_task_records_remain_readable(
    tmp_path: Path,
) -> None:
    init_project(tmp_path, "demo")
    chapter = _chapter(tmp_path, "ch_002", "# 第二章\n\n旧正文。\n")
    _dag(
        tmp_path,
        {"legacy_hook": _node(created_at="ch_001", target_chapter="ch_003")},
    )
    review_dir = (
        tmp_path / "data" / "novels" / "demo" / "data" / "reviews"
    )
    review_dir.mkdir(parents=True, exist_ok=True)
    source_revision = ManuscriptAcceptanceService.fingerprint(
        chapter.read_text(encoding="utf-8")
    )
    (review_dir / "ch_002.json").write_text(
        json.dumps(
            {
                "score": 88,
                "passed": True,
                "source_revision": source_revision,
                "reviewed_at": "2025-01-01T00:00:00+00:00",
                "issue_details": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    task_store = TaskStore(tmp_path, "demo")
    task = task_store.create(
        "chapter_review", {"chapter_id": "ch_002"}, chapter_id="ch_002"
    )
    task_path = task_store.snapshot_path(task["task_id"])
    legacy_task = yaml.safe_load(task_path.read_text(encoding="utf-8"))
    for key in ("schema_version", "phase", "attempt", "retryable"):
        legacy_task.pop(key, None)
    legacy_task["status"] = "completed"
    task_path.write_text(
        yaml.safe_dump(legacy_task, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    first = ChapterWorkBriefService(tmp_path, "demo").get("ch_002")
    second = ChapterWorkBriefService(tmp_path, "demo").get("ch_002")
    item = first["foreshadowing"]["upcoming"][0]

    assert item["id"] == "legacy_hook"
    assert item["plant_anchor"] == {
        "chapter_id": "ch_001",
        "source": "legacy_created_at",
    }
    assert item["reveal_anchor"] == {
        "chapter_id": "ch_003",
        "source": "legacy_target_chapter",
    }
    assert item["source_revision"].startswith("sha256:")
    assert item["source_revision"] == second["foreshadowing"]["upcoming"][0][
        "source_revision"
    ]
    assert first["review"]["schema_version"] == "openwrite.review.v1-adapter"
    assert first["review"]["freshness_status"] == "current"
    assert first["review"]["stale"] is False
    assert first["review"]["review_revision"].startswith("sha256:")
    assert first["review"]["deliverable"] is True
    assert first["tasks"][0]["schema_version"] == "openwrite.task.v0"
    assert first["tasks"][0]["phase"] == "complete"


def test_project_roots_are_strictly_isolated(tmp_path: Path) -> None:
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    for root, body, hook in (
        (root_a, "甲项目正文", "hook_a"),
        (root_b, "乙项目完全不同的正文", "hook_b"),
    ):
        init_project(root, "demo")
        _chapter(root, "ch_001", f"# 第一章\n\n{body}\n")
        _dag(root, {hook: _node(target_chapter="ch_001")})
        TaskStore(root, "demo").create(
            "chapter_review", {"chapter_id": "ch_001"}, chapter_id="ch_001"
        )

    brief_a = ChapterWorkBriefService(root_a, "demo").get("ch_001")
    brief_b = ChapterWorkBriefService(root_b, "demo").get("ch_001")

    assert brief_a["manuscript"]["sha256"] != brief_b["manuscript"]["sha256"]
    assert [item["id"] for item in brief_a["foreshadowing"]["must_resolve"]] == [
        "hook_a"
    ]
    assert [item["id"] for item in brief_b["foreshadowing"]["must_resolve"]] == [
        "hook_b"
    ]
    assert {item["task_id"] for item in brief_a["tasks"]}.isdisjoint(
        {item["task_id"] for item in brief_b["tasks"]}
    )
