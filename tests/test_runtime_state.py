from pathlib import Path

import pytest

from models.runtime_state import RuntimeNote, RuntimeStateDelta
from tools.runtime_state import (
    RuntimeStateError,
    RuntimeStateManager,
    legacy_updates_to_delta,
)
from tools.truth_manager import TruthFiles, TruthFilesManager


def test_legacy_truth_migration_and_delta_preserve_unmentioned_facts(tmp_path: Path):
    truth_manager = TruthFilesManager(tmp_path, "demo")
    truth_manager.save_truth_files(
        TruthFiles(
            current_state="# 当前状态\n\n- 续存派仍在港口活动。\n- 蓝色印记已被注意。",
            ledger="# 账本\n\n- M.O. 工具仍由沈烬持有。",
            relationships="# 关系\n\n- 沈烬信任刑无咎。",
        )
    )

    migrated = truth_manager.load_runtime_state()
    updated = truth_manager.apply_runtime_delta(
        {
            "chapter_id": "ch_007",
            "source_revision": migrated.revision,
            "operations": [
                {
                    "op": "append",
                    "collection": "current_state",
                    "value": "沈烬已经提交回响实习申请。",
                },
                {
                    "op": "append",
                    "collection": "ledger",
                    "value": "实习申请回执：等待审核。",
                },
            ],
        }
    )

    truth = truth_manager.load_truth_files()
    assert updated.revision == 1
    assert "续存派仍在港口活动" in truth.current_state
    assert "蓝色印记已被注意" in truth.current_state
    assert "提交回响实习申请" in truth.current_state
    assert "M.O. 工具仍由沈烬持有" in truth.ledger
    assert "实习申请回执" in truth.ledger
    assert "state_revision = 1" in (truth_manager.world_dir / "current_state.md").read_text(
        encoding="utf-8"
    )


def test_runtime_delta_rejects_revision_conflicts_and_unknown_fields(tmp_path: Path):
    manager = RuntimeStateManager(tmp_path, "demo")
    state = manager.load()

    with pytest.raises(RuntimeStateError, match="状态版本冲突"):
        manager.apply(
            state,
            {"chapter_id": "ch_001", "source_revision": 99, "operations": []},
        )

    with pytest.raises(ValueError, match="extra"):
        RuntimeStateDelta.model_validate(
            {
                "chapter_id": "ch_001",
                "operations": [
                    {
                        "op": "append",
                        "collection": "current_state",
                        "value": "事实",
                        "unexpected": True,
                    }
                ],
            }
        )


def test_unknown_relationship_entity_is_proposed_not_canonical(tmp_path: Path):
    manager = RuntimeStateManager(tmp_path, "demo")
    state = manager.load()
    updated = manager.apply(
        state,
        {
            "chapter_id": "ch_007",
            "operations": [
                {
                    "op": "set",
                    "collection": "relationship_states",
                    "target": "沈烬->周正",
                    "value": {
                        "source": "沈烬",
                        "target": "周正",
                        "status": "初次见面",
                    },
                }
            ],
        },
        known_entities=["沈烬"],
    )

    assert updated.relationships == {}
    assert updated.proposed_entities["周正"].entity_type == "character"


def test_runtime_apply_is_immutable(tmp_path: Path):
    manager = RuntimeStateManager(tmp_path, "demo")
    state = manager.load()
    updated = manager.apply(
        state,
        {
            "chapter_id": "ch_001",
            "operations": [
                {
                    "op": "append",
                    "collection": "timeline",
                    "value": {
                        "id": "event_ch_001_01",
                        "chapter_id": "ch_001",
                        "event": "钟楼敲响",
                        "story_time": "雨夜",
                    },
                }
            ],
        },
    )

    assert state.revision == 0 and state.timeline == []
    assert updated.revision == 1 and updated.timeline[0].event == "钟楼敲响"


def test_runtime_state_projection_commit_rolls_back_partial_replace(
    tmp_path: Path, monkeypatch
):
    manager = RuntimeStateManager(tmp_path, "demo")
    original = manager.load(
        {
            "current_state": "旧状态",
            "ledger": "旧账本",
            "relationships": "旧关系",
        }
    )
    manager.save_with_projections(original)
    before = {
        path: path.read_bytes()
        for path in (
            manager.state_path,
            manager.world_dir / "current_state.md",
            manager.world_dir / "ledger.md",
            manager.world_dir / "relationships.md",
        )
    }
    updated = manager.apply(
        original,
        {
            "chapter_id": "ch_001",
            "operations": [
                {"op": "append", "collection": "current_state", "value": "新状态"}
            ],
        },
    )
    original_replace = Path.replace
    failed = {"value": False}

    def fail_ledger_once(source: Path, target: Path):
        target_path = Path(target)
        if target_path.name == "ledger.md" and not failed["value"]:
            failed["value"] = True
            raise OSError("simulated replace failure")
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_ledger_once)
    with pytest.raises(OSError, match="simulated"):
        manager.save_with_projections(updated)

    assert {path: path.read_bytes() for path in before} == before


def test_legacy_save_does_not_reimport_unchanged_projection(tmp_path: Path):
    truth_manager = TruthFilesManager(tmp_path, "demo")
    truth_manager.save_truth_files(TruthFiles(current_state="初始状态"))
    truth_manager.load_runtime_state()
    truth_manager.apply_runtime_delta(
        {
            "chapter_id": "ch_001",
            "operations": [
                {"op": "append", "collection": "current_state", "value": "新增事实"}
            ],
        }
    )
    projection = truth_manager.load_truth_files()
    truth_manager.save_truth_files(projection)

    state = truth_manager.load_runtime_state()
    assert state.revision == 1
    assert len(state.current_state_notes) == 1
    assert truth_manager.load_truth_files().current_state.count("新增事实") == 1


def test_explicit_legacy_replacement_becomes_new_baseline(tmp_path: Path):
    truth_manager = TruthFilesManager(tmp_path, "demo")
    truth_manager.save_truth_files(TruthFiles(current_state="初始状态"))
    truth_manager.load_runtime_state()
    truth_manager.apply_runtime_delta(
        {
            "chapter_id": "ch_001",
            "operations": [
                {"op": "append", "collection": "current_state", "value": "新增事实"}
            ],
        }
    )
    truth = truth_manager.load_truth_files()
    truth.current_state = "作者手工校正后的完整状态"
    truth_manager.save_truth_files(truth)

    state = truth_manager.load_runtime_state()
    assert state.revision == 2
    assert state.current_state_notes == []
    assert truth_manager.load_truth_files().current_state == "作者手工校正后的完整状态"


def test_repeated_legacy_settle_keeps_one_note_per_chapter(tmp_path: Path):
    manager = RuntimeStateManager(tmp_path, "demo")
    first = manager.apply(
        manager.load(),
        legacy_updates_to_delta(
            {"current_state": "第一次结算：华生抵达。"}, chapter_id="ch_001"
        ),
    )
    manager.save_with_projections(first)
    second = manager.apply(
        first,
        legacy_updates_to_delta(
            {"current_state": "第二次结算：华生离开。"}, chapter_id="ch_001"
        ),
    )
    manager.save_with_projections(second)

    rendered = (
        tmp_path / "data" / "novels" / "demo" / "data" / "world" / "current_state.md"
    ).read_text(encoding="utf-8")
    assert rendered.count("### ch_001") == 1
    assert "第二次结算" in rendered
    assert "第一次结算" not in rendered
    assert len([note for note in second.current_state_notes if note.status == "active"]) == 1


def test_render_keeps_latest_active_note_when_history_has_duplicates(tmp_path: Path):
    manager = RuntimeStateManager(tmp_path, "demo")
    state = manager.load()
    state.current_state_notes.extend(
        [
            RuntimeNote(id="note_old", text="旧事实", source_chapter="ch_001"),
            RuntimeNote(id="note_new", text="新事实", source_chapter="ch_001"),
        ]
    )

    rendered = manager.render(state)["current_state"]

    assert "旧事实" not in rendered
    assert "新事实" in rendered


def test_snapshot_restores_canonical_state_and_markdown_projection(tmp_path: Path):
    truth_manager = TruthFilesManager(tmp_path, "demo")
    truth_manager.save_truth_files(TruthFiles(current_state="初始状态"))
    truth_manager.load_runtime_state()
    truth_manager.apply_runtime_delta(
        {
            "chapter_id": "ch_001",
            "operations": [
                {"op": "append", "collection": "current_state", "value": "第一章事实"}
            ],
        }
    )
    snapshot = truth_manager.create_snapshot(1)
    truth_manager.apply_runtime_delta(
        {
            "chapter_id": "ch_002",
            "operations": [
                {"op": "append", "collection": "current_state", "value": "第二章事实"}
            ],
        }
    )

    assert truth_manager.restore_snapshot(snapshot) is True
    restored = truth_manager.load_runtime_state()
    projection = truth_manager.load_truth_files().current_state
    assert restored.revision == 1
    assert "第一章事实" in projection
    assert "第二章事实" not in projection
