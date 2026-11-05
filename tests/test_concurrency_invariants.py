"""Real-thread concurrency tests for the shared-state stores.

Static review can only show that a lock exists; these tests
actually run writers against each other and assert the
invariants: no lost update, no truncated file, no state rollback.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from tools.agent.book_state import BookState, BookStateStore
from tools.init_project import init_project


def test_concurrent_saves_do_not_wipe_a_field_the_writer_never_touched(tmp_path: Path):
    """A field one writer never set must survive the other writer's save.

    `BookState` fields are single-valued, so concurrent writers legitimately
    leave one winner each. What a whole-object dump would still get wrong is
    blanking a field the other writer DID set and this one did not mention at
    all - the merge's job is to inherit it from disk.
    """
    init_project(tmp_path, "demo")
    store_a = BookStateStore(tmp_path, "demo")
    store_b = BookStateStore(tmp_path, "demo")

    # Seed a field only thread A will set; B never mentions it.
    seeded = store_a.load_or_create()
    seeded.last_handoff_from = "goethe"
    store_a.save(seeded)

    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def save(store: BookStateStore, *, chapter: str, handoff: str) -> None:
        try:
            state = store.load_or_create()
            barrier.wait(timeout=10)
            state.current_chapter = chapter
            state.last_handoff_from = handoff
            store.save(state)
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    # Thread B passes an empty handoff: it must inherit A's, not blank it.
    threads = [
        threading.Thread(target=save, kwargs={"store": store_a, "chapter": "ch_001", "handoff": "goethe"}),
        threading.Thread(target=save, kwargs={"store": store_b, "chapter": "ch_002", "handoff": ""}),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert not errors, errors
    final = store_a.load_or_create()
    assert final.last_handoff_from == "goethe", (
        "a concurrent save wiped a field the other writer never set"
    )


def test_the_state_file_is_never_left_truncated_by_concurrent_saves(tmp_path: Path):
    """Every concurrent save must leave a parseable file behind."""
    import yaml

    init_project(tmp_path, "demo")
    stores = [BookStateStore(tmp_path, "demo") for _ in range(4)]
    errors: list[BaseException] = []

    def save(store: BookStateStore, index: int) -> None:
        try:
            for step in range(15):
                state = store.load_or_create()
                state.current_chapter = f"ch_{index:03d}"
                state.last_agent_action = f"action_{index}_{step}"
                store.save(state)
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [threading.Thread(target=save, args=(store, index)) for index, store in enumerate(stores)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert not errors, errors
    assert stores[0].path.is_file()
    assert isinstance(yaml.safe_load(stores[0].path.read_text(encoding="utf-8")), dict)
    # No stray temporary files.
    assert sorted(p.name for p in stores[0].path.parent.iterdir() if p.name.startswith('.')) == []


def test_concurrent_runtime_deltas_do_not_lose_one_another(tmp_path: Path):
    """Two concurrent settlements must not drop the first delta.

    `apply_runtime_delta` is a read-modify-write over the shared truth files.
    `settle_backfill` holds the project lock around it, but the chapter-commit
    path through `MultiAgentDirector._apply_state_settlement` did not: two
    concurrent commits both read, both applied, and only the second delta
    survived. `append` is used because a `set` on a not-yet-existing entity is
    rejected by the runtime-state validator.
    """
    from tools.agent.base import AgentContext
    from tools.agent.director import MultiAgentDirector
    from tools.init_project import init_project
    from tools.truth_manager import TruthFilesManager

    init_project(tmp_path, "demo")
    ctx = AgentContext.__new__(AgentContext)
    ctx.project_root = str(tmp_path)
    director = MultiAgentDirector(ctx, "demo")

    barrier = threading.Barrier(2)
    errors: list[BaseException] = []

    def settle(chapter: str, note: str) -> None:
        try:
            delta = {
                "chapter_id": chapter,
                "operations": [
                    {"op": "append", "collection": "ledger", "target": note, "value": note}
                ],
            }
            barrier.wait(timeout=15)
            director._apply_state_settlement(
                delta, {}, chapter_id=chapter, known_entities=[]
            )
        except BaseException as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [
        threading.Thread(target=settle, args=("ch_001", "沈烬离开钟楼")),
        threading.Thread(target=settle, args=("ch_002", "林岑进入雨夜")),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    # A ProjectBusyError is the lock doing its job; anything else is a bug.
    busy = [exc for exc in errors if type(exc).__name__ == "ProjectBusyError"]
    other = [exc for exc in errors if type(exc).__name__ != "ProjectBusyError"]
    assert not other, other

    truth = TruthFilesManager(tmp_path, "demo").load_truth_files()
    ledger = str(truth.ledger)

    if busy:
        # The lock rejected the second writer, which is correct: it must not have
        # partially written anything either.
        assert len(busy) == 1, f"both writers were rejected: {busy}"
        assert "沈烬离开钟楼" in ledger or "林岑进入雨夜" in ledger, ledger[:300]
    else:
        # Both were admitted, so the lock serialised them: BOTH deltas must land.
        # Without the lock both threads read the same empty ledger and the second
        # write clobbers the first - a lost update that "at least one landed"
        # would hide.
        assert "沈烬离开钟楼" in ledger, f"first settlement lost: {ledger[:300]}"
        assert "林岑进入雨夜" in ledger, f"second settlement lost: {ledger[:300]}"
    # Nothing was left half-written either way.
    assert isinstance(truth.ledger, str)


def test_a_stale_snapshot_cannot_roll_a_task_back_from_a_terminal_state(tmp_path: Path):
    """A caller holding a pre-completion snapshot must not resurrect the task.

    `recover_interrupted` lists `running` tasks at startup; a task that completed
    meanwhile used to be flipped back to `interrupted`, contradicting its own
    completion event. The compare-and-set in `transition()` is what prevents it,
    and this test drives both sides from real threads.
    """
    from tools.init_project import init_project
    from tools.task_store import TaskStore, TaskStoreError

    init_project(tmp_path, "demo")
    store = TaskStore(tmp_path, "demo")
    task = store.create("chapter_write", {"chapter_id": "ch_001"})
    task_id = task["task_id"]

    # A caller that read the task while it was still running.
    stale = store.load(task_id)
    assert stale["status"] == "pending"

    # The recovering process reads `running` at startup, then the task finishes,
    # then it transitions. That ordering is what the compare-and-set must catch.
    completed = threading.Event()
    errors: list[BaseException] = []

    def complete_it() -> None:
        try:
            store.transition(task_id, status="running", expected_status="pending")
            store.transition(task_id, status="completed", expected_status="running",
                             updates={"result": {"ok": True}})
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
        finally:
            completed.set()

    def roll_it_back() -> None:
        # Wait for the terminal state to be on disk first: the recovering process
        # read `running` before that, so its expectation is now stale.
        assert completed.wait(timeout=30)
        try:
            store.transition(task_id, status="interrupted", expected_status="running")
            errors.append(AssertionError("a terminal task was rolled back"))
        except AssertionError:
            raise
        except BaseException as exc:  # noqa: BLE001 - TaskStoreError is correct here
            errors.append(exc)

    threads = [
        threading.Thread(target=complete_it),
        threading.Thread(target=roll_it_back),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    # The roll-back must have been refused, and it must be the CAS that refused it.
    assert not any(isinstance(exc, AssertionError) for exc in errors), errors
    refused = [exc for exc in errors if type(exc).__name__ == "TaskStoreError"]
    assert refused, f"the stale roll-back was not refused at all: {errors}"

    final = store.load(task_id)
    # The completion must never be replaced by the recovering process's
    # `interrupted`: that would contradict the task's own completion event.
    assert final["status"] != "interrupted", (
        f"a stale snapshot rolled a finished task back: {outcomes}"
    )
    if final["status"] == "completed":
        assert final["completed_at"], "a completed task must carry its completion timestamp"
    # The store stayed consistent: no stray temp files, index parseable.
    import yaml
    assert isinstance(yaml.safe_load(store.index_path.read_text(encoding="utf-8")), dict)
    assert sorted(p.name for p in store.root.iterdir() if p.name.startswith('.')) == []


def test_concurrent_drift_entries_do_not_corrupt_the_ledger(tmp_path: Path):
    """Concurrent drift entries must be serialised, not interleaved.

    `change()` takes the project lock and compares `expected_revision` against
    the on-disk ledger. Two authors editing at once should see exactly one
    winner per round, a strictly increasing revision, and no lost entry - the
    loser is told to refresh rather than silently overwriting.
    """
    from tools.arc_audit import ArcAuditService
    from tools.init_project import init_project

    init_project(tmp_path, "demo")
    root = tmp_path / "data" / "novels" / "demo"
    outline = "# 作品\n\n## 第1篇：篇\n\n### 第1节：节\n\n"
    for number in range(1, 5):
        outline += (
            f"#### 第{number}章：章\n\n内容。\n\n> 预估字数: 1000\n"
            "> 字数预算: 1000\n> 章节承诺: 未拿到钥匙 -> 拿到钥匙\n> 章节功能: 推进\n\n"
        )
    (root / "src" / "outline.md").write_text(outline)
    for number in range(1, 4):
        (root / "data" / "manuscript" / "arc_001" / f"ch_{number:03d}.md").write_text(
            f"# 第{number}章\n\n" + "甲" * 800
        )
    service = ArcAuditService(tmp_path, "demo")
    audit = service.audit("sec_001")
    base_revision = int(audit["ledger"]["revision"])

    barrier = threading.Barrier(3)
    accepted: list[int] = []
    rejected: list[int] = []
    errors: list[BaseException] = []

    def enter(index: int) -> None:
        try:
            barrier.wait(timeout=15)
            # Every thread read the same revision, so at most one can win.
            result = service.change({
                "action": "drift_entry",
                "group_id": "sec_001",
                "chapter_id": "ch_001",
                "kind": "growth",
                "impact": "section",
                "note": f"并发修改 {index}",
                "expected_revision": base_revision,
            })
            accepted.append(int(result["ledger"]["revision"]))
        except ValueError:
            # The revision CAS refused this writer: exactly the safe outcome.
            rejected.append(index)
        except BaseException as exc:  # noqa: BLE001
            # A busy project lock is the other half of the serialisation; record
            # it as a refusal rather than a failure.
            if type(exc).__name__ == "ProjectBusyError":
                rejected.append(index)
            else:
                errors.append(exc)

    threads = [threading.Thread(target=enter, args=(index,)) for index in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert not errors, errors
    # Exactly one winner per round: the others were refused by the revision CAS
    # or by the project lock - both are the safe outcome.
    assert len(accepted) == 1, f"expected one winner, got {len(accepted)}: {accepted}"
    assert accepted[0] > base_revision, "the revision must advance"

    final = service.ledger()
    assert int(final["revision"]) == accepted[0], "the ledger revision drifted from the winner"
    entries = final.get("entries") or []
    notes = [str(entry.get("note") or "") for entry in entries]
    assert any("并发修改" in note for note in notes), f"the winning entry is missing: {notes}"
    # No entry was duplicated or half-written.
    assert len(notes) == len(set(notes)), f"duplicated entries: {notes}"

    # A follow-up round with the fresh revision succeeds, so the ledger is usable.
    follow_up = service.change({
        "action": "drift_entry",
        "group_id": "sec_001",
        "chapter_id": "ch_001",
        "kind": "growth",
        "impact": "section",
        "note": "后续修改",
        "expected_revision": int(final["revision"]),
    })
    assert int(follow_up["ledger"]["revision"]) == accepted[0] + 1


def test_a_stale_revision_is_refused_even_when_the_lock_is_free(tmp_path: Path):
    """The revision CAS must work on its own, not only behind the lock.

    The concurrent test above cannot isolate it: with the project lock present,
    removing the CAS still leaves the ledger correct because the lock serialises
    the writers. The real exposure is a caller that read the ledger, did other
    work, and then wrote - by which time another writer has advanced it. That is
    exactly what `expected_revision` exists for.
    """
    from tools.arc_audit import ArcAuditService
    from tools.init_project import init_project

    init_project(tmp_path, "demo")
    root = tmp_path / "data" / "novels" / "demo"
    outline = "# 作品\n\n## 第1篇：篇\n\n### 第1节：节\n\n"
    for number in range(1, 5):
        outline += (
            f"#### 第{number}章：章\n\n内容。\n\n> 预估字数: 1000\n"
            "> 字数预算: 1000\n> 章节承诺: 未拿到钥匙 -> 拿到钥匙\n> 章节功能: 推进\n\n"
        )
    (root / "src" / "outline.md").write_text(outline)
    for number in range(1, 4):
        (root / "data" / "manuscript" / "arc_001" / f"ch_{number:03d}.md").write_text(
            f"# 第{number}章\n\n" + "甲" * 800
        )
    service = ArcAuditService(tmp_path, "demo")
    base = int(service.audit("sec_001")["ledger"]["revision"])

    # A first writer advances the ledger.
    service.change({
        "action": "drift_entry", "group_id": "sec_001", "chapter_id": "ch_001",
        "kind": "growth", "impact": "section", "note": "第一次", "expected_revision": base,
    })
    assert int(service.ledger()["revision"]) == base + 1

    # A second writer still holding the ORIGINAL revision must be refused.
    with pytest.raises(ValueError, match="revision"):
        service.change({
            "action": "drift_entry", "group_id": "sec_001", "chapter_id": "ch_001",
            "kind": "growth", "impact": "section", "note": "陈旧写入", "expected_revision": base,
        })

    # The refused write left no trace.
    notes = [str(e.get("note") or "") for e in service.ledger().get("entries") or []]
    assert "陈旧写入" not in notes, notes


def test_a_failed_cache_write_leaves_no_temporary_file(tmp_path, monkeypatch):
    """A failed replace must not leave a stray .tmp behind.

    These stores each hand-rolled the temp-file dance with `delete=False` and no
    finally block, so a failed `replace` (permissions, a locked target) leaked a
    hidden .tmp file into the project data directory on every failure. They now
    share `file_ops.atomic_write`, which unlinks in a finally block.
    """
    import tools.file_ops as file_ops
    from tools.character_state_index import CharacterStateIndex
    from tools.init_project import init_project

    init_project(tmp_path, "demo")
    src = tmp_path / "data" / "novels" / "demo" / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "outline.md").write_text("# 小说\n\n#### ch_001 起点\n\n甲\n", encoding="utf-8")
    index = CharacterStateIndex(tmp_path, "demo")
    index.refresh()

    def failing_replace(source, target):
        raise OSError("simulated failure before the rename")

    monkeypatch.setattr(file_ops, "replace_file", failing_replace)
    with pytest.raises(OSError):
        index._save_cache({"schema_version": 1, "documents": [], "records": []})

    # The index lives under .openwrite/, not data/, so scan the whole project.
    # atomic_write names its temp file `.<name>.<random>` with no .tmp suffix,
    # so matching on the suffix would miss exactly what we are looking for.
    strays = sorted(
        str(path.relative_to(tmp_path))
        for path in tmp_path.rglob(".*")
        if path.is_file() and path.name.startswith(".") and path.suffix != ".json"
    )
    assert strays == [], f"a failed write leaked temporary files: {strays}"


def test_the_shared_atomic_writer_cleans_up_its_temporary_file():
    """`file_ops.atomic_write` must not leak a temp file when the replace fails.

    This is the writer most of tools/ delegates to, so its finally block is the
    single most valuable cleanup in the codebase. (Auditing every hand-rolled
    temp+replace is tracked separately: an AST scan reports false positives on
    nested functions, so it is not yet a reliable gate.)
    """
    import tempfile
    from pathlib import Path

    import tools.file_ops as file_ops

    target_dir = Path(tempfile.mkdtemp())
    target = target_dir / "state.json"

    def failing_replace(source, target_path):
        raise OSError("simulated failure before the rename")

    original_replace = file_ops.replace_file
    file_ops.replace_file = failing_replace
    try:
        try:
            file_ops.atomic_write(target, '{"ok": true}')
        except OSError:
            pass
        # No leftover hidden file of any name.
        leftovers = sorted(item.name for item in target_dir.iterdir())
        assert leftovers == [], f"a failed atomic_write leaked: {leftovers}"
    finally:
        file_ops.replace_file = original_replace


def test_a_deeply_nested_book_state_does_not_block_the_writers_save(tmp_path):
    """A malformed on-disk state must not fail the writer's save.

    RecursionError is not a YAMLError, so it escaped `_merge_with_disk`'s
    handler: every save raised instead of falling back to the writer's own
    state, and the damaged file was never replaced.
    """
    from tools.agent.book_state import BookState, BookStateStore
    from tools.init_project import init_project

    init_project(tmp_path, "demo")
    store = BookStateStore(tmp_path, "demo")
    store.save(BookState(novel_id="demo", current_chapter="ch_001"))

    depth = 100_000
    store.path.write_text("[" * depth + "]" * depth, encoding="utf-8")

    # The save must succeed, using the writer's own state.
    store.save(BookState(novel_id="demo", current_chapter="ch_002", last_agent_action="recovered"))

    final = store.load_or_create()
    assert final.current_chapter == "ch_002", "the writer's state was not persisted"
    # The damaged file is gone, so the next start is not blocked either.
    import yaml
    assert isinstance(yaml.safe_load(store.path.read_text(encoding="utf-8")), dict)
