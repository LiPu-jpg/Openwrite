import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from models.runtime_state import RuntimeStateDelta
from tools.agent.reviewer import ReviewerAgent, ReviewIssue
from tools.agent.tool_runtime import build_tool_executors
from tools.agent.writer import WriterAgent
from tools.chapter_pipeline import build_writer_payload
from tools.goethe import _build_goethe_tool_definitions
from tools.init_project import init_project
from tools.llm.response import ProviderResponseError
from tools.radar import PlatformRecommendation, RadarAgent
from tools.story_planning import StoryPlanningStore
from tools.style_synthesizer import REQUIRED_STYLE_HEADINGS, synthesize_style_document
from tools.truth_manager import TruthFilesManager


def test_foundation_bundle_stays_in_planning_until_promoted(tmp_path: Path):
    store = StoryPlanningStore(tmp_path, "demo")
    store.save_foundation_draft(
        background="# 背景\n\n雨城。",
        foundation="# 基础设定\n\n钟声会改写记忆。",
        volume_outline="# 卷纲\n\n第一篇调查钟楼。",
        current_state="# 当前状态\n\n沈烬尚未进入钟楼。",
        foreshadowing={
            "nodes": {
                "f001": {
                    "id": "f001",
                    "content": "钟楼每天少响一声",
                    "weight": 8,
                    "layer": "主线",
                    "status": "埋伏",
                    "created_at": "ch_001",
                    "target_chapter": "ch_010",
                    "tags": ["钟楼"],
                }
            },
            "edges": [],
            "status": {"f001": "埋伏"},
        },
    )

    assert not (store.story_src_dir / "background.md").exists()
    assert not (store.novel_root / "data" / "foreshadowing" / "dag.yaml").exists()

    assert store.promote_foundation() is True
    assert (store.story_src_dir / "background.md").exists()
    assert "沈烬尚未进入钟楼" in TruthFilesManager(
        tmp_path, "demo"
    ).load_truth_files().current_state
    dag = yaml.safe_load(
        (store.novel_root / "data" / "foreshadowing" / "dag.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert dag["nodes"]["f001"]["content"] == "钟楼每天少响一声"
    assert store.volume_outline_draft_path.exists()


def test_character_tool_preserves_complete_generated_document(tmp_path: Path):
    init_project(tmp_path, "demo")
    content = """+++
id = "lin_zhou"
name = "林舟"
tier = "主角"
summary = "能听见缺失时间的钟表匠。"
tags = ["主角", "钟楼"]
+++

# 林舟

## 基本信息
钟表匠。
## 背景
在旧钟楼长大。
## 外貌
左手有烧伤。
## 性格
谨慎固执。
## 与主角关系
本人。
## 说话风格
短句。
## 当前戏剧用途
调查时间缺口。
"""

    result = build_tool_executors(tmp_path)["create_character"](
        {"name": "林舟", "description": "", "content": content}
    )

    assert result["ok"] is True
    saved = Path(result["file"]).read_text(encoding="utf-8")
    assert "## 当前戏剧用途\n调查时间缺口。" in saved
    assert 'tier = "主角"' in saved


def test_goethe_exposes_explicit_foundation_and_character_confirmation_tools():
    tools = {tool.name: tool for tool in _build_goethe_tool_definitions()}

    assert tools["confirm_foundation"].required == ["confirm"]
    assert tools["confirm_character_draft"].required == ["character_id", "confirm"]


def test_writer_payload_and_prompt_include_complete_chapter_contract():
    chapter = SimpleNamespace(
        title="第七章：残页",
        summary="沈烬确认残页正在被追查。",
        dramatic_position="转",
        content_focus="主角决定保护残页。",
        emotional_arc="迟疑 -> 决意",
        goals=["确认威胁"],
        beats=["发现跟踪者", "保护残页"],
        hooks=["收购者是谁"],
    )
    context = SimpleNamespace(
        current_chapter=chapter,
        target_words=3000,
        author_intent="选择必须有代价",
        creative_focus="保留悬疑",
        chapter_goals=chapter.goals,
        dramatic_context={"dramatic_position": "转"},
        character_states="沈烬位于归墟港",
        current_state="续存派正在追查残页",
        foreshadowing_summary="f001: 残页来源",
        ledger="残页：沈烬持有",
        relationships="沈烬 -> 刑无咎：互相试探",
        recent_text="上一章正文",
        semantic_references="第三章中，沈烬曾在压力下隐瞒手链来历。",
        chapter_summaries="历史摘要",
        emotion_arc=chapter.emotional_arc,
    )
    payload = build_writer_payload(
        context=context,
        truth=SimpleNamespace(relationships="旧关系"),
        packet={},
        guidance="",
        target_words=0,
    )
    prompt = WriterAgent._build_creative_user_prompt(
        object(), payload, chapter_number=7, target_words=3000
    )

    for expected in (
        "发现跟踪者",
        "收购者是谁",
        "迟疑 -> 决意",
        "f001: 残页来源",
        "残页：沈烬持有",
        "沈烬 -> 刑无咎：互相试探",
        "第三章中，沈烬曾在压力下隐瞒手链来历。",
        "不覆盖人物状态和正典事实",
    ):
        assert expected in prompt


def test_writer_observer_receives_full_chapter_and_length_is_enforced():
    writer = WriterAgent.__new__(WriterAgent)
    captured = {}

    def chat(*, messages, **kwargs):
        captured["prompt"] = messages[1].content
        return SimpleNamespace(content="事实", usage={})

    writer.chat = chat
    content = "前" * 4000 + "结尾证据"
    asyncio.run(
        writer._observe_facts({}, chapter_number=1, title="钟差", content=content)
    )
    assert "结尾证据" in captured["prompt"]

    with pytest.raises(ProviderResponseError) as raised:
        writer._parse_creative_output(
            "# 第一章：钟差\n\n太短。",
            chapter_number=1,
            usage={},
            target_words=1000,
        )
    assert raised.value.code == "CHAPTER_LENGTH_OUT_OF_RANGE"


def test_writer_rewrites_once_when_first_draft_misses_length_range():
    writer = WriterAgent.__new__(WriterAgent)
    responses = iter(
        [
            SimpleNamespace(
                content="# 第一章：钟差\n\n" + "长" * 1300,
                usage={"total_tokens": 100},
            ),
            SimpleNamespace(
                content="# 第一章：钟差\n\n" + "准" * 1000,
                usage={"total_tokens": 80},
            ),
        ]
    )
    calls: list[list] = []

    def chat(*, messages, **kwargs):
        calls.append(messages)
        return next(responses)

    writer.chat = chat

    result = asyncio.run(
        writer._creative_write({}, chapter_number=1, temperature=0.7, target_words=1000)
    )

    assert len(calls) == 2
    assert "长度不合格" in calls[1][-1].content
    assert result["word_count"] == 1000
    assert result["usage"]["total_tokens"] == 180


def test_writer_retries_truncated_state_settlement_with_compact_schema():
    writer = WriterAgent.__new__(WriterAgent)
    calls: list[list] = []

    def chat(*, messages, **kwargs):
        calls.append(messages)
        if len(calls) == 1:
            raise ProviderResponseError("MODEL_OUTPUT_TRUNCATED", "模型输出被截断")
        return SimpleNamespace(
            content=(
                "state_updates:\n"
                '  current_state: "沈烬进入旧港编号门。"\n'
                'chapter_summary: "沈烬按铜钟节拍进入旧港编号门，并发现房间记录未兑现的承诺。"\n'
            ),
            usage={"total_tokens": 40},
        )

    writer.chat = chat

    result = asyncio.run(
        writer._settle(
            {},
            chapter_number=2,
            title="编号门",
            content="沈烬推开门。",
            observations="- 沈烬进入编号门",
        )
    )

    assert len(calls) == 2
    assert "极简小说状态增量" in calls[1][0].content
    assert result["state_updates"]["current_state"] == "沈烬进入旧港编号门。"
    assert result["state_delta"]["chapter_id"] == "ch_002"


@pytest.mark.parametrize(
    "collection",
    ["characters", "resources", "relationship_states", "foreshadowing_refs"],
)
def test_runtime_delta_rejects_generic_object_for_collection(collection: str):
    with pytest.raises(ValueError):
        RuntimeStateDelta.model_validate(
            {
                "chapter_id": "ch_001",
                "operations": [
                    {
                        "op": "append",
                        "collection": collection,
                        "value": {
                            "title": "错误通用对象",
                            "status": "open",
                            "detail": "不符合目标集合",
                        },
                    }
                ],
            }
        )


def test_reviewer_strict_dimensions_and_malformed_output():
    reviewer = ReviewerAgent.__new__(ReviewerAgent)
    reviewer.ctx = SimpleNamespace(client=SimpleNamespace(config=SimpleNamespace(model="fake")))
    reviewer._rule_based_check = lambda content, target_words=0: [
        ReviewIssue("warning", "节奏检查", "拖沓", "收紧", dimension=7)
    ]
    reviewer._detect_ai_tells = lambda content: []
    reviewer._check_sensitive_words = lambda content: []

    async def audit_domains(content, context, domains, deterministic_issues):
        assert [domain.id for domain in domains] == ["pacing"]
        return [
            {
                "id": "pacing",
                "criteria": [
                    {
                        "id": "scene_function",
                        "status": "evaluated",
                        "earned": 2,
                        "evidence": ["正文"],
                    }
                ],
            }
        ], []

    reviewer._llm_review_domains = audit_domains
    result = asyncio.run(
        reviewer.review("正文", {}, dimensions=[7], strict=True)
    )
    assert result.passed is False
    assert [issue.dimension for issue in result.issues] == [7]
    assert result.review_v2["schema_version"] == "openwrite.review.v2"

    with pytest.raises(ProviderResponseError):
        reviewer._parse_llm_issues("不是 JSON", allowed_dimensions={1})


def test_incomplete_llm_style_document_uses_validated_fallback(tmp_path: Path):
    class Client:
        def chat(self, messages, temperature=0.2, max_tokens=4000):
            return SimpleNamespace(content="# 风格\n\n## 叙述声音\n\n克制")

    result = synthesize_style_document(
        tmp_path, "demo", "reference", llm_client=Client()
    )

    assert result["mode"] == "fallback"
    for heading in REQUIRED_STYLE_HEADINGS:
        assert f"## {heading}" in result["content"]


def test_radar_limits_each_platform_to_top_n():
    recommendations = [
        PlatformRecommendation(
            platform="平台A",
            genre=f"题材{index}",
            confidence=confidence,
            concept="概念",
            reasoning="理由",
            benchmarks=[],
        )
        for index, confidence in enumerate((0.7, 0.9, 0.8), start=1)
    ]

    selected = RadarAgent._limit_recommendations(recommendations, top_n=2)

    assert [item.confidence for item in selected] == [0.9, 0.8]
