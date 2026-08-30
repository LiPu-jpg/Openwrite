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

import logging
import re
from dataclasses import dataclass, field

from ..llm import Message
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
    token_usage: dict = field(default_factory=dict)
    finish_reason: str = ""
    model: str = ""
    provider: str = ""


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

        self.log.info(f"Phase 1: creative writing for chapter {chapter_number}")

        # ── Phase 1: 创意写作 ──
        creative_result = await self._creative_write(
            context=context,
            chapter_number=chapter_number,
            temperature=temperature,
            target_words=target_words,
        )

        self.log.info(
            f"Phase 2: state settlement for chapter {chapter_number} "
            f"({creative_result['word_count']} chars)"
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
            token_usage=self._merge_usage(
                creative_result.get("usage", {}),
                settlement_result.get("usage", {}),
            ),
            finish_reason=str(creative_result.get("finish_reason") or ""),
            model=str(creative_result.get("model") or ""),
            provider=str(creative_result.get("provider") or ""),
        )

    async def _creative_write(
        self,
        context: dict,
        chapter_number: int,
        temperature: float,
        target_words: int,
    ) -> dict:
        """Phase 1: 创意写作"""
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
        response = self.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max(16384, target_words * 2),
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

        # 长度不达标时循环反馈字数差让模型自纠（最多 3 次续写）
        minimum_words = max(1, int(target_words * 0.8))
        maximum_words = max(minimum_words, int(target_words * 1.2))
        current_content = response.content
        final_response = response
        all_usage = [first_usage]

        for attempt in range(3):
            chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", current_content))
            if minimum_words <= chinese_chars <= maximum_words:
                break
            comparison = "低于" if chinese_chars < minimum_words else "超过"
            action = "扩充" if chinese_chars < minimum_words else "精简"
            detail = (
                "补充场景描写、人物互动和心理活动"
                if chinese_chars < minimum_words
                else "删除重复和冗余描写"
            )
            hint = (
                f"长度不合格：你上一版正文约 {chinese_chars} 个中文字符，{comparison}"
                f"目标区间 {minimum_words}-{maximum_words}。请{action}"
                f"正文至 {target_words} 字左右：保留既定情节与章末悬念，"
                f"{detail}。"
                "只输出章节标题和完整正文，不要解释。"
            )
            getattr(self, "log", logger).info(
                f"Length retry #{attempt + 1}: {chinese_chars} chars "
                f"(target {minimum_words}-{maximum_words})"
            )
            retry_response = self.chat(
                messages=[
                    *messages,
                    Message("assistant", current_content),
                    Message("user", hint),
                ],
                temperature=max(0.2, temperature - 0.15),
                max_tokens=max(16384, target_words * 2),
            )
            if retry_response.usage:
                all_usage.append(retry_response.usage)
            current_content = retry_response.content
            final_response = retry_response

        merged_usage = self._merge_usage(*all_usage)
        parsed = self._parse_creative_output(
            current_content,
            chapter_number,
            merged_usage,
            target_words=target_words,
        )
        parsed.update(
            {
                "finish_reason": str(getattr(final_response, "finish_reason", "") or ""),
                "model": str(getattr(final_response, "model", "") or ""),
                "provider": str(getattr(final_response, "provider", "") or ""),
            }
        )
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
        minimum_words = max(1, int(target_words * 0.8))
        maximum_words = max(minimum_words, int(target_words * 1.2))
        parts.append(
            f"目标字数：约{target_words}字；正文必须控制在"
            f"{minimum_words}-{maximum_words}个中文字符内。达到上限时优先收束情节，"
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

        if context.get("chapter_beats"):
            beats = "\n".join(f"- {item}" for item in context["chapter_beats"])
            parts.append(f"## 章内节拍（按顺序落实）\n{beats}\n")

        if context.get("chapter_hooks"):
            hooks = "\n".join(f"- {item}" for item in context["chapter_hooks"])
            parts.append(f"## 章末悬念（正文结尾必须承接）\n{hooks}\n")

        if context.get("emotion_arc"):
            parts.append(f"## 章内情感弧线\n{context['emotion_arc']}\n")

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

        # 尝试提取标题
        title_match = re.search(
            r"^#{1,6}\s*第\s*[0-9零〇一二三四五六七八九十百千两]+\s*章"
            r"\s*[:：\-—]?\s*(.*?)\s*$",
            content,
            re.MULTILINE,
        )
        if title_match:
            title = title_match.group(1).strip() or f"第{chapter_number}章"
            body = content[title_match.end() :].strip()
        else:
            title = f"第{chapter_number}章"
            body = content.strip()

        # 计算字数（中文字符数）
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", body))
        word_count = chinese_chars
        if target_words > 0:
            minimum_words = max(1, int(target_words * 0.8))
            maximum_words = max(minimum_words, int(target_words * 1.2))
            if word_count < minimum_words or word_count > maximum_words:
                from ..llm.response import ProviderResponseError

                raise ProviderResponseError(
                    "CHAPTER_LENGTH_OUT_OF_RANGE",
                    f"正文约 {word_count} 个中文字符，不在目标区间 "
                    f"{minimum_words}-{maximum_words} 内",
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
        # 2a. Observer: 提取事实
        observation_result = await self._observe_facts(
            context=context,
            chapter_number=chapter_number,
            title=title,
            content=content,
        )
        observations = observation_result["content"]

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
            max_tokens=4096,
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
                max_tokens=8192,
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
            max_tokens=4096,
        )
        return self._parse_settlement(
            retry.content,
            {**context, "chapter_number": chapter_number},
            usage=retry.usage or {},
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
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    merged[key] = merged.get(key, 0) + value
                elif key not in merged and value is not None:
                    merged[key] = value
        if usage_items and has_cost_contract:
            cost_reports = [usage.get("cost_reported") is True for usage in usage_items]
            merged["cost_reported"] = all(cost_reports)
            merged["cost_reported_calls"] = sum(cost_reports)
            merged["usage_calls"] = len(cost_reports)
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
