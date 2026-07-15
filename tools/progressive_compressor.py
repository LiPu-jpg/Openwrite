"""Progressive context compressor — 渐进式上下文压缩引擎。

核心组件，实现 200万字 → 5万字 的压缩策略：
  1. 每节(Section)完成后 → 压缩本节内容为 SectionCompression (~800字)
  2. 每篇(Arc)完成后 → 上一篇压缩 + 本篇各节压缩 → 合并为 ArcCompression (~2000字)
  3. 每次生成章节时 → 组装完整 GenerationContext

压缩策略：
  - 关键词评分（"突然", "然而", "决定", "死", "突破" 等）
  - 首段/末段优先
  - 对话段落略低优先级
  - 句子边界截断
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Any

import yaml

import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
from models.context_package import GenerationContext
from models.outline import OutlineHierarchy, OutlineNode


# ── 压缩参数 ──────────────────────────────────────────────────────

# 上文长度（字符）
RECENT_TEXT_MIN = 500
RECENT_TEXT_MAX = 1000

# 节压缩目标长度
SECTION_COMPRESS_TARGET = 800

# 篇压缩目标长度
ARC_COMPRESS_TARGET = 2000


class SectionCompression:
    """节压缩结果，存储单个节(Section)的压缩数据。

    当一个节（10-20章）写完后，将全文压缩为 ~800 字的摘要，
    保留关键事件和角色变化，供后续章节的上下文组装使用。

    Args:
        section_id: 节ID，如 "sec_001"
        arc_id: 所属篇ID，如 "arc_001"
        compressed_text: 压缩后的摘要文本
        key_events: 关键事件列表，如 ["主角觉醒", "师门试练"]
        character_changes: 角色变化列表，如 ["主角等级提升"]
        word_count: 原文总字数

    Example:
        >>> comp = SectionCompression(
        ...     section_id="sec_001",
        ...     arc_id="arc_001",
        ...     compressed_text="主角觉醒，开始修炼之路...",
        ...     key_events=["觉醒", "拜师"],
        ...     word_count=50000,
        ... )
    """

    def __init__(
        self,
        section_id: str,
        arc_id: str,
        compressed_text: str,
        key_events: Optional[List[str]] = None,
        character_changes: Optional[List[str]] = None,
        word_count: int = 0,
    ):
        self.section_id = section_id
        self.arc_id = arc_id
        self.compressed_text = compressed_text
        self.key_events = key_events or []
        self.character_changes = character_changes or []
        self.word_count = word_count

    def to_dict(self) -> Dict:
        return {
            "section_id": self.section_id,
            "arc_id": self.arc_id,
            "compressed_text": self.compressed_text,
            "key_events": self.key_events,
            "character_changes": self.character_changes,
            "word_count": self.word_count,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "SectionCompression":
        return cls(
            section_id=data.get("section_id", ""),
            arc_id=data.get("arc_id", ""),
            compressed_text=data.get("compressed_text", ""),
            key_events=data.get("key_events", []),
            character_changes=data.get("character_changes", []),
            word_count=data.get("word_count", 0),
        )


class ArcCompression:
    """篇压缩结果，合并一个篇(Arc)下所有节的压缩数据。

    当一个篇（~100章）写完后，将上一篇的压缩和本篇各节压缩
    合并为 ~2000 字的综合摘要。

    Args:
        arc_id: 篇ID，如 "arc_001"
        previous_arc_summary: 上一篇的压缩摘要
        section_summaries: 本篇所有节的压缩结果列表
        merged_summary: 合并后的最终摘要
        total_word_count: 本篇原文总字数

    Example:
        >>> arc = ArcCompression(
        ...     arc_id="arc_001",
        ...     section_summaries=[section_comp_1, section_comp_2],
        ... )
        >>> arc.build_merged()
    """

    def __init__(
        self,
        arc_id: str,
        previous_arc_summary: str = "",
        section_summaries: Optional[List[SectionCompression]] = None,
        merged_summary: str = "",
        total_word_count: int = 0,
    ):
        self.arc_id = arc_id
        self.previous_arc_summary = previous_arc_summary
        self.section_summaries = section_summaries or []
        self.merged_summary = merged_summary
        self.total_word_count = total_word_count

    def build_merged(self) -> str:
        """合并所有摘要"""
        parts = []
        if self.previous_arc_summary:
            parts.append(f"【前篇摘要】\n{self.previous_arc_summary}")

        for section in self.section_summaries:
            parts.append(f"【{section.section_id}】\n{section.compressed_text}")

        self.merged_summary = "\n\n".join(parts)
        return self.merged_summary

    def to_dict(self) -> Dict:
        return {
            "arc_id": self.arc_id,
            "previous_arc_summary": self.previous_arc_summary,
            "section_summaries": [s.to_dict() for s in self.section_summaries],
            "merged_summary": self.merged_summary,
            "total_word_count": self.total_word_count,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "ArcCompression":
        section_summaries = [
            SectionCompression.from_dict(s) for s in data.get("section_summaries", [])
        ]
        return cls(
            arc_id=data.get("arc_id", ""),
            previous_arc_summary=data.get("previous_arc_summary", ""),
            section_summaries=section_summaries,
            merged_summary=data.get("merged_summary", ""),
            total_word_count=data.get("total_word_count", 0),
        )


class ProgressiveCompressor:
    """渐进式上下文压缩器 — 管理节/篇级别的滚动压缩。

    Usage:
        compressor = ProgressiveCompressor(
            project_dir=Path("/path/to/project"),
            novel_id="my_novel"
        )

        # 节完成后压缩
        section_comp = compressor.compress_section(
            section_id="sec_001",
            arc_id="arc_001",
            full_text=section_text
        )

        # 篇完成后压缩
        arc_comp = compressor.compress_arc(
            arc_id="arc_001",
            previous_arc_id="arc_000"
        )
    """

    def __init__(
        self,
        project_dir: Path,
        novel_id: str,
        recent_text_min: int = RECENT_TEXT_MIN,
        recent_text_max: int = RECENT_TEXT_MAX,
    ):
        self.project_dir = Path(project_dir).resolve()
        self.novel_id = novel_id
        self.recent_text_min = recent_text_min
        self.recent_text_max = recent_text_max
        self.base_dir = self.project_dir / "data" / "novels" / novel_id
        self.compression_dir = self.base_dir / "data" / "compressed"
        self.compression_dir.mkdir(parents=True, exist_ok=True)

    # ── 节级压缩 ──────────────────────────────────────────────────

    def compress_section(
        self,
        section_id: str,
        arc_id: str,
        full_text: str,
        key_events: Optional[List[str]] = None,
        character_changes: Optional[List[str]] = None,
    ) -> SectionCompression:
        """压缩一个完成的节(Section)的全文为摘要。

        当有 LLM 时可调用 LLM 做摘要；当前为规则引擎实现。
        """
        compressed = self._rule_compress_text(full_text, SECTION_COMPRESS_TARGET)
        result = SectionCompression(
            section_id=section_id,
            arc_id=arc_id,
            compressed_text=compressed,
            key_events=key_events or [],
            character_changes=character_changes or [],
            word_count=len(full_text),
        )
        self._save_section_compression(result)
        return result

    def _rule_compress_text(self, text: str, target_chars: int) -> str:
        """规则引擎文本压缩 — 提取关键句子。"""
        if len(text) <= target_chars:
            return text

        # 按段落分割
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
        if not paragraphs:
            return text[:target_chars]

        # 策略：保留首段 + 含关键词的段落 + 末段
        key_indicators = [
            "突然",
            "然而",
            "但是",
            "不过",
            "终于",
            "原来",
            "竟然",
            "决定",
            "发现",
            "意识到",
            "明白",
            "变化",
            "转折",
            "死",
            "伤",
            "破",
            "成功",
            "失败",
            "突破",
        ]

        scored: List[tuple[int, str]] = []
        for i, para in enumerate(paragraphs):
            score = 0
            if i == 0:
                score += 10  # 首段
            if i == len(paragraphs) - 1:
                score += 8  # 末段
            for kw in key_indicators:
                if kw in para:
                    score += 3
            # 对话段落略低优先级
            if "\u300c" in para or "\u300d" in para or "\u201c" in para:
                score -= 1
            scored.append((score, i, para))

        scored.sort(key=lambda x: x[0], reverse=True)

        # 按原始顺序选取段落直到达到目标长度
        selected_indices = set()
        total = 0
        for score, idx, para in scored:
            if total + len(para) > target_chars and selected_indices:
                break
            selected_indices.add(idx)
            total += len(para)

        result_parts = [paragraphs[i] for i in sorted(selected_indices)]
        result = "\n".join(result_parts)

        # 最终截断保护
        if len(result) > target_chars:
            result = self._truncate_at_sentence(result, target_chars)

        return result

    # ── 篇级压缩 ──────────────────────────────────────────────────

    def compress_arc(
        self,
        arc_id: str,
        previous_arc_id: Optional[str] = None,
    ) -> ArcCompression:
        """压缩一个完成的篇(Arc)。

        策略：上一篇压缩好的文字 + 本篇每节压缩的文字 → 合并。
        """
        # 加载上一篇的压缩结果
        previous_summary = ""
        if previous_arc_id:
            prev = self._load_arc_compression(previous_arc_id)
            if prev:
                previous_summary = prev.merged_summary

        # 加载本篇所有节的压缩结果
        section_compressions = self._load_sections_for_arc(arc_id)

        result = ArcCompression(
            arc_id=arc_id,
            previous_arc_summary=previous_summary,
            section_summaries=section_compressions,
            total_word_count=sum(s.word_count for s in section_compressions),
        )
        result.build_merged()

        # 如果合并后超过目标长度，再压缩一次
        if len(result.merged_summary) > ARC_COMPRESS_TARGET:
            result.merged_summary = self._rule_compress_text(
                result.merged_summary, ARC_COMPRESS_TARGET
            )

        self._save_arc_compression(result)
        return result

    # ── 上下文组装 ──────────────────────────────────────────────────

    def build_generation_context(
        self,
        chapter: OutlineNode,
        hierarchy: OutlineHierarchy,
        *,
        manuscript_text: str = "",
        character_profiles: str = "",
        foreshadowing_text: str = "",
        setting_text: str = "",
        style_guide: str = "",
        writing_prompt: str = "",
    ) -> GenerationContext:
        """为写作AI组装完整的 GenerationContext。

        包含：
        - 写作 prompt 基础提示词
        - 500-1000字的上文
        - 上个篇纲结束之前压缩好的内容
        - 大纲中计划好的本篇的部分
        - 相关的伏笔上文
        - 本次更新涉及的非炮灰人物资料
        - 本次更新涉及的相关设定
        - 通用文章风格
        """
        # 找到所属节和篇
        arc_id = ""
        section_id = ""

        # 从 chapter 的父节点找 section 和 arc
        if chapter.parent_id:
            parent = hierarchy.get_node(chapter.parent_id)
            if parent:
                section_id = parent.node_id
                if parent.parent_id:
                    grandparent = hierarchy.get_node(parent.parent_id)
                    if grandparent:
                        arc_id = grandparent.node_id

        # 上文（500-1000字）
        recent_text = self._extract_recent_text(manuscript_text)

        # 前文压缩（上个篇纲的压缩）
        previous_arc_summary = ""
        if arc_id:
            # 简化：从 arc 列表中找前一个
            arcs = [n for n in hierarchy.arcs]
            for i, arc in enumerate(arcs):
                if arc.node_id == arc_id and i > 0:
                    prev_comp = self._load_arc_compression(arcs[i - 1].node_id)
                    if prev_comp:
                        previous_arc_summary = prev_comp.merged_summary
                    break

        # 本篇大纲
        current_arc_plan = ""
        if arc_id:
            arc = hierarchy.get_node(arc_id)
            if arc:
                current_arc_plan = f"篇名：{arc.title}\n摘要：{arc.summary}"

        # 本节大纲
        current_section_plan = ""
        if section_id:
            section = hierarchy.get_node(section_id)
            if section:
                current_section_plan = f"节名：{section.title}\n摘要：{section.summary}"

        # 本章大纲
        current_chapter_plan = f"章名：{chapter.title}\n摘要：{chapter.summary}"
        if chapter.goals:
            current_chapter_plan += f"\n目标：{'、'.join(chapter.goals)}"

        return GenerationContext(
            novel_id=self.novel_id,
            chapter_id=chapter.node_id,
            chapter_goals=chapter.goals,
            writing_prompt=writing_prompt,
            recent_text=recent_text,
            previous_arc_summary=previous_arc_summary,
            current_arc_plan=current_arc_plan,
            current_section_plan=current_section_plan,
            current_chapter_plan=current_chapter_plan,
            foreshadowing_context=foreshadowing_text,
            character_profiles=character_profiles,
            setting_context=setting_text,
            style_guide=style_guide,
        )

    # ── 内部工具 ──────────────────────────────────────────────────

    def _extract_recent_text(self, manuscript_text: str) -> str:
        """从已有稿件中提取最后500-1000字作为上文。"""
        if not manuscript_text:
            return ""
        text = manuscript_text.strip()
        if len(text) <= self.recent_text_max:
            return text

        # 从末尾截取，在句子边界切割
        candidate = text[-self.recent_text_max :]
        # 找第一个句子开头
        first_sentence = re.search(r"[。！？\n]", candidate)
        if (
            first_sentence
            and first_sentence.start() < len(candidate) - self.recent_text_min
        ):
            return candidate[first_sentence.end() :].strip()
        return candidate

    @staticmethod
    def _truncate_at_sentence(text: str, max_chars: int) -> str:
        """在句子边界截断。"""
        if len(text) <= max_chars:
            return text
        region = text[:max_chars]
        ends = list(re.finditer(r"[。！？!?;；\n]", region))
        if ends:
            return text[: ends[-1].end()].strip()
        soft = list(re.finditer(r"[,，、\s]", region))
        if soft:
            return text[: soft[-1].start()].strip()
        return text[:max_chars].strip()

    # ── 持久化 ──────────────────────────────────────────────────

    def _save_section_compression(self, comp: SectionCompression) -> None:
        path = self.compression_dir / "sections" / f"{comp.section_id}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(comp.to_dict(), f, allow_unicode=True, sort_keys=False)

    def _load_section_compression(
        self, section_id: str
    ) -> Optional[SectionCompression]:
        path = self.compression_dir / "sections" / f"{section_id}.yaml"
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return SectionCompression.from_dict(data)

    def _load_sections_for_arc(self, arc_id: str) -> List[SectionCompression]:
        """加载某篇下所有节的压缩结果。"""
        sections_dir = self.compression_dir / "sections"
        if not sections_dir.exists():
            return []
        results = []
        for path in sorted(sections_dir.glob("*.yaml")):
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            comp = SectionCompression.from_dict(data)
            if comp.arc_id == arc_id:
                results.append(comp)
        return results

    def _save_arc_compression(self, comp: ArcCompression) -> None:
        path = self.compression_dir / "arcs" / f"{comp.arc_id}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(comp.to_dict(), f, allow_unicode=True, sort_keys=False)

    def _load_arc_compression(self, arc_id: str) -> Optional[ArcCompression]:
        path = self.compression_dir / "arcs" / f"{arc_id}.yaml"
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return ArcCompression.from_dict(data)

    # ── 全量前文压缩方法（用于上下文组装）──────────────────

    def get_arc_context(self, current_arc_id: str) -> Dict[str, Any]:
        """获取当前篇的压缩上下文

        用于组装写作 AI 的上下文。包含：
        - previous_arc_summary: 上一篇（或更早）的压缩
        - current_arc_sections: 本篇已完成的节压缩列表

        Args:
            current_arc_id: 当前篇 ID

        Returns:
            包含 previous_summary 和 section_summaries 的字典
        """
        # 获取本篇所有节的压缩
        current_sections = self._load_sections_for_arc(current_arc_id)

        # 获取上一篇的压缩
        previous_summary = self._get_previous_arc_summary(current_arc_id)

        return {
            "previous_arc_summary": previous_summary,
            "current_arc_sections": [s.to_dict() for s in current_sections],
        }

    def get_full_previous_summary(self, current_arc_id: str) -> str:
        """获取从开头到当前篇之前的所有压缩内容

        累积所有已完成的篇的压缩，提供完整的上文连贯性。

        Args:
            current_arc_id: 当前篇 ID

        Returns:
            所有前篇的压缩内容（合并后）
        """
        all_summaries: List[str] = []

        # 获取所有篇压缩
        arcs_dir = self.compression_dir / "arcs"
        if arcs_dir.exists():
            arc_files = sorted(arcs_dir.glob("*.yaml"))
            for arc_file in arc_files:
                with arc_file.open("r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                if data.get("arc_id") != current_arc_id:
                    merged = data.get("merged_summary", "")
                    if merged:
                        all_summaries.append(merged)

        return "\n\n".join(all_summaries)

    def _get_previous_arc_summary(self, current_arc_id: str) -> str:
        """获取直接上一篇的压缩摘要

        Args:
            current_arc_id: 当前篇 ID

        Returns:
            上一篇的压缩摘要
        """
        # 尝试从 arc_id 编号推断上一篇
        match = re.match(r"arc_(\d+)", current_arc_id)
        if match:
            arc_num = int(match.group(1))
            if arc_num > 1:
                prev_arc_id = f"arc_{arc_num - 1:03d}"
                prev_comp = self._load_arc_compression(prev_arc_id)
                if prev_comp:
                    return prev_comp.merged_summary

        return ""

    def compress_and_archive_chapter(
        self,
        chapter_id: str,
        chapter_text: str,
        hierarchy: OutlineHierarchy,
    ) -> Optional[SectionCompression]:
        """压缩并归档完成的章节

        在章节写作完成后调用，自动：
        1. 累积章节到当前节
        2. 判断节是否完成
        3. 判断篇是否完成，执行篇压缩

        Args:
            chapter_id: 章节 ID
            chapter_text: 章节文本
            hierarchy: 大纲层级

        Returns:
            节压缩结果（如果有）
        """
        # 找到章节所属的节和篇
        chapter_node = hierarchy.get_node(chapter_id)
        if not chapter_node:
            return None

        section_id = chapter_node.parent_id
        section_node = hierarchy.get_node(section_id) if section_id else None
        arc_id = section_node.parent_id if section_node else None

        # 累积章节文本（这里简化处理，实际应该累积整节的文本）
        # 暂时只压缩单个章节
        if arc_id and section_id:
            result = self.compress_section(
                section_id=section_id,
                arc_id=arc_id,
                full_text=chapter_text,
            )
            return result

        return None
