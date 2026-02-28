"""大纲序列化器 — 将结构化大纲数据转换为 Markdown 格式。

支持四级大纲层级：
- 总纲 (Master): H1 标题
- 篇纲 (Arc): H2 标题
- 节纲 (Section): H3 标题
- 章纲 (Chapter): H4 标题
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Set, Union

import yaml

from skills.outline.tools.parser import (
    ArcOutline,
    ChapterOutline,
    MasterOutline,
    OutlineHierarchy,
    SectionOutline,
)


class OutlineSerializer:
    """Markdown 大纲序列化器。"""

    # 需要从 YAML 中排除的字段
    MASTER_EXCLUDE_FIELDS: Set[str] = {"arc_ids", "compressed_summary"}
    ARC_EXCLUDE_FIELDS: Set[str] = {"novel_id", "section_ids", "compressed_summary"}
    SECTION_EXCLUDE_FIELDS: Set[str] = {"arc_id", "chapter_ids", "compressed_summary"}
    CHAPTER_EXCLUDE_FIELDS: Set[str] = {"section_id", "compressed_summary"}

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
            [
                hierarchy.arcs[aid]
                for aid in hierarchy.master.arc_ids
                if aid in hierarchy.arcs
            ],
            key=lambda a: a.order,
        )

        for arc in arcs:
            lines.append("")  # 空行分隔
            lines.extend(self._serialize_arc(arc))

            # 3. 生成该篇下的节纲 (H3)
            sections = sorted(
                [
                    hierarchy.sections[sid]
                    for sid in arc.section_ids
                    if sid in hierarchy.sections
                ],
                key=lambda s: s.order,
            )

            for section in sections:
                lines.append("")  # 空行分隔
                lines.extend(self._serialize_section(section))

                # 4. 生成该节下的章纲 (H4)
                chapters = sorted(
                    [
                        hierarchy.chapters[cid]
                        for cid in section.chapter_ids
                        if cid in hierarchy.chapters
                    ],
                    key=lambda c: c.order,
                )

                for chapter in chapters:
                    lines.append("")  # 空行分隔
                    lines.extend(self._serialize_chapter(chapter))

        return "\n".join(lines)

    def serialize_to_file(
        self, hierarchy: OutlineHierarchy, file_path: Union[str, Path]
    ) -> None:
        """序列化到文件。

        Args:
            hierarchy: OutlineHierarchy 实例
            file_path: 目标文件路径
        """
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        content = self.serialize(hierarchy)
        path.write_text(content, encoding="utf-8")

    def _serialize_master(self, master: MasterOutline) -> List[str]:
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
            master.to_dict(),
            self.MASTER_EXCLUDE_FIELDS,
        )
        lines.extend(self._format_yaml_block(metadata))

        # key_turns 作为列表输出
        if master.key_turns:
            for turn in master.key_turns:
                lines.append(f"- {turn}")

        return lines

    def _serialize_arc(self, arc: ArcOutline) -> List[str]:
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
            arc.to_dict(),
            self.ARC_EXCLUDE_FIELDS,
        )
        lines.extend(self._format_yaml_block(metadata))

        return lines

    def _serialize_section(self, section: SectionOutline) -> List[str]:
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
            section.to_dict(),
            self.SECTION_EXCLUDE_FIELDS,
        )
        lines.extend(self._format_yaml_block(metadata))

        return lines

    def _serialize_chapter(self, chapter: ChapterOutline) -> List[str]:
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
            chapter.to_dict(),
            self.CHAPTER_EXCLUDE_FIELDS,
        )
        lines.extend(self._format_yaml_block(metadata))

        return lines

    def _filter_metadata(
        self, data: Dict[str, Any], exclude_fields: Set[str]
    ) -> Dict[str, Any]:
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

    def _format_yaml_block(self, metadata: Dict[str, Any]) -> List[str]:
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


def serialize_outline(hierarchy: OutlineHierarchy) -> str:
    """将 OutlineHierarchy 序列化为 Markdown 文本。

    Args:
        hierarchy: OutlineHierarchy 实例

    Returns:
        Markdown 文本内容
    """
    serializer = OutlineSerializer()
    return serializer.serialize(hierarchy)
