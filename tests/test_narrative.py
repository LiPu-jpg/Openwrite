"""Tests for Phase 6C — 叙事线可视化系统。

覆盖：
- NarrativeTimeline 数据模型
- NarrativeTimelineManager 持久化 + 聚合
- HTML 渲染器
- Simulator 叙事上下文注入
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

import pytest
import yaml

from tools.models.narrative import (
    Link,
    LinkType,
    NarrativeThread,
    NarrativeTimeline,
    ThreadEvent,
)


# ---------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------


def _make_thread(
    tid: str = "thread_a", name: str = "角色A", chapters: int = 3
) -> NarrativeThread:
    events = [
        ThreadEvent(
            chapter_id=f"ch_{str(i + 1).zfill(3)}",
            label=f"事件{i + 1}",
            tension=min(i + 3, 10),
            tags=["test"],
        )
        for i in range(chapters)
    ]
    return NarrativeThread(id=tid, name=name, color="#FF6B6B", events=events)


def _make_timeline() -> NarrativeTimeline:
    t1 = _make_thread("thread_a", "李逍遥", 4)
    t2 = _make_thread("thread_b", "赵灵儿", 3)
    links = [
        Link(
            source_thread="thread_a",
            source_chapter="ch_002",
            target_thread="thread_b",
            target_chapter="ch_002",
            link_type=LinkType.CONVERGE,
            label="仙灵岛相遇",
        ),
        Link(
            source_thread="thread_a",
            source_chapter="ch_001",
            target_thread="thread_a",
            target_chapter="ch_003",
            link_type=LinkType.FORESHADOW,
            label="酒剑仙伏笔",
            style="dashed",
        ),
        Link(
            source_thread="thread_b",
            source_chapter="ch_003",
            target_thread="thread_a",
            target_chapter="ch_004",
            link_type=LinkType.JUMP,
            label="穿越跳转",
        ),
    ]
    return NarrativeTimeline(
        novel_id="test_novel",
        title="测试小说",
        chapters=["ch_001", "ch_002", "ch_003", "ch_004"],
        threads=[t1, t2],
        links=links,
    )


# ---------------------------------------------------------------
# 数据模型测试
# ---------------------------------------------------------------


class TestNarrativeModels:
    def test_thread_event_defaults(self):
        e = ThreadEvent(chapter_id="ch_001", label="测试")
        assert e.tension == 5
        assert e.tags == []
        assert e.detail == ""

    def test_thread_event_tension_bounds(self):
        with pytest.raises(Exception):
            ThreadEvent(chapter_id="ch_001", label="x", tension=0)
        with pytest.raises(Exception):
            ThreadEvent(chapter_id="ch_001", label="x", tension=11)

    def test_thread_chapter_ids(self):
        t = _make_thread(chapters=4)
        ids = t.chapter_ids()
        assert ids == ["ch_001", "ch_002", "ch_003", "ch_004"]

    def test_thread_chapter_ids_dedup(self):
        t = NarrativeThread(
            id="t",
            name="t",
            events=[
                ThreadEvent(chapter_id="ch_001", label="a"),
                ThreadEvent(chapter_id="ch_001", label="b"),
                ThreadEvent(chapter_id="ch_002", label="c"),
            ],
        )
        assert t.chapter_ids() == ["ch_001", "ch_002"]

    def test_link_types(self):
        assert LinkType.CONVERGE.value == "converge"
        assert LinkType.FORESHADOW.value == "foreshadow"
        assert len(LinkType) == 5

    def test_timeline_get_thread(self):
        tl = _make_timeline()
        assert tl.get_thread("thread_a") is not None
        assert tl.get_thread("thread_a").name == "李逍遥"
        assert tl.get_thread("nonexistent") is None

    def test_timeline_threads_at_chapter(self):
        tl = _make_timeline()
        at_ch2 = tl.threads_at_chapter("ch_002")
        names = {t.name for t in at_ch2}
        assert "李逍遥" in names
        assert "赵灵儿" in names

    def test_timeline_links_at_chapter(self):
        tl = _make_timeline()
        links = tl.links_at_chapter("ch_002")
        assert len(links) == 1
        assert links[0].link_type == LinkType.CONVERGE

    def test_timeline_active_foreshadowings(self):
        tl = _make_timeline()
        # ch_003 is in chapters, so the foreshadow link is resolved
        active = tl.active_foreshadowings()
        assert len(active) == 0

    def test_timeline_active_foreshadowings_unresolved(self):
        tl = _make_timeline()
        tl.links.append(
            Link(
                source_thread="thread_a",
                source_chapter="ch_001",
                target_thread="thread_b",
                target_chapter="",
                link_type=LinkType.FORESHADOW,
                label="未回收",
            )
        )
        active = tl.active_foreshadowings()
        assert len(active) == 1
        assert active[0].label == "未回收"


# ---------------------------------------------------------------
# AI 上下文导出测试
# ---------------------------------------------------------------


class TestAIContext:
    def test_to_ai_context_structure(self):
        tl = _make_timeline()
        ctx = tl.to_ai_context("ch_002")
        assert ctx["chapter_id"] == "ch_002"
        assert len(ctx["active_threads"]) == 2
        assert len(ctx["convergences"]) == 1
        assert ctx["convergences"][0]["label"] == "仙灵岛相遇"

    def test_to_ai_context_empty_chapter(self):
        tl = _make_timeline()
        ctx = tl.to_ai_context("ch_999")
        assert ctx["active_threads"] == []
        assert ctx["convergences"] == []

    def test_to_ai_context_foreshadow_refs(self):
        tl = _make_timeline()
        ctx = tl.to_ai_context("ch_001")
        refs = ctx["foreshadowing_refs"]
        assert len(refs) == 1
        assert "酒剑仙" in refs[0]["id"]

    def test_to_ai_context_serializable(self):
        tl = _make_timeline()
        ctx = tl.to_ai_context("ch_002")
        # Must be JSON-serializable
        s = json.dumps(ctx, ensure_ascii=False)
        assert "仙灵岛相遇" in s


# ---------------------------------------------------------------
# Manager 持久化测试
# ---------------------------------------------------------------


class TestTimelineManager:
    def test_save_and_load(self, tmp_path: Path):
        from tools.narrative_timeline_manager import NarrativeTimelineManager

        mgr = NarrativeTimelineManager(project_dir=tmp_path, novel_id="test")
        tl = _make_timeline()
        mgr.save(tl)
        assert mgr.timeline_file.exists()

        loaded = mgr.load()
        assert loaded.novel_id == "test_novel"
        assert len(loaded.threads) == 2
        assert len(loaded.links) == 3

    def test_load_empty(self, tmp_path: Path):
        from tools.narrative_timeline_manager import NarrativeTimelineManager

        mgr = NarrativeTimelineManager(project_dir=tmp_path, novel_id="empty")
        tl = mgr.load()
        assert tl.novel_id == "empty"
        assert tl.threads == []

    def test_add_thread(self, tmp_path: Path):
        from tools.narrative_timeline_manager import NarrativeTimelineManager

        mgr = NarrativeTimelineManager(project_dir=tmp_path, novel_id="test")
        tl = NarrativeTimeline(novel_id="test")
        new_thread = NarrativeThread(id="thread_c", name="新角色")
        mgr.add_thread(tl, new_thread)
        assert len(tl.threads) == 1
        assert tl.threads[0].color != ""  # auto-assigned

    def test_add_thread_duplicate(self, tmp_path: Path):
        from tools.narrative_timeline_manager import NarrativeTimelineManager

        mgr = NarrativeTimelineManager(project_dir=tmp_path, novel_id="test")
        tl = _make_timeline()
        with pytest.raises(ValueError, match="已存在"):
            mgr.add_thread(tl, NarrativeThread(id="thread_a", name="dup"))

    def test_add_event_sorted(self, tmp_path: Path):
        from tools.narrative_timeline_manager import NarrativeTimelineManager

        mgr = NarrativeTimelineManager(project_dir=tmp_path, novel_id="test")
        tl = NarrativeTimeline(
            novel_id="test",
            threads=[
                NarrativeThread(
                    id="t1",
                    name="t1",
                    events=[
                        ThreadEvent(chapter_id="ch_001", label="first"),
                        ThreadEvent(chapter_id="ch_003", label="third"),
                    ],
                )
            ],
        )
        mgr.add_event(tl, "t1", ThreadEvent(chapter_id="ch_002", label="second"))
        labels = [e.label for e in tl.threads[0].events]
        assert labels == ["first", "second", "third"]

    def test_add_event_nonexistent_thread(self, tmp_path: Path):
        from tools.narrative_timeline_manager import NarrativeTimelineManager

        mgr = NarrativeTimelineManager(project_dir=tmp_path, novel_id="test")
        tl = NarrativeTimeline(novel_id="test")
        with pytest.raises(ValueError, match="不存在"):
            mgr.add_event(tl, "nope", ThreadEvent(chapter_id="ch_001", label="x"))

    def test_add_link(self, tmp_path: Path):
        from tools.narrative_timeline_manager import NarrativeTimelineManager

        mgr = NarrativeTimelineManager(project_dir=tmp_path, novel_id="test")
        tl = NarrativeTimeline(novel_id="test")
        lk = Link(
            source_thread="a",
            source_chapter="ch_001",
            target_thread="b",
            target_chapter="ch_002",
            link_type=LinkType.REFERENCE,
            label="test",
        )
        mgr.add_link(tl, lk)
        assert len(tl.links) == 1


# ---------------------------------------------------------------
# HTML 渲染器测试
# ---------------------------------------------------------------


class TestHTMLRenderer:
    def test_render_html_string(self):
        from tools.narrative_renderer import render_html

        tl = _make_timeline()
        html = render_html(tl)
        assert "<!DOCTYPE html>" in html
        assert "d3.v7.min.js" in html
        assert "测试小说" in html
        assert "李逍遥" in html
        assert "thread_a" in html

    def test_render_html_to_file(self, tmp_path: Path):
        from tools.narrative_renderer import render_html

        tl = _make_timeline()
        out = tmp_path / "output" / "timeline.html"
        render_html(tl, output_path=out)
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "赵灵儿" in content

    def test_render_html_contains_links(self):
        from tools.narrative_renderer import render_html

        tl = _make_timeline()
        html = render_html(tl)
        assert "converge" in html
        assert "foreshadow" in html
        assert "jump" in html

    def test_render_html_empty_timeline(self):
        from tools.narrative_renderer import render_html

        tl = NarrativeTimeline(novel_id="empty")
        html = render_html(tl)
        assert "<!DOCTYPE html>" in html


# ---------------------------------------------------------------
# Simulator 叙事上下文注入测试
# ---------------------------------------------------------------


class TestSimulatorNarrativeContext:
    def test_narrative_context_empty(self, tmp_path: Path):
        """无 timeline 文件时返回空字符串。"""
        from tools.agents.simulator import AgentSimulator

        sim = AgentSimulator(project_dir=tmp_path, novel_id="test")
        result = sim._narrative_context("ch_001")
        assert result == ""

    def test_narrative_context_with_data(self, tmp_path: Path):
        """有 timeline 数据时返回 JSON 字符串。"""
        from tools.narrative_timeline_manager import NarrativeTimelineManager
        from tools.agents.simulator import AgentSimulator

        # 先构建并保存 timeline
        mgr = NarrativeTimelineManager(project_dir=tmp_path, novel_id="test")
        tl = _make_timeline()
        tl.novel_id = "test"
        mgr.save(tl)

        # 创建必要的项目目录结构
        (tmp_path / "data" / "novels" / "test" / "outline" / "chapters").mkdir(
            parents=True, exist_ok=True
        )
        (tmp_path / "data" / "novels" / "test" / "characters" / "cards").mkdir(
            parents=True, exist_ok=True
        )
        (tmp_path / "data" / "novels" / "test" / "characters").mkdir(
            parents=True, exist_ok=True
        )
        (tmp_path / "data" / "novels" / "test" / "foreshadowing").mkdir(
            parents=True, exist_ok=True
        )
        (tmp_path / "data" / "novels" / "test" / "world").mkdir(
            parents=True, exist_ok=True
        )
        (tmp_path / "data" / "novels" / "test" / "manuscript" / "drafts").mkdir(
            parents=True, exist_ok=True
        )
        (tmp_path / "logs" / "simulations").mkdir(parents=True, exist_ok=True)

        sim = AgentSimulator(project_dir=tmp_path, novel_id="test")
        result = sim._narrative_context("ch_002")
        assert result != ""
        parsed = json.loads(result)
        assert parsed["chapter_id"] == "ch_002"
        assert len(parsed["active_threads"]) == 2
