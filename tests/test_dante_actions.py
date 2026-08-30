import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.agent.book_state import BookStage, BookStateStore
from tools.agent.dante_actions import DanteActionAdapter
from tools.agent.goethe_actions import GoethePlanningRuntime
from tools.agent.orchestrator import OpenWriteOrchestrator, OrchestratorResult
from tools.story_planning import StoryPlanningStore


def _bootstrap_planning_project(tmp_path: Path) -> tuple[BookStateStore, StoryPlanningStore]:
    planning_store = StoryPlanningStore(tmp_path, "demo")
    planning_store.append_ideation("主角是普通上班族。")
    planning_store.append_ideation("公司地下埋着异常节点。")
    planning_store.save_foundation_draft(
        background=("# 背景\n\n现代都市表面稳定，实则少数人能看见异常术式和隐秘节点。"),
        foundation=("# 基础设定\n\n主角在公司里被迫接触术式推演能力。"),
    )
    planning_store.save_outline_draft(
        "# 测试小说\n\n"
        "## 第一篇\n\n"
        "主角从公司异常事件中觉醒，并决定继续调查。\n\n"
        "### 第一节\n\n"
        "主角在公司地下发现异常节点，并决定继续调查。\n\n"
        "#### 第一章\n\n"
        "> 内容焦点: 发现异常\n"
        "> 出场角色: char_001\n"
        "> 涉及设定: 测试场景\n"
    )

    novel_root = tmp_path / "data" / "novels" / "demo"
    (novel_root / "src" / "characters").mkdir(parents=True, exist_ok=True)
    (novel_root / "src" / "characters" / "char_001.md").write_text(
        "# 角色一\n\n## 背景\n\n角色背景。\n",
        encoding="utf-8",
    )
    (novel_root / "src" / "world" / "entities").mkdir(parents=True, exist_ok=True)
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
    (novel_root / "src" / "story").mkdir(parents=True, exist_ok=True)
    (novel_root / "src" / "story" / "background.md").write_text(
        "# 背景\n\n现代都市表面稳定。",
        encoding="utf-8",
    )
    (novel_root / "src" / "story" / "foundation.md").write_text(
        "# 基础设定\n\n主角接触术式推演能力。",
        encoding="utf-8",
    )
    (novel_root / "data" / "style").mkdir(parents=True, exist_ok=True)
    (novel_root / "data" / "style" / "fingerprint.yaml").write_text(
        "voice: 测试语气\nlanguage_style: 测试句式\nrhythm: 测试节奏\n",
        encoding="utf-8",
    )

    return BookStateStore(tmp_path, "demo"), planning_store


def test_foundation_draft_uses_canonical_context_without_regressing_stage(
    tmp_path: Path,
):
    (tmp_path / "novel_config.yaml").write_text(
        "novel_id: demo\ntitle: 测试作品\n",
        encoding="utf-8",
    )
    planning = StoryPlanningStore(tmp_path, "demo")
    planning.story_src_dir.mkdir(parents=True, exist_ok=True)
    (planning.story_src_dir / "background.md").write_text(
        "# 背景\n\n归墟港是前文明失败后的回收港。",
        encoding="utf-8",
    )
    (planning.story_src_dir / "foundation.md").write_text(
        "# 基础设定\n\n沈烬通过回响校勘改变历史变量。",
        encoding="utf-8",
    )
    planning.outline_src_path.parent.mkdir(parents=True, exist_ok=True)
    planning.outline_src_path.write_text(
        "# 第一卷\n\n## 第一幕\n\n### 第一节\n\n#### 第一章\n",
        encoding="utf-8",
    )
    state_store = BookStateStore(tmp_path, "demo")
    state = state_store.load_or_create()
    state.stage = BookStage.CHAPTER_PREFLIGHT
    state.pending_confirmation = "foundation"
    state_store.save(state)
    class FakeArchitect:
        def generate_foundation(self, **kwargs):
            raise AssertionError("mature projects must not regenerate canonical foundations")

    runtime = GoethePlanningRuntime(tmp_path, "demo")
    runtime._architect = FakeArchitect()  # type: ignore[assignment]

    result = runtime.generate_foundation_draft("仅补全现有设定")

    assert result["next_action"] == "review_foundation_draft"
    assert result["warnings"] == ["mature_project_reused_canonical_foundation"]
    assert "归墟港是前文明失败后的回收港" in result["story_bible"]
    assert "沈烬通过回响校勘改变历史变量" in result["book_rules"]
    assert "#### 第一章" in result["outline_seed"]
    assert result["foreshadowing_generated"] is False
    assert result["foreshadowing_path"] == ""
    persisted = state_store.load_or_create()
    assert persisted.stage == BookStage.CHAPTER_PREFLIGHT
    assert persisted.pending_confirmation == ""


def test_character_request_parser_treats_chinese_semicolon_as_field_boundary(
    tmp_path: Path,
):
    runtime = object.__new__(GoethePlanningRuntime)

    name, role = runtime._parse_character_request(
        "角色名：链路审校员；角色定位：归墟档案室临时审校员，专门记录异常"
    )

    assert name == "链路审校员"
    assert role == "归墟档案室临时审校员"


def test_source_extraction_accepts_inline_text_and_removes_temporary_file():
    captured: dict[str, object] = {}

    class FakeNovelService:
        def extract_source(self, *, source_id: str, source_file: Path, focus: str):
            captured.update(
                source_id=source_id,
                source_file=source_file,
                focus=focus,
                content=source_file.read_text(encoding="utf-8"),
            )
            return {"ok": True, "source_id": source_id}

    runtime = object.__new__(GoethePlanningRuntime)
    runtime.novel_service = FakeNovelService()  # type: ignore[assignment]

    result = runtime.extract_style_source("inline_demo", "雨声敲在旧港的铜门上。")

    assert result["ok"] is True
    assert captured["source_id"] == "inline_demo"
    assert captured["focus"] == "style"
    assert captured["content"] == "雨声敲在旧港的铜门上。"
    assert not Path(captured["source_file"]).exists()


def test_source_extraction_reports_missing_explicit_file_path():
    runtime = object.__new__(GoethePlanningRuntime)

    result = runtime.extract_setting_source("missing_demo", "./missing-source.txt")

    assert result["ok"] is False
    assert result["error"] == "missing_source_file"
    assert result["next_action"] == "provide_source_file"


def test_dante_action_adapter_delegates_public_orchestrator_actions(tmp_path: Path):
    calls: list[tuple[str, tuple, dict]] = []

    class FakeOrchestrator:
        def summarize_ideation(self):
            calls.append(("summarize_ideation", (), {}))
            return {"ok": True, "next_action": "confirm_ideation_summary"}

        def confirm_ideation_summary(self, text: str):
            calls.append(("confirm_ideation_summary", (text,), {}))
            return {"ok": True, "next_action": "ready_for_outline_generation"}

        def generate_outline_draft(self, request_text: str):
            calls.append(("generate_outline_draft", (request_text,), {}))
            return {"ok": True, "next_action": "request_outline_confirmation"}

        def run_chapter_preflight(self, chapter_id: str):
            calls.append(("run_chapter_preflight", (chapter_id,), {}))
            return {"ok": True, "chapter_id": chapter_id, "packet": {"chapter_id": chapter_id}}

        story_planning_store = type(
            "StoryPlanningStoreProxy",
            (),
            {"read_outline_draft": lambda self, max_chars=0: "# 测试小说"},
        )()

    adapter = DanteActionAdapter(FakeOrchestrator())

    summary = adapter.summarize_ideation()
    confirmed = adapter.confirm_ideation_summary("这个汇总可以")
    outline = adapter.generate_outline_draft("帮我生成一份四级大纲")
    preflight = adapter.run_chapter_preflight("ch_001")

    assert summary["action"] == "summarize_ideation"
    assert confirmed["action"] == "confirm_ideation_summary"
    assert outline["action"] == "generate_outline_draft"
    assert outline["outline_draft"] == "# 测试小说"
    assert preflight["action"] == "run_chapter_preflight"
    assert preflight["chapter_id"] == "ch_001"
    assert [call[0] for call in calls] == [
        "summarize_ideation",
        "confirm_ideation_summary",
        "generate_outline_draft",
        "run_chapter_preflight",
    ]


def test_dante_action_adapter_skips_outline_draft_when_generation_blocked():
    class FakeOrchestrator:
        def summarize_ideation(self):
            return {"ok": True, "next_action": "confirm_ideation_summary"}

        def confirm_ideation_summary(self, text: str):
            return {"ok": True, "next_action": "ready_for_outline_generation"}

        def generate_outline_draft(self, request_text: str):
            return OrchestratorResult(
                message="blocked",
                stage=BookStage.ROLLING_OUTLINE,
                blocked=True,
                next_action="blocked",
            )

        def run_chapter_preflight(self, chapter_id: str):
            return {"ok": True, "chapter_id": chapter_id}

        story_planning_store = type(
            "StoryPlanningStoreProxy",
            (),
            {
                "read_outline_draft": lambda self, max_chars=0: "# 测试小说\n" + ("x" * 4000),
            },
        )()

    adapter = DanteActionAdapter(FakeOrchestrator())

    payload = adapter.generate_outline_draft("帮我生成一份四级大纲")

    assert payload["blocked"] is True
    assert "outline_draft" not in payload


def test_dante_action_adapter_bounds_outline_draft_payload(tmp_path: Path):
    huge_outline = "# 测试小说\n" + ("x" * 5000)

    class FakeOrchestrator:
        def summarize_ideation(self):
            return {"ok": True, "next_action": "confirm_ideation_summary"}

        def confirm_ideation_summary(self, text: str):
            return {"ok": True, "next_action": "ready_for_outline_generation"}

        def generate_outline_draft(self, request_text: str):
            return {
                "ok": True,
                "blocked": False,
                "next_action": "request_outline_confirmation",
            }

        def run_chapter_preflight(self, chapter_id: str):
            return {"ok": True, "chapter_id": chapter_id}

        story_planning_store = type(
            "StoryPlanningStoreProxy",
            (),
            {
                "read_outline_draft": lambda self, max_chars=0: (
                    huge_outline[:max_chars] if max_chars else huge_outline
                )
            },
        )()

    adapter = DanteActionAdapter(FakeOrchestrator())

    payload = adapter.generate_outline_draft("帮我生成一份四级大纲")

    assert payload["action"] == "generate_outline_draft"
    assert len(payload["outline_draft"]) <= 1200
    assert payload["outline_draft"].startswith("# 测试小说")


def test_orchestrator_public_actions_drive_planning_flow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    state_store, planning_store = _bootstrap_planning_project(tmp_path)
    orchestrator = OpenWriteOrchestrator.for_testing(
        tmp_path,
        "demo",
        state_store=state_store,
        planning_store=planning_store,
    )

    def fake_chat(system_prompt, user_prompt, **kwargs):
        if "立项整理助手" in system_prompt:
            return "# 当前想法汇总\n\n## 核心方向\n\n- 都市职场异能"
        if "小说规划师" in system_prompt:
            return (
                "# 测试小说\n\n"
                "## 第一篇\n\n"
                "主角从公司异常事件中觉醒，并决定继续调查。\n\n"
                "### 第一节\n\n"
                "主角在公司地下发现异常节点，并决定继续调查。\n\n"
                "#### 第一章\n\n"
                "> 戏剧位置: 起\n"
                "> 内容焦点: 发现异常\n"
                "> 本章目标: 建立公司地下的异常冲突\n"
                "> 预估字数: 3000\n"
                "> 出场角色: char_001\n"
                "> 涉及设定: 测试场景\n"
                "> 情感弧线: 平静 -> 戒备\n"
                "> 节拍: 正常上班, 发现节点, 决定调查\n"
                "> 悬念: 节点为何出现在公司\n\n"
                "主角第一次确认公司地下存在异常。\n"
            )
        raise AssertionError(f"unexpected system prompt: {system_prompt}")

    monkeypatch.setattr(orchestrator, "_chat_text", fake_chat)

    summary_result = orchestrator.summarize_ideation()
    state = state_store.load_or_create()
    assert summary_result.blocked is False
    assert summary_result.next_action == "confirm_ideation_summary"
    assert state.pending_confirmation == "ideation_summary"

    confirm_result = orchestrator.confirm_ideation_summary("这个汇总可以")
    state = state_store.load_or_create()
    assert confirm_result.blocked is False
    assert confirm_result.next_action == "ready_for_outline_generation"
    assert state.stage == BookStage.FOUNDATION

    outline_result = orchestrator.generate_outline_draft("帮我生成一份四级大纲")
    state = state_store.load_or_create()
    assert outline_result.blocked is False
    assert outline_result.next_action == "request_outline_confirmation"
    assert state.stage == BookStage.ROLLING_OUTLINE
    assert planning_store.outline_src_path.exists() is False
    assert planning_store.outline_draft_path.read_text(encoding="utf-8").startswith("# 测试小说")

    promotion_result = orchestrator.confirm_outline_draft()

    assert promotion_result.blocked is False
    assert promotion_result.next_action == "chapter_preflight"
    assert planning_store.outline_src_path.read_text(encoding="utf-8").startswith("# 测试小说")

    state.stage = BookStage.CHAPTER_PREFLIGHT
    state.current_chapter = "ch_001"
    state_store.save(state)
    preflight_result = orchestrator.run_chapter_preflight("ch_001")

    assert preflight_result["ok"] is True
    assert preflight_result["chapter_id"] == "ch_001"
    assert preflight_result["packet"]["chapter_id"] == "ch_001"
