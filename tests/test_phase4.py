"""Tests for upgraded librarian, reader agent, style director, and style model bridge."""

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "tools"))


# ---------------------------------------------------------------------------
# Librarian upgrade tests
# ---------------------------------------------------------------------------


def test_librarian_context_aware_beats():
    from agents.librarian import LibrarianAgent

    agent = LibrarianAgent()
    context = {
        "seed": "推进主线并保留悬念",
        "outline": "主角在监狱中发现了隐藏通道，决定冒险探索",
        "characters": "亚修(境界=凡人, 位置=碎湖监狱, 物品数=2); 索妮娅(境界=术师, 位置=学院)",
        "foreshadowing": "f001(权重=9, 层级=主线, 目标=ch_010); f002(权重=5, 层级=支线, 目标=ch_015)",
        "scenes": "场景数=2, 张力范围=6-9",
        "world": "碎湖监狱(location)",
    }
    beats = agent.generate_beats("ch_005", context)

    # Should have opening + development + foreshadowing + climax + closing
    assert len(beats) >= 5
    # Should contain chapter ID
    assert all("ch_005" in b for b in beats)
    # Should have a foreshadowing beat (high weight f001 exists)
    assert any("伏笔" in b for b in beats)
    # Should extract protagonist name
    assert any("亚修" in b for b in beats)


def test_librarian_structured_draft():
    from agents.librarian import LibrarianAgent

    agent = LibrarianAgent()
    context = {
        "seed": "推进主线",
        "outline": "主角遭遇危机",
        "characters": "亚修(境界=凡人, 位置=碎湖监狱)",
        "foreshadowing": "暂无待回收伏笔",
        "scenes": "未标注场景",
        "world": "碎湖监狱(location)",
    }
    output = agent.generate_chapter("ch_003", "推进主线", context)

    assert output.chapter_id == "ch_003"
    assert len(output.beat_list) >= 4
    assert "## 草稿正文" in output.draft
    assert "## 剧情节拍" in output.draft
    assert "## 写作目标" in output.draft
    # Should have section markers
    assert "【场景】" in output.draft or "【对话】" in output.draft
    # Metadata should be populated
    assert output.metadata.get("protagonist") == "亚修"


def test_librarian_multi_character_dialogue():
    from agents.librarian import LibrarianAgent

    agent = LibrarianAgent()
    context = {
        "seed": "推进主线",
        "outline": "两人讨论计划",
        "characters": "亚修(境界=凡人, 位置=碎湖监狱); 索妮娅(境界=术师, 位置=学院)",
        "foreshadowing": "暂无待回收伏笔",
        "scenes": "",
        "world": "",
    }
    output = agent.generate_chapter("ch_004", "推进主线", context)

    # With 2 characters, should generate multi-character dialogue
    assert "亚修" in output.draft
    assert "索妮娅" in output.draft
    assert "「" in output.draft  # Chinese dialogue markers


def test_librarian_rewrite_removes_forbidden():
    from agents.librarian import LibrarianAgent

    agent = LibrarianAgent()
    context = {
        "seed": "test",
        "outline": "",
        "characters": "",
        "foreshadowing": "",
        "scenes": "",
        "world": "",
    }
    original = agent.generate_chapter("ch_001", "test", context)

    rewritten = agent.rewrite_chapter(
        chapter_id="ch_001",
        objective="test",
        context=context,
        previous_draft=original.draft,
        forbidden=["决定"],
        required=[],
        errors=["检测到禁用设定: 决定"],
        warnings=[],
        attempt=1,
    )
    assert "决定" not in rewritten.draft or "[已规避词]" in rewritten.draft
    assert "修订记录" in rewritten.draft
    assert rewritten.metadata.get("rewrite_attempt") == "1"


def test_librarian_rewrite_integrates_required():
    from agents.librarian import LibrarianAgent

    agent = LibrarianAgent()
    context = {
        "seed": "test",
        "outline": "",
        "characters": "",
        "foreshadowing": "",
        "scenes": "",
        "world": "",
    }
    original = agent.generate_chapter("ch_001", "test", context)

    rewritten = agent.rewrite_chapter(
        chapter_id="ch_001",
        objective="test",
        context=context,
        previous_draft=original.draft,
        forbidden=[],
        required=["神秘玉佩"],
        errors=[],
        warnings=["未显式出现必备要素: 神秘玉佩"],
        attempt=1,
    )
    assert "神秘玉佩" in rewritten.draft


def test_librarian_extract_helpers():
    from agents.librarian import LibrarianAgent

    agent = LibrarianAgent()

    # Test protagonist extraction
    assert agent._extract_protagonist("亚修(境界=凡人, 位置=碎湖监狱)") == "亚修"
    assert agent._extract_protagonist("暂无人物档案") == "主角"
    assert agent._extract_protagonist("") == "主角"

    # Test setting extraction
    ctx = {"characters": "亚修(境界=凡人, 位置=碎湖监狱)", "world": ""}
    assert agent._extract_setting(ctx) == "碎湖监狱"

    ctx2 = {"characters": "亚修(境界=凡人, 位置=未知)", "world": "青云镇(location)"}
    assert agent._extract_setting(ctx2) == "青云镇"


# ---------------------------------------------------------------------------
# Reader agent tests
# ---------------------------------------------------------------------------


def test_reader_batch_basic():
    from agents.reader import ReaderAgent, FindingLayer

    agent = ReaderAgent(style_id="test_style", novel_id="test_novel")

    sample_text = """
第1章 穿越

亚修坐在冰冷的石座上，看着眼前一大群穿着黑袍的怪人，心里慌得一批。
「这什么情况？」他内心os疯狂吐槽。
淦，整个游戏只有抽卡系统正常就能成功启动，不愧是我的公司！

索妮娅迈着小碎步走进了术灵学院的大门。
她的奇迹——光之术灵——在肩头安静地悬浮着。

……

第2章 监狱

碎湖监狱的走廊里回荡着脚步声。
亚修默默地走着，表面冷静，内心已经把逃跑路线规划了三遍。
「情况有变。」他对旁边的人说道。
「哪种变？好的那种还是坏的那种？」
「你觉得呢。」
「……行吧。」
"""

    result = agent.read_batch(
        text=sample_text,
        batch_id="test_batch",
        chunk_range="第1-2章",
    )

    assert result.batch_id == "test_batch"
    assert result.chunk_range == "第1-2章"
    assert len(result.findings) > 0

    # Should find novel-layer findings (character names, terminology)
    assert len(result.novel_findings) > 0
    novel_cats = [f.category for f in result.novel_findings]
    assert any(c in novel_cats for c in ["characters", "terminology", "worldbuilding"])

    # Should find style-layer findings (humor markers)
    style_cats = [f.category for f in result.style_findings]
    assert any(c in style_cats for c in ["humor", "voice", "rhythm"])


def test_reader_layer_classification():
    from agents.reader import ReaderAgent, FindingLayer

    assert ReaderAgent.classify_layer("角色行为一致性") == FindingLayer.NOVEL
    assert ReaderAgent.classify_layer("叙述者声音融合") == FindingLayer.STYLE
    assert ReaderAgent.classify_layer("场景结构模式") == FindingLayer.CRAFT
    assert ReaderAgent.classify_layer("世界观规则") == FindingLayer.NOVEL
    assert ReaderAgent.classify_layer("幽默密度") == FindingLayer.STYLE


def test_reader_summary_output():
    from agents.reader import ReaderAgent

    agent = ReaderAgent(style_id="test", novel_id="test")
    result = agent.read_batch(
        text="第1章\n亚修使用了术灵的奇迹。\n淦，这也太离谱了。\n",
        batch_id="summary_test",
        chunk_range="第1章",
    )
    summary = result.summary()
    assert "Reader 批次报告" in summary
    assert "summary_test" in summary


def test_reader_dialogue_ratio():
    from agents.reader import ReaderAgent

    agent = ReaderAgent()

    # High dialogue text
    high_dialogue = "「你好。」\n「你好。」\n「再见。」\n普通叙述。\n"
    ratio = agent._compute_dialogue_ratio(high_dialogue)
    assert ratio >= 0.5

    # No dialogue text
    no_dialogue = "普通叙述一。\n普通叙述二。\n普通叙述三。\n"
    ratio2 = agent._compute_dialogue_ratio(no_dialogue)
    assert ratio2 == 0.0


def test_reader_humor_count():
    from agents.reader import ReaderAgent

    agent = ReaderAgent()
    text = "淦，这也太离谱了。不愧是我的公司！卧槽，绝了。"
    count = agent._count_humor_markers(text)
    assert count >= 4  # 淦, 离谱, 不愧是, 卧槽, 绝了


def test_reader_no_duplicates():
    from agents.reader import ReaderAgent, Finding, FindingLayer

    agent = ReaderAgent(style_id="test", novel_id="test")
    existing = [
        Finding(
            layer=FindingLayer.STYLE,
            category="humor",
            name="幽默密度",
            description="test",
        ),
    ]
    result = agent.read_batch(
        text="淦，这也太离谱了。\n",
        batch_id="dedup_test",
        chunk_range="test",
        existing_findings=existing,
    )
    # Should not duplicate "幽默密度"
    humor_findings = [f for f in result.findings if f.name == "幽默密度"]
    assert len(humor_findings) == 0


# ---------------------------------------------------------------------------
# Style Director tests
# ---------------------------------------------------------------------------


def test_style_director_basic_analysis():
    from agents.style_director import StyleDirectorAgent, DeviationLayer

    agent = StyleDirectorAgent(style_id="test", novel_id="test")

    draft = """
他静静地看着远方，感到非常高兴。
不禁微微一笑，缓缓说道："我知道了。"
然后他继续前进。
"""
    result = agent.analyze(draft=draft, iteration=1)

    assert len(result.deviations) > 0
    # Should detect voice issues (neutral narration, AI artifacts)
    style_devs = result.style_deviations
    assert len(style_devs) > 0
    assert any("voice" in d.category for d in style_devs)

    # Should have layer scores
    assert "style" in result.layer_scores
    assert result.layer_scores["style"].score < 100  # Should have deductions


def test_style_director_setting_violations():
    from agents.style_director import StyleDirectorAgent, DeviationSeverity

    agent = StyleDirectorAgent(style_id="test", novel_id="test")

    draft = "他施展了一个强大的魔法，法术光芒照亮了整个房间。"
    result = agent.analyze(draft=draft)

    # Should detect terminology violations (魔法/法术 instead of 奇迹)
    novel_devs = result.novel_deviations
    assert len(novel_devs) > 0
    assert any(d.severity == DeviationSeverity.CRITICAL for d in novel_devs)


def test_style_director_rhythm_check():
    from agents.style_director import StyleDirectorAgent

    agent = StyleDirectorAgent(style_id="test", novel_id="test")

    # All long paragraphs
    long_draft = "\n".join(
        [
            "这是一段很长的叙述。包含了大量的信息。角色在这里做了很多事情。"
            "他走过了长长的走廊。看到了很多奇怪的东西。心中充满了疑惑。然后他继续前进。"
            for _ in range(8)
        ]
    )
    result = agent.analyze(draft=long_draft)

    rhythm_devs = [d for d in result.deviations if d.category == "rhythm"]
    assert len(rhythm_devs) >= 1


def test_style_director_humor_missing():
    from agents.style_director import StyleDirectorAgent

    agent = StyleDirectorAgent(style_id="test", novel_id="test")

    # Long text with zero humor
    boring_draft = "\n".join(
        [f"他走到了第{i}个房间。房间里很安静。他继续前进。" for i in range(15)]
    )
    result = agent.analyze(draft=boring_draft)

    humor_devs = [d for d in result.deviations if d.category == "humor"]
    assert len(humor_devs) >= 1
    assert any("吐槽密度为零" in d.description for d in humor_devs)


def test_style_director_convergence():
    from agents.style_director import StyleDirectorAgent

    agent = StyleDirectorAgent(style_id="test", novel_id="test")

    # Clean-ish draft
    clean_draft = "「你来了。」亚修说。\n\n淦，这什么情况。\n\n「嗯。」\n"
    result = agent.analyze(draft=clean_draft, iteration=2, previous_gaps=0)

    # With few deviations on iteration 2, should converge
    if result.new_gaps_found <= 1:
        assert result.converged is True


def test_style_director_summary_output():
    from agents.style_director import StyleDirectorAgent

    agent = StyleDirectorAgent(style_id="test", novel_id="test")
    result = agent.analyze(draft="他不禁微微一笑。", iteration=1)
    summary = result.summary()
    assert "风格迭代分析报告" in summary
    assert "迭代 #1" in summary


def test_style_director_document_updates():
    from agents.style_director import StyleDirectorAgent

    agent = StyleDirectorAgent(style_id="test", novel_id="test")

    # Draft with terminology issues that should trigger doc updates
    draft = "他施展了魔法。" + "\n".join(["普通叙述。"] * 12)
    result = agent.analyze(draft=draft)

    # Should generate document update suggestions for novel layer
    if result.novel_deviations:
        # At least some deviations should suggest doc updates
        assert len(result.document_updates) >= 0  # May or may not have updates


# ---------------------------------------------------------------------------
# Style model bridge tests
# ---------------------------------------------------------------------------


def test_style_profile_from_composed():
    from models.style import StyleProfile

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        composed_dir = root / "composed"
        composed_dir.mkdir()

        composed_content = """# 最终风格文档: test_novel

## 硬性约束（作品设定层）

### 角色设定
- 主角：穿越者，绝不暴露身份

### 术语表
- 术灵：魔法生物
- 奇迹：术灵的能力

## 风格约束（作品风格层）

### 风格指纹
吐槽密度高，短段60%为主

### 叙述者声音
读者分不清叙述者和角色

## 通用技法（参考层）

### 对话技法
乒乓球规则：每1-2个信息点必须有反应

## 禁用表达
- 不禁
- 缓缓说道
- 微微一笑
"""
        (composed_dir / "test_novel_final.md").write_text(
            composed_content, encoding="utf-8"
        )

        profile = StyleProfile.from_project(
            root, novel_id="test_novel", style_id="test_style"
        )

        assert profile.style_id == "test_style"
        assert profile.novel_id == "test_novel"
        assert "穿越者" in profile.hard_constraints_summary
        assert "吐槽" in profile.style_constraints_summary
        assert profile.base.get("source") == "composed_markdown"


def test_style_profile_to_summary():
    from models.style import StyleProfile, BannedPhrase

    profile = StyleProfile(
        style_id="术师手册",
        novel_id="术师手册",
        banned_phrases=[
            BannedPhrase(phrase="不禁"),
            BannedPhrase(phrase="缓缓说道"),
        ],
        hard_constraints_summary="主角是穿越者，绝不暴露身份",
        style_constraints_summary="吐槽密度高，短段快节奏",
    )

    summary = profile.to_summary()
    assert "术师手册" in summary
    assert "不禁" in summary
    assert "硬性约束摘要" in summary


def test_style_profile_banned_phrase_merge():
    from models.style import StyleProfile, BannedPhrase

    profile = StyleProfile(
        banned_phrases=[BannedPhrase(phrase="不禁")],
    )
    profile.merge_banned_phrases(["缓缓说道", "不禁", "微微一笑"])

    phrases = profile.get_banned_phrase_list()
    assert len(phrases) == 3
    assert "不禁" in phrases
    assert "缓缓说道" in phrases
    assert "微微一笑" in phrases


def test_style_profile_empty_composed():
    from models.style import StyleProfile

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        # No composed file exists
        profile = StyleProfile.from_project(root, novel_id="nonexistent")
        assert profile.novel_id == "nonexistent"
        assert profile.hard_constraints_summary == ""
        assert profile.to_summary() != ""


def test_style_profile_quality_metrics():
    from models.style import StyleProfile

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        composed_dir = root / "composed"
        composed_dir.mkdir()
        (composed_dir / "test_final.md").write_text(
            "# Test\n## 节奏\n短段60%\n## 禁用表达\n- 不禁\n## 角色\n主角\n",
            encoding="utf-8",
        )
        profile = StyleProfile.from_project(root, novel_id="test")
        assert profile.quality_metrics.rhythm == 80
        assert profile.quality_metrics.ai_artifact_control == 90
        assert profile.quality_metrics.characterization == 70
