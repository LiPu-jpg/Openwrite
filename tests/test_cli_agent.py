import sys
import builtins
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import tools.cli as cli_module
import tools.agent as agent_module
import tools.context_builder as context_builder_module
import tools.llm as llm_module
import tools.chapter_assembler as chapter_assembler_module
import tools.chapter_pipeline as chapter_pipeline_module
from tools.agent.book_state import BookStage, BookStateStore
import tools.agent.orchestrator as orchestrator_module
import tools.agent.tool_runtime as tool_runtime_module
from tools.frontmatter import parse_toml_front_matter
from tools.review_store import ReviewStore
from tools.story_planning import StoryPlanningStore
from tools.truth_manager import TruthFiles, TruthFilesManager
from tools.workflow_scheduler import WorkflowScheduler


def _fake_args(instruction: str = "查看项目状态", max_turns: int = 20, quiet: bool = False):
    return SimpleNamespace(instruction=instruction, max_turns=max_turns, quiet=quiet)


def test_cmd_init_uses_default_initializer_and_returns_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(cli_module, "Path", SimpleNamespace(cwd=lambda: tmp_path))

    args = SimpleNamespace(novel_id="demo", template="legacy")

    result = cli_module._cmd_init(args)

    assert result == 0
    assert (tmp_path / "novel_config.yaml").exists()
    assert (tmp_path / "data" / "novels" / "demo" / "src" / "outline.md").exists()


def test_cmd_goethe_routes_to_goethe_runner(monkeypatch: pytest.MonkeyPatch):
    import tools.goethe as goethe_module

    calls = {"count": 0}

    monkeypatch.setattr(goethe_module, "run_goethe", lambda: calls.__setitem__("count", calls["count"] + 1) or 0)

    assert cli_module._cmd_goethe(SimpleNamespace()) == 0
    assert calls["count"] == 1


def test_build_prompt_session_falls_back_without_prompt_toolkit(
    monkeypatch: pytest.MonkeyPatch,
):
    import tools.goethe as goethe_module

    real_import = builtins.__import__
    prompts: list[str] = []

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.startswith("prompt_toolkit"):
            raise ImportError("prompt_toolkit missing")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.setattr(
        builtins,
        "input",
        lambda prompt="": prompts.append(prompt) or "exit",
    )

    session = goethe_module.build_prompt_session()

    assert session.prompt("🕯️ Dante> ") == "exit"
    assert prompts == ["🕯️ Dante> "]


def test_main_rejects_legacy_wizard_command(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sys, "argv", ["openwrite", "wizard"])

    with pytest.raises(SystemExit) as exc:
        cli_module.main()

    assert exc.value.code == 2


def test_cmd_dante_routes_to_dante_runner(monkeypatch: pytest.MonkeyPatch):
    import tools.agent.dante as dante_module

    calls = {"count": 0}

    monkeypatch.setattr(
        dante_module,
        "run_dante",
        lambda: calls.__setitem__("count", calls["count"] + 1) or 17,
    )

    result = cli_module._cmd_dante(_fake_args("查看项目状态", max_turns=7, quiet=True))

    assert result == 17
    assert calls["count"] == 1


def test_cmd_dante_no_longer_uses_orchestrator_bridge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(cli_module, "Path", SimpleNamespace(cwd=lambda: tmp_path))
    import tools.agent.dante as dante_module

    orchestrator_called = {"value": False}
    tool_runtime_called = {"value": False}

    def forbidden(*args, **kwargs):
        orchestrator_called["value"] = True
        raise AssertionError("orchestrator bridge should not be used")

    def forbidden_tool_runtime(*args, **kwargs):
        tool_runtime_called["value"] = True
        raise AssertionError("tool runtime bridge should not be used")

    monkeypatch.setattr(orchestrator_module, "OpenWriteOrchestrator", forbidden)
    monkeypatch.setattr(
        tool_runtime_module,
        "build_tool_executors",
        forbidden_tool_runtime,
    )
    monkeypatch.setattr(dante_module, "run_dante", lambda: 0)

    assert cli_module._cmd_dante(_fake_args("基础设定准备好了")) == 0
    assert orchestrator_called["value"] is False
    assert tool_runtime_called["value"] is False


def test_dante_help_no_longer_mentions_placeholder(monkeypatch: pytest.MonkeyPatch, capsys):
    monkeypatch.setattr(sys, "argv", ["openwrite", "dante", "--help"])

    with pytest.raises(SystemExit) as exc:
        cli_module.main()

    captured = capsys.readouterr()

    assert exc.value.code == 0
    assert "占位" not in captured.out
    assert "待实现" not in captured.out
    assert "过渡性主入口" not in captured.out
    assert "复用现有确定性编排器" not in captured.out
    assert "长期会话主入口" in captured.out


def test_cmd_dante_reports_dante_named_import_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    monkeypatch.setattr(cli_module, "Path", SimpleNamespace(cwd=lambda: tmp_path))
    real_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "tools.agent.dante":
            raise ImportError("missing runtime")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with caplog.at_level("ERROR"):
        result = cli_module._cmd_dante(_fake_args("查看项目状态"))

    assert result == 1
    assert "Dante 模块未安装" in caplog.text


def test_cmd_agent_is_retired_and_tells_users_to_use_dante(
    caplog: pytest.LogCaptureFixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(cli_module, "Path", SimpleNamespace(cwd=lambda: tmp_path))

    called = {"value": False}

    def forbidden(*args, **kwargs):
        called["value"] = True
        return SimpleNamespace(run_cli=lambda **_: 0)

    monkeypatch.setattr(orchestrator_module, "OpenWriteOrchestrator", forbidden)

    with caplog.at_level("ERROR"):
        result = cli_module._cmd_agent(_fake_args("查看项目状态"))

    assert result == 1
    assert called["value"] is False
    assert "openwrite agent 已退役" in caplog.text
    assert "openwrite dante" in caplog.text


def test_agent_help_only_reports_retired_status(monkeypatch: pytest.MonkeyPatch, capsys):
    monkeypatch.setattr(sys, "argv", ["openwrite", "agent", "--help"])

    with pytest.raises(SystemExit) as exc:
        cli_module.main()

    captured = capsys.readouterr()

    assert exc.value.code == 0
    assert "已退役" in captured.out
    assert "instruction" not in captured.out
    assert "--max-turns" not in captured.out
    assert "--quiet" not in captured.out


def test_run_cli_status_instruction_is_read_only(tmp_path: Path):
    state_store = BookStateStore(tmp_path, "demo")
    assert state_store.path.exists() is False

    orchestrator = orchestrator_module.OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=StoryPlanningStore(tmp_path, "demo"),
        tool_executors={},
    )

    assert state_store.path.exists() is False
    result = orchestrator.run_cli("查看项目状态", quiet=True)

    assert result == 0
    assert state_store.path.exists() is False


def test_run_cli_reuses_a_single_preflight_for_chapter_delegation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    state_store = BookStateStore(tmp_path, "demo")
    state = state_store.load_or_create()
    state.stage = BookStage.CHAPTER_PREFLIGHT
    state_store.save(state)

    orchestrator = orchestrator_module.OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=StoryPlanningStore(tmp_path, "demo"),
        tool_executors={
            "write_chapter": lambda args: {"ok": True, "draft_path": "drafts/ch_001.md"}
        },
    )

    preflight_calls = {"count": 0}

    def fake_run_preflight(chapter_id: str):
        preflight_calls["count"] += 1
        return {
            "ok": True,
            "chapter_id": chapter_id,
            "reason": "",
            "missing_items": [],
            "packet": {
                "chapter_id": chapter_id,
                "prompt_sections": {},
                "story_background": "",
                "foundation": "",
                "previous_chapter_content": "",
                "style_documents": {},
                "character_documents": [],
                "concept_documents": {},
            },
        }

    monkeypatch.setattr(orchestrator, "run_preflight", fake_run_preflight)

    delegate_calls = {}
    real_delegate = orchestrator.delegate_writing

    def spying_delegate(chapter_id: str, preflight_result=None, guidance: str = "", target_words: int = 0):
        delegate_calls["preflight_result"] = preflight_result
        delegate_calls["guidance"] = guidance
        delegate_calls["target_words"] = target_words
        return real_delegate(
            chapter_id,
            preflight_result=preflight_result,
            guidance=guidance,
            target_words=target_words,
        )

    monkeypatch.setattr(orchestrator, "delegate_writing", spying_delegate)

    result = orchestrator.run_cli("写 ch_001", quiet=True)

    assert result == 0
    assert preflight_calls["count"] == 1
    assert delegate_calls["preflight_result"]["chapter_id"] == "ch_001"
    assert delegate_calls["guidance"] == ""
    assert delegate_calls["target_words"] == 0


def test_exec_write_chapter_uses_asyncio_run_without_missing_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    (tmp_path / "novel_config.yaml").write_text("novel_id: demo\n", encoding="utf-8")
    expected_draft_path = (
        tmp_path / "data" / "novels" / "demo" / "data" / "manuscript" / "arc_001" / "ch_001.md"
    )
    captured = {}

    class FakeContext:
        target_words = 1200
        chapter_goals = ["推进剧情"]
        current_state = "现状"
        pending_hooks = "伏笔"

    class FakeBuilder:
        def __init__(self, project_root: Path, novel_id: str, reference_style: str | None = None):
            self.project_root = project_root
            self.novel_id = novel_id

        def build_generation_context(self, chapter_id: str):
            return FakeContext()

    class FakeWriter:
        def __init__(self, agent_ctx):
            self.agent_ctx = agent_ctx

        async def write_chapter(
            self,
            context,
            chapter_number: int,
            temperature: float = 0.7,
            target_words: int | None = None,
        ):
            captured["context"] = context
            captured["target_words"] = target_words
            return SimpleNamespace(title="测试标题", content="测试内容", word_count=321)

    monkeypatch.setattr(context_builder_module, "ContextBuilder", FakeBuilder)
    monkeypatch.setattr(agent_module, "WriterAgent", FakeWriter)
    monkeypatch.setattr(
        agent_module,
        "AgentContext",
        lambda client, model, project_root: SimpleNamespace(
            client=client, model=model, project_root=project_root
        ),
    )
    monkeypatch.setattr(llm_module.LLMConfig, "from_env", classmethod(lambda cls: SimpleNamespace(model="fake-model")))
    monkeypatch.setattr(llm_module, "LLMClient", lambda config: object())
    monkeypatch.setattr(
        cli_module,
        "_save_chapter",
        lambda *args, **kwargs: expected_draft_path,
    )

    result = cli_module._exec_write_chapter(
        tmp_path,
        {
            "chapter_id": "ch_001",
            "guidance": "偏冷峻，冲突更直接",
            "target_words": 3500,
            "context_packet": {
                "story_background": "背景设定",
                "foundation": "基础设定",
                "previous_chapter_content": "上一章正文",
                "style_documents": {
                    "summary": "冷峻节奏",
                    "prompt_section": "短句推进",
                    "work.composed": "# 合成风格\n\n克制冷硬，避免解释性总结。",
                    "craft.dialogue_craft": "# 对话技法\n\n对话短促，避免解释性台词。",
                },
                "character_documents": ["# 主角档案\n\n冷静谨慎。"],
                "concept_documents": {
                    "world_rules": "规则A",
                    "current_state": "运行态现状",
                    "pending_hooks": "伏笔A",
                },
                "prompt_sections": {
                    "大纲窗口": "- 第一章: 开篇",
                    "当前章节": "第一章\n开篇",
                    "戏剧位置": "▶ 本章位于: 起",
                    "本章目标": "- 推进剧情",
                    "上文": "上文内容",
                },
            },
        },
    )

    assert result == {
        "ok": True,
        "chapter_id": "ch_001",
        "title": "测试标题",
        "word_count": 321,
        "draft_path": str(expected_draft_path),
        "truth_updates": {},
    }
    assert captured["target_words"] == 3500
    assert captured["context"]["target_words"] == 3500
    assert "背景设定" in captured["context"]["external_context"]
    assert "基础设定" in captured["context"]["external_context"]
    assert "偏冷峻" in captured["context"]["external_context"]
    assert "克制冷硬" in captured["context"]["style_profile"]
    assert "对话短促" in captured["context"]["style_profile"]
    assert captured["context"]["current_state"] == "运行态现状"
    assert captured["context"]["foreshadowing_summary"] == "伏笔A"
    assert captured["context"]["recent_chapters"] == "上一章正文"
    assert captured["context"]["active_characters"][0]["name"] == "主角档案"
    assert "第一章" in captured["context"]["outline"]
    assert "particle_ledger" not in captured["context"]
    assert "character_matrix" not in captured["context"]
    assert "pending_hooks" not in captured["context"]
    state = BookStateStore(tmp_path, "demo").load_or_create()
    workflow = WorkflowScheduler(tmp_path, "demo").load_workflow("ch_001")
    assert state.current_chapter == "ch_001"
    assert state.stage == BookStage.REVIEW_AND_REVISE
    assert workflow is not None
    assert workflow.current_stage == "review"


def test_exec_create_character_normalizes_shared_source_document(tmp_path: Path):
    (tmp_path / "novel_config.yaml").write_text("novel_id: demo\n", encoding="utf-8")

    result = cli_module._exec_create_character(
        tmp_path,
        {
            "name": "林月",
            "description": "高冷强势的技术组长。",
        },
    )

    assert result["ok"] is True
    target = tmp_path / "data" / "novels" / "demo" / "src" / "characters" / "林月.md"
    meta, body = parse_toml_front_matter(target.read_text(encoding="utf-8"))
    assert meta["id"] == "林月"
    assert meta["name"] == "林月"
    assert meta["tier"] == "普通配角"
    assert meta["summary"] == "高冷强势的技术组长。"
    assert meta["detail_refs"] == ["基本信息", "背景", "外貌", "性格", "关系"]
    assert body.lstrip().startswith("# 林月")
    assert "## 背景" in body


def test_cmd_write_routes_through_canonical_packet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    (tmp_path / "novel_config.yaml").write_text(
        "novel_id: demo\nstyle_id: demo\ncurrent_arc: arc_001\ncurrent_chapter: ch_001\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli_module, "Path", SimpleNamespace(cwd=lambda: tmp_path))

    packet_dict = {
        "story_background": "背景设定",
        "foundation": "基础设定",
        "previous_chapter_content": "上一章正文",
        "style_documents": {"summary": "冷峻节奏"},
        "character_documents": ["# 陈明\n\n冷静谨慎。"],
        "concept_documents": {"current_state": "运行态现状"},
        "prompt_sections": {"当前章节": "第一章"},
    }

    class FakePacket:
        def to_markdown(self):
            return "# packet"

    for key, value in packet_dict.items():
        setattr(FakePacket, key, value)

    class FakeAssembler:
        def __init__(self, project_root: Path, novel_id: str, style_id: str = ""):
            self.project_root = project_root
            self.novel_id = novel_id
            self.style_id = style_id

        def assemble(self, chapter_id: str):
            return FakePacket()

    exec_calls: list[dict] = []

    def fake_exec_write_chapter(project_root: Path, args: dict) -> dict:
        exec_calls.append(args)
        draft_path = (
            project_root
            / "data"
            / "novels"
            / "demo"
            / "data"
            / "manuscript"
            / "arc_001"
            / "ch_001.md"
        )
        draft_path.parent.mkdir(parents=True, exist_ok=True)
        draft_path.write_text("# 第一章\n\n正文", encoding="utf-8")
        return {
            "ok": True,
            "chapter_id": "ch_001",
            "title": "第一章",
            "word_count": 1234,
            "draft_path": str(draft_path),
        }

    class FakeContext:
        target_words = 4000
        chapter_goals = ["推进剧情"]
        current_state = "现状"
        foreshadowing_summary = "伏笔"
        ledger = "账本"
        relationships = "关系"
        chapter_summaries = "摘要"

    class FakeBuilder:
        def __init__(self, project_root: Path, novel_id: str, reference_style: str | None = None):
            self.project_root = project_root
            self.novel_id = novel_id

        def build_generation_context(self, chapter_id: str, window_size: int = 5):
            return FakeContext()

    class FakeWriter:
        def __init__(self, agent_ctx):
            self.agent_ctx = agent_ctx

        async def write_chapter(self, context, chapter_number: int, temperature: float = 0.7):
            return SimpleNamespace(
                title="第一章",
                content="正文",
                word_count=1234,
                state_updates={},
            )

    monkeypatch.setattr(chapter_assembler_module, "ChapterAssemblerV2", FakeAssembler)
    monkeypatch.setattr(
        chapter_pipeline_module,
        "execute_write_chapter",
        fake_exec_write_chapter,
    )
    monkeypatch.setattr(context_builder_module, "ContextBuilder", FakeBuilder)
    monkeypatch.setattr(agent_module, "WriterAgent", FakeWriter)
    monkeypatch.setattr(
        agent_module,
        "AgentContext",
        lambda client, model, project_root: SimpleNamespace(
            client=client, model=model, project_root=project_root
        ),
    )
    monkeypatch.setattr(
        llm_module.LLMConfig,
        "from_env",
        classmethod(lambda cls: SimpleNamespace(model="fake-model")),
    )
    monkeypatch.setattr(llm_module, "LLMClient", lambda config: object())

    result = cli_module._cmd_write(SimpleNamespace(chapter="ch_001", temperature=0.6, show=False))

    assert result == 0
    assert exec_calls and exec_calls[0]["context_packet"]["story_background"] == "背景设定"


def test_cmd_multi_write_updates_runtime_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    (tmp_path / "novel_config.yaml").write_text(
        "novel_id: demo\nstyle_id: demo\ncurrent_arc: arc_001\ncurrent_chapter: ch_001\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli_module, "Path", SimpleNamespace(cwd=lambda: tmp_path))
    monkeypatch.setattr(
        llm_module.LLMConfig,
        "from_env",
        classmethod(lambda cls: SimpleNamespace(model="fake-model")),
    )
    monkeypatch.setattr(llm_module, "LLMClient", lambda config: object())
    monkeypatch.setattr(
        agent_module,
        "AgentContext",
        lambda client, model, project_root: SimpleNamespace(
            client=client, model=model, project_root=project_root
        ),
    )

    class FakeDirector:
        def __init__(self, agent_ctx, novel_id: str, style_id: str = ""):
            self.agent_ctx = agent_ctx
            self.novel_id = novel_id
            self.style_id = style_id

        async def run(self, chapter_id: str, temperature: float = 0.7, run_review: bool = True):
            return SimpleNamespace(
                draft=SimpleNamespace(title="第二章", content="正文"),
                review=SimpleNamespace(passed=True, score=93, issues=[]),
                applied_state_updates={"current_state": "已更新"},
                new_concepts=[],
            )

    monkeypatch.setattr(agent_module, "MultiAgentDirector", FakeDirector)

    result = cli_module._cmd_multi_write(
        SimpleNamespace(
            chapter="ch_002",
            temperature=0.7,
            no_review=False,
            show_packet=False,
            packet_output_dir=None,
        )
    )

    assert result == 0
    state = BookStateStore(tmp_path, "demo").load_or_create()
    workflow = WorkflowScheduler(tmp_path, "demo").load_workflow("ch_002")
    assert state.current_chapter == "ch_002"
    assert state.stage == BookStage.CHAPTER_PREFLIGHT
    assert workflow is not None
    assert workflow.current_stage == "user_confirm"
    review = ReviewStore(tmp_path, "demo").load("ch_002")
    assert review is not None and review["score"] == 93
    assert not (
        tmp_path
        / "data"
        / "novels"
        / "demo"
        / "data"
        / "workflows"
        / "project.lock"
    ).exists()


def test_exec_review_chapter_uses_packet_based_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    (tmp_path / "novel_config.yaml").write_text(
        "novel_id: demo\nstyle_id: demo\ncurrent_arc: arc_001\ncurrent_chapter: ch_001\n",
        encoding="utf-8",
    )
    draft_path = (
        tmp_path / "data" / "novels" / "demo" / "data" / "manuscript" / "arc_001" / "ch_001.md"
    )
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    draft_path.write_text("# 第一章\n\n正文", encoding="utf-8")
    truth_manager = TruthFilesManager(tmp_path, "demo")
    truth_manager.save_truth_files(
        TruthFiles(current_state="写前状态", relationships="写前关系")
    )
    truth_manager.create_snapshot(0)
    truth_manager.save_truth_files(
        TruthFiles(current_state="本章结算后状态", relationships="本章结算后关系")
    )

    class FakePacket:
        character_documents = {"陈明": "# 陈明\n\n角色档案"}
        current_state = "运行态"
        relationships = "关系矩阵"
        story_background = "故事背景"
        style_documents = {"summary": "冷峻"}
        concept_documents = {"world_rules": "规则A"}
        previous_chapter_content = "上一章"
        prompt_sections = {"当前章节": "第一章"}

        def to_markdown(self):
            return "# packet"

    class FakeAssembler:
        def __init__(self, project_root: Path, novel_id: str, style_id: str = ""):
            self.project_root = project_root
            self.novel_id = novel_id
            self.style_id = style_id

        def assemble(self, chapter_id: str):
            return FakePacket()

    captured: dict[str, object] = {}

    class FakeReviewer:
        def __init__(self, agent_ctx):
            self.agent_ctx = agent_ctx

        async def review(self, content: str, context: dict):
            captured["content"] = content
            captured["context"] = context
            return SimpleNamespace(passed=True, score=96, issues=[])

    def forbidden_builder(*args, **kwargs):
        raise AssertionError("review should use canonical packet, not ContextBuilder fallback")

    monkeypatch.setattr(chapter_assembler_module, "ChapterAssemblerV2", FakeAssembler)
    monkeypatch.setattr(context_builder_module, "ContextBuilder", forbidden_builder)
    monkeypatch.setattr(agent_module, "ReviewerAgent", FakeReviewer)
    monkeypatch.setattr(
        agent_module,
        "AgentContext",
        lambda client, model, project_root: SimpleNamespace(
            client=client, model=model, project_root=project_root
        ),
    )
    monkeypatch.setattr(
        llm_module.LLMConfig,
        "from_env",
        classmethod(lambda cls: SimpleNamespace(model="fake-model")),
    )
    monkeypatch.setattr(llm_module, "LLMClient", lambda config: object())

    result = cli_module._exec_review_chapter(tmp_path, {"chapter_id": "ch_001"})

    assert result["ok"] is True
    assert captured["content"] == "# 第一章\n\n正文"
    assert "角色档案" in captured["context"]["character_profiles"]
    assert captured["context"]["current_state"] == "写前状态"
    assert captured["context"]["relationships"] == "写前关系"


def test_cmd_style_synthesize_writes_composed_style_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    (tmp_path / "novel_config.yaml").write_text(
        "novel_id: demo\nstyle_id: 术师手册\ncurrent_arc: arc_001\ncurrent_chapter: ch_001\n",
        encoding="utf-8",
    )
    style_dir = tmp_path / "data" / "novels" / "demo" / "data" / "style"
    style_dir.mkdir(parents=True, exist_ok=True)
    (style_dir / "fingerprint.yaml").write_text(
        "voice: 冷静\nlanguage_style: 口语化\nrhythm: 张弛有度\n",
        encoding="utf-8",
    )
    craft_dir = tmp_path / "craft"
    craft_dir.mkdir(parents=True, exist_ok=True)
    (craft_dir / "humanization.yaml").write_text(
        "banned_phrases:\n  - phrase: 然而\n  - phrase: 不禁\n",
        encoding="utf-8",
    )
    ref_dir = tmp_path / "data" / "reference_styles" / "术师手册"
    ref_dir.mkdir(parents=True, exist_ok=True)
    (ref_dir / "summary.md").write_text("# 摘要\n\n参考风格摘要", encoding="utf-8")

    monkeypatch.setattr(cli_module, "Path", SimpleNamespace(cwd=lambda: tmp_path))

    result = cli_module._cmd_style(SimpleNamespace(style_action="synthesize", novel_id="current"))

    composed_path = style_dir / "composed.md"
    assert result == 0
    assert composed_path.exists()
    text = composed_path.read_text(encoding="utf-8")
    assert "冷静" in text
    assert "口语化" in text
    assert "然而" in text


def test_cmd_review_does_not_rewind_book_state_for_older_chapter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    (tmp_path / "novel_config.yaml").write_text(
        "novel_id: demo\nstyle_id: demo\ncurrent_arc: arc_001\ncurrent_chapter: ch_008\n",
        encoding="utf-8",
    )
    manuscript = (
        tmp_path / "data" / "novels" / "demo" / "data" / "manuscript" / "arc_001" / "ch_006.md"
    )
    manuscript.parent.mkdir(parents=True, exist_ok=True)
    manuscript.write_text("# 第六章\n\n正文", encoding="utf-8")

    state_store = BookStateStore(tmp_path, "demo")
    state = state_store.load_or_create()
    state.current_chapter = "ch_008"
    state.stage = BookStage.REVIEW_AND_REVISE
    state_store.save(state)

    monkeypatch.setattr(cli_module, "Path", SimpleNamespace(cwd=lambda: tmp_path))
    monkeypatch.setattr(
        chapter_pipeline_module,
        "execute_review_chapter",
        lambda project_root, args: {
            "ok": True,
            "chapter_id": "ch_006",
            "passed": True,
            "score": 98,
            "issues": 0,
        },
    )

    assert cli_module._cmd_review(SimpleNamespace(chapter="ch_006", strict=False)) == 0
    reloaded = state_store.load_or_create()
    assert reloaded.current_chapter == "ch_008"
