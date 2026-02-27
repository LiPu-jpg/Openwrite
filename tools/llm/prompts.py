"""Prompt 构建器 — 为每个 Agent 生成结构化 LLM prompt。

每个 Agent 有独立的 system prompt 和 user prompt 模板。
模板使用 str.format() 占位符，由 Agent 在调用时填充。
"""

from __future__ import annotations

from typing import Dict, List, Optional


class PromptBuilder:
    """为各 Agent 构建 LLM 消息列表。"""

    # ------------------------------------------------------------------
    # Director prompts
    # ------------------------------------------------------------------

    @staticmethod
    def director_plan(
        objective: str,
        chapter_id: str,
        context_summary: str,
        style_summary: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """构建 Director 路由决策 prompt。"""
        system = (
            "你是一位资深小说编辑（Director），负责分析章节目标和上下文，做出以下决策：\n"
            "1. 判断本章是否需要严格逻辑检查（涉及战斗、死亡、伏笔回收等高风险内容）\n"
            "2. 提取本章必须处理的重点要素（高权重伏笔、关键角色、场景要求）\n"
            "3. 生成给 Librarian（写手）的创作指令\n"
            "4. 如有风格文档，生成风格润色指令\n\n"
            "输出格式（严格 JSON）：\n"
            "```json\n"
            "{\n"
            '  "strict_lore": true/false,\n'
            '  "priority_elements": ["要素1", "要素2"],\n'
            '  "generation_instructions": "给写手的具体创作指令...",\n'
            '  "style_instructions": "风格润色指令（无风格文档时为空字符串）",\n'
            '  "notes": ["决策备注1", "决策备注2"]\n'
            "}\n"
            "```"
        )

        user_parts = [
            f"## 章节目标\n{objective}",
            f"## 章节编号\n{chapter_id}",
            f"## 上下文摘要\n{context_summary}",
        ]
        if style_summary:
            user_parts.append(f"## 风格文档摘要\n{style_summary[:2000]}")

        return [
            {"role": "system", "content": system},
            {"role": "user", "content": "\n\n".join(user_parts)},
        ]

    # ------------------------------------------------------------------
    # Librarian prompts
    # ------------------------------------------------------------------

    @staticmethod
    def librarian_generate(
        chapter_id: str,
        objective: str,
        beats: List[str],
        context: Dict[str, str],
        style_instructions: str = "",
    ) -> List[Dict[str, str]]:
        """构建 Librarian 草稿生成 prompt。

        节拍（beats）由规则引擎预生成，LLM 负责将节拍扩写为散文。
        """
        system = (
            "你是一位专业网文写手（Librarian），根据给定的节拍列表（beat list）"
            "将每个节拍扩写为完整的小说段落。\n\n"
            "写作要求：\n"
            "1. 严格按照节拍顺序展开，每个节拍对应一个或多个段落\n"
            "2. 使用【场景】【对话】【叙述】【内心】【动作】【转场】标记区分段落类型\n"
            "3. 对话要有个性化语气，避免千人一面\n"
            "4. 叙述要有节奏感：短段（<50字）占60%，中段（50-150字）占30%，长段（>150字）占10%\n"
            "5. 避免以下 AI 痕迹表达：不禁、缓缓说道、微微一笑、心中暗想、"
            "眼中闪过一丝、嘴角微微上扬、深吸一口气\n"
            "6. 自然融入伏笔和角色状态变化\n"
        )
        if style_instructions:
            system += f"\n## 风格要求\n{style_instructions}\n"

        beats_text = "\n".join(f"- {b}" for b in beats)
        context_text = "\n".join(
            f"- {k}: {v[:200]}" for k, v in context.items() if v and "暂无" not in v
        )

        user = (
            f"## 章节编号\n{chapter_id}\n\n"
            f"## 章节目标\n{objective}\n\n"
            f"## 节拍列表\n{beats_text}\n\n"
            f"## 上下文\n{context_text}\n\n"
            "请按节拍顺序扩写为完整章节草稿。"
        )

        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    @staticmethod
    def librarian_rewrite(
        chapter_id: str,
        objective: str,
        previous_draft: str,
        errors: List[str],
        warnings: List[str],
    ) -> List[Dict[str, str]]:
        """构建 Librarian 重写 prompt（基于 LoreChecker 反馈）。"""
        system = (
            "你是一位专业网文写手（Librarian），需要根据逻辑审查反馈修改草稿。\n"
            "修改原则：\n"
            "1. 只修改有问题的部分，保留原文的好段落\n"
            "2. 修复所有 errors（必须修复）\n"
            "3. 尽量处理 warnings（建议修复）\n"
            "4. 保持原文的节奏和风格\n"
            "5. 输出完整的修改后草稿\n"
        )

        issues = ""
        if errors:
            issues += (
                "### 必须修复的错误\n" + "\n".join(f"- ❌ {e}" for e in errors) + "\n\n"
            )
        if warnings:
            issues += (
                "### 建议修复的警告\n"
                + "\n".join(f"- ⚠️ {w}" for w in warnings)
                + "\n\n"
            )

        user = (
            f"## 章节编号\n{chapter_id}\n\n"
            f"## 章节目标\n{objective}\n\n"
            f"## 审查反馈\n{issues}\n"
            f"## 原始草稿\n{previous_draft}\n\n"
            "请输出修改后的完整草稿。"
        )

        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    # ------------------------------------------------------------------
    # LoreChecker prompts
    # ------------------------------------------------------------------

    @staticmethod
    def lore_checker_review(
        draft: str,
        context: Dict[str, str],
        forbidden: List[str],
        required: List[str],
        strict: bool = False,
    ) -> List[Dict[str, str]]:
        """构建 LoreChecker 逻辑审查 prompt。"""
        mode = "严格模式" if strict else "宽松模式"
        system = (
            f"你是一位严谨的小说逻辑审查员（LoreChecker），当前为{mode}。\n"
            "审查维度：\n"
            "1. 角色一致性：名字、境界、位置、性格是否与设定一致\n"
            "2. 世界观一致性：术语、规则、地理是否符合设定\n"
            "3. 伏笔一致性：已埋伏笔是否被正确引用或回收\n"
            "4. 禁用词检查：草稿中不应出现的词汇\n"
            "5. 必含元素检查：草稿中必须包含的元素\n\n"
            "输出格式（严格 JSON）：\n"
            "```json\n"
            "{\n"
            '  "passed": true/false,\n'
            '  "errors": ["严重问题1", "严重问题2"],\n'
            '  "warnings": ["轻微问题1", "轻微问题2"],\n'
            '  "suggestions": ["改进建议1"]\n'
            "}\n"
            "```\n"
        )
        if strict:
            system += "严格模式：任何不一致都应标记为 error。\n"
        else:
            system += "宽松模式：仅明显矛盾标记为 error，轻微不一致标记为 warning。\n"

        context_text = "\n".join(
            f"### {k}\n{v[:300]}" for k, v in context.items() if v and "暂无" not in v
        )
        forbidden_text = ", ".join(forbidden) if forbidden else "无"
        required_text = ", ".join(required) if required else "无"

        user = (
            f"## 设定上下文\n{context_text}\n\n"
            f"## 禁用词\n{forbidden_text}\n\n"
            f"## 必含元素\n{required_text}\n\n"
            f"## 待审查草稿\n{draft}\n\n"
            "请审查以上草稿并输出 JSON 结果。"
        )

        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    # ------------------------------------------------------------------
    # Stylist prompts
    # ------------------------------------------------------------------

    @staticmethod
    def stylist_polish(
        draft: str,
        style_profile_summary: str = "",
        banned_phrases: Optional[List[str]] = None,
    ) -> List[Dict[str, str]]:
        """构建 Stylist 风格润色 prompt。"""
        banned = banned_phrases or []
        system = (
            "你是一位文风润色专家（Stylist），负责消除 AI 痕迹并提升文本质量。\n"
            "润色原则：\n"
            "1. 移除所有 AI 痕迹表达，替换为更自然的表述\n"
            "2. 调整段落节奏：短段占60%，中段30%，长段10%\n"
            "3. 确保叙述者声音一致\n"
            "4. 保持原文的情节和信息量不变\n"
            "5. 不要添加原文没有的内容\n"
            "6. 输出润色后的完整文本\n"
        )
        if banned:
            system += (
                f"\n## 禁用表达清单\n" + "\n".join(f"- {p}" for p in banned[:30]) + "\n"
            )
        if style_profile_summary:
            system += f"\n## 风格档案\n{style_profile_summary[:1500]}\n"

        user = f"## 待润色草稿\n{draft}\n\n请输出润色后的完整文本。"

        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
