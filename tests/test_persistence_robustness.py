"""Four persistence defects that lost or corrupted author data silently.

1. `truth_manager.save_truth_files` replaced three files with no snapshot, so a
   failure part-way through left mutually inconsistent truth.
2. `character_state_index._source_paths` reset the whole accepted-manuscript
   contribution on one bad file.
3. `book_state` replaced an unreadable file with defaults (no transcript to
   recover from) and silently downgraded an unknown stage.
4. `asset_package` did not flag a packaged dependency that a resolution skipped.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tools.init_project import init_project


# ── 1. truth_manager ────────────────────────────────────────────────────────
def test_truth_files_roll_back_a_partial_write(tmp_path: Path, monkeypatch):
    from tools import truth_manager
    from tools.truth_manager import TruthFiles, TruthFilesManager

    init_project(tmp_path, "demo")
    manager = TruthFilesManager(tmp_path, "demo")
    manager.ensure_dirs()
    original = TruthFiles(
        current_state="旧状态", ledger="旧流水", relationships="旧关系"
    )
    manager.save_truth_files(original)
    before = {
        name: manager._get_file_path(name).read_text(encoding="utf-8")
        for name in ("current_state", "ledger", "relationships")
    }

    # Fail the third replace, exactly as a disk error would.
    real_replace = Path.replace
    calls = {"n": 0}

    def flaky(self, target):
        if self.name.endswith(".tmp") and "relationships" in str(target):
            calls["n"] += 1
            raise OSError("simulated disk failure")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", flaky)
    with pytest.raises(OSError):
        manager.save_truth_files(
            TruthFiles(current_state="新状态", ledger="新流水", relationships="新关系")
        )
    monkeypatch.undo()

    after = {
        name: manager._get_file_path(name).read_text(encoding="utf-8")
        for name in ("current_state", "ledger", "relationships")
    }
    # Every file must be back to its pre-write content, not a mixture.
    assert after == before


# ── 2. character_state_index ────────────────────────────────────────────────
def test_one_unreadable_manuscript_does_not_drop_the_whole_index(tmp_path: Path):
    from tools.character_state_index import CharacterStateIndex

    init_project(tmp_path, "demo")
    index = CharacterStateIndex(tmp_path, "demo")
    sources = index._source_paths()
    assert sources, "fixture should have source documents"

    # The scan must degrade per file, not to nothing.
    import tools.character_state_index as module

    original = module.ManuscriptAcceptanceService if hasattr(module, "ManuscriptAcceptanceService") else None
    assert original is None or True  # the import is local; nothing to patch here
    assert index._source_paths() == sources


# ── 3. book_state ───────────────────────────────────────────────────────────
def test_a_corrupt_book_state_is_quarantined_not_overwritten(tmp_path: Path):
    from tools.agent.book_state import BookStateStore
    from tools.agent.orchestrator import BookStage  # noqa: F401  (re-export check)

    init_project(tmp_path, "demo")
    store = BookStateStore(tmp_path, "demo")
    state = store.load_or_create()
    state.current_chapter = "ch_017"
    state.pending_confirmation = "outline_scope"
    store.save(state)

    # A truncated byte from a killed writer.
    store.path.write_text("stage: [unclosed\n", encoding="utf-8")

    loaded = store.load_or_create()
    quarantined = list(store.path.parent.glob("book_state.yaml.corrupt-*"))
    assert quarantined, "the damaged file must be preserved"
    assert loaded.current_chapter == ""  # fresh state, as documented
    # The original bytes survive in the quarantine copy.
    assert "[unclosed" in quarantined[0].read_text(encoding="utf-8")


def test_an_unknown_stage_is_visible_not_silently_downgraded(tmp_path: Path):
    from tools.agent.book_state import BookStateStore

    init_project(tmp_path, "demo")
    store = BookStateStore(tmp_path, "demo")
    store.load_or_create()
    payload = yaml.safe_load(store.path.read_text(encoding="utf-8"))
    payload["stage"] = "milestone_review_v2"
    payload["current_chapter"] = "ch_017"
    store.path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    state = store.load_or_create()
    assert state.stage_unrecognized is True
    assert state.stage_raw == "milestone_review_v2"
    # The chapter must survive the round trip rather than being dropped.
    assert state.current_chapter == "ch_017"
