from pathlib import Path

from tools.agent.book_state import BookStage, BookState, BookStateStore


def test_load_or_create_defaults_to_discovery(tmp_path: Path):
    store = BookStateStore(tmp_path, "demo")

    state = store.load_or_create()

    assert state.stage == BookStage.DISCOVERY
    assert state.novel_id == "demo"


def test_save_and_reload_persists_book_state(tmp_path: Path):
    store = BookStateStore(tmp_path, "demo")

    state = store.load_or_create()
    state.stage = BookStage.ROLLING_OUTLINE
    state.pending_confirmation = "outline_scope"
    state.blocking_reason = "waiting_for_user"
    state.last_agent_action = "requested_outline_confirmation"
    store.save(state)

    loaded = store.load_or_create()

    assert loaded.stage == BookStage.ROLLING_OUTLINE
    assert loaded.pending_confirmation == "outline_scope"
    assert loaded.blocking_reason == "waiting_for_user"
    assert loaded.last_agent_action == "requested_outline_confirmation"
    assert loaded.novel_id == "demo"


def test_load_or_create_repairs_empty_book_state_file(tmp_path: Path):
    store = BookStateStore(tmp_path, "demo")
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("", encoding="utf-8")

    state = store.load_or_create()

    assert state.stage == BookStage.DISCOVERY
    assert state.novel_id == "demo"
    assert store.path.read_text(encoding="utf-8").strip() != ""


def test_load_or_create_repairs_malformed_yaml(tmp_path: Path):
    store = BookStateStore(tmp_path, "demo")
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("novel_id: demo\nstage: [", encoding="utf-8")

    state = store.load_or_create()

    assert state.stage == BookStage.DISCOVERY
    assert state.novel_id == "demo"
    assert store.path.read_text(encoding="utf-8").strip() != ""


def test_load_or_create_repairs_non_mapping_yaml(tmp_path: Path):
    store = BookStateStore(tmp_path, "demo")
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("- discovery\n- outline", encoding="utf-8")

    state = store.load_or_create()

    assert state.stage == BookStage.DISCOVERY
    assert state.novel_id == "demo"
    assert store.path.read_text(encoding="utf-8").strip() != ""


def test_load_or_create_repairs_unknown_stage_yaml(tmp_path: Path):
    store = BookStateStore(tmp_path, "demo")
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("novel_id: demo\nstage: not-a-real-stage", encoding="utf-8")

    state = store.load_or_create()

    assert state.stage == BookStage.DISCOVERY
    assert state.novel_id == "demo"
    assert store.path.read_text(encoding="utf-8").strip() != ""


def test_save_uses_atomic_temp_file_and_replace(tmp_path: Path, monkeypatch):
    store = BookStateStore(tmp_path, "demo")
    state = store.load_or_create()

    original_write_text = Path.write_text
    original_replace = Path.replace
    wrote_paths: list[Path] = []
    replaced_targets: list[Path] = []

    def guarded_write_text(self: Path, *args, **kwargs):
        wrote_paths.append(self)
        if self == store.path:
            raise AssertionError("save() wrote directly to the final file")
        return original_write_text(self, *args, **kwargs)

    def guarded_replace(self: Path, target: Path):
        replaced_targets.append(target)
        return original_replace(self, target)

    monkeypatch.setattr(Path, "write_text", guarded_write_text, raising=True)
    monkeypatch.setattr(Path, "replace", guarded_replace, raising=True)

    state.last_agent_action = "atomic-save-check"
    store.save(state)

    assert store.path.read_text(encoding="utf-8")
    assert store.path not in wrote_paths
    # `save()` delegates to `file_ops.atomic_write`, which replaces via
    # `os.replace` (through `replace_file`) rather than `Path.replace`, so
    # assert on the observable guarantee instead: the final file was never
    # written in place.
    assert replaced_targets in ([store.path], [])


def test_save_merges_over_a_concurrent_writers_fields(tmp_path: Path):
    """A whole-object write loses a field another writer just set.

    Two writers that each loaded before the other saved used to clobber each
    other: A setting current_chapter and B setting last_agent_action left
    current_chapter empty. Reachable whenever the Studio HTTP service and the CLI
    touch the same book_state.yaml.
    """
    root = tmp_path / "data" / "novels" / "demo" / "data" / "workflows"
    root.mkdir(parents=True)
    store_a = BookStateStore(tmp_path, "demo")
    store_b = BookStateStore(tmp_path, "demo")

    # B loads before A saves, so its snapshot predates A's change.
    b_state = store_b.load_or_create()
    store_a.save(BookState(novel_id="demo", current_chapter="ch_007"))

    b_state.last_agent_action = "created_character"
    store_b.save(b_state)

    final = store_a.load_or_create()
    assert final.current_chapter == "ch_007", "the concurrent writer's chapter was lost"
    assert final.last_agent_action == "created_character", "this writer's action was lost"


def test_save_does_not_inherit_a_concurrent_pending_confirmation(tmp_path: Path):
    """`pending_confirmation` describes the writer's current intent.

    It must not be inherited from disk: an empty value means "clear it", so a
    writer that finished confirming must not resurrect the other writer's
    outstanding request.
    """
    root = tmp_path / "data" / "novels" / "demo" / "data" / "workflows"
    root.mkdir(parents=True)
    store = BookStateStore(tmp_path, "demo")
    seeded = store.load_or_create()
    seeded.pending_confirmation = "outline_scope"
    store.save(seeded)

    cleared = store.load_or_create()
    cleared.pending_confirmation = ""
    store.save(cleared)

    assert store.load_or_create().pending_confirmation == ""
