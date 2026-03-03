"""Tests for style composer and upgraded stylist agent."""

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))


def _create_style_fixture(tmpdir: Path) -> Path:
    """Create a minimal three-layer style fixture for testing."""
    root = tmpdir / "project"
    root.mkdir()

    # craft layer
    craft = root / "craft"
    craft.mkdir()
    (craft / "dialogue_craft.md").write_text(
        "# 通用对话技法\n\n## 乒乓球规则\n信息提供者每说1-2个信息点，接收者必须有反应。\n",
        encoding="utf-8",
    )
    (craft / "tension_patterns.md").write_text(
        "# 张力模型\n\n## 基础模式\n紧张→松弛→紧张循环。\n",
        encoding="utf-8",
    )

    # styles layer
    style_dir = root / "styles" / "test_style"
    style_dir.mkdir(parents=True)
    (style_dir / "fingerprint.md").write_text(
        "# 风格指纹\n\n## 核心标识\n1. 吐槽密度高\n2. 表里不一角色塑造\n\n"
        "## 风格反模式\n- 中性叙述句\n- 煽情段落无冷静转折\n",
        encoding="utf-8",
    )
    (style_dir / "voice.md").write_text(
        "# 叙述者声音\n\n## 核心原则\n读者分不清叙述者和角色。\n",
        encoding="utf-8",
    )
    (style_dir / "language.md").write_text(
        "# 语言风格\n\n## 句式特征\n短句为主，节奏明快。\n",
        encoding="utf-8",
    )
    (style_dir / "dialogue_craft.md").write_text(
        "# 对话风格（作品特有）\n\n## 吐槽式对话\n对话中穿插内心吐槽。\n",
        encoding="utf-8",
    )

    # novels layer
    novel_dir = root / "novels" / "test_novel"
    novel_dir.mkdir(parents=True)
    (novel_dir / "characters.md").write_text(
        "# 角色设定\n\n## 主角\n- 身份：穿越者\n- 绝不会：暴露身份\n",
        encoding="utf-8",
    )
    (novel_dir / "worldbuilding_rules.md").write_text(
        "# 世界观规则\n\n## 魔法体系\n术灵系统，三大派系。\n",
        encoding="utf-8",
    )
    (novel_dir / "terminology.md").write_text(
        "# 术语表\n\n- 术灵：魔法生物\n- 奇迹：术灵的能力\n",
        encoding="utf-8",
    )

    # composed output dir
    (root / "composed").mkdir()

    return root


def test_style_composer_load_layers():
    from utils.style_composer import StyleComposer

    with tempfile.TemporaryDirectory() as tmpdir:
        root = _create_style_fixture(Path(tmpdir))
        composer = StyleComposer(root)

        craft = composer.load_craft_layer()
        assert craft.name == "通用技法"
        assert craft.priority == 1
        assert "dialogue_craft" in craft.files
        assert "tension_patterns" in craft.files

        style = composer.load_style_layer("test_style")
        assert style.priority == 2
        assert "fingerprint" in style.files
        assert "voice" in style.files

        novel = composer.load_novel_layer("test_novel")
        assert novel.priority == 3
        assert "characters" in novel.files
        assert "worldbuilding_rules" in novel.files


def test_style_composer_compose():
    from utils.style_composer import StyleComposer

    with tempfile.TemporaryDirectory() as tmpdir:
        root = _create_style_fixture(Path(tmpdir))
        composer = StyleComposer(root)

        result = composer.compose(
            novel_id="test_novel",
            style_id="test_style",
            write_output=True,
        )

        # Check composed content
        assert "test_novel" in result.novel_id
        assert "test_style" in result.style_id
        assert len(result.hard_constraints) > 0
        assert len(result.style_constraints) > 0
        assert len(result.craft_reference) > 0
        assert "穿越者" in result.hard_constraints
        assert "术灵" in result.hard_constraints
        assert (
            "风格指纹" in result.style_constraints or "吐槽" in result.style_constraints
        )
        # dialogue_craft in style layer should override craft layer
        assert "tension_patterns" in result.craft_reference
        assert "对话风格" not in result.craft_reference  # overridden by style layer

        # Check output file
        output_path = composer.get_composed_path("test_novel")
        assert output_path.exists()
        content = output_path.read_text(encoding="utf-8")
        assert "最终风格文档" in content
        assert "硬性约束" in content
        assert "风格约束" in content

        # Check load_composed
        loaded = composer.load_composed("test_novel")
        assert loaded is not None
        assert "最终风格文档" in loaded


def test_style_composer_user_overrides():
    from utils.style_composer import StyleComposer

    with tempfile.TemporaryDirectory() as tmpdir:
        root = _create_style_fixture(Path(tmpdir))
        composer = StyleComposer(root)

        result = composer.compose(
            novel_id="test_novel",
            style_id="test_style",
            user_overrides={"章节长度": "2000-3000字", "吐槽密度": "降低30%"},
            write_output=False,
        )

        assert "章节长度" in result.user_overrides
        assert "2000-3000字" in result.user_overrides
        md = result.to_markdown()
        assert "用户覆盖" in md
        assert "章节长度" in md


def test_style_composer_list():
    from utils.style_composer import StyleComposer

    with tempfile.TemporaryDirectory() as tmpdir:
        root = _create_style_fixture(Path(tmpdir))
        composer = StyleComposer(root)

        styles = composer.list_available_styles()
        assert "test_style" in styles

        novels = composer.list_available_novels()
        assert "test_novel" in novels


def test_stylist_check_ai_artifacts():
    from agents.stylist import StylistAgent

    agent = StylistAgent()

    text_with_ai = '他不禁微微一笑，缓缓说道："我知道了。"\n她嘴角微微上扬。'
    result = agent.check_style(text_with_ai)

    ai_issues = [i for i in result.issues if i.category == "anti_pattern"]
    assert len(ai_issues) >= 3
    phrases_found = [i.message for i in ai_issues]
    assert any("不禁" in m for m in phrases_found)
    assert any("微微一笑" in m for m in phrases_found)
    assert any("缓缓说道" in m for m in phrases_found)


def test_stylist_check_rhythm():
    from agents.stylist import StylistAgent

    agent = StylistAgent()

    # All long paragraphs — should trigger rhythm warning
    long_text = "\n".join(
        [
            "这是一段很长的叙述。包含了大量的信息。角色在这里做了很多事情。"
            "他走过了长长的走廊。看到了很多奇怪的东西。心中充满了疑惑。然后他继续前进。"
            for _ in range(6)
        ]
    )
    result = agent.check_style(long_text)
    rhythm_issues = [i for i in result.issues if i.category == "rhythm"]
    assert len(rhythm_issues) >= 1


def test_stylist_check_voice():
    from agents.stylist import StylistAgent

    agent = StylistAgent()

    neutral_text = "他静静地看着远方。她的内心十分高兴。"
    result = agent.check_style(neutral_text)
    voice_issues = [i for i in result.issues if i.category == "voice"]
    assert len(voice_issues) >= 1


def test_stylist_polish_backward_compat():
    from agents.stylist import StylistAgent

    agent = StylistAgent()

    text = "他不禁微微一笑。这里有冲突发生。"
    result = agent.polish(text, banned_phrases=["冲突"])

    assert "冲突" not in result.text
    assert "不禁" not in result.text
    assert isinstance(result.edits, list)
    assert len(result.edits) > 0
    assert isinstance(result.score, dict)
    assert "overall" in result.score


def test_stylist_score_computation():
    from agents.stylist import StylistAgent

    agent = StylistAgent()

    # Clean text should score high
    clean_text = '"你来了。"亚修说道。\n\n淦，这什么情况。他心里慌得一批。\n\n"嗯。"对方简短回应。'
    result = agent.check_style(clean_text)
    assert result.score["anti_pattern"] >= 80
    assert result.score["overall"] >= 60


def test_director_context_compression():
    from agents.director_v2 import DirectorAgent

    agent = DirectorAgent()

    long_context = {
        "summary": "x" * 1000,
        "seed": "推进主线",
        "outline": "主角在监狱中遭遇挑战" * 20,
        "characters": "亚修(境界=凡人, 位置=碎湖监狱)" * 10,
        "foreshadowing": "f001(权重=9, 层级=主线, 目标=ch_010)",
        "scenes": "场景数=2, 张力范围=6-9",
        "world": "碎湖监狱(location)" * 10,
    }

    decision = agent.plan(
        objective="推进主线：战斗场景",
        context=long_context,
        chapter_id="ch_005",
    )

    # Context should be compressed
    assert len(decision.compressed_context["outline"]) <= agent.BUDGET_OUTLINE + 10
    assert (
        len(decision.compressed_context["characters"]) <= agent.BUDGET_CHARACTERS + 10
    )
    # suggested_strict_lore is now always False (removed hardcoded logic)
    assert decision.suggested_strict_lore is False
    assert len(decision.priority_elements) > 0


def test_director_stylist_routing():
    from tools.agents.director_v2 import DirectorAgent

    agent = DirectorAgent()
    context = {
        "summary": "",
        "seed": "test",
        "outline": "",
        "characters": "",
        "foreshadowing": "暂无待回收伏笔",
        "scenes": "",
        "world": "",
    }

    # Without stylist
    d1 = agent.plan(objective="日常", context=context, use_stylist=False)
    assert "stylist" not in d1.required_agents

    # With stylist
    d2 = agent.plan(
        objective="日常", context=context, use_stylist=True, style_summary="风格DNA维度"
    )
    assert "stylist" in d2.required_agents
    assert len(d2.style_instructions) > 0
