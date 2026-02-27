"""叙事线管理器 — 从现有数据聚合生成 NarrativeTimeline。

支持两种模式：
1. 自动聚合：从 CharacterStateManager、ForeshadowingDAG、OutlineQuery 自动提取
2. 手动编辑：直接操作 NarrativeTimeline YAML 文件

自动聚合为每个角色生成一条叙事线，从 mutation 日志提取事件节点，
从伏笔 DAG 提取伏笔弧线连接。手动编辑允许添加自定义线和连接。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from tools.models.narrative import (
    Link,
    LinkType,
    NarrativeThread,
    NarrativeTimeline,
    ThreadEvent,
)

logger = logging.getLogger(__name__)

# 默认调色板（最多 12 条线自动分配颜色）
_PALETTE = [
    "#FF6B6B",
    "#4ECDC4",
    "#45B7D1",
    "#96CEB4",
    "#FFEAA7",
    "#DDA0DD",
    "#98D8C8",
    "#F7DC6F",
    "#BB8FCE",
    "#85C1E9",
    "#F0B27A",
    "#AED6F1",
]


def _chapter_order(chapter_id: str) -> int:
    """从章节 ID 提取数字序号用于排序。"""
    match = re.search(r"\d+", chapter_id)
    return int(match.group()) if match else 0


class NarrativeTimelineManager:
    """叙事线管理器。"""

    def __init__(
        self,
        project_dir: Path,
        novel_id: str,
    ):
        self.project_dir = project_dir
        self.novel_id = novel_id
        self.base_dir = project_dir / "data" / "novels" / novel_id
        self.timeline_file = self.base_dir / "narrative" / "timeline.yaml"
        self.timeline_file.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def load(self) -> NarrativeTimeline:
        """加载已保存的时间线，不存在则返回空时间线。"""
        if not self.timeline_file.exists():
            return NarrativeTimeline(novel_id=self.novel_id)
        try:
            with self.timeline_file.open("r", encoding="utf-8") as f:
                raw = yaml.safe_load(f)
            if not raw or not isinstance(raw, dict):
                return NarrativeTimeline(novel_id=self.novel_id)
            return NarrativeTimeline.model_validate(raw)
        except Exception as e:
            logger.warning("加载叙事时间线失败: %s", e)
            return NarrativeTimeline(novel_id=self.novel_id)

    def save(self, timeline: NarrativeTimeline) -> Path:
        """保存时间线到 YAML。"""
        data = timeline.model_dump(mode="json")
        with self.timeline_file.open("w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
        return self.timeline_file

    # ------------------------------------------------------------------
    # 自动聚合
    # ------------------------------------------------------------------

    def build_from_existing(self) -> NarrativeTimeline:
        """从现有数据源自动聚合生成完整时间线。

        数据源：
        - OutlineQuery → 章节列表 + 场景标注
        - CharacterStateManager → 角色叙事线（mutation 日志）
        - ForeshadowingDAGManager → 伏笔弧线连接
        """
        from tools.character_state_manager import CharacterStateManager
        from tools.graph.foreshadowing_dag import ForeshadowingDAGManager
        from tools.queries.outline_query import OutlineQuery

        outline = OutlineQuery(project_dir=self.project_dir, novel_id=self.novel_id)
        char_mgr = CharacterStateManager(
            project_dir=self.project_dir, novel_id=self.novel_id
        )
        fs_mgr = ForeshadowingDAGManager(
            project_dir=self.project_dir, novel_id=self.novel_id
        )

        # 1. 章节列表
        chapters = outline.get_all_chapters()
        chapters.sort(key=_chapter_order)

        # 2. 角色叙事线
        threads: List[NarrativeThread] = []
        characters = char_mgr.list_characters()
        for idx, char_info in enumerate(characters):
            char_id = char_info.get("id", "")
            char_name = char_info.get("name", char_id)
            thread = self._build_character_thread(
                char_mgr,
                char_id,
                char_name,
                color=_PALETTE[idx % len(_PALETTE)],
            )
            if thread.events:
                threads.append(thread)

        # 3. 从大纲标注补充事件（角色线上没有 mutation 的章节）
        for chapter_id in chapters:
            chapter_data = outline.get_chapter(chapter_id)
            if not chapter_data:
                continue
            annotations = chapter_data.get("annotations", {})
            self._enrich_from_annotations(threads, chapter_id, annotations)

        # 4. 伏笔弧线
        links: List[Link] = self._build_foreshadowing_links(fs_mgr, outline, threads)

        # 5. 合并手动编辑的数据
        existing = self.load()
        timeline = NarrativeTimeline(
            novel_id=self.novel_id,
            title=existing.title or self.novel_id,
            chapters=chapters,
            threads=self._merge_threads(threads, existing.threads),
            links=self._merge_links(links, existing.links),
        )
        return timeline

    def _build_character_thread(
        self,
        char_mgr: Any,
        char_id: str,
        char_name: str,
        color: str = "",
    ) -> NarrativeThread:
        """从角色 mutation 日志构建叙事线。"""
        thread_id = f"thread_{char_id}"
        events: List[ThreadEvent] = []

        try:
            card = char_mgr.get_character_card(character_id=char_id)
        except FileNotFoundError:
            return NarrativeThread(id=thread_id, name=char_name, color=color)

        mutations = char_mgr.get_timeline(character_id=card.static.id)
        for m in mutations:
            label = m.note or m.reason or f"{m.action or '事件'}"
            tags: List[str] = []
            if m.action:
                tags.append(m.action)
            events.append(
                ThreadEvent(
                    chapter_id=m.chapter_id,
                    label=label,
                    detail=m.reason or "",
                    tags=tags,
                    meta={"mutation_id": m.mutation_id} if m.mutation_id else {},
                )
            )

        return NarrativeThread(
            id=thread_id,
            name=char_name,
            color=color,
            events=events,
        )

    def _enrich_from_annotations(
        self,
        threads: List[NarrativeThread],
        chapter_id: str,
        annotations: Dict[str, Any],
    ) -> None:
        """从大纲标注中补充角色事件（如果 mutation 日志中没有该章节的记录）。"""
        char_annotations = annotations.get("characters", [])
        for ca in char_annotations:
            attrs = ca.get("attributes", {})
            char_id = attrs.get("id", "")
            action = attrs.get("action", "")
            content = ca.get("content", "").strip()
            if not char_id:
                continue

            thread = self._find_or_create_thread(threads, char_id)
            # 检查该章节是否已有事件
            has_event = any(e.chapter_id == chapter_id for e in thread.events)
            if not has_event and (action or content):
                thread.events.append(
                    ThreadEvent(
                        chapter_id=chapter_id,
                        label=action or content[:40],
                        detail=content,
                        tags=["outline_annotation"],
                    )
                )

        # 场景标注 → 更新已有事件的 tension
        scene_annotations = annotations.get("scenes", [])
        tensions = []
        for sa in scene_annotations:
            attrs = sa.get("attributes", {})
            try:
                tensions.append(int(str(attrs.get("tension", 5))))
            except ValueError:
                pass
        if tensions:
            avg_tension = sum(tensions) // len(tensions)
            for thread in threads:
                for event in thread.events:
                    if event.chapter_id == chapter_id and event.tension == 5:
                        event.tension = avg_tension

    def _build_foreshadowing_links(
        self,
        fs_mgr: Any,
        outline: Any,
        threads: List[NarrativeThread],
    ) -> List[Link]:
        """从伏笔 DAG 构建伏笔弧线连接。"""
        links: List[Link] = []
        dag = fs_mgr._load_dag()

        for node_id, node_data in dag.nodes.items():
            node = node_data if hasattr(node_data, "created_at") else None
            if node is None:
                continue

            status = dag.status.get(node_id, "埋伏")
            created_at = node.created_at or ""
            target_ch = node.target_chapter or ""
            weight = node.weight if hasattr(node, "weight") else 5

            if not created_at:
                continue

            # 找到涉及的叙事线（优先匹配有该章节事件的线）
            source_thread = self._find_thread_at_chapter(threads, created_at)
            if not source_thread:
                source_thread = threads[0].id if threads else "thread_unknown"

            target_thread = source_thread
            if target_ch:
                found = self._find_thread_at_chapter(threads, target_ch)
                if found:
                    target_thread = found

            style = "dashed" if status in ("埋伏", "待收") else "solid"
            links.append(
                Link(
                    source_thread=source_thread,
                    source_chapter=created_at,
                    target_thread=target_thread,
                    target_chapter=target_ch or "",
                    link_type=LinkType.FORESHADOW,
                    label=f"{node_id}: {node.content[:30]}",
                    weight=min(weight, 10),
                    style=style,
                )
            )

        return links

    # ------------------------------------------------------------------
    # 手动编辑 API
    # ------------------------------------------------------------------

    def add_thread(self, timeline: NarrativeTimeline, thread: NarrativeThread) -> None:
        """添加一条叙事线。"""
        existing = timeline.get_thread(thread.id)
        if existing:
            raise ValueError(f"叙事线已存在: {thread.id}")
        if not thread.color:
            idx = len(timeline.threads)
            thread.color = _PALETTE[idx % len(_PALETTE)]
        timeline.threads.append(thread)

    def add_event(
        self,
        timeline: NarrativeTimeline,
        thread_id: str,
        event: ThreadEvent,
    ) -> None:
        """向指定叙事线添加事件。"""
        thread = timeline.get_thread(thread_id)
        if not thread:
            raise ValueError(f"叙事线不存在: {thread_id}")
        thread.events.append(event)
        thread.events.sort(key=lambda e: _chapter_order(e.chapter_id))

    def add_link(self, timeline: NarrativeTimeline, link: Link) -> None:
        """添加连接。"""
        timeline.links.append(link)

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def _find_or_create_thread(
        self,
        threads: List[NarrativeThread],
        char_id: str,
    ) -> NarrativeThread:
        """查找或创建角色叙事线。"""
        thread_id = f"thread_{char_id}"
        for t in threads:
            if t.id == thread_id:
                return t
        new_thread = NarrativeThread(
            id=thread_id,
            name=char_id,
            color=_PALETTE[len(threads) % len(_PALETTE)],
        )
        threads.append(new_thread)
        return new_thread

    def _find_thread_at_chapter(
        self,
        threads: List[NarrativeThread],
        chapter_id: str,
    ) -> str:
        """找到在指定章节有事件的第一条叙事线 ID。"""
        for t in threads:
            if any(e.chapter_id == chapter_id for e in t.events):
                return t.id
        return ""

    @staticmethod
    def _merge_threads(
        auto: List[NarrativeThread],
        manual: List[NarrativeThread],
    ) -> List[NarrativeThread]:
        """合并自动生成和手动编辑的叙事线（手动优先）。"""
        manual_ids = {t.id for t in manual}
        merged = list(manual)
        for t in auto:
            if t.id not in manual_ids:
                merged.append(t)
        return merged

    @staticmethod
    def _merge_links(auto: List[Link], manual: List[Link]) -> List[Link]:
        """合并连接（去重：相同 source+target+type 视为重复）。"""
        seen = set()
        merged: List[Link] = []
        for lk in manual + auto:
            key = (
                lk.source_thread,
                lk.source_chapter,
                lk.target_thread,
                lk.target_chapter,
                lk.link_type,
            )
            if key not in seen:
                seen.add(key)
                merged.append(lk)
        return merged
