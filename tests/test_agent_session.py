from pathlib import Path

import yaml

from tools.agent.session_state import (
    MAX_COMPRESSION_MARKERS,
    MAX_RECENT_TURNS,
    MAX_SESSION_BYTES,
    MAX_WORKING_MEMORY_KEYS,
    CompressionMarker,
    DanteSessionState,
    SessionStateStore,
    SessionTurn,
)


def test_load_or_create_creates_default_session_state(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo")

    state = store.load_or_create()

    assert state.session_id == "demo"
    assert state.active_agent == "dante"
    assert state.conversation_summary == ""
    assert state.recent_turns == []
    assert state.working_memory == {}
    assert state.open_questions == []
    assert state.recent_files == []
    assert state.last_action == ""
    assert state.compression_markers == []
    assert state.updated_at != ""
    assert store.path.exists()
    assert store.path.name == "agent_session.yaml"


def test_append_turn_archives_full_transcript_separately_from_rolling_state(
    tmp_path: Path,
):
    store = SessionStateStore(tmp_path, "demo")

    store.append_turn("user", "这是一段完整的历史讨论。" * 100)
    store.append_turn("assistant", "这是完整回复。" * 100)

    assert store.transcript_path.name == "agent_session.jsonl"
    records = [
        yaml.safe_load(line)
        for line in store.transcript_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [record["role"] for record in records] == ["user", "assistant"]
    assert len(records[0]["content"]) > 256
    assert records[0]["session_id"] == "demo"


def test_named_session_store_writes_isolated_state_and_transcript(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo", session_id="dante-20260729-120000-a1b2c3")

    state = store.load_or_create()
    store.append_turn("user", "推进第一章")

    assert state.session_id == "dante-20260729-120000-a1b2c3"
    assert store.path.relative_to(tmp_path).as_posix().endswith(
        "data/workflows/sessions/dante/dante-20260729-120000-a1b2c3.yaml"
    )
    assert store.transcript_path.name == "dante-20260729-120000-a1b2c3.jsonl"
    default_transcript = (
        tmp_path
        / "data"
        / "novels"
        / "demo"
        / "data"
        / "workflows"
        / "agent_session.jsonl"
    )
    assert not default_transcript.exists()
    record = yaml.safe_load(store.transcript_path.read_text(encoding="utf-8"))
    assert record["session_id"] == "dante-20260729-120000-a1b2c3"


def test_save_compresses_old_turns_into_summary(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo")
    state = DanteSessionState(session_id="demo")
    state.recent_turns = [
        SessionTurn(role="user", content=f"turn-{index:02d}")
        for index in range(MAX_RECENT_TURNS + 2)
    ]

    store.save(state)
    loaded = store.load_or_create()

    assert len(loaded.recent_turns) == MAX_RECENT_TURNS
    assert [turn.content for turn in loaded.recent_turns] == [
        f"turn-{index:02d}" for index in range(2, MAX_RECENT_TURNS + 2)
    ]
    assert "turn-00" in loaded.conversation_summary
    assert "turn-01" in loaded.conversation_summary
    assert loaded.compression_markers
    assert loaded.compression_markers[-1].dropped_turns == 2
    assert loaded.compression_markers[-1].kept_turns == MAX_RECENT_TURNS


def test_load_or_create_compresses_existing_overlong_session_and_keeps_recent_window(
    tmp_path: Path,
):
    store = SessionStateStore(tmp_path, "demo")
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        yaml.safe_dump(
            {
                "session_id": "demo",
                "active_agent": "dante",
                "conversation_summary": "seed summary",
                "recent_turns": [
                    {"role": "user", "content": f"turn-{index:02d}"}
                    for index in range(MAX_RECENT_TURNS + 3)
                ],
                "working_memory": {"topic": "outline"},
                "open_questions": ["confirm premise"],
                "recent_files": ["src/chapter_1.md"],
                "last_action": "chat",
                "compression_markers": [],
                "updated_at": "2026-03-30T10:05:00",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    state = store.load_or_create()

    assert len(state.recent_turns) == MAX_RECENT_TURNS
    assert [turn.content for turn in state.recent_turns] == [
        f"turn-{index:02d}" for index in range(3, MAX_RECENT_TURNS + 3)
    ]
    assert state.conversation_summary != "seed summary"
    assert "seed summary" in state.conversation_summary
    assert "turn-00" in state.conversation_summary
    assert state.compression_markers[-1].reason == "count"
    assert state.compression_markers[-1].kept_turns == MAX_RECENT_TURNS


def test_load_or_create_restores_valid_existing_session(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo")
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        yaml.safe_dump(
            {
                "session_id": "session-123",
                "active_agent": "dante",
                "conversation_summary": "old summary",
                "recent_turns": [
                    {"role": "assistant", "content": "hello"},
                    {"role": "user", "content": "world"},
                ],
                "working_memory": {"topic": "outline"},
                "open_questions": ["confirm premise"],
                "recent_files": ["src/chapter_1.md"],
                "last_action": "summarize",
                    "compression_markers": [
                        {
                            "compressed_at": "2026-03-30T10:00:00",
                            "dropped_turns": 3,
                            "kept_turns": 2,
                            "reason": "count",
                        }
                    ],
                "updated_at": "2026-03-30T10:05:00",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    state = store.load_or_create()

    assert state.session_id == "session-123"
    assert state.active_agent == "dante"
    assert state.conversation_summary == "old summary"
    assert [turn.content for turn in state.recent_turns] == ["hello", "world"]
    assert isinstance(state.recent_turns[0], SessionTurn)
    assert state.working_memory == {"topic": "outline"}
    assert state.open_questions == ["confirm premise"]
    assert state.recent_files == ["src/chapter_1.md"]
    assert state.last_action == "summarize"
    assert state.compression_markers[0].dropped_turns == 3
    assert isinstance(state.compression_markers[0], CompressionMarker)
    assert state.updated_at == "2026-03-30T10:05:00"


def test_load_or_create_upgrades_partial_session_without_data_loss(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo")
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        yaml.safe_dump(
            {
                "session_id": "legacy-1",
                "conversation_summary": "legacy summary",
                "recent_turns": [
                    {"role": "user", "content": "old question"},
                ],
                "updated_at": "2026-03-29T09:00:00",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    state = store.load_or_create()

    assert state.session_id == "legacy-1"
    assert state.conversation_summary == "legacy summary"
    assert [turn.content for turn in state.recent_turns] == ["old question"]
    assert state.active_agent == "dante"
    assert state.working_memory == {}
    assert yaml.safe_load(store.path.read_text(encoding="utf-8"))["session_id"] == "legacy-1"


def test_load_or_create_surfaces_filesystem_errors(tmp_path: Path, monkeypatch):
    store = SessionStateStore(tmp_path, "demo")
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        yaml.safe_dump(
            {
                "session_id": "demo",
                "active_agent": "dante",
                "conversation_summary": "",
                "recent_turns": [],
                "working_memory": {},
                "open_questions": [],
                "recent_files": [],
                "last_action": "",
                "compression_markers": [],
                "updated_at": "",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    def raise_ioerror(self: Path, *args, **kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr(Path, "read_text", raise_ioerror, raising=True)

    try:
        store.load_or_create()
    except OSError as exc:
        assert "disk unavailable" in str(exc)
    else:
        raise AssertionError("load_or_create() swallowed a filesystem error")


def test_save_compresses_huge_turns_by_size(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo")
    huge_text = "x" * (MAX_SESSION_BYTES)
    state = DanteSessionState(session_id="demo")
    state.recent_turns = [
        SessionTurn(role="user", content="first"),
        SessionTurn(role="assistant", content=f"second {huge_text}"),
    ]

    store.save(state)
    loaded = store.load_or_create()
    persisted_size = len(store.path.read_text(encoding="utf-8").encode("utf-8"))

    assert persisted_size <= MAX_SESSION_BYTES
    assert loaded.recent_turns
    assert loaded.compression_markers[-1].reason == "size"


def test_save_by_size_preserves_older_turn_content_in_summary(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo")
    huge_text = "x" * (MAX_SESSION_BYTES)
    state = DanteSessionState(session_id="demo")
    state.recent_turns = [
        SessionTurn(role="user", content=f"older {huge_text}"),
        SessionTurn(role="assistant", content="tail"),
    ]

    store.save(state)
    loaded = store.load_or_create()

    assert "older" in loaded.conversation_summary
    assert loaded.recent_turns[-1].content == "tail"


def test_save_by_size_records_moved_turn_count(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo")
    huge_text = "x" * (MAX_SESSION_BYTES)
    state = DanteSessionState(session_id="demo")
    state.recent_turns = [
        SessionTurn(role="user", content=f"older {huge_text}"),
        SessionTurn(role="assistant", content="tail"),
    ]
    state.working_memory = {"notes": "y" * (MAX_SESSION_BYTES // 2)}

    store.save(state)
    loaded = store.load_or_create()

    assert loaded.compression_markers[-1].reason == "size"
    assert loaded.compression_markers[-1].dropped_turns >= 1
    assert "older" in loaded.conversation_summary


def test_save_by_size_records_moved_turn_count_after_extra_compaction(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo")
    huge_text = "x" * MAX_SESSION_BYTES
    state = DanteSessionState(session_id="demo")
    state.recent_turns = [
        SessionTurn(role="user", content=f"older {huge_text}"),
        SessionTurn(role="assistant", content="tail"),
    ]
    state.working_memory = {"notes": "y" * MAX_SESSION_BYTES}
    state.open_questions = ["q" * MAX_SESSION_BYTES]
    state.recent_files = ["file-" + ("z" * MAX_SESSION_BYTES)]
    state.last_action = "w" * (MAX_SESSION_BYTES // 2)

    store.save(state)
    loaded = store.load_or_create()

    assert loaded.compression_markers[-1].reason == "size"
    assert loaded.compression_markers[-1].dropped_turns >= 1
    assert "older" in loaded.conversation_summary


def test_save_compresses_oversized_metadata_payload(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo")
    huge_text = "x" * (MAX_SESSION_BYTES)
    state = DanteSessionState(session_id="demo")
    state.working_memory = {"notes": huge_text}
    state.open_questions = [huge_text, huge_text]
    state.recent_files = [f"file-{index}-{huge_text}" for index in range(3)]
    state.last_action = huge_text

    store.save(state)
    loaded = store.load_or_create()
    persisted_size = len(store.path.read_text(encoding="utf-8").encode("utf-8"))

    assert persisted_size <= MAX_SESSION_BYTES
    assert loaded.working_memory
    assert loaded.open_questions
    assert loaded.recent_files
    assert len(loaded.last_action) <= len(huge_text)
    assert loaded.compression_markers[-1].reason == "size"


def test_save_compresses_metadata_only_payload_without_missing_helper(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo")
    state = DanteSessionState(session_id="demo")
    state.working_memory = {"notes": "x" * (MAX_SESSION_BYTES * 2)}
    state.last_action = "y" * (MAX_SESSION_BYTES // 2)

    store.save(state)

    persisted_size = len(store.path.read_text(encoding="utf-8").encode("utf-8"))
    loaded = store.load_or_create()

    assert persisted_size <= MAX_SESSION_BYTES
    assert loaded.working_memory
    assert loaded.compression_markers[-1].reason == "size"


def test_repeated_save_load_cycles_bound_compression_markers(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo")
    state = DanteSessionState(session_id="demo")
    state.recent_turns = [
        SessionTurn(role="user", content=f"turn-{index:02d}")
        for index in range(MAX_RECENT_TURNS + 1)
    ]
    state.compression_markers = [
        CompressionMarker(
            compressed_at=f"2026-03-30T10:00:{index:02d}",
            dropped_turns=1,
            kept_turns=1,
            reason="count",
        )
        for index in range(40)
    ]

    for _ in range(3):
        store.save(state)
        state = store.load_or_create()

    persisted_size = len(store.path.read_text(encoding="utf-8").encode("utf-8"))

    assert persisted_size <= MAX_SESSION_BYTES
    assert len(state.compression_markers) <= MAX_COMPRESSION_MARKERS


def test_load_or_create_repairs_complete_file_with_too_many_markers(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo")
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        yaml.safe_dump(
            {
                "session_id": "demo",
                "active_agent": "dante",
                "conversation_summary": "summary",
                "recent_turns": [],
                "working_memory": {},
                "open_questions": [],
                "recent_files": [],
                "last_action": "",
                "compression_markers": [
                    {
                        "compressed_at": f"2026-03-30T10:00:{index:02d}",
                        "dropped_turns": 1,
                        "kept_turns": 1,
                        "reason": "count",
                    }
                    for index in range(MAX_COMPRESSION_MARKERS + 4)
                ],
                "updated_at": "2026-03-30T10:05:00",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    state = store.load_or_create()
    reloaded = yaml.safe_load(store.path.read_text(encoding="utf-8"))

    assert len(state.compression_markers) == MAX_COMPRESSION_MARKERS
    assert len(reloaded["compression_markers"]) == MAX_COMPRESSION_MARKERS
    assert reloaded["compression_markers"][0]["compressed_at"].endswith(":04")


def test_repeat_save_is_idempotent_after_compression(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo")
    huge_text = "x" * (MAX_SESSION_BYTES // 2)
    state = DanteSessionState(session_id="demo")
    state.recent_turns = [
        SessionTurn(role="user", content=f"first {huge_text}"),
        SessionTurn(role="assistant", content=f"second {huge_text}"),
    ]

    store.save(state)
    first = store.load_or_create()
    first_summary = first.conversation_summary
    first_turns = list(first.recent_turns)
    first_markers = list(first.compression_markers)

    store.save(first)
    second = store.load_or_create()

    assert second.conversation_summary == first_summary
    assert second.recent_turns == first_turns
    assert second.compression_markers == first_markers


def test_load_or_create_persists_normalized_malformed_data(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo")
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        yaml.safe_dump(
            {
                "session_id": "legacy-2",
                "conversation_summary": "summary",
                "recent_turns": [
                    {"role": "user", "content": "prompt"},
                ],
                "compression_markers": [
                    {"compressed_at": "2026-03-30T10:00:00", "reason": "bogus"}
                ],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    state = store.load_or_create()
    reloaded = yaml.safe_load(store.path.read_text(encoding="utf-8"))

    assert state.session_id == "legacy-2"
    assert reloaded["active_agent"] == "dante"
    assert reloaded["working_memory"] == {}
    assert reloaded["compression_markers"][0]["reason"] == "count"


def test_load_or_create_persists_normalized_schema_complete_data(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo")
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        yaml.safe_dump(
            {
                "session_id": "legacy-3",
                "active_agent": "dante",
                "conversation_summary": "",
                "recent_turns": [],
                "working_memory": {"nested": {"unsafe": "keep"}},
                "open_questions": [1, "keep"],
                "recent_files": ["chapter.md", 2],
                "last_action": 999,
                "compression_markers": [
                    {
                        "compressed_at": "2026-03-30T10:00:00",
                        "dropped_turns": "bad",
                        "kept_turns": 1,
                        "reason": "bogus",
                    }
                ],
                "updated_at": "",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    state = store.load_or_create()
    reloaded = yaml.safe_load(store.path.read_text(encoding="utf-8"))

    assert state.session_id == "legacy-3"
    assert state.compression_markers[0].reason == "count"
    assert reloaded["compression_markers"][0]["dropped_turns"] == 0
    assert reloaded["compression_markers"][0]["reason"] == "count"
    assert reloaded["open_questions"] == ["1", "keep"]
    assert reloaded["recent_files"] == ["chapter.md", "2"]
    assert reloaded["last_action"] == "999"


def test_save_stringifies_unsafe_working_memory_values(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo")

    class UnsafeValue:
        pass

    state = DanteSessionState(session_id="demo")
    state.working_memory = {
        "nested": {
            "unsafe": UnsafeValue(),
            "list": [UnsafeValue(), "ok"],
        }
    }

    store.save(state)
    reloaded = yaml.safe_load(store.path.read_text(encoding="utf-8"))

    assert reloaded["working_memory"]["nested"]["unsafe"].startswith("<")
    assert reloaded["working_memory"]["nested"]["list"][0].startswith("<")


def test_save_nested_working_memory_lists_keep_newest_entries(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo")
    state = DanteSessionState(session_id="demo")
    state.working_memory = {
        "notes": [f"item-{index}-" + ("x" * MAX_SESSION_BYTES) for index in range(10)]
    }

    store.save(state)
    reloaded = yaml.safe_load(store.path.read_text(encoding="utf-8"))

    assert [item.split("-", 2)[1] for item in reloaded["working_memory"]["notes"]] == [
        "2",
        "3",
        "4",
        "5",
        "6",
        "7",
        "8",
        "9",
    ]


def test_save_stringifies_non_string_lists_and_scalars(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo")
    state = DanteSessionState(session_id="demo")
    state.open_questions = [1, Path("question.md"), {"prompt": "q"}]
    state.recent_files = [Path("file.md"), 2, {"path": "docs.md"}]
    state.last_action = 12345

    store.save(state)
    reloaded = yaml.safe_load(store.path.read_text(encoding="utf-8"))

    assert reloaded["open_questions"] == ["1", "question.md", "{'prompt': 'q'}"]
    assert reloaded["recent_files"] == ["file.md", "2", "{'path': 'docs.md'}"]
    assert reloaded["last_action"] == "12345"


def test_save_compresses_wide_working_memory(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo")
    state = DanteSessionState(session_id="demo")
    state.working_memory = {f"k{index:03d}": "v" for index in range(2000)}

    store.save(state)

    persisted_size = len(store.path.read_text(encoding="utf-8").encode("utf-8"))
    reloaded = store.load_or_create()

    assert persisted_size <= MAX_SESSION_BYTES
    assert len(reloaded.working_memory) <= len(state.working_memory)


def test_save_compresses_wide_working_memory_with_many_small_keys(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo")
    state = DanteSessionState(session_id="demo")
    state.working_memory = {f"key_{index:04d}": index for index in range(2000)}

    store.save(state)

    persisted_size = len(store.path.read_text(encoding="utf-8").encode("utf-8"))
    reloaded = store.load_or_create()

    assert persisted_size <= MAX_SESSION_BYTES
    assert len(reloaded.working_memory) <= MAX_WORKING_MEMORY_KEYS


def test_save_compresses_oversized_working_memory_key_name(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo")
    state = DanteSessionState(session_id="demo")
    state.working_memory = {"k" * (MAX_SESSION_BYTES * 2): "value"}

    store.save(state)

    persisted_size = len(store.path.read_text(encoding="utf-8").encode("utf-8"))

    assert persisted_size <= MAX_SESSION_BYTES


def test_save_compresses_oversized_turn_role(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo")
    state = DanteSessionState(session_id="demo")
    state.recent_turns = [
        SessionTurn(role="r" * (MAX_SESSION_BYTES * 2), content="hello")
    ]

    store.save(state)

    persisted_size = len(store.path.read_text(encoding="utf-8").encode("utf-8"))

    assert persisted_size <= MAX_SESSION_BYTES


def test_save_repairs_oversized_identity_scalars(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo")
    huge_text = "s" * (MAX_SESSION_BYTES * 2)
    state = DanteSessionState(session_id=huge_text)
    state.active_agent = "a" * (MAX_SESSION_BYTES * 2)

    store.save(state)

    persisted_size = len(store.path.read_text(encoding="utf-8").encode("utf-8"))
    reloaded = store.load_or_create()

    assert persisted_size <= MAX_SESSION_BYTES
    assert len(reloaded.session_id.encode("utf-8")) <= 64
    assert len(reloaded.active_agent.encode("utf-8")) <= 64


def test_save_preserves_distinct_long_session_ids(tmp_path: Path):
    prefix = "shared-session-prefix-" + ("s" * 120)
    first_store = SessionStateStore(tmp_path / "one", "demo")
    second_store = SessionStateStore(tmp_path / "two", "demo")

    first_state = DanteSessionState(session_id=f"{prefix}-one")
    second_state = DanteSessionState(session_id=f"{prefix}-two")

    first_store.save(first_state)
    second_store.save(second_state)

    first_loaded = first_store.load_or_create()
    second_loaded = second_store.load_or_create()

    assert len(first_loaded.session_id.encode("utf-8")) <= 64
    assert len(second_loaded.session_id.encode("utf-8")) <= 64
    assert first_loaded.session_id != second_loaded.session_id


def test_save_compresses_oversized_nested_working_memory_key_name(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo")
    state = DanteSessionState(session_id="demo")
    state.working_memory = {
        "outer": {"k" * (MAX_SESSION_BYTES * 2): "value"}
    }

    store.save(state)

    persisted_size = len(store.path.read_text(encoding="utf-8").encode("utf-8"))

    assert persisted_size <= MAX_SESSION_BYTES


def test_save_preserves_distinct_long_working_memory_keys(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo")
    state = DanteSessionState(session_id="demo")
    prefix = "shared-prefix-" + ("k" * 80)
    state.working_memory = {
        f"{prefix}-one": "alpha",
        f"{prefix}-two": "beta",
    }

    store.save(state)
    reloaded = store.load_or_create()

    assert len(reloaded.working_memory) == 2
    assert set(reloaded.working_memory.values()) == {"alpha", "beta"}


def test_save_preserves_distinct_long_keys_near_marker_boundary(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo")
    state = DanteSessionState(session_id="demo")
    prefix = "shared-prefix-" + ("k" * 80)
    state.conversation_summary = "x" * (MAX_SESSION_BYTES // 2)
    state.recent_turns = [SessionTurn(role="user", content="tail")]
    state.working_memory = {
        f"{prefix}-one": "alpha",
        f"{prefix}-two": "beta",
    }
    state.compression_markers = [
        CompressionMarker(
            compressed_at="2026-03-30T10:00:00",
            dropped_turns=1,
            kept_turns=1,
            reason="count",
        )
    ]

    store.save(state)
    persisted_size = len(store.path.read_text(encoding="utf-8").encode("utf-8"))
    reloaded = store.load_or_create()

    assert persisted_size <= MAX_SESSION_BYTES
    assert len(reloaded.working_memory) == 2
    assert set(reloaded.working_memory.values()) == {"alpha", "beta"}


def test_save_normalizes_non_dict_working_memory(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo")
    state = DanteSessionState(session_id="demo")
    state.working_memory = ["not", "a", "dict"]

    store.save(state)
    reloaded = yaml.safe_load(store.path.read_text(encoding="utf-8"))

    assert isinstance(reloaded["working_memory"], dict)
    assert reloaded["working_memory"]


def test_load_or_create_refreshes_compression_timestamp_on_load(tmp_path: Path, monkeypatch):
    store = SessionStateStore(tmp_path, "demo")
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        yaml.safe_dump(
            {
                "session_id": "demo",
                "active_agent": "dante",
                "conversation_summary": "",
                "recent_turns": [
                    {"role": "user", "content": "x" * (MAX_SESSION_BYTES)},
                    {"role": "assistant", "content": "tail"},
                ],
                "working_memory": {},
                "open_questions": [],
                "recent_files": [],
                "last_action": "",
                "compression_markers": [],
                "updated_at": "2026-03-29T09:00:00",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    class FixedDatetime:
        @staticmethod
        def now():
            class FixedNow:
                def isoformat(self):
                    return "2026-03-30T12:34:56"

            return FixedNow()

    monkeypatch.setattr("tools.agent.session_state.datetime", FixedDatetime)

    state = store.load_or_create()
    reloaded = yaml.safe_load(store.path.read_text(encoding="utf-8"))

    assert state.compression_markers[-1].compressed_at == "2026-03-30T12:34:56"
    assert reloaded["compression_markers"][-1]["compressed_at"] == "2026-03-30T12:34:56"


def test_load_or_create_repairs_non_utf8_corrupt_bytes(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo")
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_bytes(b"\xff\xfe\x00\x00not-yaml")

    state = store.load_or_create()
    reloaded = yaml.safe_load(store.path.read_text(encoding="utf-8"))

    assert state.session_id == "demo"
    assert reloaded["session_id"] == "demo"


def test_load_or_create_repairs_null_scalars_without_string_none(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo")
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        yaml.safe_dump(
            {
                "session_id": "demo",
                "active_agent": None,
                "conversation_summary": None,
                "recent_turns": [{"role": "user", "content": "hello"}],
                "working_memory": {},
                "open_questions": None,
                "recent_files": None,
                "last_action": None,
                "compression_markers": None,
                "updated_at": None,
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    state = store.load_or_create()
    reloaded = yaml.safe_load(store.path.read_text(encoding="utf-8"))

    assert state.active_agent == "dante"
    assert state.conversation_summary == ""
    assert state.last_action == ""
    assert state.open_questions == []
    assert state.recent_files == []
    assert reloaded["active_agent"] == "dante"
    assert reloaded["conversation_summary"] == ""


def test_load_or_create_repairs_empty_required_scalars(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo")
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        yaml.safe_dump(
            {
                "session_id": "",
                "active_agent": "",
                "conversation_summary": "",
                "recent_turns": [],
                "working_memory": {},
                "open_questions": [],
                "recent_files": [],
                "last_action": "",
                "compression_markers": [],
                "updated_at": "",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    state = store.load_or_create()
    reloaded = yaml.safe_load(store.path.read_text(encoding="utf-8"))

    assert state.session_id == "demo"
    assert state.active_agent == "dante"
    assert reloaded["session_id"] == "demo"
    assert reloaded["active_agent"] == "dante"


def test_load_or_create_normalizes_null_compression_marker_timestamp(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo")
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        yaml.safe_dump(
            {
                "session_id": "demo",
                "active_agent": "dante",
                "conversation_summary": "",
                "recent_turns": [],
                "working_memory": {},
                "open_questions": [],
                "recent_files": [],
                "last_action": "",
                "compression_markers": [
                    {
                        "compressed_at": None,
                        "dropped_turns": 1,
                        "kept_turns": 0,
                        "reason": None,
                    }
                ],
                "updated_at": "",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    state = store.load_or_create()

    assert state.compression_markers[0].compressed_at == ""
    assert state.compression_markers[0].reason == "count"


def test_size_marker_near_limit_boundary_stays_within_cap(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo")
    state = DanteSessionState(session_id="demo")

    low = 0
    high = MAX_SESSION_BYTES
    best = 0
    while low <= high:
        mid = (low + high) // 2
        state.conversation_summary = "x" * mid
        if store._estimate_size(state) < MAX_SESSION_BYTES:
            best = mid
            low = mid + 1
        else:
            high = mid - 1

    state.conversation_summary = "x" * best
    assert store._estimate_size(state) < MAX_SESSION_BYTES
    state.compression_markers.append(
        CompressionMarker(
            compressed_at="2026-03-30T10:00:00",
            dropped_turns=0,
            kept_turns=0,
            reason="size",
        )
    )

    store._enforce_size_after_marker(state)

    assert store._estimate_size(state) <= MAX_SESSION_BYTES


def test_load_or_create_coerces_scalar_listish_fields(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo")
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        yaml.safe_dump(
            {
                "session_id": "demo",
                "active_agent": "dante",
                "conversation_summary": "",
                "recent_turns": {"role": "user", "content": "hello"},
                "working_memory": {},
                "open_questions": {"prompt": "ask"},
                "recent_files": {"path": "chapter.md"},
                "last_action": "summarize",
                "compression_markers": {"compressed_at": "2026-03-30T10:00:00"},
                "updated_at": "",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    state = store.load_or_create()

    assert [turn.content for turn in state.recent_turns] == ["hello"]
    assert state.open_questions == ["{'prompt': 'ask'}"]
    assert state.recent_files == ["{'path': 'chapter.md'}"]
    assert len(state.compression_markers) == 1


def test_save_keeps_newest_items_when_compacting_lists(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo")
    state = DanteSessionState(session_id="demo")
    state.open_questions = [f"question-{index}" for index in range(20)]
    state.recent_files = [f"file-{index}" for index in range(20)]
    state.working_memory = {"notes": "x" * (MAX_SESSION_BYTES * 2)}

    store.save(state)
    reloaded = store.load_or_create()

    assert reloaded.open_questions[-1] == "question-19"
    assert reloaded.recent_files[-1] == "file-19"


def test_load_or_create_normalizes_malformed_compression_markers(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo")
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        yaml.safe_dump(
            {
                "session_id": "demo",
                "active_agent": "dante",
                "conversation_summary": "",
                "recent_turns": [],
                "working_memory": {},
                "open_questions": [],
                "recent_files": [],
                "last_action": "",
                "compression_markers": [
                    {
                        "compressed_at": "2026-03-30T10:00:00",
                        "dropped_turns": "not-an-int",
                        "kept_turns": 2,
                        "reason": "bogus",
                    },
                    "skip-me",
                ],
                "updated_at": "",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    state = store.load_or_create()

    assert len(state.compression_markers) == 1
    assert state.compression_markers[0].dropped_turns == 0
    assert state.compression_markers[0].kept_turns == 2
    assert state.compression_markers[0].reason == "count"


def test_load_or_create_repairs_oversized_compression_marker_payload(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo")
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        yaml.safe_dump(
            {
                "session_id": "demo",
                "active_agent": "dante",
                "conversation_summary": "",
                "recent_turns": [],
                "working_memory": {},
                "open_questions": [],
                "recent_files": [],
                "last_action": "",
                "compression_markers": [
                    {
                        "compressed_at": "m" * (MAX_SESSION_BYTES * 2),
                        "dropped_turns": 1,
                        "kept_turns": 0,
                        "reason": "size",
                    }
                ],
                "updated_at": "",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    state = store.load_or_create()
    reloaded = yaml.safe_load(store.path.read_text(encoding="utf-8"))
    persisted_size = len(store.path.read_text(encoding="utf-8").encode("utf-8"))

    assert persisted_size <= MAX_SESSION_BYTES
    assert len(state.compression_markers) == 1
    assert len(state.compression_markers[0].compressed_at.encode("utf-8")) < MAX_SESSION_BYTES
    assert (
        len(reloaded["compression_markers"][0]["compressed_at"].encode("utf-8"))
        < MAX_SESSION_BYTES
    )


def test_load_or_create_repairs_oversized_top_level_scalars(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo")
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        yaml.safe_dump(
            {
                "session_id": "s" * (MAX_SESSION_BYTES * 2),
                "active_agent": "a" * (MAX_SESSION_BYTES * 2),
                "conversation_summary": "",
                "recent_turns": [],
                "working_memory": {},
                "open_questions": [],
                "recent_files": [],
                "last_action": "",
                "compression_markers": [],
                "updated_at": "u" * (MAX_SESSION_BYTES * 2),
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    state = store.load_or_create()
    reloaded = yaml.safe_load(store.path.read_text(encoding="utf-8"))
    persisted_size = len(store.path.read_text(encoding="utf-8").encode("utf-8"))

    assert persisted_size <= MAX_SESSION_BYTES
    assert len(state.session_id.encode("utf-8")) <= 64
    assert len(state.active_agent.encode("utf-8")) <= 64
    assert len(state.updated_at.encode("utf-8")) <= 64
    assert len(reloaded["session_id"].encode("utf-8")) <= 64
    assert len(reloaded["active_agent"].encode("utf-8")) <= 64
    assert len(reloaded["updated_at"].encode("utf-8")) <= 64


def test_load_or_create_repairs_corrupt_session_file(tmp_path: Path):
    store = SessionStateStore(tmp_path, "demo")
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("session_id: demo\nrecent_turns: [", encoding="utf-8")

    state = store.load_or_create()

    assert state.session_id == "demo"
    assert state.active_agent == "dante"
    assert state.recent_turns == []
    assert yaml.safe_load(store.path.read_text(encoding="utf-8"))["session_id"] == "demo"


def test_transcript_rotates_once_it_exceeds_the_byte_budget(tmp_path: Path):
    """The JSONL transcript must not grow without bound.

    The rolling YAML is carefully bounded (`_compress_for_size`,
    `_hard_truncate_state`), but the append-only transcript had no cap at all:
    500 turns of 4 KB each produced an 18 KB YAML beside a 2 MB JSONL.
    """
    store = SessionStateStore(tmp_path, "demo")

    # Stay under the budget first: nothing should rotate.
    for _ in range(50):
        store.append_turn("user", "x" * 100)
    assert not store.transcript_path.with_name(store.transcript_path.name + ".1").exists()

    # Push past the 8 MiB budget. Each turn is ~4 KB, so 2200 of them is ~9 MB.
    for _ in range(2200):
        store.append_turn("user", "y" * 4000)

    rotated = store.transcript_path.with_name(store.transcript_path.name + ".1")
    assert rotated.is_file(), "the oversized transcript must have rotated"
    assert store.transcript_path.stat().st_size < rotated.stat().st_size
    # A marker records the rotation so a reader can tell the live file starts fresh.
    lines = store.transcript_path.read_text(encoding="utf-8").splitlines()
    assert lines, "the live transcript must not be empty after rotation"
    marker = yaml.safe_load(lines[0])
    assert marker.get("rotation") is True
