"""Progressive context compressor — 渐进式上下文压缩引擎。

Phase 7 架构重设计核心组件。

压缩策略：
  1. 每节(Section)完成后 → 压缩本节内容为 SectionCompression
  2. 每篇(Arc)完成后 → 上一篇压缩 + 本篇各节压缩 → 合并为 ArcCompression
  3. 每次生成章节时 → 组装完整 GenerationContext（不再是扁平2000字预算）

旧 ContextCompressor 保留不动，本模块为新管线专用。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional

import yaml

try:
    from tools.models.context_package import (
        ArcCompression,
        GenerationContext,
        ReviewContext,
        SectionCompression,
        StylistContext,
    )
    from tools.models.outline import (
        ArcOutline,
        ChapterOutline,
        MasterOutline,
        OutlineHierarchy,
        SectionOutline,
    )
    from tools.models.character import TextCharacterProfile
except ImportError:  # pragma: no cover
    from models.context_package import (
        ArcCompression,
        GenerationContext,
        ReviewContext,
        SectionCompression,
        StylistContext,
    )
    from models.outline import (
        ArcOutline,
        ChapterOutline,
        MasterOutline,
        OutlineHierarchy,
        SectionOutline,
    )
    from models.character import TextCharacterProfile


# ── 压缩参数 ──────────────────────────────────────────────────────

# 上文长度（字符）
RECENT_TEXT_MIN = 500
RECENT_TEXT_MAX = 1000

# 节压缩目标长度
SECTION_COMPRESS_TARGET = 800

# 篇压缩目标长度
ARC_COMPRESS_TARGET = 2000


class ProgressiveCompressor:
    """渐进式上下文压缩器 — 管理节/篇级别的滚动压缩。"""

    def __init__(
        self,
        project_dir: Path,
        novel_id: str,
        recent_text_min: int = RECENT_TEXT_MIN,
        recent_text_max: int = RECENT_TEXT_MAX,
    ):
        self.project_dir = project_dir
        self.novel_id = novel_id
        self.recent_text_min = recent_text_min
        self.recent_text_max = recent_text_max
        self.base_dir = project_dir / "data" / "novels" / novel_id
        self.compression_dir = self.base_dir / "compression"
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
            "突然", "然而", "但是", "不过", "终于", "原来", "竟然",
            "决定", "发现", "意识到", "明白", "变化", "转折",
            "死", "伤", "破", "成功", "失败", "突破",
        ]

        scored: List[tuple] = []
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

        result_parts = [
            paragraphs[i] for i in sorted(selected_indices)
        ]
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
        chapter: ChapterOutline,
        hierarchy: OutlineHierarchy,
        *,
        manuscript_text: str = "",
        characters: Optional[List[TextCharacterProfile]] = None,
        foreshadowing_text: str = "",
        setting_text: str = "",
        style_guide: str = "",
        writing_prompt: str = "",
    ) -> GenerationContext:
        """为写作AI组装完整的 GenerationContext。"""
        # 找到所属节和篇
        section = hierarchy.get_section(chapter.section_id) if chapter.section_id else None
        arc_id = section.arc_id if section else ""
        arc = hierarchy.get_arc(arc_id) if arc_id else None

        # 2. 上文（500-1000字）
        recent_text = self._extract_recent_text(manuscript_text)

        # 3. 前文压缩（上个篇纲的压缩）
        previous_arc_summary = ""
        if arc:
            prev_arc_id = self._find_previous_arc_id(arc_id, hierarchy)
            if prev_arc_id:
                prev_comp = self._load_arc_compression(prev_arc_id)
                if prev_comp:
                    previous_arc_summary = prev_comp.merged_summary

        # 4. 本篇大纲
        current_arc_plan = ""
        if arc:
            current_arc_plan = (
                f"篇名：{arc.title}\n"
                f"主要矛盾：{arc.main_conflict}\n"
                f"收束方向：{arc.resolution}"
            )

        current_section_plan = ""
        if section:
            current_section_plan = (
                f"节名：{section.title}\n"
                f"情节概要：{section.plot_summary}\n"
                f"关键事件：{'、'.join(section.key_events)}"
            )

        current_chapter_plan = ""
        if chapter.goals or chapter.key_scenes:
            parts = []
            if chapter.goals:
                parts.append(f"目标：{'、'.join(chapter.goals)}")
            if chapter.key_scenes:
                parts.append(f"关键场景：{'、'.join(chapter.key_scenes)}")
            if chapter.emotion_arc:
                parts.append(f"情绪弧线：{chapter.emotion_arc}")
            current_chapter_plan = "\n".join(parts)

        # 6. 人物资料
        character_profiles = ""
        if characters:
            profiles = [c.to_context_text() for c in characters]
            character_profiles = "\n\n".join(profiles)

        return GenerationContext(
            novel_id=self.novel_id,
            chapter_id=chapter.chapter_id,
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
            target_words=chapter.target_words,
            emotion_arc=chapter.emotion_arc,
        )

    def build_stylist_context(
        self,
        chapter_id: str,
        draft_text: str,
        manuscript_text: str = "",
        character_voice: str = "",
        style_document: str = "",
    ) -> StylistContext:
        """为文风完善者组装 StylistContext。"""
        recent_text = self._extract_recent_text(manuscript_text)
        return StylistContext(
            novel_id=self.novel_id,
            chapter_id=chapter_id,
            draft_text=draft_text,
            recent_text=recent_text,
            character_voice=character_voice,
            style_document=style_document,
        )

    def build_review_context(
        self,
        chapter_id: str,
        draft_text: str,
        manuscript_text: str = "",
        character_profiles: str = "",
        setting_context: str = "",
        foreshadowing_context: str = "",
        current_chapter_plan: str = "",
    ) -> ReviewContext:
        """为审查AI组装 ReviewContext。"""
        recent_text = self._extract_recent_text(manuscript_text)
        return ReviewContext(
            novel_id=self.novel_id,
            chapter_id=chapter_id,
            draft_text=draft_text,
            recent_text=recent_text,
            character_profiles=character_profiles,
            setting_context=setting_context,
            foreshadowing_context=foreshadowing_context,
            current_chapter_plan=current_chapter_plan,
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
        candidate = text[-self.recent_text_max:]
        # 找第一个句子开头
        first_sentence = re.search(r"[。！？\n]", candidate)
        if first_sentence and first_sentence.start() < len(candidate) - self.recent_text_min:
            return candidate[first_sentence.end():].strip()
        return candidate

    def _find_previous_arc_id(
        self, current_arc_id: str, hierarchy: OutlineHierarchy
    ) -> Optional[str]:
        """在总纲的 arc_ids 列表中找到当前篇的前一篇。"""
        arc_ids = hierarchy.master.arc_ids
        try:
            idx = arc_ids.index(current_arc_id)
            if idx > 0:
                return arc_ids[idx - 1]
        except ValueError:
            pass
        return None

    @staticmethod
    def _truncate_at_sentence(text: str, max_chars: int) -> str:
        """在句子边界截断。"""
        if len(text) <= max_chars:
            return text
        region = text[:max_chars]
        ends = list(re.finditer(r"[。！？!?;；\n]", region))
        if ends:
            return text[:ends[-1].end()].strip()
        soft = list(re.finditer(r"[,，、\s]", region))
        if soft:
            return text[:soft[-1].start()].strip()
        return text[:max_chars].strip()

    # ── 持久化 ──────────────────────────────────────────────────

    def _save_section_compression(self, comp: SectionCompression) -> None:
        path = self.compression_dir / "sections" / f"{comp.section_id}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(
                comp.model_dump(), f, allow_unicode=True, sort_keys=False
            )

    def _load_section_compression(
        self, section_id: str
    ) -> Optional[SectionCompression]:
        path = self.compression_dir / "sections" / f"{section_id}.yaml"
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return SectionCompression.model_validate(data)

    def _load_sections_for_arc(self, arc_id: str) -> List[SectionCompression]:
        """加载某篇下所有节的压缩结果。"""
        sections_dir = self.compression_dir / "sections"
        if not sections_dir.exists():
            return []
        results = []
        for path in sorted(sections_dir.glob("*.yaml")):
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            comp = SectionCompression.model_validate(data)
            if comp.arc_id == arc_id:
                results.append(comp)
        return results

    def _save_arc_compression(self, comp: ArcCompression) -> None:
        path = self.compression_dir / "arcs" / f"{comp.arc_id}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(
                comp.model_dump(), f, allow_unicode=True, sort_keys=False
            )

    def _load_arc_compression(
        self, arc_id: str
    ) -> Optional[ArcCompression]:
        path = self.compression_dir / "arcs" / f"{arc_id}.yaml"
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return ArcCompression.model_validate(data)
