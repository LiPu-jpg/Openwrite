"""Markdown 大纲序列化器 — 将 OutlineHierarchy 转换为 outline.md。

根据 docs/OUTLINE_MD_SPEC.md 规范实现。
"""

from __future__ import annotations

from typing import Any, Dict

import yaml

try:
    from tools.models.outline import OutlineHierarchy
except ImportError:  # pragma: no cover
    from models.outline import OutlineHierarchy


class OutlineMdSerializer:
    """Markdown 大纲序列化器。"""

    def __init__(self):
        self.lines: list[str] = []

    def serialize(self, hierarchy: OutlineHierarchy) -> str:
        """将 OutlineHierarchy 序列化为 Markdown 文本。

        Args:
            hierarchy: OutlineHierarchy 实例

        Returns:
            Markdown 文本内容
        """
        self.lines = []

        # 序列化总纲
        self._serialize_master(hierarchy.master)

        # 序列化篇纲（按 order 排序）
        for arc in hierarchy.get_all_arcs_ordered():
            self._serialize_arc(arc)

            # 序列化该篇下的节纲
            for section in hierarchy.get_sections_for_arc(arc.arc_id):
                self._serialize_section(section)

                # 序列化该节下的章纲
                for chapter in hierarchy.get_chapters_for_section(section.section_id):
                    self._serialize_chapter(chapter)

        return "\n".join(self.lines)

    def _serialize_master(self, master):
        """序列化总纲。"""
        # 标题
        title = master.title or master.novel_id
        self.lines.append(f"# 总纲：{title}")
        self.lines.append("")

        # 元数据
        metadata = self._filter_metadata(
            master.model_dump(exclude_none=True),
            exclude=["title", "arc_ids", "key_turns"],
        )
        self._append_yaml_block(metadata)

        # 关键转折点
        if master.key_turns:
            self.lines.append("**关键转折点**：")
            for turn in master.key_turns:
                self.lines.append(f"- {turn}")
            self.lines.append("")

    def _serialize_arc(self, arc):
        """序列化篇纲。"""
        self.lines.append(f"## 第{arc.order}篇：{arc.title}")
        self.lines.append("")

        metadata = self._filter_metadata(
            arc.model_dump(exclude_none=True),
            exclude=["title", "order", "novel_id", "section_ids", "compressed_summary"],
        )
        self._append_yaml_block(metadata)

    def _serialize_section(self, section):
        """序列化节纲。"""
        self.lines.append(f"### 第{section.order}节：{section.title}")
        self.lines.append("")

        metadata = self._filter_metadata(
            section.model_dump(exclude_none=True),
            exclude=["title", "order", "arc_id", "chapter_ids", "compressed_summary"],
        )
        self._append_yaml_block(metadata)

    def _serialize_chapter(self, chapter):
        """序列化章纲。"""
        self.lines.append(f"#### 第{chapter.order}章：{chapter.title}")
        self.lines.append("")

        metadata = self._filter_metadata(
            chapter.model_dump(exclude_none=True),
            exclude=["title", "order", "section_id"],
        )
        self._append_yaml_block(metadata)

    def _filter_metadata(self, data: Dict[str, Any], exclude: list[str]) -> Dict[str, Any]:
        """过滤元数据字段。

        Args:
            data: 原始数据字典
            exclude: 要排除的字段列表

        Returns:
            过滤后的字典
        """
        filtered = {}
        for key, value in data.items():
            if key in exclude:
                continue
            # 排除空值
            if value is None or value == "" or value == []:
                continue
            filtered[key] = value
        return filtered

    def _append_yaml_block(self, metadata: Dict[str, Any]):
        """追加 YAML 元数据块。

        Args:
            metadata: 元数据字典
        """
        if not metadata:
            return

        self.lines.append("---")
        yaml_str = yaml.dump(
            metadata,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )
        # 移除末尾换行
        yaml_str = yaml_str.rstrip("\n")
        self.lines.append(yaml_str)
        self.lines.append("---")
        self.lines.append("")


def serialize_outline_md(hierarchy: OutlineHierarchy) -> str:
    """将 OutlineHierarchy 序列化为 Markdown 文本。

    Args:
        hierarchy: OutlineHierarchy 实例

    Returns:
        Markdown 文本内容
    """
    serializer = OutlineMdSerializer()
    return serializer.serialize(hierarchy)
