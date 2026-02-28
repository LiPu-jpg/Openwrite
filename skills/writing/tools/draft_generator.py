"""Draft Generator - 草稿生成器。

将节拍列表扩写为结构化草稿。支持规则引擎和 LLM 两种模式：
- 规则引擎：使用模板生成基础草稿
- LLM：调用大模型将节拍扩写为散文

草稿格式使用段落标记（【场景】、【对话】等）组织内容。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional

from skills.writing.tools.beat_generator import (
    BeatGenerator,
    BeatTemplates,
    SectionMarkers,
)

if TYPE_CHECKING:
    from tools.llm.client import LLMClient
    from tools.llm.router import ModelRouter

logger = logging.getLogger(__name__)


@dataclass
class DraftOutput:
    """草稿输出。"""

    chapter_id: str
    beat_list: List[str]
    draft: str
    metadata: Dict[str, str] = field(default_factory=dict)


class DraftGenerator:
    """草稿生成器。

    将节拍扩写为结构化草稿。支持规则引擎和 LLM 两种模式。

    Attributes:
        beat_generator: 节拍生成器
        markers: 段落标记
        llm_client: LLM 客户端（可选）
        router: 模型路由器（可选）
        style_context: 风格指导文本（可选）
    """

    def __init__(
        self,
        beat_generator: Optional[BeatGenerator] = None,
        markers: Optional[SectionMarkers] = None,
        llm_client: Optional["LLMClient"] = None,
        router: Optional["ModelRouter"] = None,
        style_context: Optional[str] = None,
    ):
        """初始化草稿生成器。

        Args:
            beat_generator: 节拍生成器，为空则创建默认实例
            markers: 段落标记，为空则使用默认标记
            llm_client: LLM 客户端，为空则使用规则引擎
            router: 模型路由器，为空则使用规则引擎
            style_context: 风格指导文本
        """
        self.beat_generator = beat_generator or BeatGenerator()
        self.markers = markers or SectionMarkers.default()
        self._llm_client = llm_client
        self._router = router
        self._style_context = style_context

    def generate_chapter(
        self, chapter_id: str, objective: str, context: Dict[str, str]
    ) -> DraftOutput:
        """生成章节草稿。

        节拍始终由规则引擎生成。当配置了 LLM 时，
        LLM 负责将节拍扩写为散文；否则使用模板生成。

        Args:
            chapter_id: 章节标识符
            objective: 写作目标
            context: 上下文字典

        Returns:
            DraftOutput 包含草稿和元数据
        """
        beats = self.beat_generator.generate_beats(chapter_id, context)

        # LLM 模式
        if self._llm_client and self._router:
            return self._generate_with_llm(chapter_id, objective, context, beats)

        # 规则引擎模式
        return self._generate_rule_based(chapter_id, objective, context, beats)

    def rewrite_chapter(
        self,
        *,
        chapter_id: str,
        objective: str,
        context: Dict[str, str],
        previous_draft: str,
        forbidden: List[str],
        required: List[str],
        errors: List[str],
        warnings: List[str],
        attempt: int,
    ) -> DraftOutput:
        """重写章节草稿。

        根据 LoreChecker 和 Stylist 的反馈重写草稿。

        Args:
            chapter_id: 章节标识符
            objective: 写作目标
            context: 上下文字典
            previous_draft: 上一版草稿
            forbidden: 禁止使用的词/短语
            required: 必须包含的元素
            errors: 错误列表（必须修复）
            warnings: 警告列表（建议修复）
            attempt: 重试轮次

        Returns:
            DraftOutput 包含重写后的草稿
        """
        # LLM 模式
        if self._llm_client and self._router:
            return self._rewrite_with_llm(
                chapter_id=chapter_id,
                objective=objective,
                previous_draft=previous_draft,
                errors=errors,
                warnings=warnings,
                context=context,
                attempt=attempt,
            )

        # 规则引擎模式
        return self._rewrite_rule_based(
            chapter_id=chapter_id,
            objective=objective,
            context=context,
            previous_draft=previous_draft,
            forbidden=forbidden,
            required=required,
            errors=errors,
            warnings=warnings,
            attempt=attempt,
        )

    # ------------------------------------------------------------------
    # 规则引擎生成
    # ------------------------------------------------------------------

    def _generate_rule_based(
        self,
        chapter_id: str,
        objective: str,
        context: Dict[str, str],
        beats: List[str],
    ) -> DraftOutput:
        """规则引擎草稿生成。"""
        outline_brief = context.get("outline", "暂无章节大纲")
        character_brief = context.get("characters", "暂无人物状态")
        foreshadowing_brief = context.get("foreshadowing", "暂无待回收伏笔")
        scene_brief = context.get("scenes", "未标注场景")
        world_brief = context.get("world", "暂无世界观")

        protagonist = self.beat_generator._extract_protagonist(character_brief)
        setting = self.beat_generator._extract_setting(context)

        lines: List[str] = [
            f"# {chapter_id} 章节草稿",
            "",
            "## 写作目标",
            objective,
            "",
            "## 上下文摘要",
            f"- 章节提要: {outline_brief}",
            f"- 人物状态: {character_brief}",
            f"- 待回收伏笔: {foreshadowing_brief}",
            f"- 场景标记: {scene_brief}",
            f"- 世界观: {world_brief}",
            "",
            "## 剧情节拍",
        ]
        lines.extend([f"{idx}. {beat}" for idx, beat in enumerate(beats, start=1)])
        lines.extend(["", "## 草稿正文", ""])
        lines.extend(
            self._generate_draft_body(
                chapter_id=chapter_id,
                beats=beats,
                protagonist=protagonist,
                setting=setting,
                context=context,
            )
        )

        return DraftOutput(
            chapter_id=chapter_id,
            beat_list=beats,
            draft="\n".join(lines) + "\n",
            metadata={
                "beat_count": str(len(beats)),
                "protagonist": protagonist,
                "setting": setting,
            },
        )

    def _generate_draft_body(
        self,
        chapter_id: str,
        beats: List[str],
        protagonist: str,
        setting: str,
        context: Dict[str, str],
    ) -> List[str]:
        """生成结构化草稿正文。"""
        lines: List[str] = []
        foreshadowing = context.get("foreshadowing", "")
        has_foreshadowing = foreshadowing and "暂无" not in foreshadowing

        # 开场场景
        lines.extend(
            [
                f"{self.markers.scene} {setting}",
                "",
                f"{protagonist}站在{setting}的边缘，目光扫过眼前的局面。",
                f"空气中弥漫着一股说不清的紧迫感——不是那种戏剧化的压迫，",
                f"而是像考试前五分钟才发现自己走错考场的那种。",
                "",
            ]
        )

        # 对话部分
        lines.extend(
            [
                f"{self.markers.dialogue}",
                "",
            ]
        )

        characters = context.get("characters", "")
        char_names = re.findall(r"(\S+?)\(境界=", characters)
        if len(char_names) >= 2:
            lines.extend(
                [
                    f"\u300c情况有变。\u300d{char_names[0]}开口，语气里没有多余的修饰。",
                    "",
                    f"\u300c哪种变？好的那种还是坏的那种？\u300d{char_names[1]}问。",
                    "",
                    f"\u300c你觉得呢。\u300d",
                    "",
                    f"\u300c……行吧。\u300d",
                    "",
                ]
            )
        else:
            lines.extend(
                [
                    f"\u300c情况有变。\u300d{protagonist}自言自语，语气平淡得像在念菜单。",
                    "",
                    f"没人回应。这倒也正常——自言自语本来就不指望有人接话。",
                    "",
                ]
            )

        # 动作部分
        lines.extend(
            [
                f"{self.markers.action}",
                "",
                f"{protagonist}做出了决定。不是那种深思熟虑后的决定，",
                f"更像是被推到悬崖边上时本能的选择。",
                "",
            ]
        )

        # 伏笔部分
        if has_foreshadowing:
            lines.extend(
                [
                    f"{self.markers.narration}",
                    "",
                    f"在混乱中，有些细节被忽略了。",
                    f"但这些细节不会永远沉默——它们只是在等一个合适的时机。",
                    "",
                ]
            )

        # 内心独白
        lines.extend(
            [
                f"{self.markers.internal}",
                "",
                f"事情正在朝着不可控的方向发展。{protagonist}清楚这一点。",
                f"但「清楚」和「能做点什么」之间，隔着一条叫做「现实」的鸿沟。",
                "",
            ]
        )

        # 转场收束
        lines.extend(
            [
                f"{self.markers.transition}",
                "",
                f"这一章的故事暂时告一段落。",
                f"但{protagonist}知道，真正的麻烦才刚刚开始。",
                f"至少，他现在多了一个问题需要回答——而答案，不在这里。",
            ]
        )

        return lines

    # ------------------------------------------------------------------
    # 规则引擎重写
    # ------------------------------------------------------------------

    def _rewrite_rule_based(
        self,
        *,
        chapter_id: str,
        objective: str,
        context: Dict[str, str],
        previous_draft: str,
        forbidden: List[str],
        required: List[str],
        errors: List[str],
        warnings: List[str],
        attempt: int,
    ) -> DraftOutput:
        """规则引擎重写。"""
        text = previous_draft

        # 移除禁止词
        for token in forbidden:
            if token and token in text:
                text = self._remove_forbidden(text, token)

        # 添加缺失元素
        missing_required = [t for t in required if t and t not in text]
        if missing_required:
            text = self._integrate_required(text, missing_required, context)

        # 处理错误和警告
        text = self._address_errors(text, errors, context)
        text = self._address_warnings(text, warnings, context)

        # 添加修订记录
        feedback = (errors + warnings)[:5]
        if feedback:
            sanitized: List[str] = []
            for item in feedback:
                clean = item
                for token in forbidden:
                    if token:
                        clean = clean.replace(token, "[已规避]")
                sanitized.append(clean)
            text += f"\n\n> 修订记录（第{attempt}轮）\n"
            text += f"> 处理反馈{len(feedback)}条：{'；'.join(sanitized)}\n"

        beats = self.beat_generator.generate_beats(chapter_id, context)
        return DraftOutput(
            chapter_id=chapter_id,
            beat_list=beats,
            draft=text,
            metadata={"rewrite_attempt": str(attempt)},
        )

    def _remove_forbidden(self, text: str, token: str) -> str:
        """移除禁止词。"""
        lines = text.split("\n")
        new_lines: List[str] = []
        for line in lines:
            if token in line:
                cleaned = line.replace(token, "[已规避词]")
                new_lines.append(cleaned)
            else:
                new_lines.append(line)
        return "\n".join(new_lines)

    def _integrate_required(
        self, text: str, missing: List[str], context: Dict[str, str]
    ) -> str:
        """整合缺失的必备元素。"""
        protagonist = self.beat_generator._extract_protagonist(
            context.get("characters", "")
        )

        insertion_marker = self.markers.narration
        insert_idx = text.find(insertion_marker)

        integration_lines: List[str] = ["\n"]
        for element in missing:
            integration_lines.append(
                f"{protagonist}注意到了{element}的存在——"
                f"这不是偶然，而是局势发展的必然结果。"
            )
            integration_lines.append("")

        integration_text = "\n".join(integration_lines)

        if insert_idx >= 0:
            next_newline = text.find("\n", insert_idx)
            if next_newline >= 0:
                text = text[:next_newline] + integration_text + text[next_newline:]
            else:
                text += integration_text
        else:
            text += integration_text

        return text

    def _address_errors(
        self, text: str, errors: List[str], context: Dict[str, str]
    ) -> str:
        """处理错误。"""
        for error in errors:
            if "禁用设定" in error:
                continue
            if "tension 超出范围" in error:
                continue
            if "mutation" in error:
                if "不存在/不足物品" in error:
                    match = re.search(r"物品: (.+)$", error)
                    if match:
                        item = match.group(1)
                        text = text.replace(
                            f"使用{item}",
                            f"寻找{item}（尚未获得）",
                        )
            if "格式错误" in error or "不支持" in error:
                continue
        return text

    def _address_warnings(
        self, text: str, warnings: List[str], context: Dict[str, str]
    ) -> str:
        """处理警告。"""
        for warning in warnings:
            if "未显式出现必备要素" in warning:
                continue
            if "张力均低于" in warning:
                if "## 草稿正文" in text:
                    text = text.replace(
                        "## 草稿正文",
                        "## 草稿正文\n\n> [张力提升] 本章需要增加冲突强度\n",
                        1,
                    )
            if "情绪标签单一" in warning:
                pass
        return text

    # ------------------------------------------------------------------
    # LLM 生成/重写（占位符，实际实现在 tools.llm.prompts）
    # ------------------------------------------------------------------

    def _generate_with_llm(
        self,
        chapter_id: str,
        objective: str,
        context: Dict[str, str],
        beats: List[str],
    ) -> DraftOutput:
        """LLM 草稿生成。"""
        # 实际实现在 tools.llm.prompts.PromptBuilder.librarian_generate
        # 这里作为占位符，回退到规则引擎
        logger.warning("LLM 调用未实现，回退到规则引擎")
        return self._generate_rule_based(chapter_id, objective, context, beats)

    def _rewrite_with_llm(
        self,
        chapter_id: str,
        objective: str,
        previous_draft: str,
        errors: List[str],
        warnings: List[str],
        context: Dict[str, str],
        attempt: int,
    ) -> DraftOutput:
        """LLM 重写。"""
        # 实际实现在 tools.llm.prompts.PromptBuilder.librarian_rewrite
        # 这里作为占位符，回退到规则引擎
        logger.warning("LLM 重写未实现，回退到规则引擎")
        return self._rewrite_rule_based(
            chapter_id=chapter_id,
            objective=objective,
            context=context,
            previous_draft=previous_draft,
            forbidden=[],
            required=[],
            errors=errors,
            warnings=warnings,
            attempt=attempt,
        )


def load_draft_generator(
    templates_path: Optional[str] = None,
    markers_path: Optional[str] = None,
    llm_client: Optional["LLMClient"] = None,
    router: Optional["ModelRouter"] = None,
    style_context: Optional[str] = None,
) -> DraftGenerator:
    """加载草稿生成器。

    Args:
        templates_path: 节拍模板路径
        markers_path: 段落标记路径
        llm_client: LLM 客户端
        router: 模型路由器
        style_context: 风格指导文本

    Returns:
        DraftGenerator 实例
    """
    from pathlib import Path

    beat_gen = None
    markers = None

    if templates_path:
        templates_path = Path(templates_path)
        if templates_path.exists():
            from skills.writing.tools.beat_generator import BeatTemplates

            beat_gen = BeatGenerator(templates=BeatTemplates.from_yaml(templates_path))

    if markers_path:
        markers_path = Path(markers_path)
        if markers_path.exists():
            markers = SectionMarkers.from_yaml(markers_path)

    return DraftGenerator(
        beat_generator=beat_gen,
        markers=markers,
        llm_client=llm_client,
        router=router,
        style_context=style_context,
    )
