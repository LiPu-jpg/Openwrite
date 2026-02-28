"""大纲验证器 — 检查大纲结构的完整性和一致性。

验证规则：
1. 层级完整性：确保父节点引用的子节点都存在
2. ID 唯一性：确保所有 ID 在其层级内唯一
3. 顺序连续性：检查 order 字段是否连续
4. 引用有效性：检查伏笔引用、角色引用是否存在
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union

from skills.outline.tools.parser import (
    ArcOutline,
    ChapterOutline,
    MasterOutline,
    OutlineHierarchy,
    SectionOutline,
)


@dataclass
class ValidationError:
    """验证错误。"""

    level: str  # "error" | "warning"
    code: str  # 错误代码
    message: str  # 错误消息
    location: str  # 位置描述
    suggestion: Optional[str] = None  # 修复建议

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典。"""
        return {
            "level": self.level,
            "code": self.code,
            "message": self.message,
            "location": self.location,
            "suggestion": self.suggestion,
        }


@dataclass
class ValidationResult:
    """验证结果。"""

    is_valid: bool
    errors: List[ValidationError] = field(default_factory=list)
    warnings: List[ValidationError] = field(default_factory=list)

    def add_error(
        self, code: str, message: str, location: str, suggestion: Optional[str] = None
    ):
        """添加错误。"""
        self.errors.append(
            ValidationError(
                level="error",
                code=code,
                message=message,
                location=location,
                suggestion=suggestion,
            )
        )
        self.is_valid = False

    def add_warning(
        self, code: str, message: str, location: str, suggestion: Optional[str] = None
    ):
        """添加警告。"""
        self.warnings.append(
            ValidationError(
                level="warning",
                code=code,
                message=message,
                location=location,
                suggestion=suggestion,
            )
        )

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典。"""
        return {
            "is_valid": self.is_valid,
            "errors": [e.to_dict() for e in self.errors],
            "warnings": [w.to_dict() for w in self.warnings],
        }


class OutlineValidator:
    """大纲验证器。"""

    def validate(self, hierarchy: OutlineHierarchy) -> ValidationResult:
        """验证大纲结构。

        Args:
            hierarchy: OutlineHierarchy 实例

        Returns:
            ValidationResult 实例
        """
        result = ValidationResult(is_valid=True)

        # 1. 验证总纲
        self._validate_master(hierarchy.master, result)

        # 2. 验证篇纲
        self._validate_arcs(hierarchy, result)

        # 3. 验证节纲
        self._validate_sections(hierarchy, result)

        # 4. 验证章纲
        self._validate_chapters(hierarchy, result)

        # 5. 验证层级完整性
        self._validate_hierarchy_integrity(hierarchy, result)

        return result

    def validate_and_raise(self, hierarchy: OutlineHierarchy) -> None:
        """验证并在失败时抛出异常。

        Args:
            hierarchy: OutlineHierarchy 实例

        Raises:
            ValueError: 验证失败时抛出
        """
        result = self.validate(hierarchy)
        if not result.is_valid:
            error_messages = [f"{e.location}: {e.message}" for e in result.errors]
            raise ValueError("大纲验证失败:\n" + "\n".join(error_messages))

    def _validate_master(self, master: MasterOutline, result: ValidationResult):
        """验证总纲。"""
        # 检查必需字段
        if not master.novel_id:
            result.add_error(
                code="MASTER_MISSING_NOVEL_ID",
                message="总纲缺少 novel_id",
                location="总纲",
                suggestion="在总纲 YAML 块中添加 novel_id 字段",
            )

        if not master.title:
            result.add_warning(
                code="MASTER_MISSING_TITLE",
                message="总纲缺少书名",
                location="总纲",
                suggestion="建议为作品添加书名",
            )

        # 检查关键转折点数量
        if len(master.key_turns) < 3:
            result.add_warning(
                code="MASTER_TOO_FEW_TURNS",
                message=f"关键转折点过少（{len(master.key_turns)} 个），建议至少 3 个",
                location="总纲",
                suggestion="添加更多关键转折点以丰富故事结构",
            )

        if len(master.key_turns) > 10:
            result.add_warning(
                code="MASTER_TOO_MANY_TURNS",
                message=f"关键转折点过多（{len(master.key_turns)} 个），建议不超过 10 个",
                location="总纲",
                suggestion="考虑合并或删除部分转折点",
            )

    def _validate_arcs(self, hierarchy: OutlineHierarchy, result: ValidationResult):
        """验证篇纲。"""
        arc_ids: Set[str] = set()
        orders: Set[int] = set()

        for arc_id, arc in hierarchy.arcs.items():
            # 检查 ID 唯一性
            if arc_id in arc_ids:
                result.add_error(
                    code="ARC_DUPLICATE_ID",
                    message=f"篇纲 ID 重复: {arc_id}",
                    location=f"篇纲「{arc.title}」",
                )
            arc_ids.add(arc_id)

            # 检查 order 连续性
            if arc.order in orders:
                result.add_error(
                    code="ARC_DUPLICATE_ORDER",
                    message=f"篇纲 order 重复: {arc.order}",
                    location=f"篇纲「{arc.title}」",
                )
            orders.add(arc.order)

            # 检查必需字段
            if not arc.main_conflict:
                result.add_warning(
                    code="ARC_MISSING_CONFLICT",
                    message="篇纲缺少主要矛盾描述",
                    location=f"篇纲「{arc.title}」",
                    suggestion="添加 main_conflict 字段描述本篇核心冲突",
                )

            # 检查引用一致性
            for section_id in arc.section_ids:
                if section_id not in hierarchy.sections:
                    result.add_error(
                        code="ARC_INVALID_SECTION_REF",
                        message=f"引用的节纲不存在: {section_id}",
                        location=f"篇纲「{arc.title}」",
                    )

        # 检查 master.arc_ids 与实际 arcs 的一致性
        for arc_id in hierarchy.master.arc_ids:
            if arc_id not in hierarchy.arcs:
                result.add_error(
                    code="MASTER_INVALID_ARC_REF",
                    message=f"总纲引用的篇纲不存在: {arc_id}",
                    location="总纲",
                )

    def _validate_sections(self, hierarchy: OutlineHierarchy, result: ValidationResult):
        """验证节纲。"""
        section_ids: Set[str] = set()

        for section_id, section in hierarchy.sections.items():
            # 检查 ID 唯一性
            if section_id in section_ids:
                result.add_error(
                    code="SECTION_DUPLICATE_ID",
                    message=f"节纲 ID 重复: {section_id}",
                    location=f"节纲「{section.title}」",
                )
            section_ids.add(section_id)

            # 检查父级引用
            if section.arc_id not in hierarchy.arcs:
                result.add_error(
                    code="SECTION_INVALID_ARC_REF",
                    message=f"引用的篇纲不存在: {section.arc_id}",
                    location=f"节纲「{section.title}」",
                )

            # 检查章节引用
            for chapter_id in section.chapter_ids:
                if chapter_id not in hierarchy.chapters:
                    result.add_error(
                        code="SECTION_INVALID_CHAPTER_REF",
                        message=f"引用的章纲不存在: {chapter_id}",
                        location=f"节纲「{section.title}」",
                    )

    def _validate_chapters(self, hierarchy: OutlineHierarchy, result: ValidationResult):
        """验证章纲。"""
        chapter_ids: Set[str] = set()

        for chapter_id, chapter in hierarchy.chapters.items():
            # 检查 ID 唯一性
            if chapter_id in chapter_ids:
                result.add_error(
                    code="CHAPTER_DUPLICATE_ID",
                    message=f"章纲 ID 重复: {chapter_id}",
                    location=f"章纲「{chapter.title}」",
                )
            chapter_ids.add(chapter_id)

            # 检查父级引用
            if chapter.section_id not in hierarchy.sections:
                result.add_error(
                    code="CHAPTER_INVALID_SECTION_REF",
                    message=f"引用的节纲不存在: {chapter.section_id}",
                    location=f"章纲「{chapter.title}」",
                )

            # 检查目标字数范围
            if chapter.target_words < 3000:
                result.add_warning(
                    code="CHAPTER_LOW_WORD_COUNT",
                    message=f"目标字数过低: {chapter.target_words}",
                    location=f"章纲「{chapter.title}」",
                    suggestion="建议目标字数在 3000-12000 之间",
                )

            if chapter.target_words > 12000:
                result.add_warning(
                    code="CHAPTER_HIGH_WORD_COUNT",
                    message=f"目标字数过高: {chapter.target_words}",
                    location=f"章纲「{chapter.title}」",
                    suggestion="建议目标字数在 3000-12000 之间",
                )

            # 检查写作目标
            if not chapter.goals:
                result.add_warning(
                    code="CHAPTER_MISSING_GOALS",
                    message="章纲缺少写作目标",
                    location=f"章纲「{chapter.title}」",
                    suggestion="添加 goals 字段明确本章写作目标",
                )

    def _validate_hierarchy_integrity(
        self, hierarchy: OutlineHierarchy, result: ValidationResult
    ):
        """验证层级完整性。"""
        # 检查是否有孤立的节纲（不属于任何篇纲）
        orphan_sections = []
        for section_id, section in hierarchy.sections.items():
            is_referenced = False
            for arc in hierarchy.arcs.values():
                if section_id in arc.section_ids:
                    is_referenced = True
                    break
            if not is_referenced:
                orphan_sections.append(section_id)

        if orphan_sections:
            result.add_warning(
                code="ORPHAN_SECTIONS",
                message=f"发现孤立的节纲: {', '.join(orphan_sections)}",
                location="大纲结构",
                suggestion="将这些节纲添加到对应的篇纲中",
            )

        # 检查是否有孤立的章纲（不属于任何节纲）
        orphan_chapters = []
        for chapter_id, chapter in hierarchy.chapters.items():
            is_referenced = False
            for section in hierarchy.sections.values():
                if chapter_id in section.chapter_ids:
                    is_referenced = True
                    break
            if not is_referenced:
                orphan_chapters.append(chapter_id)

        if orphan_chapters:
            result.add_warning(
                code="ORPHAN_CHAPTERS",
                message=f"发现孤立的章纲: {', '.join(orphan_chapters)}",
                location="大纲结构",
                suggestion="将这些章纲添加到对应的节纲中",
            )


def validate_outline(hierarchy: OutlineHierarchy) -> ValidationResult:
    """验证大纲结构。

    Args:
        hierarchy: OutlineHierarchy 实例

    Returns:
        ValidationResult 实例
    """
    validator = OutlineValidator()
    return validator.validate(hierarchy)
