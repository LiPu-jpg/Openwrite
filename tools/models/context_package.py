"""Context package models — 定义写作AI和文风AI每次接收的上下文结构。

Phase 7 架构重设计核心：
  GenerationContext — 写作AI的完整上下文包
  StylistContext — 文风完善者的上下文包
  ArcCompression — 篇纲级压缩结果
  SectionCompression — 节纲级压缩结果
"""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class SectionCompression(BaseModel):
    """节纲级压缩结果 — 一个完整情节单元完成后的摘要。"""

    section_id: str = Field(..., description="节纲ID")
    arc_id: str = Field(default="", description="所属篇纲ID")
    compressed_text: str = Field(default="", description="本节压缩后的文字摘要")
    key_events: List[str] = Field(default_factory=list, description="关键事件列表")
    character_changes: List[str] = Field(
        default_factory=list, description="人物状态变化摘要"
    )
    word_count: int = Field(default=0, description="原文字数")


class ArcCompression(BaseModel):
    """篇纲级压缩结果 — 一个大剧情弧完成后的滚动压缩。

    压缩策略：上一个篇纲压缩好的文字 + 本篇每节压缩的文字 → 合并压缩。
    """

    arc_id: str = Field(..., description="篇纲ID")
    previous_arc_summary: str = Field(
        default="", description="上一个篇纲结束时的累积压缩（如果有）"
    )
    section_summaries: List[SectionCompression] = Field(
        default_factory=list, description="本篇各节的压缩结果"
    )
    merged_summary: str = Field(
        default="", description="合并后的完整压缩文字（previous + sections）"
    )
    total_word_count: int = Field(default=0, description="本篇原文总字数")

    def build_merged(self) -> str:
        """将 previous_arc_summary + 各节摘要合并为完整压缩文字。"""
        parts: List[str] = []
        if self.previous_arc_summary:
            parts.append(self.previous_arc_summary)
        for sec in self.section_summaries:
            if sec.compressed_text:
                parts.append(sec.compressed_text)
        self.merged_summary = "\n".join(parts)
        return self.merged_summary


class GenerationContext(BaseModel):
    """写作AI的完整上下文包 — 每次生成章节时由调度器组装。

    包含用户要求的全部要素：
    1. writing_prompt — 写作prompt基础提示词
    2. recent_text — 500-1000字的上文（保持完整性与风格一致）
    3. previous_arc_summary — 上个篇纲结束之前压缩好的内容
    4. current_arc_plan — 大纲中计划好的本篇的部分
    5. foreshadowing_context — 相关的伏笔上文
    6. character_profiles — 本次更新涉及的非炮灰人物资料
    7. setting_context — 本次更新涉及的相关设定（地点、道具等）
    8. style_guide — 通用文章风格文档
    """

    # 基础信息
    novel_id: str = Field(default="", description="小说ID")
    chapter_id: str = Field(default="", description="当前章节ID")
    chapter_goals: List[str] = Field(default_factory=list, description="本章写作目标")

    # 1. 写作prompt基础提示词
    writing_prompt: str = Field(
        default="", description="写作基础提示词（角色设定、写作要求等）"
    )

    # 2. 上文（500-1000字）
    recent_text: str = Field(
        default="",
        description="前文500-1000字，用于保持完整性与风格一致",
    )

    # 3. 前文压缩
    previous_arc_summary: str = Field(
        default="",
        description="上个篇纲结束之前压缩好的内容",
    )

    # 4. 本篇大纲
    current_arc_plan: str = Field(default="", description="大纲中计划好的本篇的部分")
    current_section_plan: str = Field(default="", description="当前节纲的情节计划")
    current_chapter_plan: str = Field(default="", description="当前章纲的详细计划")

    # 5. 伏笔上下文
    foreshadowing_context: str = Field(
        default="", description="相关的伏笔上文（待回收/待埋设）"
    )

    # 6. 人物资料（仅非炮灰）
    character_profiles: str = Field(
        default="",
        description="本次更新涉及的非炮灰人物资料（TextCharacterProfile格式）",
    )

    # 7. 相关设定
    setting_context: str = Field(
        default="",
        description="本次更新涉及的相关设定（地点、道具、世界观规则等）",
    )

    # 8. 通用文章风格
    style_guide: str = Field(default="", description="通用文章风格文档")

    # 额外元数据
    target_words: int = Field(default=6000, description="目标字数")
    emotion_arc: str = Field(default="", description="情绪弧线描述")

    def to_prompt_sections(self) -> Dict[str, str]:
        """将上下文包转为有序的 prompt 段落字典，供 LLM 调用。"""
        sections: Dict[str, str] = {}
        if self.writing_prompt:
            sections["写作指令"] = self.writing_prompt
        if self.previous_arc_summary:
            sections["前文摘要"] = self.previous_arc_summary
        if self.recent_text:
            sections["上文"] = self.recent_text
        if self.current_arc_plan:
            sections["本篇大纲"] = self.current_arc_plan
        if self.current_section_plan:
            sections["本节计划"] = self.current_section_plan
        if self.current_chapter_plan:
            sections["本章计划"] = self.current_chapter_plan
        if self.foreshadowing_context:
            sections["伏笔"] = self.foreshadowing_context
        if self.character_profiles:
            sections["人物资料"] = self.character_profiles
        if self.setting_context:
            sections["相关设定"] = self.setting_context
        if self.style_guide:
            sections["风格指南"] = self.style_guide
        if self.chapter_goals:
            sections["本章目标"] = "\n".join(f"- {g}" for g in self.chapter_goals)
        if self.emotion_arc:
            sections["情绪弧线"] = self.emotion_arc
        return sections

    def estimate_token_count(self) -> int:
        """粗略估算总 token 数（中文约1.5字/token）。"""
        total_chars = sum(len(v) for v in self.to_prompt_sections().values())
        return int(total_chars / 1.5)


class StylistContext(BaseModel):
    """文风完善者的上下文包 — 用户确认后由调度器组装。

    包含：
    1. recent_text — 500-1000字的上文（保持完整性与风格一致）
    2. character_voice — 人物性格设定、人物语气设定
    3. style_document — 本作品专属文风文档
    """

    novel_id: str = Field(default="", description="小说ID")
    chapter_id: str = Field(default="", description="当前章节ID")

    # 待润色的草稿
    draft_text: str = Field(default="", description="待润色的章节草稿")

    # 1. 上文
    recent_text: str = Field(
        default="",
        description="前文500-1000字，用于保持完整性与风格一致",
    )

    # 2. 人物语气
    character_voice: str = Field(
        default="",
        description="涉及人物的性格设定与语气设定",
    )

    # 3. 专属文风文档
    style_document: str = Field(
        default="", description="本作品专属文风文档（composed style）"
    )

    def to_prompt_sections(self) -> Dict[str, str]:
        """将上下文包转为有序的 prompt 段落字典。"""
        sections: Dict[str, str] = {}
        if self.recent_text:
            sections["上文"] = self.recent_text
        if self.character_voice:
            sections["人物语气"] = self.character_voice
        if self.style_document:
            sections["文风文档"] = self.style_document
        sections["待润色草稿"] = self.draft_text
        return sections


class ReviewContext(BaseModel):
    """审查AI的上下文包 — 一致性核查用。

    审查AI对作品生成内容仅有读取权限。
    只有十分严重的逻辑错误才交给上一步修改，
    其他轻度或没问题提示使用者进行文字逻辑与走向确认。
    """

    novel_id: str = Field(default="", description="小说ID")
    chapter_id: str = Field(default="", description="当前章节ID")

    # 待审查草稿
    draft_text: str = Field(default="", description="待审查的章节草稿")

    # 审查参考
    recent_text: str = Field(default="", description="前文（用于连续性检查）")
    character_profiles: str = Field(
        default="", description="涉及人物资料（用于一致性检查）"
    )
    setting_context: str = Field(default="", description="相关设定（用于逻辑检查）")
    foreshadowing_context: str = Field(
        default="", description="伏笔上下文（用于伏笔一致性）"
    )
    current_chapter_plan: str = Field(
        default="", description="本章计划（用于走向检查）"
    )


class ReviewResult(BaseModel):
    """审查AI的输出结果。"""

    passed: bool = Field(default=True, description="是否通过审查")
    severity: str = Field(
        default="none",
        description="问题严重程度: none/mild/severe",
    )
    errors: List[str] = Field(
        default_factory=list, description="严重逻辑错误（需要重写）"
    )
    warnings: List[str] = Field(
        default_factory=list, description="轻度问题（提示用户确认）"
    )
    suggestions: List[str] = Field(default_factory=list, description="改进建议")
