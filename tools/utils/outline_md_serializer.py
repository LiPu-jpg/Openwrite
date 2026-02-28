"""Markdown 大纲序列化器 — 将 OutlineHierarchy 转换为 outline.md。

根据 docs/OUTLINE_MD_SPEC.md 规范实现。
"""

from __future__ import annotations

from typing import Any, Dict

import yaml

try:
    from tools.models.outline import (
        ArcOutline,
        ChapterOutline,
        MasterOutline,
        OutlineHierarchy,
        SectionOutline,
    )
except ImportError:  # pragma: no cover
    from models.outline import (
        ArcOutline,
        ChapterOutline,
        MasterOutline,
        OutlineHierarchy,
        SectionOutline,
    )

class OutlineMdSerializer:
    """Markdown 大纲序列化器。"""

    # 需要从 YAML 中排除的字段
    MASTER_EXCLUDE_FIELDS = {"arc_ids", "compressed_summary"}
    ARC_EXCLUDE_FIELDS = {"novel_id", "section_ids", "compressed_summary"}
    SECTION_EXCLUDE_FIELDS = {"arc_id", "chapter_ids", "compressed_summary"}
    CHAPTER_EXCLUDE_FIELDS = {"section_id", "compressed_summary"}
    def serialize(self, hierarchy: OutlineHierarchy) -> str:
        """将 OutlineHierarchy 序列化为 Markdown 文本。

        Args:
            hierarchy: OutlineHierarchy 实例

        Returns:
            Markdown 格式的大纲文本
        """
        lines = []

        # 1. 生成总纲 (H1)
        lines.extend(self._serialize_master(hierarchy.master))

        # 2. 按 order 排序生成篇纲 (H2)
        arcs = sorted(
            [hierarchy.arcs[aid] for aid in hierarchy.master.arc_ids if aid in hierarchy.arcs],
            key=lambda a: a.order,
        )

        for arc in arcs:
            lines.append("")  # 空行分隔
            lines.extend(self._serialize_arc(arc))

            # 3. 生成该篇下的节纲 (H3)
            sections = sorted(
                [hierarchy.sections[sid] for sid in arc.section_ids if sid in hierarchy.sections],
                key=lambda s: s.order,
            )

            for section in sections:
                lines.append("")  # 空行分隔
                lines.extend(self._serialize_section(section))

                # 4. 生成该节下的章纲 (H4)
                chapters = sorted(
                    [hierarchy.chapters[cid] for cid in section.chapter_ids if cid in hierarchy.chapters],
                    key=lambda c: c.order,
                )

                for chapter in chapters:
                    lines.append("")  # 空行分隔
                    lines.extend(self._serialize_chapter(chapter))

        return "\n".join(lines)

    def _serialize_master(self, master: MasterOutline) -> list[str]:
        """序列化总纲 (H1)。

        Args:
            master: MasterOutline 实例

        Returns:
            Markdown 行列表
        """
        lines = []

        # 标题
        title = master.title or "未命名总纲"
        lines.append(f"# {title}")

        # YAML 元数据
        metadata = self._filter_metadata(
            master.model_dump(exclude_none=True),
            self.MASTER_EXCLUDE_FIELDS,
        )
        lines.extend(self._format_yaml_block(metadata))

        # key_turns 作为列表输出
        if master.key_turns:
            for turn in master.key_turns:
                lines.append(f"- {turn}")

        return lines
    def _serialize_arc(self, arc: ArcOutline) -> list[str]:
        """序列化篇纲 (H2)。

        Args:
            arc: ArcOutline 实例

        Returns:
            Markdown 行列表
        """
        lines = []

        # 标题
        title = arc.title or f"第{arc.order}篇"
        lines.append(f"## {title}")

        # YAML 元数据
        metadata = self._filter_metadata(
            arc.model_dump(exclude_none=True),
            self.ARC_EXCLUDE_FIELDS,
        )
        lines.extend(self._format_yaml_block(metadata))

        return lines
    def _serialize_section(self, section: SectionOutline) -> list[str]:
        """序列化节纲 (H3)。

        Args:
            section: SectionOutline 实例

        Returns:
            Markdown 行列表
        """
        lines = []

        # 标题
        title = section.title or f"第{section.order}节"
        lines.append(f"### {title}")

        # YAML 元数据
        metadata = self._filter_metadata(
            section.model_dump(exclude_none=True),
            self.SECTION_EXCLUDE_FIELDS,
        )
        lines.extend(self._format_yaml_block(metadata))

        return lines
    def _serialize_chapter(self, chapter: ChapterOutline) -> list[str]:
        """序列化章纲 (H4)。

        Args:
            chapter: ChapterOutline 实例

        Returns:
            Markdown 行列表
        """
        lines = []

        # 标题
        title = chapter.title or f"第{chapter.order}章"
        lines.append(f"#### {title}")

        # YAML 元数据
        metadata = self._filter_metadata(
            chapter.model_dump(exclude_none=True),
            self.CHAPTER_EXCLUDE_FIELDS,
        )
        lines.extend(self._format_yaml_block(metadata))

        return lines
    def _filter_metadata(self, data: Dict[str, Any], exclude_fields: set[str]) -> Dict[str, Any]:
        """过滤元数据，移除排除字段和空值。

        Args:
            data: 原始数据字典
            exclude_fields: 需要排除的字段集合

        Returns:
            过滤后的数据字典
        """
        filtered = {}

        for key, value in data.items():
            # 跳过排除字段
            if key in exclude_fields:
                continue

            # 跳过 title 字段（已在标题中显示）
            if key == "title":
                continue

            # 跳过空值
            if value is None:
                continue
            if isinstance(value, str) and value == "":
                continue
            if isinstance(value, list) and len(value) == 0:
                continue
            if isinstance(value, dict) and len(value) == 0:
                continue

            filtered[key] = value

        return filtered
    def _format_yaml_block(self, metadata: Dict[str, Any]) -> list[str]:
        """格式化 YAML 块。

        Args:
            metadata: 元数据字典

        Returns:
            YAML 块行列表（包含 --- 分隔符）
        """
        if not metadata:
            return []

        lines = ["---"]

        # 使用 yaml.dump 生成 YAML 内容
        yaml_content = yaml.dump(
            metadata,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        ).strip()

        lines.extend(yaml_content.split("\n"))
        lines.append("---")

        return lines

def serialize_outline_md(hierarchy: OutlineHierarchy) -> str:
    """将 OutlineHierarchy 序列化为 Markdown 文本。

    Args:
        hierarchy: OutlineHierarchy 实例

    Returns:
        Markdown 文本内容
    """
    serializer = OutlineMdSerializer()
    return serializer.serialize(hierarchy)
