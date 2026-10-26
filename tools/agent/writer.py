"""WriterAgent - 两阶段写作 Agent

核心能力：
- Phase 1: 创意写作 (temperature=0.7)
- Phase 2: 状态结算
  - 2a. Observer: 提取本章事实
  - 2b. Settler: 合并到真相文件

结合本项目能力：
- 四级大纲架构
- 渐进压缩
- 风格系统

附加能力：
- 后置验证 (PostWriteValidator)
- 对话指纹提取 (DialogueFingerprintExtractor)
- 状态验证 (StateValidator)
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..character_state_index import normalize_character_state_annotation_fences
from ..llm import Message
from ..novel_workspace import count_writing_units
from ..outline_contract import INLINE_ANNOTATION_CONTRACT
from ..runtime_state_contract import RUNTIME_DELTA_PROMPT_CONTRACT
from .base import BaseAgent

logger = logging.getLogger(__name__)


@dataclass
class WritingResult:
    """写作结果"""

    chapter_number: int
    title: str
    content: str
    word_count: int
    observations: str = ""
    state_updates: dict = field(default_factory=dict)
    state_delta: dict = field(default_factory=dict)
    chapter_summary: str = ""
    validation_issues: list = field(default_factory=list)
    length_out_of_range: bool = False
    length_warning: str = ""
    token_usage: dict = field(default_factory=dict)
    finish_reason: str = ""
    model: str = ""
    provider: str = ""
    model_calls: int = 0


class WriterAgent(BaseAgent):
    """两阶段写作 Agent

    用法:
        from tools.llm import LLMClient, LLMConfig
        from tools.agent import WriterAgent, AgentContext

        config = LLMConfig.from_env()
        client = LLMClient(config)
        ctx = AgentContext(client, config.model, project_root)

        writer = WriterAgent(ctx)
        result = await writer.write_chapter(
            context=context,
            chapter_number=5,
            temperature=0.7
        )
    """

    def get_name(self) -> str:
        return "writer"

    def chat(self, *args, usage_stage="draft", segment_index=None, attempt_index=1, **kwargs):
        """Retain billing provenance for every provider attempt, including failures."""
        from tools.llm.cancellation import check_model_cancellation

        check_model_cancellation()

        def tagged(usage, *, error="", model=""):
            raw = dict(usage or {})
            raw.pop("calls", None)
            raw.setdefault("cost_reported", False)
            if raw.get("cost_reported") is True:
                cost = raw.get("cost_usd")
                raw["cost_reported"] = (
                    type(cost) in {int, float} and math.isfinite(cost) and cost >= 0
                )
            entry = {
                "stage": usage_stage,
                "segment_index": segment_index,
                "attempt_index": attempt_index,
                "model": model or self.ctx.model,
                "usage": dict(raw),
                "error_code": error,
            }
            if not hasattr(self, "_usage_history"):
                self._usage_history = []
            self._usage_history.append(entry)
            return {**raw, "calls": [entry]}

        try:
            response = super().chat(*args, **kwargs)
        except Exception as exc:
            exc.usage = tagged(
                getattr(exc, "usage", {}), error=str(getattr(exc, "code", "PROVIDER_CALL_FAILED"))
            )
            raise
        response.usage = tagged(response.usage, model=str(getattr(response, "model", "") or ""))
        return response

    async def write_chapter(
        self,
        context: dict,
        chapter_number: int,
        temperature: float = 0.7,
        target_words: int | None = None,
    ) -> WritingResult:
        """写章节（两阶段）

        Args:
            context: 写作上下文（包含大纲、角色、伏笔等）
            chapter_number: 章节编号
            temperature: 创意写作温度
            target_words: 目标字数

        Returns:
            WritingResult 写作结果
        """
        target_words = target_words or context.get("target_words", 6000)
        self.model_call_count = 0
        self._usage_history = []

        self.log.info(f"Phase 1: creative writing for chapter {chapter_number}")

        # ── Phase 1: 创意写作 ──
        creative_result = await self._creative_write(
            context=context,
            chapter_number=chapter_number,
            temperature=temperature,
            target_words=target_words,
        )

        on_draft = getattr(self.ctx, "on_draft", None)
        if callable(on_draft):
            on_draft(creative_result)

        self.log.info(
            f"Phase 2: state settlement for chapter {chapter_number} "
            f"({creative_result['word_count']} writing units)"
        )

        # ── Phase 1.5: 后置验证（零 LLM 成本）─
        validation_issues = self._post_write_validation(creative_result["content"])

        # ── Phase 2: 状态结算 ──
        settlement_result = await self._settle_state(
            context=context,
            chapter_number=chapter_number,
            title=creative_result["title"],
            content=creative_result["content"],
        )

        # ── Phase 2.5: 状态验证 ──
        state_issues = self._validate_state_consistency(
            settlement_result.get("state_updates", {}),
            creative_result["content"],
            chapter_number,
        )

        all_issues = validation_issues + state_issues
        if creative_result.get("length_out_of_range"):
            from ..post_validator import ValidationViolation

            all_issues = [
                *all_issues,
                ValidationViolation(
                    severity="warning",
                    rule="length_out_of_range",
                    description=str(
                        creative_result.get("length_warning") or "正文字数不在目标区间"
                    ),
                    location="可在导出前人工去水或拆分章节",
                ),
            ]

        return WritingResult(
            chapter_number=chapter_number,
            title=creative_result["title"],
            content=creative_result["content"],
            word_count=creative_result["word_count"],
            observations=settlement_result["observations"],
            state_updates=settlement_result["state_updates"],
            state_delta=settlement_result.get("state_delta", {}),
            chapter_summary=settlement_result["chapter_summary"],
            validation_issues=all_issues,
            length_out_of_range=bool(creative_result.get("length_out_of_range")),
            length_warning=str(creative_result.get("length_warning") or ""),
            token_usage=self._merge_usage(
                creative_result.get("usage", {}),
                settlement_result.get("usage", {}),
            ),
            finish_reason=str(creative_result.get("finish_reason") or ""),
            model=str(creative_result.get("model") or ""),
            provider=str(creative_result.get("provider") or ""),
            model_calls=getattr(self, "model_call_count", 0),
        )

    async def _creative_write(
        self,
        context: dict,
        chapter_number: int,
        temperature: float,
        target_words: int,
    ) -> dict:
        """Phase 1: 创意写作"""
        context = self._serial_context(context, chapter_number)
        resume_content = str(context.pop("_resume_draft", "") or "")
        if resume_content:
            from types import SimpleNamespace

            return await self._segmented_write(
                context,
                chapter_number,
                temperature,
                target_words,
                initial_response=SimpleNamespace(
                    content=resume_content, usage={}, finish_reason="resume"
                ),
            )
        if target_words >= 6000 and context.get("segmented_write", True):
            return await self._segmented_write(context, chapter_number, temperature, target_words)
        system_prompt = self._build_creative_system_prompt(context)
        user_prompt = self._build_creative_user_prompt(
            context=context,
            chapter_number=chapter_number,
            target_words=target_words,
        )

        messages = [
            Message("system", system_prompt),
            Message("user", user_prompt),
        ]
        response = await self._creative_chat(
            messages=messages,
            temperature=temperature,
            max_tokens=None,  # Respect the selected model profile output budget.
        )
        first_usage = response.usage if response.usage else {}
        try:
            parsed = self._parse_creative_output(
                response.content,
                chapter_number,
                first_usage,
                target_words=target_words,
            )
            parsed.update(
                {
                    "finish_reason": str(getattr(response, "finish_reason", "") or ""),
                    "model": str(getattr(response, "model", "") or ""),
                    "provider": str(getattr(response, "provider", "") or ""),
                }
            )
            return parsed
        except Exception as exc:
            from ..llm.response import ProviderResponseError

            if not isinstance(exc, ProviderResponseError) or exc.code != (
                "CHAPTER_LENGTH_OUT_OF_RANGE"
            ):
                raise

        # Two bounded edits precede the single full-prose fallback.
        from ..writing_policy import chapter_word_bounds

        minimum_words, _, maximum_words = chapter_word_bounds(target_words)
        initial = self._parse_creative_output(response.content, chapter_number, first_usage)
        if initial["word_count"] < minimum_words and context.get("segmented_write", True):
            return await self._segmented_write(
                context, chapter_number, temperature, target_words, initial_response=response
            )
        current_content = response.content
        final_response = response
        all_usage = [first_usage]

        for attempt in range(3):
            from tools.llm.cancellation import check_model_cancellation

            check_model_cancellation()
            word_count = self._parse_creative_output(current_content, chapter_number, {})[
                "word_count"
            ]
            if minimum_words <= word_count <= maximum_words:
                break
            comparison = "低于" if word_count < minimum_words else "超过"
            action = "扩充" if word_count < minimum_words else "精简"
            detail = (
                "补充场景描写、人物互动和心理活动"
                if word_count < minimum_words
                else "删除重复和冗余描写"
            )
            hint = (
                f"长度不合格：你上一版正文约 {word_count} 字（不含标题和内联批注），{comparison}"
                f"目标区间 {minimum_words}-{maximum_words}。请{action}"
                f"正文至 {target_words} 字左右：保留既定情节与章末悬念，"
                f"{detail}。"
            )
            if attempt < 2:
                hint += (
                    '\n先做定点修改，保留未改段落。只返回 JSON：{"edits": [{"old": "原文中唯一的连续片段", "new": "扩写或精简后的片段"}]}。'
                    "每个 old 必须逐字引用且仅出现一次；不得返回完整章节。"
                )
            else:
                hint += "只输出章节标题和完整正文，不要解释。"
            getattr(self, "log", logger).info(
                f"Length retry #{attempt + 1}: {word_count} writing units "
                f"(target {minimum_words}-{maximum_words})"
            )
            retry_response = await self._creative_chat(
                messages=[
                    *messages,
                    Message("assistant", current_content),
                    Message("user", hint),
                ],
                temperature=max(0.2, temperature - 0.15),
                max_tokens=None,  # Respect the selected model profile output budget.
            )
            if retry_response.usage:
                all_usage.append(retry_response.usage)
            if attempt < 2:
                try:
                    from ..llm.response import load_structured_mapping, ProviderResponseError

                    edits = load_structured_mapping(retry_response.content).get("edits")
                    candidate = current_content
                    if not isinstance(edits, list) or not edits:
                        raise ValueError("No length edits")
                    for item in edits:
                        old, new = item["old"], item["new"]
                        if (
                            not isinstance(old, str)
                            or not isinstance(new, str)
                            or not old
                            or candidate.count(old) != 1
                        ):
                            raise ValueError("Length edit is not uniquely anchored")
                        candidate = candidate.replace(old, new, 1)
                    self._parse_creative_output(candidate, chapter_number, {})
                    current_content = candidate
                except (ValueError, KeyError, TypeError, ProviderResponseError):
                    continue
            else:
                current_content = retry_response.content
            final_response = retry_response

        merged_usage = self._merge_usage(*all_usage)
        try:
            parsed = self._parse_creative_output(
                current_content,
                chapter_number,
                merged_usage,
                target_words=target_words,
            )
        except Exception as exc:
            from ..llm.response import ProviderResponseError

            if not isinstance(exc, ProviderResponseError) or exc.code != (
                "CHAPTER_LENGTH_OUT_OF_RANGE"
            ):
                raise
            # 精简重试已耗尽：保留最后一版正文（去水/分章可由人工处理），
            # 标记后回流给调用方，而不是丢弃整份初稿。
            parsed = self._parse_creative_output(current_content, chapter_number, merged_usage)
            parsed["length_out_of_range"] = True
            parsed["length_warning"] = str(exc)
        parsed.update(
            {
                "finish_reason": str(getattr(final_response, "finish_reason", "") or ""),
                "model": str(getattr(final_response, "model", "") or ""),
                "provider": str(getattr(final_response, "provider", "") or ""),
            }
        )
        return parsed

    async def _creative_chat(self, **kwargs):
        """Bound retries to transient generation failures; cancellation propagates."""
        failures = []
        for attempt in range(3):
            from tools.llm.cancellation import check_model_cancellation

            check_model_cancellation()
            try:
                response = self.chat(**kwargs, attempt_index=attempt + 1)
                if failures:
                    response.usage = self._merge_usage(*failures, response.usage)
                return response
            except Exception as exc:
                if (
                    getattr(exc, "code", "")
                    not in {"PROVIDER_NETWORK_ERROR", "MODEL_OUTPUT_TRUNCATED"}
                    or attempt == 2
                ):
                    if failures:
                        exc.usage = self._merge_usage(*failures, getattr(exc, "usage", {}) or {})
                    raise
                failures.append(getattr(exc, "usage", None) or {"cost_reported": False})
                self.log.info("Generation retry %s after %s", attempt + 2, exc.code)
                await asyncio.sleep(2**attempt)

    def _serial_context(self, context: dict, chapter_number: int) -> dict:
        import yaml
        from tools.writing_assets import WritingAssets

        if not getattr(getattr(self, "ctx", None), "project_root", None):
            return context
        root = Path(self.ctx.project_root)
        novel_id = getattr(self.ctx, "book_id", None)
        if not novel_id and (root / "novel_config.yaml").is_file():
            config = yaml.safe_load((root / "novel_config.yaml").read_text(encoding="utf-8")) or {}
            novel_id = config.get("novel_id")
        if not novel_id:
            return context
        source_assets = WritingAssets(root, novel_id)
        assets = source_assets.context(f"ch_{chapter_number:03d}")
        result = {**context, **assets}
        if (root / "novel_config.yaml").is_file():
            options = yaml.safe_load((root / "novel_config.yaml").read_text(encoding="utf-8")) or {}
            options = options.get("writing_options", {})
            if isinstance(options, dict):
                for key in ("segmented_write", "segment_similarity_threshold"):
                    if key in options:
                        result.setdefault(key, options[key])
        from tools.arc_audit import ArcAuditService
        plans = ArcAuditService(root, novel_id).chapter_guidance(f"ch_{chapter_number:03d}")
        if plans:
            result["external_context"] = str(context.get("external_context") or "") + "\n后文回收计划：\n" + "\n".join(plans)
        # Group texts are optional descriptive material. Canonical identity,
        # relationships and state remain in the original character card.
        characters = []
        incoming = context.get("active_characters") or [
            {"name": name, "description": text}
            for name, text in (context.get("character_documents") or {}).items()
        ]
        group_table = source_assets.load()["character_groups"]
        for item in incoming:
            if not isinstance(item, dict):
                continue
            description = str(item.get("description") or "")
            groups = group_table.get(item.get("name"), [])
            for group in groups:
                description = description.replace(group["text"], "")
            selected = assets["character_group_selection"].get(item.get("name"), [])
            if selected:
                description += "\n本章可用描写素材（不必全部使用）：\n" + "\n".join(g["text"] for g in selected)
            characters.append({**item, "description": description})
        if characters:
            result["active_characters"] = characters
        return result

    async def _segmented_write(self, context: dict, chapter_number: int, temperature: float,
                               target_words: int, initial_response=None) -> dict:
        from tools.writing_assets import join_segment
        from tools.writing_policy import chapter_word_bounds

        minimum, _, maximum = chapter_word_bounds(target_words)
        planned = max(1, math.ceil(target_words / 2500))
        beats = list(context.get("chapter_beats") or context.get("chapter_requirements", {}).get("beats") or [])
        current = initial_response.content if initial_response else ""
        initial_count = (
            self._parse_creative_output(current, chapter_number, {})["word_count"] if current else 0
        )
        if initial_response:
            planned = max(1, math.ceil(max(0, target_words - initial_count) / 2500))
        usages = [initial_response.usage] if initial_response and initial_response.usage else []
        response = initial_response
        completed = 0
        # Bounded generation, including repair continuations for early model stops.
        for index in range(planned + 3):
            count = self._parse_creative_output(current, chapter_number, {})["word_count"] if current else 0
            if count >= minimum and (initial_response or completed >= planned):
                break
            remaining = max(1, target_words - count)
            slots = max(1, planned - completed)
            segment_target = min(3000, math.ceil(remaining / slots))
            segment_context = dict(context)
            start = math.floor(count * len(beats) / target_words)
            end = math.ceil(min(target_words, count + segment_target) * len(beats) / target_words)
            segment_context["chapter_beats"] = beats[start:end] if completed < planned else []
            final = segment_target >= remaining
            if not final:
                segment_context.pop("chapter_hooks", None)
            prompt = self._build_creative_user_prompt(segment_context, chapter_number, segment_target)
            prompt += (f"\n这是同一章的第 {completed + 1} 段，本章总目标 {target_words} 字，已完成 {count} 字。"
                       f"本段约 {segment_target} 字。只写本段，按当前节拍推进；"
                       "不要重复前文、不要复述人物卡。")
            prompt += "不要重复章节标题。" if current else "首段须输出章节标题和本段正文。"
            prompt += "本段完成章末钩子。" if final else "本段不要结束整章，为下一段保留行动。"
            messages = [Message("system", self._build_creative_system_prompt(segment_context))]
            if current:
                messages.append(Message("assistant", current[-1500:]))
                prompt += "\n从上述前文尾部之后直接续写，不得重写已经完成的段落。"
            messages.append(Message("user", prompt))
            try:
                response = await self._creative_chat(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=None,
                    segment_index=completed + 1,
                )
            except Exception as exc:
                partial = str(getattr(exc, "partial_content", "") or "")
                if current:
                    exc.partial_content = join_segment(current, partial) if partial else current
                exc.usage = self._merge_usage(*usages, getattr(exc, "usage", {}) or {})
                raise
            if response.usage:
                usages.append(response.usage)
            new = (
                join_segment(
                    current,
                    response.content,
                    similarity_threshold=float(context.get("segment_similarity_threshold", 0.96)),
                )
                if current
                else response.content
            )
            if new == current:
                break
            current = new
            completed += 1
            parsed = self._parse_creative_output(current, chapter_number, self._merge_usage(*usages))
            on_draft = getattr(getattr(self, "ctx", None), "on_draft", None)
            if callable(on_draft):
                on_draft({**parsed, "segmented": True, "segments_completed": completed})
            if parsed["word_count"] >= maximum:
                break
        parsed = self._parse_creative_output(current, chapter_number, self._merge_usage(*usages))
        parsed.update(segmented=True, segments_completed=completed,
                      finish_reason=str(getattr(response, "finish_reason", "") or ""),
                      model=str(getattr(response, "model", "") or ""),
                      provider=str(getattr(response, "provider", "") or ""))
        if not minimum <= parsed["word_count"] <= maximum:
            parsed.update(length_out_of_range=True,
                          length_warning=f"Chapter has {parsed['word_count']} writing units; expected {minimum}-{maximum}")
        return parsed

    def _build_creative_system_prompt(self, context: dict) -> str:
        """构建创意写作系统提示"""
        parts = []

        # 基本角色指导
        parts.append("""你是一位专业的小说作家，擅长创作引人入胜的故事。
写作风格要求：
- 生动具体的描写，避免抽象概括
- 对话自然，符合角色性格
- 节奏紧凑，高潮迭起
- 情感真挚，代入感强

中文网络小说惯例：
- 第三人称或第一人称叙事
- 章节结尾留有悬念
- 适当的环境描写烘托气氛
- 人物心理通过动作和表情展现""")
        parts.append(INLINE_ANNOTATION_CONTRACT)
        if context.get("term_table"):
            import json
            parts.append("项目术语表（规范词、禁用词、最低次数与用法）：\n" +
                         json.dumps(context["term_table"], ensure_ascii=False))
            parts.append("最低出现次数按整章计算，不要求每个分段都达到该次数。")
        if context.get("anchor_samples"):
            parts.append("范本仅供句法、节奏和段落结构参照。禁止照抄具体句子、情节与专名。\n" +
                         "\n\n".join(context["anchor_samples"].values()))

        # 题材指导
        if context.get("genre"):
            parts.append(f"\n题材：{context['genre']}")
            if context.get("genre_guide"):
                parts.append(f"题材指南：\n{context['genre_guide']}")

        # 风格指导
        if context.get("style_profile"):
            parts.append(f"\n风格要求：\n{context['style_profile']}")

        # 禁忌
        if context.get("taboos"):
            parts.append(f"\n写作禁忌：\n{context['taboos']}")

        return "\n\n".join(parts)

    def _build_creative_user_prompt(
        self,
        context: dict,
        chapter_number: int,
        target_words: int,
    ) -> str:
        """构建创意写作用户提示"""
        parts = []

        # 章节信息
        parts.append(f"# 第{chapter_number}章写作任务\n")
        from ..writing_policy import chapter_word_bounds

        minimum_words, _, maximum_words = chapter_word_bounds(target_words)
        parts.append(
            f"目标字数：约{target_words}字；正文必须控制在"
            f"{minimum_words}-{maximum_words}字内（中文字符与外文单词，"
            "不含标题和内联批注）。达到上限时优先收束情节，"
            "不要用额外支线扩写。\n"
        )

        if context.get("author_intent"):
            parts.append(f"## 作者意图（长期约束）\n{context['author_intent']}\n")

        if context.get("creative_focus"):
            parts.append(f"## 创作罗盘（本次最高优先级）\n{context['creative_focus']}\n")

        # 大纲
        if context.get("outline"):
            parts.append(f"## 本章大纲\n{context['outline']}\n")

        # 章节目标
        if context.get("chapter_goals"):
            goals = "\n".join(f"- {g}" for g in context["chapter_goals"])
            parts.append(f"## 章节目标\n{goals}\n")
        if context.get("chapter_promise"):
            parts.append(f"## 本章可观察状态承诺\n{context['chapter_promise']}")
        if context.get("chapter_payoffs"):
            parts.append("## 本章回收伏笔 ID\n" + ", ".join(context["chapter_payoffs"]))

        if context.get("chapter_beats"):
            beats = "\n".join(f"- {item}" for item in context["chapter_beats"])
            parts.append(f"## 章内节拍（按顺序落实）\n{beats}\n")

        if context.get("chapter_hooks"):
            hooks = "\n".join(f"- {item}" for item in context["chapter_hooks"])
            parts.append(f"## 章末悬念（正文结尾必须承接）\n{hooks}\n")

        if context.get("emotion_arc"):
            parts.append(f"## 章内情感弧线\n{context['emotion_arc']}\n")

        if context.get("scene_context"):
            from tools.scene_integration import render_scene_context

            rendered_scenes = render_scene_context(context["scene_context"])
            if rendered_scenes:
                parts.append(f"## 本章场景结构（按顺序落实）\n{rendered_scenes}\n")

        # 戏剧位置
        if context.get("dramatic_context"):
            parts.append(f"## 戏剧位置\n{context['dramatic_context']}\n")

        # 角色
        if context.get("active_characters"):
            chars = "\n\n".join(
                f"### {c['name']}\n{c.get('description', '暂无描述')}"
                for c in context["active_characters"]
            )
            parts.append(f"## 本章出场角色\n{chars}\n")

        # 伏笔
        if context.get("foreshadowing_summary"):
            parts.append(
                f"## 规范伏笔摘要（只推进与本章相关的条目）\n{context['foreshadowing_summary']}\n"
            )
        elif context.get("foreshadowing"):
            pending = context["foreshadowing"].get("pending", [])
            if pending:
                hooks = "\n".join(f"- {h['content']}" for h in pending[:5])
                parts.append(f"## 待回收伏笔（选择性埋设）\n{hooks}\n")

        # 真相文件
        if context.get("character_states"):
            parts.append(f"## 人物当前状态（内联批注）\n{context['character_states']}\n")

        if context.get("current_state"):
            parts.append(f"## 世界当前状态\n{context['current_state']}\n")

        if context.get("ledger"):
            parts.append(f"## 资源账本\n{context['ledger']}\n")

        if context.get("relationships"):
            parts.append(f"## 人物关系\n{context['relationships']}\n")

        if context.get("recent_chapters"):
            parts.append(f"## 前文内容\n{context['recent_chapters']}\n")

        if context.get("semantic_references"):
            parts.append(
                "## 远程相关片段（语义召回，仅供参考，不覆盖人物状态和正典事实）\n"
                f"{context['semantic_references']}\n"
            )

        if context.get("chapter_summaries"):
            parts.append(f"## 历史章节记忆\n{context['chapter_summaries']}\n")

        # 外部上下文
        if context.get("external_context"):
            parts.append(f"## 额外要求\n{context['external_context']}\n")

        return "\n".join(parts)

    def _parse_creative_output(
        self,
        content: str,
        chapter_number: int,
        usage: dict,
        *,
        target_words: int = 0,
    ) -> dict:
        """解析创意写作输出"""
        if not str(content or "").strip():
            raise RuntimeError("empty model reply")

        content = re.sub(
            r"<(?:think|analysis|reasoning)\b[^>]*>.*?</(?:think|analysis|reasoning)>",
            "",
            content,
            flags=re.I | re.S,
        ).strip()
        if re.search(r"<(?:think|analysis|reasoning)\b", content, re.I):
            from ..llm.response import ProviderResponseError

            raise ProviderResponseError(
                "MANUSCRIPT_STRUCTURE_INVALID", "Unclosed reasoning block in model output"
            )

        # 尝试提取标题
        title_match = re.search(
            r"^#{1,6}[ \t]*第[ \t]*[0-9零〇一二三四五六七八九十百千两]+[ \t]*章"
            r"[ \t]*[:：\-—]?[ \t]*(.*?)[ \t]*$|^#{1,6}[ \t]*Chapter[ \t]+[\dIVXLC]+[ \t]*[:：\-—]?[ \t]*(.*?)[ \t]*$",
            content,
            re.MULTILINE,
        )
        if title_match:
            if content[: title_match.start()].strip():
                from ..llm.response import ProviderResponseError

                raise ProviderResponseError(
                    "MANUSCRIPT_STRUCTURE_INVALID", "Unexpected preamble before chapter heading"
                )
            title = (title_match.group(1) or "").strip() or f"第{chapter_number}章"
            if title_match.group(2) is not None:
                title = title_match.group(0).lstrip("# ").strip()
            body = content[title_match.end() :].strip()
        else:
            from ..llm.response import ProviderResponseError

            raise ProviderResponseError(
                "MANUSCRIPT_STRUCTURE_INVALID", "Model output must begin with a chapter heading"
            )

        body = normalize_character_state_annotation_fences(body).strip()
        word_count = count_writing_units(body)
        if target_words > 0:
            from ..writing_policy import chapter_word_bounds

            minimum_words, _, maximum_words = chapter_word_bounds(target_words)
            if word_count < minimum_words or word_count > maximum_words:
                from ..llm.response import ProviderResponseError

                raise ProviderResponseError(
                    "CHAPTER_LENGTH_OUT_OF_RANGE",
                    f"正文约 {word_count} 字（不含标题和内联批注），不在目标区间 "
                    f"{minimum_words}-{maximum_words} 内; suggested_target_words={max(200, int(word_count / 1.5) + 1)}",
                )

        return {
            "title": title,
            "content": body,
            "word_count": word_count,
            "usage": usage,
        }

    async def _settle_state(
        self,
        context: dict,
        chapter_number: int,
        title: str,
        content: str,
    ) -> dict:
        """Phase 2: 状态结算"""
        on_stage = getattr(getattr(self, "ctx", None), "on_stage", None)
        if callable(on_stage):
            on_stage("fact_extract")
        # 2a. Observer: 提取事实
        observation_result = await self._observe_facts(
            context=context,
            chapter_number=chapter_number,
            title=title,
            content=content,
        )
        observations = observation_result["content"]

        if callable(on_stage):
            on_stage("settle")
        # 2b. Settler: 合并状态
        settlement = await self._settle(
            context=context,
            chapter_number=chapter_number,
            title=title,
            content=content,
            observations=observations,
        )

        return {
            "observations": observations,
            "state_updates": settlement.get("state_updates", {}),
            "state_delta": settlement.get("state_delta", {}),
            "chapter_summary": settlement.get("chapter_summary", ""),
            "usage": self._merge_usage(
                observation_result.get("usage", {}),
                settlement.get("usage", {}),
            ),
        }

    async def _observe_facts(
        self,
        context: dict,
        chapter_number: int,
        title: str,
        content: str,
    ) -> dict:
        """2a: 观察者 - 从章节中提取关键事实"""
        system_prompt = """你是一位细心的观察者，负责从小说章节中提取关键信息。

提取以下类型的信息：
1. 角色状态变化（情绪、能力、关系）
2. 物品获得/失去/转移
3. 地点变化
4. 重要事件
5. 伏笔埋设/回收
6. 数值变化（金钱、等级等）
7. 新角色登场
8. 关键对话要点

格式要求：
- 每条信息一行
- 使用简洁的标记语言
- 标注信息来源（章节位置）

保持客观，不要添加你的推测。"""

        user_prompt = f"""从以下章节中提取关键事实：

章节标题：{title}
章节内容：
{content}

请提取所有关键事实："""

        response = self.chat(
            messages=[
                Message("system", system_prompt),
                Message("user", user_prompt),
            ],
            temperature=0.5,
            max_tokens=None,  # Reasoning and final content share the configured budget.
            usage_stage="fact_extract",
        )

        return {"content": response.content, "usage": response.usage or {}}

    async def _settle(
        self,
        context: dict,
        chapter_number: int,
        title: str,
        content: str,
        observations: str,
    ) -> dict:
        """2b: 结算者 - 将观察结果合并到真相文件"""
        system_prompt = f"""你是一位细心的编辑，负责将章节中的变化合并到世界观状态中。

根据观察结果，更新以下真相文件：
1. current_state.md - 世界当前状态
2. ledger.md - 资源账本（如有数值系统）
3. relationships.md - 角色关系
4. （可选）foreshadowing/dag.yaml - 伏笔状态（仅摘要提示，不在本次输出中落盘）
5. （可选）hierarchy.yaml / compressed/*.md - 章节摘要（仅摘要提示，不在本次输出中落盘）

原则：
- 只记录客观变化，不创造新内容
- 保持简洁，每文件不超过200字更新
- 使用 Markdown 格式输出
- 只输出确有变化的字段

输出格式（优先使用结构化增量；旧 state_updates 仅用于兼容）：
```yaml
state_delta:
  chapter_id: ch_[章节编号]
  operations:
    - op: append
      collection: current_state
      value: "只写本章新增的客观事实"
    # 可用 collection：current_state / ledger / relationships / characters /
    # resources / relationship_states / open_threads / foreshadowing_refs /
    # timeline / proposed_entities
    # current_state / ledger / relationships 的 value 使用字符串。
    # 对象 collection 的 value 必须严格遵守下方 runtime-delta-v1 契约。
state_updates:
  current_state: |
    [旧客户端兼容字段：只写本章新增事实，不要重写整份文件]
  ledger: |
    [本章新增账本事实]
  relationships: |
    [本章新增关系事实]
chapter_summary: |
  [用80-150字概括本章发生的关键事件、选择、关系变化和未决悬念]

# 兼容字段（可选，同义于 ledger/relationships）
# particle_ledger: |
# character_matrix: |

注意：对外文档与公共接口以 current_state / ledger / relationships 为准，
历史别名仅用于兼容旧链路输入。
```

{RUNTIME_DELTA_PROMPT_CONTRACT}"""

        user_prompt = f"""根据以下观察结果，更新真相文件：

章节编号：{chapter_number}
章节标题：{title}
观察结果：
{observations}

当前真相文件状态：
{self._format_truth_files(context)}

请输出更新后的真相文件："""

        try:
            response = self.chat(
                messages=[
                    Message("system", system_prompt),
                    Message("user", user_prompt),
                ],
                temperature=0.3,
                max_tokens=None,  # Do not silently shrink the configured model budget.
                usage_stage="settle",
            )
            return self._parse_settlement(
                response.content,
                {**context, "chapter_number": chapter_number},
                usage=response.usage or {},
                observations=observations,
            )
        except Exception as exc:
            from ..llm.response import ProviderResponseError

            if not isinstance(exc, ProviderResponseError) or exc.code not in {
                "MALFORMED_STRUCTURED_OUTPUT",
                "MODEL_OUTPUT_TRUNCATED",
            }:
                raise
            failed_usage = getattr(exc, "usage", {}) or getattr(
                locals().get("response"), "usage", {}
            )

        compact_prompt = f"""章节编号：ch_{chapter_number:03d}
章节标题：{title}
客观观察：
{observations}

只提取本章新增事实。不要复述正文，不要重写现有真相文件。"""
        retry = self.chat(
            messages=[
                Message(
                    "system",
                    """你负责生成极简小说状态增量。只输出合法 YAML，不要代码围栏或解释。
严格使用以下结构，省略没有变化的字段；每个字段不超过 120 个汉字：
state_updates:
  current_state: "本章新增客观事实"
  ledger: "本章新增资源变化"
  relationships: "本章新增关系变化"
chapter_summary: "80-150字章节摘要"
不得输出 state_delta、完整正文、旧状态、推理过程或其他字段。""",
                ),
                Message("user", compact_prompt),
            ],
            temperature=0.1,
            max_tokens=None,  # Reasoning and final content share the configured budget.
            usage_stage="settle",
            attempt_index=2,
        )
        return self._parse_settlement(
            retry.content,
            {**context, "chapter_number": chapter_number},
            usage=self._merge_usage(failed_usage, retry.usage or {}),
            observations=observations,
        )

    def _format_truth_files(self, context: dict) -> str:
        """格式化真相文件"""
        parts = []

        if context.get("current_state"):
            parts.append(f"## current_state.md\n{context['current_state']}\n")

        if context.get("character_states"):
            parts.append(f"## 人物当前状态（内联批注，只读）\n{context['character_states']}\n")

        ledger_text = context.get("ledger") or context.get("particle_ledger")
        if ledger_text:
            parts.append(f"## ledger.md\n{ledger_text}\n")

        relationships_text = context.get("relationships") or context.get("character_matrix")
        if relationships_text:
            parts.append(f"## relationships.md\n{relationships_text}\n")

        hooks_text = context.get("foreshadowing_summary") or context.get("pending_hooks")
        if hooks_text:
            parts.append(f"## foreshadowing/dag.yaml（摘要）\n{hooks_text}\n")

        if context.get("chapter_summaries"):
            parts.append(
                f"## hierarchy.yaml / compressed/*.md（摘要）\n{context['chapter_summaries']}\n"
            )

        if context.get("active_characters"):
            character_parts = []
            for item in context["active_characters"]:
                if isinstance(item, dict):
                    name = str(item.get("name") or "角色").strip()
                    description = str(item.get("description") or "").strip()
                    character_parts.append(f"### {name}\n{description}")
                elif hasattr(item, "to_context_text"):
                    character_parts.append(item.to_context_text())
            if character_parts:
                parts.append(
                    "## 角色正典（不得改写身份与关系）\n" + "\n\n".join(character_parts) + "\n"
                )

        return "\n".join(parts) if parts else "（无现有真相文件）"

    def _parse_settlement(
        self,
        content: str,
        context: dict,
        *,
        usage: dict | None = None,
        observations: str = "",
    ) -> dict:
        """解析结算输出"""
        result = {
            "state_updates": {},
            "state_delta": {},
            "chapter_summary": "",
            "usage": dict(usage or {}),
        }

        payload = self._load_settlement_payload(content)
        if payload:
            delta_error: Exception | None = None
            raw_delta = payload.get("state_delta")
            if isinstance(raw_delta, dict):
                try:
                    from ..runtime_state import RuntimeStateDelta

                    parsed_delta = RuntimeStateDelta.model_validate(
                        {
                            **raw_delta,
                            "chapter_id": raw_delta.get("chapter_id")
                            or f"ch_{int(context.get('chapter_number') or 0):03d}",
                        }
                    )
                    result["state_delta"] = parsed_delta.model_dump(mode="json")
                except (ImportError, ValueError) as exc:
                    delta_error = exc
            updates = payload.get("state_updates", {})
            if isinstance(updates, dict):
                aliases = {
                    "particle_ledger": "ledger",
                    "character_matrix": "relationships",
                }
                for field, value in updates.items():
                    canonical = aliases.get(str(field), str(field))
                    if canonical not in {"current_state", "ledger", "relationships"}:
                        continue
                    text = str(value or "").strip()
                    if text:
                        result["state_updates"][canonical] = text
            result["chapter_summary"] = str(payload.get("chapter_summary") or "").strip()

            if not result["state_delta"] and result["state_updates"]:
                from ..runtime_state import legacy_updates_to_delta

                result["state_delta"] = legacy_updates_to_delta(
                    result["state_updates"],
                    chapter_id=f"ch_{int(context.get('chapter_number') or 0):03d}",
                ).model_dump(mode="json")
            elif delta_error is not None:
                from ..llm.response import ProviderResponseError

                raise ProviderResponseError(
                    "MALFORMED_STRUCTURED_OUTPUT",
                    "模型返回的状态增量不符合 runtime-delta-v1",
                ) from delta_error
            elif result["state_delta"].get("operations") and not result["state_updates"]:
                from ..llm.response import ProviderResponseError

                raise ProviderResponseError(
                    "MALFORMED_STRUCTURED_OUTPUT",
                    "state_delta 必须同时提供追加式 state_updates 安全回退",
                )

        if not result["chapter_summary"] and observations:
            compact = " ".join(
                line.strip("- ") for line in observations.splitlines() if line.strip()
            )
            result["chapter_summary"] = compact[:500]

        return result

    @staticmethod
    def _load_settlement_payload(content: str) -> dict:
        """Parse common structured-output variants without executing model content."""
        from ..llm.response import load_structured_mapping

        return load_structured_mapping(
            content,
            required_keys=("state_delta", "state_updates", "chapter_summary"),
        )

    @staticmethod
    def usage_for_stage(usage: dict, stage: str) -> dict:
        calls = [call for call in usage.get("calls", []) if call.get("stage") == stage]
        if not usage.get("calls"):
            return dict(usage) if stage == "draft" else {"usage_reported": False}
        return WriterAgent._merge_usage(
            *[{**call.get("usage", {}), "calls": [call]} for call in calls]
        )

    def usage_summary(self):
        return self._merge_usage(
            *[
                {**call.get("usage", {}), "calls": [call]}
                for call in getattr(self, "_usage_history", [])
            ]
        )

    @staticmethod
    def _merge_usage(*usages: dict) -> dict:
        merged: dict = {}
        usage_items: list[dict] = []
        has_cost_contract = False
        for usage in usages:
            if not isinstance(usage, dict):
                continue
            if usage:
                usage_items.append(usage)
                has_cost_contract = has_cost_contract or "cost_reported" in usage
            for key, value in usage.items():
                if key == "cost_reported":
                    continue
                if key == "calls" and isinstance(value, list):
                    merged.setdefault("calls", []).extend(value)
                    continue
                if key in {"completion_tokens_details", "prompt_tokens_details"} and isinstance(
                    value, dict
                ):
                    target = merged.setdefault(key, {})
                    for detail, amount in value.items():
                        if isinstance(amount, (int, float)) and not isinstance(amount, bool):
                            target[detail] = target.get(detail, 0) + amount
                    continue
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    merged[key] = merged.get(key, 0) + value
                elif key not in merged and value is not None:
                    merged[key] = value
        if usage_items and has_cost_contract:
            cost_reports = [usage.get("cost_reported") is True for usage in usage_items]
            merged["cost_reported"] = all(cost_reports)
            merged["cost_reported_calls"] = sum(cost_reports)
            merged["usage_calls"] = len(cost_reports)
        if merged.get("calls"):
            calls = merged["calls"]
            reports = [c.get("usage", {}).get("cost_reported") is True for c in calls]
            merged["usage_calls"] = len(calls)
            merged["cost_reported_calls"] = sum(reports)
            merged["cost_reported"] = all(reports)
            merged["cost_summary"] = {
                "reported_usd": sum(
                    float(c["usage"].get("cost_usd") or 0)
                    for c, reported in zip(calls, reports)
                    if reported
                ),
                "complete": all(reports),
                "missing_calls": len(calls) - sum(reports),
            }
        return merged

    def _post_write_validation(self, content: str) -> list:
        """Phase 1.5: 后置验证（零 LLM 成本）

        纯规则检测，禁止句式、元叙事、疲劳词等。
        """
        try:
            from ..post_validator import PostWriteValidator

            validator = PostWriteValidator()
            violations = validator.validate(content)
            return violations
        except ImportError:
            self.log.warning("PostWriteValidator not available")
            return []

    def _validate_state_consistency(
        self,
        state_updates: dict,
        content: str,
        chapter_number: int,
    ) -> list:
        """Phase 2.5: 状态验证

        验证 settler 输出的状态文件一致性。
        """
        try:
            from ..state_validator import StateValidator

            validator = StateValidator()
            current_state = state_updates.get("current_state", "")

            issues = validator.validate(
                current_state=current_state,
                content=content,
                chapter_number=chapter_number,
            )
            return issues
        except ImportError:
            self.log.warning("StateValidator not available")
            return []

    def _extract_dialogue_fingerprints(
        self,
        chapters_content: list[str],
        character_names: list[str],
    ) -> list:
        """提取对话指纹

        从最近章节提取角色对话风格特征。
        """
        try:
            from ..dialogue_fingerprint import DialogueFingerprintExtractor

            extractor = DialogueFingerprintExtractor()
            fingerprints = extractor.extract(chapters_content, character_names)
            return fingerprints
        except ImportError:
            self.log.warning("DialogueFingerprintExtractor not available")
            return []
