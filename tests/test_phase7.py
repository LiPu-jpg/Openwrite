"""Phase 7 测试 — 新数据模型、渐进压缩器、管线V2、初始化器、新API端点。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

import pytest
import yaml
from fastapi.testclient import TestClient

from tools.models.outline import (
    ArcOutline,
    ChapterOutline,
    MasterOutline,
    OutlineHierarchy,
    SectionOutline,
)
from tools.models.character import CharacterCard, CharacterStatic, TextCharacterProfile
from tools.models.context_package import (
    ArcCompression,
    GenerationContext,
    ReviewContext,
    ReviewResult,
    SectionCompression,
    StylistContext,
)
from tools.utils.progressive_compressor import ProgressiveCompressor
from tools.agents.pipeline_v2 import PipelineResult, PipelineSimulatorV2, PipelineStage
from tools.agents.initializer import InitResult, NovelInitializer
from tools.web import create_app


# ── 公共 fixtures ──────────────────────────────────────────────────


def _make_project(tmp_path: Path, novel_id: str = "test_novel") -> Path:
    """创建最小项目目录结构。"""
    base = tmp_path / "data" / "novels" / novel_id
    for sub in [
        "outline/chapters",
        "characters/cards",
        "characters/profiles",
        "characters/timeline/logs",
        "characters/text_profiles",
        "foreshadowing/logs",
        "world",
        "style",
        "manuscript",
        "manuscript/drafts",
        "compression",
    ]:
        (base / sub).mkdir(parents=True, exist_ok=True)
    (tmp_path / "logs" / "pipeline_v2").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _make_hierarchy(novel_id: str = "test_novel") -> OutlineHierarchy:
    """创建测试用四级大纲层级。"""
    master = MasterOutline(
        novel_id=novel_id,
        title="测试小说",
        core_theme="成长",
        ending_direction="大团圆",
        key_turns=["转折一", "转折二"],
        arc_ids=["arc_001"],
    )
    arc = ArcOutline(
        arc_id="arc_001",
        novel_id=novel_id,
        title="第一篇",
        order=0,
        main_conflict="主角觉醒",
        section_ids=["sec_001"],
    )
    section = SectionOutline(
        section_id="sec_001",
        arc_id="arc_001",
        title="第一节",
        order=0,
        plot_summary="主角初入江湖",
        chapter_ids=["ch_001", "ch_002"],
    )
    ch1 = ChapterOutline(
        chapter_id="ch_001",
        section_id="sec_001",
        title="第一章",
        order=0,
        goals=["介绍主角", "建立世界观"],
        target_words=6000,
    )
    ch2 = ChapterOutline(
        chapter_id="ch_002",
        section_id="sec_001",
        title="第二章",
        order=1,
        goals=["推进冲突"],
        target_words=6000,
    )
    return OutlineHierarchy(
        master=master,
        arcs={"arc_001": arc},
        sections={"sec_001": section},
        chapters={"ch_001": ch1, "ch_002": ch2},
    )


@pytest.fixture()
def project_dir(tmp_path: Path) -> Path:
    return _make_project(tmp_path)


@pytest.fixture()
def hierarchy() -> OutlineHierarchy:
    return _make_hierarchy()


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    """创建测试用 FastAPI 客户端。"""
    proj = _make_project(tmp_path)
    novel_id = "test_novel"
    app = create_app(project_dir=proj, novel_id=novel_id)
    return TestClient(app)


# ══════════════════════════════════════════════════════════════════════
# 1. 大纲模型测试
# ══════════════════════════════════════════════════════════════════════


class TestOutlineModels:
    """四级大纲层级模型测试。"""

    def test_master_outline_creation(self):
        m = MasterOutline(novel_id="n1", title="书名", core_theme="主题")
        assert m.novel_id == "n1"
        assert m.title == "书名"
        assert m.arc_ids == []

    def test_arc_outline_creation(self):
        a = ArcOutline(arc_id="arc_001", novel_id="n1", title="第一篇", order=0)
        assert a.arc_id == "arc_001"
        assert a.status == "TODO"
        assert a.section_ids == []

    def test_section_outline_creation(self):
        s = SectionOutline(section_id="sec_001", arc_id="arc_001", title="第一节")
        assert s.section_id == "sec_001"
        assert s.chapter_ids == []
        assert s.status == "TODO"

    def test_chapter_outline_creation(self):
        c = ChapterOutline(chapter_id="ch_001", section_id="sec_001", title="第一章")
        assert c.chapter_id == "ch_001"
        assert c.target_words == 6000
        assert c.status == "TODO"

    def test_chapter_outline_target_words_bounds(self):
        c = ChapterOutline(chapter_id="ch_001", target_words=3000)
        assert c.target_words == 3000
        with pytest.raises(Exception):
            ChapterOutline(chapter_id="ch_001", target_words=2000)
        with pytest.raises(Exception):
            ChapterOutline(chapter_id="ch_001", target_words=15000)

    def test_hierarchy_get_chapter(self, hierarchy: OutlineHierarchy):
        ch = hierarchy.get_chapter("ch_001")
        assert ch is not None
        assert ch.title == "第一章"
        assert hierarchy.get_chapter("nonexistent") is None

    def test_hierarchy_get_section(self, hierarchy: OutlineHierarchy):
        sec = hierarchy.get_section("sec_001")
        assert sec is not None
        assert sec.title == "第一节"

    def test_hierarchy_get_arc(self, hierarchy: OutlineHierarchy):
        arc = hierarchy.get_arc("arc_001")
        assert arc is not None
        assert arc.title == "第一篇"

    def test_hierarchy_get_chapters_for_section(self, hierarchy: OutlineHierarchy):
        chapters = hierarchy.get_chapters_for_section("sec_001")
        assert len(chapters) == 2
        assert chapters[0].chapter_id == "ch_001"
        assert chapters[1].chapter_id == "ch_002"

    def test_hierarchy_get_sections_for_arc(self, hierarchy: OutlineHierarchy):
        sections = hierarchy.get_sections_for_arc("arc_001")
        assert len(sections) == 1
        assert sections[0].section_id == "sec_001"

    def test_hierarchy_get_all_arcs_ordered(self, hierarchy: OutlineHierarchy):
        arcs = hierarchy.get_all_arcs_ordered()
        assert len(arcs) == 1
        assert arcs[0].arc_id == "arc_001"

    def test_hierarchy_empty_lookups(self, hierarchy: OutlineHierarchy):
        assert hierarchy.get_chapters_for_section("nonexistent") == []
        assert hierarchy.get_sections_for_arc("nonexistent") == []


# ══════════════════════════════════════════════════════════════════════
# 2. TextCharacterProfile 测试
# ══════════════════════════════════════════════════════════════════════


class TestTextCharacterProfile:
    """文本优先人物档案测试。"""

    def test_creation(self):
        p = TextCharacterProfile(id="char_001", name="李逍遥", char_type="主角")
        assert p.name == "李逍遥"
        assert p.char_type == "主角"
        assert p.appearance == ""

    def test_to_context_text(self):
        p = TextCharacterProfile(
            id="char_001",
            name="李逍遥",
            char_type="主角",
            appearance="身穿白衣",
            personality_and_voice="豪爽直率",
            skills_and_abilities="剑法高超",
        )
        text = p.to_context_text()
        assert "李逍遥" in text
        assert "主角" in text
        assert "身穿白衣" in text
        assert "豪爽直率" in text
        assert "剑法高超" in text

    def test_to_context_text_truncation(self):
        p = TextCharacterProfile(
            id="char_001",
            name="李逍遥",
            char_type="主角",
            appearance="身穿白衣" * 100,
        )
        text = p.to_context_text(max_chars=50)
        assert len(text) <= 51  # 50 + ellipsis
        assert text.endswith("\u2026")

    def test_to_context_text_no_truncation_when_short(self):
        p = TextCharacterProfile(id="c1", name="A", char_type="配角")
        text = p.to_context_text(max_chars=500)
        assert not text.endswith("\u2026")

    def test_from_legacy_card(self):
        static = CharacterStatic(
            id="char_lyr", name="\u6797\u6708\u5982", tier="\u91cd\u8981\u914d\u89d2",
            appearance="\u7ea2\u8863\u5973\u5b50",
            personality=["\u6cfc\u8fa3", "\u91cd\u60c5\u4e49"],
            faction="\u5357\u8bcf\u56fd",
        )
        card = CharacterCard(static=static)
        profile = TextCharacterProfile.from_legacy_card(card)
        assert profile.name == "林月如"
        assert profile.char_type == "重要配角"
        assert "红衣女子" in profile.appearance
        assert "泼辣" in profile.personality_and_voice


# ══════════════════════════════════════════════════════════════════════
# 3. Context Package 模型测试
# ══════════════════════════════════════════════════════════════════════


class TestContextPackageModels:
    """上下文包模型测试。"""

    def test_section_compression(self):
        sc = SectionCompression(
            section_id="sec_001",
            arc_id="arc_001",
            compressed_text="摘要文字",
            key_events=["事件一"],
            word_count=5000,
        )
        assert sc.section_id == "sec_001"
        assert sc.word_count == 5000

    def test_arc_compression_build_merged(self):
        sc1 = SectionCompression(
            section_id="s1", compressed_text="节一摘要", word_count=3000
        )
        sc2 = SectionCompression(
            section_id="s2", compressed_text="节二摘要", word_count=4000
        )
        ac = ArcCompression(
            arc_id="arc_001",
            previous_arc_summary="前篇摘要",
            section_summaries=[sc1, sc2],
            total_word_count=7000,
        )
        merged = ac.build_merged()
        assert "前篇摘要" in merged
        assert "节一摘要" in merged
        assert "节二摘要" in merged

    def test_arc_compression_build_merged_no_previous(self):
        sc = SectionCompression(section_id="s1", compressed_text="摘要", word_count=100)
        ac = ArcCompression(arc_id="a1", section_summaries=[sc])
        merged = ac.build_merged()
        assert merged == "摘要"

    def test_generation_context_to_prompt_sections(self):
        ctx = GenerationContext(
            novel_id="n1",
            chapter_id="ch_001",
            writing_prompt="写一章",
            recent_text="上文内容",
            current_arc_plan="本篇大纲",
            character_profiles="人物资料",
            chapter_goals=["目标一", "目标二"],
        )
        sections = ctx.to_prompt_sections()
        assert "写作指令" in sections
        assert "上文" in sections
        assert "本篇大纲" in sections
        assert "人物资料" in sections
        assert "本章目标" in sections
        assert "目标一" in sections["本章目标"]

    def test_generation_context_empty_fields_excluded(self):
        ctx = GenerationContext(novel_id="n1", chapter_id="ch_001")
        sections = ctx.to_prompt_sections()
        assert len(sections) == 0

    def test_generation_context_estimate_tokens(self):
        ctx = GenerationContext(
            novel_id="n1",
            chapter_id="ch_001",
            writing_prompt="写" * 150,
        )
        tokens = ctx.estimate_token_count()
        assert tokens > 0
        assert tokens == int(150 / 1.5)

    def test_stylist_context_to_prompt_sections(self):
        ctx = StylistContext(
            novel_id="n1",
            chapter_id="ch_001",
            draft_text="草稿内容",
            recent_text="上文",
            character_voice="人物语气",
            style_document="文风文档",
        )
        sections = ctx.to_prompt_sections()
        assert "上文" in sections
        assert "人物语气" in sections
        assert "文风文档" in sections
        assert "待润色草稿" in sections

    def test_review_context_creation(self):
        ctx = ReviewContext(
            novel_id="n1",
            chapter_id="ch_001",
            draft_text="草稿",
            recent_text="上文",
        )
        assert ctx.draft_text == "草稿"

    def test_review_result_defaults(self):
        r = ReviewResult()
        assert r.passed is True
        assert r.severity == "none"
        assert r.errors == []
        assert r.warnings == []

    def test_review_result_with_errors(self):
        r = ReviewResult(
            passed=False,
            severity="severe",
            errors=["逻辑错误"],
            warnings=["轻微问题"],
        )
        assert not r.passed
        assert r.severity == "severe"


# ══════════════════════════════════════════════════════════════════════
# 4. ProgressiveCompressor 测试
# ══════════════════════════════════════════════════════════════════════


class TestProgressiveCompressor:
    """渐进式上下文压缩器测试。"""

    def test_compress_section_short_text(self, project_dir: Path):
        pc = ProgressiveCompressor(project_dir, "test_novel")
        result = pc.compress_section("sec_001", "arc_001", "短文本内容")
        assert result.section_id == "sec_001"
        assert result.compressed_text == "短文本内容"
        assert result.word_count == len("短文本内容")

    def test_compress_section_long_text(self, project_dir: Path):
        pc = ProgressiveCompressor(project_dir, "test_novel")
        long_text = "\n".join(
            [f"第{i}段。这是一段较长的文字内容，用于测试压缩功能。" for i in range(50)]
        )
        result = pc.compress_section("sec_001", "arc_001", long_text)
        assert result.section_id == "sec_001"
        assert len(result.compressed_text) <= len(long_text)
        assert result.word_count == len(long_text)

    def test_compress_section_saves_file(self, project_dir: Path):
        pc = ProgressiveCompressor(project_dir, "test_novel")
        pc.compress_section("sec_001", "arc_001", "测试内容")
        comp_dir = project_dir / "data" / "novels" / "test_novel" / "compression" / "sections"
        files = list(comp_dir.glob("*.yaml"))
        assert len(files) == 1

    def test_rule_compress_preserves_key_paragraphs(self, project_dir: Path):
        pc = ProgressiveCompressor(project_dir, "test_novel")
        text = "开头段落，介绍背景。\n普通段落内容。\n然而事情发生了转折。\n结尾段落。"
        result = pc._rule_compress_text(text, 60)
        # 首段和含关键词的段落应被保留
        assert "开头段落" in result or "转折" in result

    def test_compress_arc(self, project_dir: Path):
        pc = ProgressiveCompressor(project_dir, "test_novel")
        # 先压缩一个节
        pc.compress_section("sec_001", "arc_001", "节一的完整内容，包含很多情节。")
        # 再压缩篇
        result = pc.compress_arc("arc_001")
        assert result.arc_id == "arc_001"
        assert result.merged_summary != ""

    def test_build_generation_context(
        self, project_dir: Path, hierarchy: OutlineHierarchy
    ):
        pc = ProgressiveCompressor(project_dir, "test_novel")
        chapter = hierarchy.get_chapter("ch_001")
        ctx = pc.build_generation_context(
            chapter=chapter,
            hierarchy=hierarchy,
            manuscript_text="这是前文内容" * 100,
            writing_prompt="写一章精彩的",
        )
        assert isinstance(ctx, GenerationContext)
        assert ctx.chapter_id == "ch_001"
        assert ctx.writing_prompt == "写一章精彩的"

    def test_build_generation_context_with_characters(
        self, project_dir: Path, hierarchy: OutlineHierarchy
    ):
        pc = ProgressiveCompressor(project_dir, "test_novel")
        chapter = hierarchy.get_chapter("ch_001")
        chars = [
            TextCharacterProfile(
                id="c1", name="主角", char_type="主角", appearance="高大"
            ),
        ]
        ctx = pc.build_generation_context(
            chapter=chapter,
            hierarchy=hierarchy,
            characters=chars,
        )
        assert "主角" in ctx.character_profiles

    def test_extract_recent_text(self, project_dir: Path):
        pc = ProgressiveCompressor(project_dir, "test_novel")
        text = "字" * 2000
        recent = pc._extract_recent_text(text)
        assert len(recent) >= pc.recent_text_min
        assert len(recent) <= pc.recent_text_max


# ══════════════════════════════════════════════════════════════════════
# 5. PipelineSimulatorV2 测试
# ══════════════════════════════════════════════════════════════════════


class TestPipelineV2:
    """管线V2模拟器测试。"""

    def test_pipeline_stage_defaults(self):
        s = PipelineStage(name="director")
        assert s.status == "pending"
        assert s.data == {}

    def test_pipeline_result_properties(self):
        r = PipelineResult(novel_id="n1", chapter_id="ch_001")
        assert not r.passed  # review is None
        assert not r.has_severe_errors

    def test_pipeline_result_with_review(self):
        review = ReviewResult(passed=True, severity="none")
        r = PipelineResult(novel_id="n1", chapter_id="ch_001", review=review)
        assert r.passed
        assert not r.has_severe_errors

    def test_pipeline_result_severe(self):
        review = ReviewResult(passed=False, severity="severe", errors=["错误"])
        r = PipelineResult(novel_id="n1", chapter_id="ch_001", review=review)
        assert not r.passed
        assert r.has_severe_errors

    def test_assemble_context(self, project_dir: Path, hierarchy: OutlineHierarchy):
        sim = PipelineSimulatorV2(project_dir=project_dir, novel_id="test_novel")
        chapter = hierarchy.get_chapter("ch_001")
        ctx = sim.assemble_context(chapter, hierarchy, writing_prompt="测试")
        assert isinstance(ctx, GenerationContext)
        assert ctx.chapter_id == "ch_001"
        assert ctx.writing_prompt == "测试"

    def test_generate_chapter(self, project_dir: Path, hierarchy: OutlineHierarchy):
        sim = PipelineSimulatorV2(project_dir=project_dir, novel_id="test_novel")
        chapter = hierarchy.get_chapter("ch_001")
        ctx = sim.assemble_context(chapter, hierarchy)
        draft = sim.generate_chapter(ctx)
        assert isinstance(draft, str)
        assert len(draft) > 0

    def test_review_draft(self, project_dir: Path, hierarchy: OutlineHierarchy):
        sim = PipelineSimulatorV2(project_dir=project_dir, novel_id="test_novel")
        chapter = hierarchy.get_chapter("ch_001")
        ctx = sim.assemble_context(chapter, hierarchy)
        review = sim.review_draft("这是一段草稿内容。", ctx)
        assert isinstance(review, ReviewResult)
        assert review.severity in ("none", "mild", "severe")

    def test_run_pipeline_full(self, project_dir: Path, hierarchy: OutlineHierarchy):
        sim = PipelineSimulatorV2(project_dir=project_dir, novel_id="test_novel")
        chapter = hierarchy.get_chapter("ch_001")
        result = sim.run_pipeline(
            chapter=chapter,
            hierarchy=hierarchy,
            writing_prompt="生成测试章节",
            auto_approve=True,
        )
        assert isinstance(result, PipelineResult)
        assert result.novel_id == "test_novel"
        assert result.chapter_id == "ch_001"
        assert len(result.draft_text) > 0
        assert len(result.stages) >= 3  # director, writer, reviewer

    def test_run_pipeline_saves_draft(
        self, project_dir: Path, hierarchy: OutlineHierarchy
    ):
        sim = PipelineSimulatorV2(project_dir=project_dir, novel_id="test_novel")
        chapter = hierarchy.get_chapter("ch_001")
        sim.run_pipeline(chapter=chapter, hierarchy=hierarchy, auto_approve=True)
        draft_file = (
            project_dir
            / "data"
            / "novels"
            / "test_novel"
            / "manuscript"
            / "drafts"
            / "ch_001_draft.md"
        )
        assert draft_file.exists()

    def test_run_pipeline_with_stylist(
        self, project_dir: Path, hierarchy: OutlineHierarchy
    ):
        sim = PipelineSimulatorV2(project_dir=project_dir, novel_id="test_novel")
        chapter = hierarchy.get_chapter("ch_001")
        result = sim.run_pipeline(
            chapter=chapter,
            hierarchy=hierarchy,
            auto_approve=True,
            use_stylist=True,
        )
        # Stylist stage should be present
        stage_names = [s.name for s in result.stages]
        assert "stylist" in stage_names


# ══════════════════════════════════════════════════════════════════════
# 6. NovelInitializer 测试
# ══════════════════════════════════════════════════════════════════════


class TestNovelInitializer:
    """作品初始化器测试。"""

    def test_create_skeleton_hierarchy(self, project_dir: Path):
        init = NovelInitializer(project_dir=project_dir, novel_id="test_novel")
        result = init.initialize(
            title="\u6d4b\u8bd5\u5c0f\u8bf4",
            core_theme="\u6210\u957f\u5192\u9669",
        )
        assert isinstance(result, InitResult)
        assert result.success
        assert result.master_outline is not None
        assert result.master_outline.title == "\u6d4b\u8bd5\u5c0f\u8bf4"

    def test_init_creates_hierarchy_file(self, project_dir: Path):
        init = NovelInitializer(project_dir=project_dir, novel_id="test_novel")
        init.initialize(title="\u6d4b\u8bd5", core_theme="\u6d4b\u8bd5\u4e3b\u9898")
        hierarchy_file = (
            project_dir
            / "data"
            / "novels"
            / "test_novel"
            / "outline"
            / "hierarchy.yaml"
        )
        assert hierarchy_file.exists()

    def test_load_hierarchy(self, project_dir: Path):
        init = NovelInitializer(project_dir=project_dir, novel_id="test_novel")
        init.initialize(title="\u6d4b\u8bd5", core_theme="\u6d4b\u8bd5\u4e3b\u9898")
        h = init.load_hierarchy()
        assert h is not None
        assert isinstance(h, OutlineHierarchy)
        assert h.master.title == "\u6d4b\u8bd5"

    def test_load_hierarchy_nonexistent(self, project_dir: Path):
        init = NovelInitializer(project_dir=project_dir, novel_id="test_novel")
        h = init.load_hierarchy()
        assert h is None


# ══════════════════════════════════════════════════════════════════════
# 7. 新 Web API 端点测试
# ══════════════════════════════════════════════════════════════════════


class TestSettingsPage:
    """设置页面测试。"""

    def test_settings_page_renders(self, client: TestClient):
        resp = client.get("/settings")
        assert resp.status_code == 200
        assert "LLM" in resp.text or "设置" in resp.text


class TestLLMSettingsAPI:
    """LLM 配置 API 测试。"""

    def test_get_llm_settings(self, client: TestClient):
        resp = client.get("/api/settings/llm")
        assert resp.status_code == 200
        data = resp.json()
        assert "enabled" in data

    def test_put_llm_settings(self, client: TestClient):
        payload = {
            "enabled": True,
            "retry_count": 3,
            "retry_delay": 2.0,
            "default_route": {"primary": {"model": "test-model"}},
            "routes": {},
        }
        resp = client.put("/api/settings/llm", json=payload)
        assert resp.status_code == 200


class TestTextCharactersAPI:
    """文本人物档案 API 测试。"""

    def test_get_characters_empty(self, client: TestClient):
        resp = client.get("/api/v2/characters")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_create_and_get_character(self, client: TestClient):
        payload = {
            "id": "char_001",
            "name": "李逍遥",
            "char_type": "主角",
            "appearance": "白衣少年",
            "personality_and_voice": "豪爽",
        }
        resp = client.post("/api/v2/characters", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "李逍遥"

        # 验证列表
        resp2 = client.get("/api/v2/characters")
        assert resp2.status_code == 200
        chars = resp2.json()
        assert len(chars) == 1
        assert chars[0]["name"] == "李逍遥"

    def test_delete_character(self, client: TestClient):
        # \u5148\u521b\u5efa\u2014\u2014API\u4f1a\u751f\u6210 char_id = f"char_{name}"
        client.post(
            "/api/v2/characters",
            json={
                "name": "\u5f85\u5220\u9664",
                "char_type": "\u914d\u89d2",
            },
        )
        # char_id = "char_\u5f85\u5220\u9664"
        resp = client.delete("/api/v2/characters/char_\u5f85\u5220\u9664")
        assert resp.status_code == 200

        # \u9a8c\u8bc1\u5df2\u5220\u9664
        resp2 = client.get("/api/v2/characters")
        chars = resp2.json()
        assert len(chars) == 0


class TestOutlineHierarchyAPI:
    """大纲层级 API 测试。"""

    def test_get_hierarchy_empty(self, client: TestClient):
        resp = client.get("/api/outline/hierarchy")
        # 没有初始化时应返回404或空
        assert resp.status_code in (200, 404)

    def test_get_master_empty(self, client: TestClient):
        resp = client.get("/api/outline/master")
        assert resp.status_code in (200, 404)


class TestPipelineV2API:
    """管线V2 API 测试。"""

    def test_start_pipeline_no_hierarchy(self, client: TestClient):
        """没有初始化大纲时应返回404。"""
        resp = client.post(
            "/api/v2/pipeline/start",
            json={
                "chapter_id": "ch_001",
                "writing_prompt": "测试",
            },
        )
        assert resp.status_code == 404

    def test_pipeline_status_not_found(self, client: TestClient):
        resp = client.get("/api/v2/pipeline/status/nonexistent")
        assert resp.status_code == 404
