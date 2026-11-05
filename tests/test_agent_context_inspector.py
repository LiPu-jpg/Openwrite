from pathlib import Path
from types import SimpleNamespace

from tools.agent.session_state import DanteSessionState, SessionStateStore, SessionTurn
from tools.agent_context_inspector import AgentContextInspector
from tools.chapter_pipeline import save_chapter
from tools.chapter_run_store import ChapterRunStore
from tools.cli import _cmd_context
from tools.init_project import init_project
from tools.truth_manager import TruthFiles, TruthFilesManager


def _project(tmp_path: Path) -> Path:
    init_project(tmp_path, "demo", "上下文检查", template="demo_short")
    TruthFilesManager(tmp_path, "demo").save_truth_files(
        TruthFiles(
            current_state="主角位于旧钟楼。",
            ledger="旧钥匙仍在主角手中。",
            relationships="主角信任守钟人。",
        )
    )
    return tmp_path


def test_writer_inspection_contains_exact_messages_manifest_and_checks(
    tmp_path: Path, monkeypatch
):
    root = _project(tmp_path)
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("LLM_MODEL", "deepseek-v4-flash")
    inspector = AgentContextInspector(root)

    result = inspector.inspect(
        "ch_001",
        agent="writer",
        guidance="从钟声开始",
        target_words=800,
    )

    assert [message["role"] for message in result["messages"]] == ["system", "user"]
    assert "从钟声开始" in result["messages"][1]["content"]
    assert "主角位于旧钟楼" in result["messages"][1]["content"]
    assert result["context_manifest"]["revision"]
    assert result["inspection_revision"].startswith("sha256:")
    assert result["request_config"]["thinking"] == "disabled"
    required = [item for item in result["checks"] if item["importance"] == "required"]
    assert required and all(item["status"] == "included" for item in required)


def test_canonical_inspection_checks_creator_facing_context_groups(tmp_path: Path):
    result = AgentContextInspector(_project(tmp_path)).inspect(
        "ch_001",
        agent="canonical",
    )

    check_names = {item["field"] for item in result["checks"]}
    assert {"core_documents", "setting_documents", "continuity_documents"} <= check_names
    assert "concept_documents" not in check_names


def test_reviewer_inspection_uses_canonical_state_and_written_run_target(tmp_path: Path):
    root = _project(tmp_path)
    save_chapter(root, "demo", "ch_001", "钟差", "雨落在钟楼上。")
    run_store = ChapterRunStore(root, "demo")
    run = run_store.create(
        "ch_001",
        requested_target_words=800,
        outline_target_words=3200,
        effective_target_words=800,
        provider="custom",
        model="flash",
        context_payload={},
        baseline_state_revision=0,
    )
    run_store.complete_write(run, draft_content="雨落在钟楼上。", usage={})

    result = AgentContextInspector(root).inspect("ch_001", agent="reviewer")

    user_message = result["messages"][1]["content"]
    assert "主角位于旧钟楼" in user_message
    assert "目标字数：\n800" in user_message
    assert result["agent_payload"]["target_words"] == 800
    required = [item for item in result["checks"] if item["importance"] == "required"]
    assert all(item["status"] == "included" for item in required)


def test_react_agent_inspection_is_read_only_and_exposes_tools(tmp_path: Path):
    root = _project(tmp_path)
    workflow_root = root / "data" / "novels" / "demo" / "data" / "workflows"
    dante_session = workflow_root / "agent_session.yaml"
    goethe_session = workflow_root / "goethe_session.yaml"
    inspector = AgentContextInspector(root)

    dante = inspector.inspect(
        "ch_001", agent="dante", instruction="检查第一章是否可以开始写"
    )
    goethe = inspector.inspect(
        "ch_001", agent="goethe", instruction="检查当前规划缺口"
    )

    assert not dante_session.exists()
    assert not goethe_session.exists()
    assert any(tool["name"] == "get_context" for tool in dante["tools"])
    assert dante["messages"][-1]["content"] == "检查第一章是否可以开始写"
    assert goethe["messages"][-1]["content"] == "检查当前规划缺口"
    assert any("不会自动接收" in warning for warning in dante["warnings"])


def test_live_turn_inspection_does_not_duplicate_latest_user_turn(tmp_path: Path):
    root = _project(tmp_path)
    store = SessionStateStore(root, "demo")
    store.save(
        DanteSessionState(
            session_id=store.session_id,
            recent_turns=[
                SessionTurn(role="assistant", content="上一轮答复"),
                SessionTurn(role="user", content="检查第一章"),
            ],
        )
    )

    result = AgentContextInspector(root).inspect(
        "ch_001",
        agent="dante",
        instruction="检查第一章",
        exclude_latest_session_turn=True,
    )

    rendered = "\n".join(message["content"] for message in result["messages"])
    assert rendered.count("检查第一章") == 1
    assert "上一轮答复" in rendered


def test_context_cli_prints_agent_level_json(
    tmp_path: Path, monkeypatch, capsys
):
    root = _project(tmp_path)
    monkeypatch.chdir(root)

    result = _cmd_context(
        SimpleNamespace(
            chapter="ch_001",
            show=True,
            agent="writer",
            instruction="",
            guidance="保留钟声",
            target_words=800,
            format="json",
            output="",
        )
    )

    output = capsys.readouterr().out
    assert result == 0
    assert '"agent": "writer"' in output
    assert '"messages"' in output
    assert "保留钟声" in output


def test_inspection_restores_derived_caches_instead_of_leaving_them_behind(tmp_path: Path):
    """An inspection must not leave derived caches that mask real staleness.

    The module advertises itself as read-only, but assembling a packet runs the
    auto-sync chain and refreshes the character-state index. Leaving those behind
    makes source_sync's freshness check believe the caches are current, so a
    later writer sees stale content as fresh.
    """
    root = _project(tmp_path)
    novel_root = root / "data" / "novels" / "demo"
    cards = novel_root / "data" / "characters" / "cards"
    index = novel_root / ".openwrite" / "character-state-index.json"

    # Capture the pre-inspection bytes of everything the sync chain owns.
    watched: dict[Path, bytes] = {}
    for path in list(cards.glob("*.yaml")) + [index]:
        if path.is_file():
            watched[path] = path.read_bytes()

    inspector = AgentContextInspector(root)
    inspector.inspect(agent="dante")

    for path, content in watched.items():
        assert path.is_file(), f"{path.name} disappeared during inspection"
        assert path.read_bytes() == content, f"{path.name} was rewritten by a read-only inspection"

    # A card that did not exist before must not appear because of the inspection.
    for path in cards.glob("*.yaml"):
        assert path in watched, f"inspection created a derived card {path.name}"
