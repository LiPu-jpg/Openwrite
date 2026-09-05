import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.agent.book_state import BookStage, BookStateStore
from tools.agent.dante_actions import DanteActionAdapter
from tools.agent.goethe_actions import GoethePlanningRuntime
from tools.agent.orchestrator import OpenWriteOrchestrator
from tools.agent.toolkits import WRITING_TOOLKIT
from tools.chapter_pipeline import build_writer_payload
from tools.context_builder import ContextBuilder
from tools.frontmatter import parse_toml_front_matter
from tools.init_project import init_project
from tools.story_planning import StoryPlanningStore
from tools.truth_manager import TruthFilesManager
from tools.workflow_scheduler import WorkflowScheduler


def _bootstrap_novel(tmp_path: Path, novel_id: str = "demo") -> tuple[Path, Path]:
    init_project(tmp_path, novel_id)
    novel_root = tmp_path / "data" / "novels" / novel_id
    hierarchy_path = novel_root / "data" / "hierarchy.yaml"
    hierarchy = {
        "story_info": {"title": "测试小说", "theme": "测试主题"},
        "arcs": [
            {
                "id": "arc_001",
                "title": "第一篇",
                "description": "开篇",
                "chapters": ["ch_001", "ch_002"],
            }
        ],
        "sections": [
            {
                "id": "sec_001",
                "title": "第一节",
                "arc_id": "arc_001",
                "chapters": ["ch_001", "ch_002"],
            }
        ],
        "chapters": [
            {
                "id": "ch_001",
                "title": "第一章",
                "summary": "开篇",
                "goals": ["建立主角"],
                "involved_characters": ["char_001"],
                "involved_settings": ["测试场景"],
            },
            {
                "id": "ch_002",
                "title": "第二章",
                "summary": "承接",
                "goals": ["推进剧情"],
                "involved_characters": ["char_001"],
                "involved_settings": ["测试场景"],
            },
        ],
    }
    hierarchy_path.write_text(
        yaml.safe_dump(hierarchy, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    outline_path = novel_root / "src" / "outline.md"
    outline_path.write_text(
        "# 测试小说\n\n"
        "## 第一篇\n\n"
        "主角发现异常并决定追查。\n\n"
        "### 第一节\n\n"
        "主角发现异常并开始追查。\n\n"
        "#### 第一章\n\n"
        "> 内容焦点: 开篇\n"
        "> 出场角色: char_001\n"
        "> 涉及设定: 测试场景\n\n"
        "#### 第二章\n\n"
        "> 内容焦点: 承接\n"
        "> 出场角色: char_001\n"
        "> 涉及设定: 测试场景\n",
        encoding="utf-8",
    )

    story_dir = novel_root / "src" / "story"
    story_dir.mkdir(parents=True, exist_ok=True)
    (story_dir / "background.md").write_text("# 背景\n\n测试背景。", encoding="utf-8")
    (story_dir / "foundation.md").write_text("# 设定\n\n测试设定。", encoding="utf-8")

    (novel_root / "src" / "characters" / "char_001.md").write_text(
        "# 角色一\n\n## 背景\n\n角色背景。\n\n## 外貌\n\n普通。\n\n## 性格\n\n- 冷静\n- 直接\n",
        encoding="utf-8",
    )
    (novel_root / "src" / "world" / "rules.md").write_text(
        "# 世界规则\n\n## 力量体系\n- 测试规则\n",
        encoding="utf-8",
    )
    (novel_root / "src" / "world" / "terminology.md").write_text(
        "# 术语表\n\n"
        "| 术语 | 定义 | 分类 |\n"
        "|------|------|------|\n"
        "| 测试术语 | 定义 | concept |\n",
        encoding="utf-8",
    )
    (novel_root / "src" / "world" / "entities").mkdir(parents=True, exist_ok=True)
    (novel_root / "data" / "style").mkdir(parents=True, exist_ok=True)
    (novel_root / "data" / "style" / "fingerprint.yaml").write_text(
        "voice: 测试语气\nlanguage_style: 测试句式\nrhythm: 测试节奏\n",
        encoding="utf-8",
    )
    return tmp_path, novel_root


def test_outline_agent_prompt_uses_project_writing_targets(tmp_path: Path):
    root, _ = _bootstrap_novel(tmp_path)
    config_path = root / "novel_config.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["writing_targets"] = {
        "book_words": 360000,
        "chapter_words": 4200,
        "outline_volume_words": 1100,
        "outline_act_words": 700,
        "outline_section_words": 420,
        "outline_chapter_words": 260,
    }
    config_path.write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    orchestrator = OpenWriteOrchestrator.for_testing(root, "demo")
    captured: dict[str, str] = {}

    def fake_chat(system: str, user: str, **_kwargs) -> str:
        captured["system"] = system
        captured["user"] = user
        return "# 第一卷"

    orchestrator._chat_text = fake_chat  # type: ignore[method-assign]

    assert orchestrator._generate_outline_draft("生成详细大纲") == "# 第一卷"
    assert "每章正文默认目标 4200 字" in captured["system"]
    assert "每幕节点说明约 700 字" in captured["system"]
    assert "每个章纲说明约 260 字" in captured["system"]


def test_discovery_appends_ideation_and_stays_in_discovery(tmp_path: Path):
    state_store = BookStateStore(tmp_path, "demo")
    planning_store = StoryPlanningStore(tmp_path, "demo")
    orchestrator = OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
    )

    result = orchestrator.handle_user_message("主角是普通上班族")

    state = state_store.load_or_create()
    assert state.stage == BookStage.DISCOVERY
    assert result.stage == BookStage.DISCOVERY
    assert result.blocked is False
    assert result.next_action == "request_more_background"
    assert "主角是普通上班族" in planning_store.ideation_path.read_text(encoding="utf-8")
    assert "背景" in result.message


def test_discovery_summary_request_generates_summary_and_waits_for_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    state_store = BookStateStore(tmp_path, "demo")
    planning_store = StoryPlanningStore(tmp_path, "demo")
    planning_store.append_ideation("主角是普通上班族")
    planning_store.append_ideation("公司地下埋着异常节点")
    orchestrator = OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
    )
    monkeypatch.setattr(
        orchestrator,
        "_chat_text",
        lambda system_prompt, user_prompt, **kwargs: (
            "# 当前想法汇总\n\n## 核心方向\n\n- 都市职场异能"
        ),
    )

    result = orchestrator.handle_user_message("先帮我汇总一下当前想法")

    state = state_store.load_or_create()
    assert result.blocked is False
    assert result.next_action == "confirm_ideation_summary"
    assert state.pending_confirmation == "ideation_summary"
    assert state.last_agent_action == "generated_ideation_summary"
    assert planning_store.ideation_summary_path.exists()
    assert "都市职场异能" in planning_store.ideation_summary_path.read_text(encoding="utf-8")


def test_summary_request_infers_ideation_from_confirmed_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    init_project(tmp_path, "demo", "雨巷回声")
    state_store = BookStateStore(tmp_path, "demo")
    planning_store = StoryPlanningStore(tmp_path, "demo")
    planning_store.save_foundation_draft(
        background="镜雨区常年落雨，钟楼会在 23:17 停摆。",
        foundation="雨声会影响记忆，第十三枚齿轮是找回真相的关键。",
    )
    planning_store.outline_src_path.write_text(
        "# 大纲\n\n## 第一篇\n\n### 开头\n\n#### 第一章：雨巷开钟\n\n梁知遥发现停摆怀表。\n",
        encoding="utf-8",
    )
    character_dir = planning_store.novel_root / "src" / "characters"
    character_dir.mkdir(parents=True, exist_ok=True)
    (character_dir / "梁知遥.md").write_text("# 梁知遥\n\n寻找第十三枚齿轮。\n", encoding="utf-8")
    orchestrator = OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
    )

    def fake_chat(system_prompt: str, user_prompt: str, **kwargs) -> str:
        assert "从已确认资产反推的灵感记录" in user_prompt
        return "# 当前想法汇总\n\n## 核心方向\n\n- 镜雨区雨声记忆悬疑"

    monkeypatch.setattr(orchestrator, "_chat_text", fake_chat)

    result = orchestrator.summarize_ideation()

    assert result.next_action == "confirm_ideation_summary"
    assert state_store.load_or_create().pending_confirmation == "ideation_summary"
    assert "从已确认资产反推" in planning_store.ideation_path.read_text(encoding="utf-8")
    assert "镜雨区雨声记忆悬疑" in planning_store.ideation_summary_path.read_text(encoding="utf-8")


def test_dante_actions_require_summary_confirmation_before_outline_generation(
    tmp_path: Path,
):
    state_store = BookStateStore(tmp_path, "demo")
    planning_store = StoryPlanningStore(tmp_path, "demo")
    planning_store.append_ideation("主角是普通上班族")
    planning_store.save_ideation_summary("# 当前想法汇总\n\n- 都市职场异能")
    orchestrator = OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
    )
    adapter = DanteActionAdapter(orchestrator)

    payload = adapter.generate_outline_draft("帮我生成一份四级大纲")

    state = state_store.load_or_create()
    assert payload["blocked"] is True
    assert payload["next_action"] == "confirm_ideation_summary"
    assert payload["stage"] == BookStage.DISCOVERY.value
    assert state.stage == BookStage.DISCOVERY
    assert state.pending_confirmation == "ideation_summary"


def test_dante_actions_confirm_summary_only_when_gate_is_pending(
    tmp_path: Path,
):
    state_store = BookStateStore(tmp_path, "demo")
    planning_store = StoryPlanningStore(tmp_path, "demo")
    planning_store.append_ideation("主角是普通上班族")
    orchestrator = OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
    )
    adapter = DanteActionAdapter(orchestrator)

    payload = adapter.confirm_ideation_summary("这个汇总可以")

    state = state_store.load_or_create()
    assert payload["blocked"] is True
    assert payload["next_action"] == "ignore"
    assert payload["stage"] == BookStage.DISCOVERY.value
    assert state.stage == BookStage.DISCOVERY
    assert state.pending_confirmation == ""


def test_dante_actions_confirm_summary_advances_discovery_to_foundation(
    tmp_path: Path,
):
    state_store = BookStateStore(tmp_path, "demo")
    planning_store = StoryPlanningStore(tmp_path, "demo")
    planning_store.append_ideation("主角是普通上班族")
    planning_store.save_ideation_summary("# 当前想法汇总\n\n- 都市职场异能")
    state = state_store.load_or_create()
    state.stage = BookStage.DISCOVERY
    state.pending_confirmation = "ideation_summary"
    state.last_agent_action = "generated_ideation_summary"
    state_store.save(state)
    orchestrator = OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
    )
    adapter = DanteActionAdapter(orchestrator)

    payload = adapter.confirm_ideation_summary("这个汇总可以")

    state = state_store.load_or_create()
    assert payload["blocked"] is False
    assert payload["next_action"] == "ready_for_outline_generation"
    assert payload["stage"] == BookStage.FOUNDATION.value
    assert state.stage == BookStage.FOUNDATION
    assert state.pending_confirmation == ""
    assert state.last_agent_action == "confirmed_ideation_summary"


def test_confirm_summary_does_not_generate_outline_when_request_is_negated(
    tmp_path: Path,
):
    state_store = BookStateStore(tmp_path, "demo")
    planning_store = StoryPlanningStore(tmp_path, "demo")
    planning_store.append_ideation("主角要追查失踪案")
    planning_store.save_ideation_summary("# 当前想法汇总\n\n- 追查失踪案")
    planning_store.outline_src_path.parent.mkdir(parents=True, exist_ok=True)
    planning_store.outline_src_path.write_text(
        "# 已确认大纲\n\n## 第一篇\n",
        encoding="utf-8",
    )
    state = state_store.load_or_create()
    state.stage = BookStage.CHAPTER_PREFLIGHT
    state.pending_confirmation = "ideation_summary"
    state_store.save(state)
    orchestrator = OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
    )
    adapter = DanteActionAdapter(orchestrator)

    payload = adapter.confirm_ideation_summary("确认这版想法汇总，但不要生成大纲。")

    persisted = state_store.load_or_create()
    assert payload["blocked"] is False
    assert payload["next_action"] == "ready_for_outline_generation"
    assert persisted.stage == BookStage.CHAPTER_PREFLIGHT
    assert persisted.pending_confirmation == ""
    assert not planning_store.outline_draft_path.exists()


def test_summary_confirmation_and_outline_request_are_handled_in_one_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    init_project(tmp_path, "demo", "顶流")
    state_store = BookStateStore(tmp_path, "demo")
    planning_store = StoryPlanningStore(tmp_path, "demo")
    planning_store.append_ideation("主角是被雪藏的穿越艺人")
    planning_store.save_ideation_summary("# 当前想法汇总\n\n## 核心方向\n\n- 娱乐圈成长爽文\n")
    state = state_store.load_or_create()
    state.pending_confirmation = "ideation_summary"
    state.last_agent_action = "generated_ideation_summary"
    state_store.save(state)
    orchestrator = OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
    )
    monkeypatch.setattr(
        orchestrator,
        "_generate_outline_draft",
        lambda text: (
            "# 四卷大纲\n\n## 第一卷\n\n主角遭遇雪藏后重新争取舞台并获得复出机会。\n\n"
            "### 第一节\n主角遭遇雪藏危机，并决定重新争取舞台。\n\n"
            "#### 第一章：重新出发\n"
            "> 戏剧位置: 起\n> 内容焦点: 主角决定重新争取舞台。\n"
            "> 本章目标: 建立雪藏危机\n> 预估字数: 3000\n"
            "> 出场角色: 主角\n> 涉及设定: 经纪公司\n"
            "> 情感弧线: 低落 -> 决意\n> 节拍: 收到解约通知, 作出选择\n"
            "> 悬念: 新机会来自谁\n\n主角从雪藏危机重新出发。\n"
        ),
    )

    result = orchestrator.handle_user_message("确认汇总了，生成大纲草案吧")

    state = state_store.load_or_create()
    assert result.blocked is False
    assert result.next_action == "request_outline_confirmation"
    assert state.stage == BookStage.ROLLING_OUTLINE
    assert state.pending_confirmation == "outline_scope"
    assert "第一卷" in planning_store.outline_draft_path.read_text(encoding="utf-8")
    assert "娱乐圈成长爽文" in (planning_store.story_src_dir / "foundation.md").read_text(
        encoding="utf-8"
    )

    monkeypatch.setattr(
        orchestrator,
        "_generate_outline_draft",
        lambda text: pytest.fail("pending outline draft must be reused"),
    )
    repeated = orchestrator.generate_outline_draft("再生成一次大纲")
    assert repeated.blocked is False
    assert repeated.next_action == "request_outline_confirmation"
    assert state_store.load_or_create().pending_confirmation == "outline_scope"


def test_chat_text_retries_reasoning_only_response_with_configured_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    import tools.llm as llm_module

    calls: list[tuple[int, str]] = []
    responses = iter(
        [
            SimpleNamespace(
                content="",
                finish_reason="length",
                reasoning="尚未形成最终答案",
            ),
            SimpleNamespace(
                content="# 完整大纲",
                finish_reason="stop",
                reasoning="",
            ),
        ]
    )

    class FakeConfig:
        provider = "openai"
        base_url = "https://api.deepseek.com"
        model = "deepseek-v4-flash"
        max_tokens = 8192
        extra = {}

        @classmethod
        def from_env(cls):
            return cls()

    class FakeClient:
        def __init__(self, config):
            assert config.max_tokens == 8192
            assert config.extra["extra_body"]["thinking"] == {"type": "disabled"}

        def chat(self, *, messages, temperature, max_tokens):
            calls.append((max_tokens, messages[-1].content))
            return next(responses)

    monkeypatch.setattr(llm_module, "LLMConfig", FakeConfig)
    monkeypatch.setattr(llm_module, "LLMClient", FakeClient)
    orchestrator = OpenWriteOrchestrator.for_testing(tmp_path, "demo")

    content = orchestrator._chat_text(
        "system",
        "生成大纲",
        temperature=0.4,
        max_tokens=6000,
    )

    assert content == "# 完整大纲"
    assert [budget for budget, _ in calls] == [6000, 8192]
    assert "立即从要求的最终内容开始输出" in calls[1][1]


def test_dante_actions_require_outline_scope_confirmation_before_preflight(
    tmp_path: Path,
):
    _, novel_root = _bootstrap_novel(tmp_path)
    state_store = BookStateStore(tmp_path, "demo")
    planning_store = StoryPlanningStore(tmp_path, "demo")
    state = state_store.load_or_create()
    state.stage = BookStage.ROLLING_OUTLINE
    state.pending_confirmation = "outline_scope"
    state_store.save(state)
    orchestrator = OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
    )
    adapter = DanteActionAdapter(orchestrator)

    payload = adapter.run_chapter_preflight("ch_001")

    assert novel_root.exists()
    assert payload["ok"] is False
    assert payload["reason"] == "outline_not_confirmed"
    assert payload["missing_items"] == ["outline_scope"]


def test_dante_preflight_stays_blocked_when_outline_scope_is_pending(
    tmp_path: Path,
):
    _bootstrap_novel(tmp_path)
    state_store = BookStateStore(tmp_path, "demo")
    planning_store = StoryPlanningStore(tmp_path, "demo")
    state = state_store.load_or_create()
    state.stage = BookStage.CHAPTER_PREFLIGHT
    state.pending_confirmation = "outline_scope"
    state.current_chapter = "ch_001"
    state_store.save(state)
    orchestrator = OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
    )
    adapter = DanteActionAdapter(orchestrator)

    payload = adapter.run_chapter_preflight("ch_001")

    assert payload["ok"] is False
    assert payload["reason"] == "outline_not_confirmed"
    assert payload["missing_items"] == ["outline_scope"]


def test_status_request_accepts_current_status_phrase(tmp_path: Path):
    state_store = BookStateStore(tmp_path, "demo")
    state = state_store.load_or_create()
    state.stage = BookStage.CHAPTER_PREFLIGHT
    state.current_chapter = "ch_007"
    state_store.save(state)

    orchestrator = OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=StoryPlanningStore(tmp_path, "demo"),
    )

    result = orchestrator.handle_user_message("查看当前状态")

    assert result.blocked is False
    assert result.next_action == "report_status"
    assert result.stage == BookStage.CHAPTER_PREFLIGHT
    assert "当前章节: ch_007" in result.message


def test_foundation_confirmation_promotes_drafts_and_advances_to_rolling_outline(
    tmp_path: Path,
):
    state_store = BookStateStore(tmp_path, "demo")
    planning_store = StoryPlanningStore(tmp_path, "demo")
    planning_store.save_foundation_draft(background="背景A", foundation="设定B")
    orchestrator = OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
    )

    result = orchestrator.handle_user_message("基础设定准备好了，开始 outline")

    state = state_store.load_or_create()
    assert result.blocked is False
    assert result.stage == BookStage.ROLLING_OUTLINE
    assert result.next_action == "request_outline_confirmation"
    assert state.stage == BookStage.ROLLING_OUTLINE
    assert state.pending_confirmation == "outline_scope"
    assert state.last_agent_action == "requested_outline_confirmation"
    _, background_body = parse_toml_front_matter(
        (planning_store.story_src_dir / "background.md").read_text(encoding="utf-8")
    )
    _, foundation_body = parse_toml_front_matter(
        (planning_store.story_src_dir / "foundation.md").read_text(encoding="utf-8")
    )
    assert background_body.strip() == "背景A"
    assert foundation_body.strip() == "设定B"


def test_missing_outline_blocks_writing_with_request_outline_confirmation(tmp_path: Path):
    state_store = BookStateStore(tmp_path, "demo")
    planning_store = StoryPlanningStore(tmp_path, "demo")
    orchestrator = OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
    )

    result = orchestrator.handle_user_message("写 ch_001")

    state = state_store.load_or_create()
    assert result.blocked is True
    assert result.next_action == "request_outline_confirmation"
    assert result.stage == BookStage.DISCOVERY
    assert state.stage == BookStage.DISCOVERY
    assert state.current_chapter == ""


def test_ambiguous_writing_text_does_not_mutate_current_chapter(tmp_path: Path):
    state_store = BookStateStore(tmp_path, "demo")
    planning_store = StoryPlanningStore(tmp_path, "demo")
    state = state_store.load_or_create()
    state.stage = BookStage.CHAPTER_PREFLIGHT
    state.current_chapter = "ch_003"
    state.last_agent_action = "seed"
    state_store.save(state)
    orchestrator = OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
    )

    result = orchestrator.handle_user_message("写作时要注意 10 个问题")

    state = state_store.load_or_create()
    assert result.next_action == "request_more_background"
    assert result.stage == BookStage.CHAPTER_PREFLIGHT
    assert state.stage == BookStage.CHAPTER_PREFLIGHT
    assert state.current_chapter == "ch_003"


def test_negated_chapter_requests_do_not_enter_chapter_flow(tmp_path: Path):
    state_store = BookStateStore(tmp_path, "demo")
    planning_store = StoryPlanningStore(tmp_path, "demo")
    state = state_store.load_or_create()
    state.stage = BookStage.CHAPTER_PREFLIGHT
    state.current_chapter = "ch_003"
    state_store.save(state)
    orchestrator = OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
    )

    for message in ("不要写第1章", "先别写第1章"):
        result = orchestrator.handle_user_message(message)
        state = state_store.load_or_create()
        assert result.blocked is True
        assert result.stage == BookStage.CHAPTER_PREFLIGHT
        assert result.next_action == "ignore"
        assert state.stage == BookStage.CHAPTER_PREFLIGHT
        assert state.current_chapter == "ch_003"


def test_suffix_negated_chapter_request_does_not_enter_chapter_flow(tmp_path: Path):
    state_store = BookStateStore(tmp_path, "demo")
    planning_store = StoryPlanningStore(tmp_path, "demo")
    state = state_store.load_or_create()
    state.stage = BookStage.CHAPTER_PREFLIGHT
    state.current_chapter = "ch_003"
    state_store.save(state)
    orchestrator = OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
    )

    result = orchestrator.handle_user_message("第1章不要写")

    state = state_store.load_or_create()
    assert result.blocked is True
    assert result.stage == BookStage.CHAPTER_PREFLIGHT
    assert result.next_action == "ignore"
    assert state.stage == BookStage.CHAPTER_PREFLIGHT
    assert state.current_chapter == "ch_003"


def test_postfix_negated_chapter_request_does_not_enter_chapter_flow(tmp_path: Path):
    state_store = BookStateStore(tmp_path, "demo")
    planning_store = StoryPlanningStore(tmp_path, "demo")
    state = state_store.load_or_create()
    state.stage = BookStage.CHAPTER_PREFLIGHT
    state.current_chapter = "ch_003"
    state_store.save(state)
    orchestrator = OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
    )

    result = orchestrator.handle_user_message("写第1章不要")

    state = state_store.load_or_create()
    assert result.blocked is True
    assert result.stage == BookStage.CHAPTER_PREFLIGHT
    assert result.next_action == "ignore"
    assert state.stage == BookStage.CHAPTER_PREFLIGHT
    assert state.current_chapter == "ch_003"


def test_postfix_prefixed_chapter_request_does_not_enter_chapter_flow(tmp_path: Path):
    state_store = BookStateStore(tmp_path, "demo")
    planning_store = StoryPlanningStore(tmp_path, "demo")
    state = state_store.load_or_create()
    state.stage = BookStage.CHAPTER_PREFLIGHT
    state.current_chapter = "ch_003"
    state_store.save(state)
    orchestrator = OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
    )

    result = orchestrator.handle_user_message("帮我写第1章不要")

    state = state_store.load_or_create()
    assert result.blocked is True
    assert result.stage == BookStage.CHAPTER_PREFLIGHT
    assert result.next_action == "ignore"
    assert state.stage == BookStage.CHAPTER_PREFLIGHT
    assert state.current_chapter == "ch_003"


def test_spaced_chapter_request_records_current_chapter(tmp_path: Path):
    state_store = BookStateStore(tmp_path, "demo")
    planning_store = StoryPlanningStore(tmp_path, "demo")
    state = state_store.load_or_create()
    state.stage = BookStage.CHAPTER_PREFLIGHT
    state_store.save(state)
    orchestrator = OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
    )

    result = orchestrator.handle_user_message("帮我写第 1 章")

    state = state_store.load_or_create()
    assert result.blocked is False
    assert result.next_action == "chapter_preflight"
    assert result.stage == BookStage.CHAPTER_PREFLIGHT
    assert state.current_chapter == "ch_001"
    assert state.stage == BookStage.CHAPTER_PREFLIGHT


def test_mixed_foundation_and_outline_prefers_foundation_promotion(tmp_path: Path):
    state_store = BookStateStore(tmp_path, "demo")
    planning_store = StoryPlanningStore(tmp_path, "demo")
    planning_store.save_foundation_draft(background="背景A", foundation="设定B")
    planning_store.save_outline_draft("# 大纲草案")
    orchestrator = OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
    )

    result = orchestrator.handle_user_message("基础设定准备好了，可以确认大纲范围")

    state = state_store.load_or_create()
    assert result.blocked is False
    assert result.next_action == "request_outline_confirmation"
    assert result.stage == BookStage.ROLLING_OUTLINE
    assert state.stage == BookStage.ROLLING_OUTLINE
    assert state.pending_confirmation == "outline_scope"
    _, background_body = parse_toml_front_matter(
        (planning_store.story_src_dir / "background.md").read_text(encoding="utf-8")
    )
    _, foundation_body = parse_toml_front_matter(
        (planning_store.story_src_dir / "foundation.md").read_text(encoding="utf-8")
    )
    assert background_body.strip() == "背景A"
    assert foundation_body.strip() == "设定B"
    assert planning_store.outline_src_path.exists() is False


def test_outline_confirmation_promotes_outline_and_advances_to_chapter_preflight(
    tmp_path: Path,
):
    state_store = BookStateStore(tmp_path, "demo")
    planning_store = StoryPlanningStore(tmp_path, "demo")
    planning_store.save_outline_draft("# 大纲草案")
    state = state_store.load_or_create()
    state.stage = BookStage.ROLLING_OUTLINE
    state.pending_confirmation = "outline_scope"
    state.last_agent_action = "requested_outline_confirmation"
    state_store.save(state)
    orchestrator = OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
    )

    result = orchestrator.handle_user_message("大纲范围确认，可以直接写")

    state = state_store.load_or_create()
    assert result.blocked is False
    assert result.stage == BookStage.CHAPTER_PREFLIGHT
    assert result.next_action == "chapter_preflight"
    assert state.stage == BookStage.CHAPTER_PREFLIGHT
    assert state.pending_confirmation == ""
    assert state.last_agent_action == "promoted_outline"
    assert planning_store.outline_src_path.read_text(encoding="utf-8") == "# 大纲草案"


def test_outline_confirmation_explains_that_edit_batches_are_incomplete(tmp_path: Path):
    state_store = BookStateStore(tmp_path, "demo")
    planning_store = StoryPlanningStore(tmp_path, "demo")
    planning_store.outline_src_path.parent.mkdir(parents=True)
    original = "# 原大纲\n\n第一幕\n\n第二幕\n"
    planning_store.outline_src_path.write_text(original, encoding="utf-8")
    staged = planning_store.stage_outline_edits(
        base_revision=planning_store.outline_source_revision(),
        edits=[{"old_text": "第一幕", "new_text": "第一幕已改"}],
        batch_label="第一幕",
        final_batch=False,
    )
    assert staged["ok"] is True
    state = state_store.load_or_create()
    state.stage = BookStage.ROLLING_OUTLINE
    state.pending_confirmation = "outline_scope"
    state_store.save(state)
    orchestrator = OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
    )

    result = orchestrator.confirm_outline_draft()

    state = state_store.load_or_create()
    assert result.blocked is True
    assert result.next_action == "continue_outline_edit_batches"
    assert "final_batch=true" in result.message
    assert state.blocking_reason == "incomplete_outline_edit_batches"
    assert planning_store.outline_src_path.read_text(encoding="utf-8") == original
    assert planning_store.outline_edit_state_path.exists() is True


def test_outline_confirmation_requires_outline_stage(tmp_path: Path):
    state_store = BookStateStore(tmp_path, "demo")
    planning_store = StoryPlanningStore(tmp_path, "demo")
    planning_store.save_outline_draft("# 大纲草案")
    state = state_store.load_or_create()
    state.stage = BookStage.REVIEW_AND_REVISE
    state.current_chapter = "ch_001"
    state_store.save(state)
    orchestrator = OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
    )

    result = orchestrator.handle_user_message("大纲确认好了，可以直接写")

    state = state_store.load_or_create()
    assert result.blocked is True
    assert result.next_action == "ignore"
    assert result.stage == BookStage.REVIEW_AND_REVISE
    assert state.stage == BookStage.REVIEW_AND_REVISE
    assert planning_store.outline_src_path.exists() is False


def test_ambiguous_outline_question_does_not_promote_outline(tmp_path: Path):
    state_store = BookStateStore(tmp_path, "demo")
    planning_store = StoryPlanningStore(tmp_path, "demo")
    planning_store.save_outline_draft("# 大纲草案")
    state = state_store.load_or_create()
    state.stage = BookStage.ROLLING_OUTLINE
    state.pending_confirmation = "outline_scope"
    state.last_agent_action = "requested_outline_confirmation"
    state_store.save(state)
    orchestrator = OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
    )

    result = orchestrator.handle_user_message("可以先确认一下范围吗？")

    state = state_store.load_or_create()
    assert result.stage == BookStage.ROLLING_OUTLINE
    assert state.stage == BookStage.ROLLING_OUTLINE
    assert state.pending_confirmation == "outline_scope"
    assert planning_store.outline_src_path.exists() is False


def test_negated_outline_confirmation_does_not_promote_outline(tmp_path: Path):
    state_store = BookStateStore(tmp_path, "demo")
    planning_store = StoryPlanningStore(tmp_path, "demo")
    planning_store.save_outline_draft("# 大纲草案")
    state = state_store.load_or_create()
    state.stage = BookStage.ROLLING_OUTLINE
    state.pending_confirmation = "outline_scope"
    state_store.save(state)
    orchestrator = OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
    )

    result = orchestrator.handle_user_message("先不确认大纲范围")

    state = state_store.load_or_create()
    assert result.blocked is True
    assert result.stage == BookStage.ROLLING_OUTLINE
    assert result.next_action == "ignore"
    assert state.stage == BookStage.ROLLING_OUTLINE
    assert state.pending_confirmation == "outline_scope"
    assert planning_store.outline_src_path.exists() is False


def test_suffix_negated_outline_confirmation_does_not_promote_outline(tmp_path: Path):
    state_store = BookStateStore(tmp_path, "demo")
    planning_store = StoryPlanningStore(tmp_path, "demo")
    planning_store.save_outline_draft("# 大纲草案")
    state = state_store.load_or_create()
    state.stage = BookStage.ROLLING_OUTLINE
    state.pending_confirmation = "outline_scope"
    state_store.save(state)
    orchestrator = OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
    )

    result = orchestrator.handle_user_message("大纲范围不确认")

    state = state_store.load_or_create()
    assert result.blocked is True
    assert result.stage == BookStage.ROLLING_OUTLINE
    assert result.next_action == "ignore"
    assert state.stage == BookStage.ROLLING_OUTLINE
    assert state.pending_confirmation == "outline_scope"
    assert planning_store.outline_src_path.exists() is False


def test_plain_negated_outline_confirmation_does_not_promote_outline(tmp_path: Path):
    state_store = BookStateStore(tmp_path, "demo")
    planning_store = StoryPlanningStore(tmp_path, "demo")
    planning_store.save_outline_draft("# 大纲草案")
    state = state_store.load_or_create()
    state.stage = BookStage.ROLLING_OUTLINE
    state.pending_confirmation = "outline_scope"
    state_store.save(state)
    orchestrator = OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
    )

    result = orchestrator.handle_user_message("不确认大纲范围")

    state = state_store.load_or_create()
    assert result.blocked is True
    assert result.stage == BookStage.ROLLING_OUTLINE
    assert result.next_action == "ignore"
    assert state.stage == BookStage.ROLLING_OUTLINE
    assert state.pending_confirmation == "outline_scope"
    assert planning_store.outline_src_path.exists() is False


def test_negative_agreement_outline_confirmation_does_not_promote_outline(tmp_path: Path):
    state_store = BookStateStore(tmp_path, "demo")
    planning_store = StoryPlanningStore(tmp_path, "demo")
    planning_store.save_outline_draft("# 大纲草案")
    state = state_store.load_or_create()
    state.stage = BookStage.ROLLING_OUTLINE
    state.pending_confirmation = "outline_scope"
    state_store.save(state)
    orchestrator = OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
    )

    result = orchestrator.handle_user_message("我不同意大纲范围")

    state = state_store.load_or_create()
    assert result.blocked is True
    assert result.stage == BookStage.ROLLING_OUTLINE
    assert result.next_action == "ignore"
    assert state.stage == BookStage.ROLLING_OUTLINE
    assert state.pending_confirmation == "outline_scope"
    assert planning_store.outline_src_path.exists() is False


def test_natural_outline_approval_promotes_outline(tmp_path: Path):
    state_store = BookStateStore(tmp_path, "demo")
    planning_store = StoryPlanningStore(tmp_path, "demo")
    planning_store.save_outline_draft("# 大纲草案")
    state = state_store.load_or_create()
    state.stage = BookStage.ROLLING_OUTLINE
    state.pending_confirmation = "outline_scope"
    state.last_agent_action = "requested_outline_confirmation"
    state_store.save(state)
    orchestrator = OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
    )

    result = orchestrator.handle_user_message("我同意大纲范围")

    state = state_store.load_or_create()
    assert result.blocked is False
    assert result.next_action == "chapter_preflight"
    assert result.stage == BookStage.CHAPTER_PREFLIGHT
    assert state.stage == BookStage.CHAPTER_PREFLIGHT
    assert state.pending_confirmation == ""
    assert planning_store.outline_src_path.read_text(encoding="utf-8") == "# 大纲草案"


def test_dante_can_confirm_current_outline_scope_before_preflight(tmp_path: Path):
    _bootstrap_novel(tmp_path)
    state_store = BookStateStore(tmp_path, "demo")
    planning_store = StoryPlanningStore(tmp_path, "demo")
    state = state_store.load_or_create()
    state.stage = BookStage.ROLLING_OUTLINE
    state.pending_confirmation = ""
    state.current_chapter = "ch_001"
    state_store.save(state)
    orchestrator = OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
    )
    adapter = DanteActionAdapter(orchestrator)

    confirmed = adapter.confirm_outline_scope()

    state = state_store.load_or_create()
    assert confirmed["ok"] is True
    assert confirmed["action"] == "confirm_outline_scope"
    assert confirmed["next_action"] == "chapter_preflight"
    assert state.stage == BookStage.CHAPTER_PREFLIGHT
    assert state.pending_confirmation == ""

    preflight = adapter.run_chapter_preflight("ch_001")
    assert preflight["ok"] is True
    assert preflight["chapter_id"] == "ch_001"
    assert preflight["reason"] == ""


def test_dante_can_confirm_canonical_outline_from_review_stage_without_pending_draft(
    tmp_path: Path,
):
    _bootstrap_novel(tmp_path)
    state_store = BookStateStore(tmp_path, "demo")
    planning_store = StoryPlanningStore(tmp_path, "demo")
    planning_store.outline_edit_state_path.unlink(missing_ok=True)
    planning_store.outline_draft_path.unlink(missing_ok=True)
    state = state_store.load_or_create()
    state.stage = BookStage.REVIEW_AND_REVISE
    state.pending_confirmation = "outline_scope"
    state.blocking_reason = "outline_not_confirmed"
    state_store.save(state)
    orchestrator = OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
    )

    result = orchestrator.confirm_outline_scope()

    persisted = state_store.load_or_create()
    assert result.blocked is False
    assert result.next_action == "chapter_preflight"
    assert persisted.stage == BookStage.CHAPTER_PREFLIGHT
    assert persisted.pending_confirmation == ""
    assert persisted.blocking_reason == ""
    assert persisted.last_agent_action == "confirmed_existing_outline_scope"


def test_goethe_handoff_accepts_legacy_canonical_assets_after_writing_started(
    tmp_path: Path,
):
    _, novel_root = _bootstrap_novel(tmp_path)
    planning_store = StoryPlanningStore(tmp_path, "demo")
    planning_store.append_ideation("已有正文项目继续维护")
    planning_store.save_ideation_summary("# 当前想法汇总\n\n- 沿用现有正典资产")
    manuscript = novel_root / "data" / "manuscript" / "arc_001" / "ch_001.md"
    manuscript.parent.mkdir(parents=True, exist_ok=True)
    manuscript.write_text("# 第一章\n\n已有正文。\n", encoding="utf-8")

    result = GoethePlanningRuntime(tmp_path, "demo").prepare_dante_handoff()

    assert result["ok"] is True
    assert result["missing_items"] == []
    assert result["next_action"] == "chapter_preflight"
    assert len(result["compatibility_warnings"]) == 2
    assert Path(result["handoff_markdown_path"]).is_file()
    assert Path(result["handoff_yaml_path"]).is_file()


def test_outline_generation_request_writes_draft_and_requests_confirmation(
    tmp_path: Path, monkeypatch
):
    state_store = BookStateStore(tmp_path, "demo")
    planning_store = StoryPlanningStore(tmp_path, "demo")
    planning_store.append_ideation("主角是普通上班族")
    planning_store.save_ideation_summary("# 当前想法汇总\n\n- 都市职场异能")
    orchestrator = OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
    )
    state = state_store.load_or_create()
    state.stage = BookStage.FOUNDATION
    state_store.save(state)
    complete_outline = (
        "# 新大纲\n\n## 第一篇\n\n主角接到异常来电并由此卷入新的冲突。\n\n"
        "### 第一节\n主角接到异常来电，由此卷入新的冲突。\n\n"
        "#### 第一章：异常来电\n"
        "> 戏剧位置: 起\n> 内容焦点: 主角收到异常来电。\n"
        "> 本章目标: 建立核心冲突\n> 预估字数: 3000\n"
        "> 出场角色: 主角\n> 涉及设定: 异常节点\n"
        "> 情感弧线: 平静 -> 戒备\n> 节拍: 日常切入, 异常来电\n"
        "> 悬念: 来电者身份\n\n主角首次接触异常。"
    )
    monkeypatch.setattr(orchestrator, "_generate_outline_draft", lambda text: complete_outline)

    result = orchestrator.handle_user_message("帮我生成一份都市异能题材四级大纲")

    state = state_store.load_or_create()
    assert result.blocked is False
    assert result.next_action == "request_outline_confirmation"
    assert result.stage == BookStage.ROLLING_OUTLINE
    assert state.stage == BookStage.ROLLING_OUTLINE
    assert state.pending_confirmation == "outline_scope"
    assert planning_store.outline_draft_path.read_text(encoding="utf-8") == complete_outline
    assert planning_store.outline_src_path.exists() is False


def test_outline_generation_requires_confirmed_ideation_summary_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    state_store = BookStateStore(tmp_path, "demo")
    planning_store = StoryPlanningStore(tmp_path, "demo")
    planning_store.append_ideation("主角是普通上班族")
    planning_store.append_ideation("公司地下埋着异常节点")
    orchestrator = OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
    )

    monkeypatch.setattr(
        orchestrator,
        "_chat_text",
        lambda system_prompt, user_prompt, **kwargs: (
            "# 当前想法汇总\n\n## 核心方向\n\n- 都市职场异能"
        ),
    )
    monkeypatch.setattr(
        orchestrator,
        "_generate_outline_draft",
        lambda text: (_ for _ in ()).throw(
            AssertionError("outline draft should not be generated before summary confirmation")
        ),
    )

    result = orchestrator.handle_user_message("帮我生成一份都市异能题材四级大纲")

    state = state_store.load_or_create()
    assert result.blocked is True
    assert result.next_action == "confirm_ideation_summary"
    assert state.pending_confirmation == "ideation_summary"
    assert planning_store.ideation_summary_path.exists()
    assert planning_store.outline_draft_path.exists() is False


def test_negated_foundation_confirmation_does_not_promote_foundation(tmp_path: Path):
    state_store = BookStateStore(tmp_path, "demo")
    planning_store = StoryPlanningStore(tmp_path, "demo")
    planning_store.save_foundation_draft(background="背景A", foundation="设定B")
    state = state_store.load_or_create()
    state.stage = BookStage.DISCOVERY
    state_store.save(state)
    orchestrator = OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
    )

    result = orchestrator.handle_user_message("先不要开始 outline")

    state = state_store.load_or_create()
    assert result.blocked is True
    assert result.stage == BookStage.DISCOVERY
    assert result.next_action == "ignore"
    assert state.stage == BookStage.DISCOVERY
    assert state.current_chapter == ""
    assert not (planning_store.story_src_dir / "background.md").exists()
    assert not (planning_store.story_src_dir / "foundation.md").exists()


def test_writing_request_after_outline_confirmation_records_current_chapter(
    tmp_path: Path,
):
    state_store = BookStateStore(tmp_path, "demo")
    planning_store = StoryPlanningStore(tmp_path, "demo")
    state = state_store.load_or_create()
    state.stage = BookStage.CHAPTER_PREFLIGHT
    state_store.save(state)
    orchestrator = OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
    )

    result = orchestrator.handle_user_message("写 ch_001")

    state = state_store.load_or_create()
    assert result.blocked is False
    assert result.stage == BookStage.CHAPTER_PREFLIGHT
    assert result.next_action == "chapter_preflight"
    assert state.current_chapter == "ch_001"
    assert state.stage == BookStage.CHAPTER_PREFLIGHT


def test_review_request_routes_to_review_executor_without_touching_ideation(tmp_path: Path):
    state_store = BookStateStore(tmp_path, "demo")
    planning_store = StoryPlanningStore(tmp_path, "demo")
    calls = {}

    def review_chapter(args: dict) -> dict:
        calls["chapter_id"] = args["chapter_id"]
        return {"ok": True, "passed": True, "score": 92}

    orchestrator = OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
        tool_executors={"review_chapter": review_chapter},
    )

    result = orchestrator.handle_user_message("审查第六章并给出可执行修改建议")

    assert result.blocked is False
    assert result.next_action == "review_completed"
    assert calls["chapter_id"] == "ch_006"
    assert planning_store.ideation_path.exists() is False


def test_character_creation_request_routes_to_executor_and_syncs(tmp_path: Path, monkeypatch):
    root, _novel_root = _bootstrap_novel(tmp_path)
    state_store = BookStateStore(root, "demo")
    planning_store = StoryPlanningStore(root, "demo")
    captured = {}

    def create_character(args: dict) -> dict:
        captured["args"] = args
        return {"ok": True, "file": "x"}

    orchestrator = OpenWriteOrchestrator.for_testing(
        root,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
        tool_executors={"create_character": create_character},
    )
    monkeypatch.setattr(
        orchestrator,
        "_generate_character_document",
        lambda text: (
            """+++
name = "苏晚"
+++

# 苏晚

## 背景

旧友反派。
"""
        ),
    )
    sync_calls = []
    monkeypatch.setattr(
        orchestrator,
        "_sync_runtime_caches",
        lambda **kwargs: sync_calls.append(kwargs),
    )

    result = orchestrator.handle_user_message("创建一个反派角色，和主角是旧友")

    assert result.blocked is False
    assert result.next_action == "character_created"
    assert captured["args"]["name"] == "苏晚"
    assert "旧友反派" in captured["args"]["content"]
    assert sync_calls == [{"sync_outline": False, "sync_characters": True}]


def test_run_preflight_reports_missing_previous_chapter_when_scope_exists(
    tmp_path: Path,
):
    root, _novel_root = _bootstrap_novel(tmp_path)
    state_store = BookStateStore(root, "demo")
    planning_store = StoryPlanningStore(root, "demo")
    state = state_store.load_or_create()
    state.stage = BookStage.CHAPTER_PREFLIGHT
    state.current_chapter = "ch_002"
    state_store.save(state)

    orchestrator = OpenWriteOrchestrator.for_testing(
        root,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
    )

    result = orchestrator.run_preflight("ch_002")

    assert result["ok"] is False
    assert result["reason"] == "missing_previous_chapter"
    assert "ch_001" in result["missing_items"]


def test_run_preflight_rejects_missing_chapter_node_even_with_previous_content(
    tmp_path: Path,
):
    root, _novel_root = _bootstrap_novel(tmp_path)
    state_store = BookStateStore(root, "demo")
    planning_store = StoryPlanningStore(root, "demo")
    state = state_store.load_or_create()
    state.stage = BookStage.CHAPTER_PREFLIGHT
    state.current_chapter = "ch_003"
    state_store.save(state)

    manuscript_dir = root / "data" / "novels" / "demo" / "data" / "manuscript" / "arc_001"
    manuscript_dir.mkdir(parents=True, exist_ok=True)
    (manuscript_dir / "ch_002.md").write_text("第二章正文", encoding="utf-8")

    orchestrator = OpenWriteOrchestrator.for_testing(
        root,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
    )

    result = orchestrator.run_preflight("ch_003")

    assert result["ok"] is False
    assert result["reason"] == "missing_chapter_scope"
    assert result["missing_items"] == ["ch_003"]


def test_build_chapter_packet_persists_context_snapshot(tmp_path: Path):
    root, novel_root = _bootstrap_novel(tmp_path)
    state_store = BookStateStore(root, "demo")
    planning_store = StoryPlanningStore(root, "demo")
    planning_store.promote_foundation()
    orchestrator = OpenWriteOrchestrator.for_testing(
        root,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
    )

    packet = orchestrator.build_chapter_packet("ch_001")

    snapshot_dir = novel_root / "data" / "test_outputs" / "context_packets"
    snapshot_path = snapshot_dir / "ch_001.yaml"

    assert packet["story_background"]
    assert packet["core_documents"]
    assert "world_rules" in packet["setting_documents"]
    assert {"current_state", "ledger", "relationships"} <= set(packet["continuity_documents"])
    assert packet["concept_documents"] == {
        **packet["setting_documents"],
        **packet["continuity_documents"],
    }
    assert packet["style_documents"]
    assert isinstance(packet["character_documents"], dict)
    assert "角色1" not in packet["character_documents"]
    assert packet["prompt_sections"]
    assert snapshot_path.exists()
    assert yaml.safe_load(snapshot_path.read_text(encoding="utf-8"))["chapter_id"] == "ch_001"

    context = ContextBuilder(root, "demo").build_generation_context("ch_001")
    writer_payload = build_writer_payload(
        context=context,
        truth=TruthFilesManager(root, "demo").load_truth_files(),
        packet=packet,
        guidance="",
        target_words=0,
    )
    assert "角色1" not in {character["name"] for character in writer_payload["active_characters"]}


def test_run_preflight_reuses_the_context_it_already_validated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root, _novel_root = _bootstrap_novel(tmp_path)
    state_store = BookStateStore(root, "demo")
    state = state_store.load_or_create()
    state.stage = BookStage.CHAPTER_PREFLIGHT
    state_store.save(state)
    orchestrator = OpenWriteOrchestrator.for_testing(
        root,
        "demo",
        state_store=state_store,
        planning_store=StoryPlanningStore(root, "demo"),
    )
    original_build = ContextBuilder.build_generation_context
    context_builds: list[str] = []

    def counted_build(builder, chapter_id, window_size=5):
        context_builds.append(chapter_id)
        return original_build(builder, chapter_id, window_size)

    monkeypatch.setattr(ContextBuilder, "build_generation_context", counted_build)

    result = orchestrator.run_chapter_preflight("ch_001")

    assert result["ok"] is True
    assert result["packet"]["chapter_id"] == "ch_001"
    assert context_builds == ["ch_001"]


def test_orchestrator_character_documents_keep_canonical_name_and_full_context(
    tmp_path: Path,
):
    from models.character import CharacterProfile

    orchestrator = OpenWriteOrchestrator.for_testing(tmp_path, "demo")
    profile = CharacterProfile(
        character_id="shen_jin",
        name="沈烬",
        backstory="旧事" * 500,
    )

    documents = orchestrator._build_character_documents(
        SimpleNamespace(active_characters=[profile])
    )

    assert list(documents) == ["沈烬"]
    assert len(documents["沈烬"]) > 800
    assert documents["沈烬"].endswith("旧事")


def test_delegate_writing_runs_review_when_executor_available(
    tmp_path: Path,
):
    root, novel_root = _bootstrap_novel(tmp_path)
    state_store = BookStateStore(root, "demo")
    planning_store = StoryPlanningStore(root, "demo")
    planning_store.promote_foundation()
    state = state_store.load_or_create()
    state.stage = BookStage.CHAPTER_PREFLIGHT
    state.current_chapter = "ch_001"
    state_store.save(state)

    calls: dict[str, int] = {"write_chapter": 0, "review_chapter": 0}

    def write_chapter(args: dict) -> dict:
        calls["write_chapter"] += 1
        assert args["chapter_id"] == "ch_001"
        assert args["target_words"] == 2800
        assert args["temperature"] == 0.25
        return {
            "ok": True,
            "chapter_id": "ch_001",
            "draft_path": str(novel_root / "data" / "manuscript" / "arc_001" / "ch_001.md"),
        }

    def review_chapter(args: dict) -> dict:
        calls["review_chapter"] += 1
        return {"ok": True}

    executors = {name: (lambda args: {"ok": True}) for name in WRITING_TOOLKIT}
    executors["write_chapter"] = write_chapter
    executors["review_chapter"] = review_chapter

    orchestrator = OpenWriteOrchestrator.for_testing(
        root,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
        tool_executors=executors,
    )

    result = orchestrator.delegate_writing(
        "ch_001",
        target_words=2800,
        temperature=0.25,
    )

    loaded_state = state_store.load_or_create()

    assert result["ok"] is True
    assert result["chapter_id"] == "ch_001"
    assert result["next_action"] == "ready_for_next_chapter"
    assert calls["write_chapter"] == 1
    assert calls["review_chapter"] == 1
    assert loaded_state.stage == BookStage.CHAPTER_PREFLIGHT
    assert loaded_state.last_agent_action == "delegated_writing_review_passed"


def test_delegate_writing_records_failure_when_executor_raises(
    tmp_path: Path,
):
    root, novel_root = _bootstrap_novel(tmp_path)
    state_store = BookStateStore(root, "demo")
    planning_store = StoryPlanningStore(root, "demo")
    planning_store.promote_foundation()
    state = state_store.load_or_create()
    state.stage = BookStage.CHAPTER_PREFLIGHT
    state.current_chapter = "ch_001"
    state_store.save(state)

    def write_chapter(args: dict) -> dict:
        raise RuntimeError("boom")

    orchestrator = OpenWriteOrchestrator.for_testing(
        root,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
        tool_executors={"write_chapter": write_chapter},
    )

    result = orchestrator.delegate_writing("ch_001")

    workflow = WorkflowScheduler(root, "demo").load_workflow("ch_001")
    loaded_state = state_store.load_or_create()

    assert result["ok"] is False
    assert result["reason"] == "boom"
    assert workflow is not None
    assert next(stage for stage in workflow.stages if stage.name == "writing").status == "failed"
    assert loaded_state.blocking_reason == "writing_failed"
    assert loaded_state.last_agent_action == "delegated_writing_failed"


def test_delegate_writing_persists_failure_when_fail_stage_raises(
    tmp_path: Path,
    monkeypatch,
):
    root, novel_root = _bootstrap_novel(tmp_path)
    state_store = BookStateStore(root, "demo")
    planning_store = StoryPlanningStore(root, "demo")
    planning_store.promote_foundation()
    state = state_store.load_or_create()
    state.stage = BookStage.CHAPTER_PREFLIGHT
    state.current_chapter = "ch_001"
    state_store.save(state)

    def write_chapter(args: dict) -> dict:
        raise RuntimeError("boom")

    def broken_fail_stage(self, state, stage_name: str, error: str):
        raise RuntimeError("cannot persist failure")

    monkeypatch.setattr(WorkflowScheduler, "fail_stage", broken_fail_stage, raising=True)

    orchestrator = OpenWriteOrchestrator.for_testing(
        root,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
        tool_executors={"write_chapter": write_chapter},
    )

    result = orchestrator.delegate_writing("ch_001")

    workflow = WorkflowScheduler(root, "demo").load_workflow("ch_001")
    assert result["ok"] is False
    assert workflow is not None
    writing_stage = next(stage for stage in workflow.stages if stage.name == "writing")
    assert writing_stage.status == "failed"
    assert workflow.error.startswith("writing:")


def test_delegate_writing_sanitizes_invalid_draft_path(
    tmp_path: Path,
):
    root, novel_root = _bootstrap_novel(tmp_path)
    state_store = BookStateStore(root, "demo")
    planning_store = StoryPlanningStore(root, "demo")
    planning_store.promote_foundation()
    state = state_store.load_or_create()
    state.stage = BookStage.CHAPTER_PREFLIGHT
    state.current_chapter = "ch_001"
    state_store.save(state)

    def write_chapter(args: dict) -> dict:
        return {
            "ok": True,
            "chapter_id": "ch_001",
            "draft_path": "../../outside.md",
        }

    orchestrator = OpenWriteOrchestrator.for_testing(
        root,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
        tool_executors={"write_chapter": write_chapter},
    )

    result = orchestrator.delegate_writing("ch_001")

    workflow = WorkflowScheduler(root, "demo").load_workflow("ch_001")

    assert result["ok"] is True
    assert workflow is not None
    assert workflow.draft_path == ""


def test_delegate_writing_advances_book_state_and_creates_workflow(
    tmp_path: Path,
):
    root, novel_root = _bootstrap_novel(tmp_path)
    state_store = BookStateStore(root, "demo")
    planning_store = StoryPlanningStore(root, "demo")
    planning_store.promote_foundation()
    state = state_store.load_or_create()
    state.stage = BookStage.CHAPTER_PREFLIGHT
    state.current_chapter = "ch_001"
    state_store.save(state)

    def write_chapter(args: dict) -> dict:
        draft_path = novel_root / "data" / "manuscript" / "arc_001" / "ch_001.md"
        draft_path.parent.mkdir(parents=True, exist_ok=True)
        draft_path.write_text("正文", encoding="utf-8")
        return {"ok": True, "chapter_id": args["chapter_id"], "draft_path": str(draft_path)}

    orchestrator = OpenWriteOrchestrator.for_testing(
        root,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
        tool_executors={"write_chapter": write_chapter},
    )

    result = orchestrator.delegate_writing("ch_001")

    loaded_state = state_store.load_or_create()
    workflow = WorkflowScheduler(root, "demo").load_workflow("ch_001")

    assert result["ok"] is True
    assert result["next_stage"] == BookStage.REVIEW_AND_REVISE.value
    assert loaded_state.stage == BookStage.REVIEW_AND_REVISE
    assert workflow is not None
    assert workflow.current_stage == "review"
