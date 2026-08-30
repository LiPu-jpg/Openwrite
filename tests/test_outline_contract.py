from __future__ import annotations

import asyncio
from types import SimpleNamespace

from tools.agent.dante import DEFAULT_DANTE_SYSTEM_PROMPT
from tools.agent.orchestrator import OpenWriteOrchestrator
from tools.agent.react import OPENWRITE_SYSTEM_PROMPT
from tools.architect import ArchitectAgent
from tools.goethe import DEFAULT_GOETHE_SYSTEM_PROMPT
from tools.outline_contract import INLINE_ANNOTATION_CONTRACT, OUTLINE_MARKDOWN_CONTRACT
from tools.outline_parser import OutlineMdParser

REQUIRED_MARKDOWN_FIELDS = (
    "> 戏剧位置:",
    "> 内容焦点:",
    "> 本章目标:",
    "> 预估字数:",
    "> 出场角色:",
    "> 涉及设定:",
    "> 情感弧线:",
    "> 节拍:",
    "> 悬念:",
)


def test_outline_writing_agents_share_parser_aligned_contract() -> None:
    for prompt in (
        DEFAULT_GOETHE_SYSTEM_PROMPT,
        DEFAULT_DANTE_SYSTEM_PROMPT,
        OPENWRITE_SYSTEM_PROMPT,
    ):
        assert OUTLINE_MARKDOWN_CONTRACT in prompt
        assert INLINE_ANNOTATION_CONTRACT in prompt
        for field in REQUIRED_MARKDOWN_FIELDS:
            assert field in prompt


def test_writer_receives_inline_annotation_contract() -> None:
    from tools.agent.writer import WriterAgent

    prompt = WriterAgent.__new__(WriterAgent)._build_creative_system_prompt({})

    assert INLINE_ANNOTATION_CONTRACT in prompt
    assert "//**关系源~>关系目标:具体关系**" in prompt


def test_outline_draft_generator_uses_shared_contract(tmp_path, monkeypatch) -> None:
    novel_root = tmp_path / "data" / "novels" / "demo"
    characters = novel_root / "src" / "characters"
    settings = novel_root / "src" / "world" / "entities"
    characters.mkdir(parents=True)
    settings.mkdir(parents=True)
    (characters / "lin_cen.md").write_text(
        '+++\nid = "lin_cen"\nname = "林岑"\nrole = "主角"\n+++\n# 林岑\n\n雨夜调查员。',
        encoding="utf-8",
    )
    (settings / "mirror_rain.md").write_text(
        '+++\nid = "mirror_rain"\nname = "镜雨区"\ntype = "location"\n+++'
        "\n# 镜雨区\n\n雨声会影响记忆。",
        encoding="utf-8",
    )
    orchestrator = OpenWriteOrchestrator.for_testing(tmp_path, "demo")
    captured: dict[str, str] = {}

    def fake_chat(system_prompt: str, user_prompt: str, **kwargs) -> str:
        captured["system"] = system_prompt
        captured["user"] = user_prompt
        return "# 测试大纲"

    monkeypatch.setattr(orchestrator, "_chat_text", fake_chat)

    assert orchestrator._generate_outline_draft("生成可写大纲") == "# 测试大纲"
    assert OUTLINE_MARKDOWN_CONTRACT in captured["system"]
    assert "生成可写大纲" in captured["user"]
    assert "可用人物规范目录" in captured["user"]
    assert "林岑 (lin_cen)" in captured["user"]
    assert "可用设定规范目录" in captured["user"]
    assert "镜雨区 (mirror_rain)" in captured["user"]


def test_markdown_contract_fields_round_trip_through_parser() -> None:
    hierarchy = OutlineMdParser().parse(
        """# 测试作品

## 第1篇：开端

林岑从异常来客追查到钟楼危机，并在揭开真相后决定继续守护镜雨区。

### 第1节：入局

林岑在雨夜接待异常来客，循着停摆怀表的线索决定调查钟楼。

#### 第1章：来客
> 戏剧位置: 起
> 内容焦点: 林岑发现异常来客
> 本章目标: 建立冲突，明确选择
> 预估字数: 3200
> 出场角色: 林岑、周岚
> 涉及设定: 镜雨区，停摆怀表
> 情感弧线: 戒备 -> 动摇 -> 决意
> 节拍: 场景切入、冲突升级，关键选择
> 悬念: 来客身份、怀表来源

林岑在雨夜发现钟楼停摆。
""",
        "demo",
    )

    section = hierarchy.sections[0]
    arc = hierarchy.arcs[0]
    chapter = hierarchy.chapters[0]
    assert arc.summary == "林岑从异常来客追查到钟楼危机，并在揭开真相后决定继续守护镜雨区。"
    assert section.summary == "林岑在雨夜接待异常来客，循着停摆怀表的线索决定调查钟楼。"
    assert chapter.dramatic_position == "起"
    assert chapter.content_focus == "林岑发现异常来客"
    assert chapter.goals == ["建立冲突", "明确选择"]
    assert chapter.estimated_words == 3200
    assert chapter.involved_characters == ["林岑", "周岚"]
    assert chapter.involved_settings == ["镜雨区", "停摆怀表"]
    assert chapter.emotional_arc == "戒备 -> 动摇 -> 决意"
    assert chapter.beats == ["场景切入", "冲突升级", "关键选择"]
    assert chapter.hooks == ["来客身份", "怀表来源"]
    assert chapter.summary == "林岑在雨夜发现钟楼停摆。"


def test_architect_requests_and_preserves_complete_chapter_fields() -> None:
    calls: list[object] = []

    class FakeClient:
        def chat(self, messages, **kwargs):
            calls.append(messages)
            return SimpleNamespace(
                content="""[
  {
    "number": 1,
    "title": "来客",
    "summary": "林岑发现异常来客。",
    "dramatic_position": "起",
    "content_focus": "建立异常事件",
    "goals": ["建立冲突"],
    "estimated_words": 3200,
    "involved_characters": ["林岑"],
    "involved_settings": ["镜雨区"],
    "emotional_arc": "戒备 -> 决意",
    "beats": ["发现异常", "决定追查"],
    "hooks": ["来客身份"]
  }
]"""
            )

    architect = ArchitectAgent(SimpleNamespace(client=FakeClient()))
    chapters = asyncio.run(architect.generate_outline("测试作品", "悬疑", "镜雨区会影响记忆", 1))

    system_prompt = calls[0][0].content
    for field in (
        "estimated_words",
        "involved_characters",
        "involved_settings",
        "emotional_arc",
        "beats",
        "hooks",
    ):
        assert field in system_prompt
    assert chapters[0].estimated_words == 3200
    assert chapters[0].involved_characters == ["林岑"]
    assert chapters[0].involved_settings == ["镜雨区"]
    assert chapters[0].beats == ["发现异常", "决定追查"]
    assert chapters[0].hooks == ["来客身份"]


def test_architect_retries_one_empty_model_response() -> None:
    responses = [SimpleNamespace(content=""), SimpleNamespace(content="有效内容")]

    class FakeClient:
        def chat(self, **kwargs):
            return responses.pop(0)

    architect = ArchitectAgent(SimpleNamespace(client=FakeClient()))

    content = architect._chat_required(
        messages=[],
        temperature=0.3,
        max_tokens=128,
        label="test",
    )

    assert content == "有效内容"
    assert responses == []


def test_architect_character_does_not_duplicate_model_heading() -> None:
    class FakeClient:
        def chat(self, **kwargs):
            return SimpleNamespace(content="# 链路审校员\n\n## 基本信息\n\n测试角色")

    architect = ArchitectAgent(SimpleNamespace(client=FakeClient()))

    content = asyncio.run(
        architect.generate_character(
            "链路审校员",
            "归墟档案室临时审校员",
            "unspecified",
            "归墟负责回收历史残骸。",
        )
    )

    assert content.count("# 链路审校员") == 1
