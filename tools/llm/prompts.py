"""Prompt 构建器 — 为每个 Agent 生成结构化 LLM prompt。

每个 Agent 有独立的 system prompt 和 user prompt 模板。
模板使用 str.format() 占位符，由 Agent 在调用时填充。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


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

    # ------------------------------------------------------------------
    # Director 对话 prompts（Web Chat 用）
    # ------------------------------------------------------------------

    @staticmethod
    def director_chat(
        phase_name: str,
        phase_description: str,
        phase_prompt: str,
        phase_questions: List[str],
        phase_options: List[Dict[str, str]],
        user_message: str,
        context_summary: str = "",
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> List[Dict[str, str]]:
        """构建 Director 工作流对话 prompt。

        在 workflow 阶段内，用 LLM 生成自然语言回复，
        替代硬编码的 user_prompt 字符串。
        """
        system = (
            "你是 OpenWrite 创作助手，正在引导用户完成小说创作工作流。\n"
            "当前处于工作流阶段，你的职责是：\n"
            "1. 根据当前阶段的目标，用自然、友好的语言与用户对话\n"
            "2. 引导用户提供该阶段所需的信息\n"
            "3. 如果用户提供了信息，确认并总结，然后引导进入下一步\n"
            "4. 如果用户的回答不够具体，温和地追问细节\n"
            "5. 保持专业但不生硬，像一位经验丰富的编辑在和作者讨论\n\n"
            "重要规则：\n"
            "- 不要一次性抛出所有问题，根据对话进度逐步引导\n"
            "- 用户已经回答过的问题不要重复问\n"
            "- 回复控制在 200 字以内，简洁有力\n"
            "- 使用 Markdown 格式让回复更易读\n"
        )

        # 构建阶段上下文
        phase_info = (
            f"## 当前阶段：{phase_name}\n"
            f"{phase_description}\n\n"
        )
        if phase_questions:
            phase_info += "## 本阶段需要收集的信息\n"
            phase_info += "\n".join(f"- {q}" for q in phase_questions) + "\n\n"
        if phase_options:
            phase_info += "## 用户可选的操作\n"
            for opt in phase_options:
                phase_info += (
                    f"- **{opt.get('label', '')}**: {opt.get('description', '')}\n"
                )
            phase_info += "\n"
        if context_summary:
            phase_info += f"## 项目上下文\n{context_summary}\n\n"

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": phase_info + "（以上是阶段背景，请根据这些信息引导对话）",
            },
            {
                "role": "assistant",
                "content": phase_prompt or f"好的，让我们开始{phase_name}。",
            },
        ]

        # 注入历史对话
        if conversation_history:
            for msg in conversation_history[-10:]:
                if msg.get("role") in ("user", "assistant"):
                    messages.append(msg)

        # 当前用户消息
        messages.append({"role": "user", "content": user_message})

        return messages

    @staticmethod
    def director_intent_response(
        intent: str,
        user_message: str,
        context_summary: str = "",
        available_tools: Optional[List[str]] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
    ) -> List[Dict[str, str]]:
        """构建 Director 意图响应 prompt。

        无 workflow 匹配时，根据识别到的意图和上下文，
        用 LLM 生成智能回复（而非硬编码的"请问您具体想做什么"）。
        """
        tools_desc = ""
        if available_tools:
            tools_desc = (
                "\n## 你可以调用的工具\n"
                + "\n".join(f"- {t}" for t in available_tools)
                + "\n"
            )

        system = (
            "你是 OpenWrite 创作助手，一位经验丰富的小说编辑。\n"
            "用户表达了一个创作意图，但当前没有匹配到具体的工作流。\n"
            "你的职责是：\n"
            "1. 确认你理解了用户的意图\n"
            "2. 根据意图和上下文，给出具体的、可操作的建议\n"
            "3. 如果缺少关键信息（如项目未选择），明确告知用户下一步\n",
            "4. 如果可以直接帮助，就直接开始工作\n\n"
            "回复规则：\n"
            "- 简洁有力，不超过 200 字\n"
            "- 给出 1-3 个具体的下一步建议\n"
            "- 使用 Markdown 格式\n"
            f"{tools_desc}"
        )

        context_part = ""
        if context_summary:
            context_part = f"\n## 项目上下文\n{context_summary}\n"

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system},
        ]

        if conversation_history:
            for msg in conversation_history[-10:]:
                if msg.get("role") in ("user", "assistant"):
                    messages.append(msg)

        user_content = (
            f"## 识别到的意图\n{intent}\n"
            f"{context_part}"
            f"## 用户消息\n{user_message}"
        )
        messages.append({"role": "user", "content": user_content})

        return messages

    @staticmethod
    def director_tool_selection(
        user_message: str,
        available_tools: List[Dict[str, Any]],
        context_summary: str,
    ) -> List[Dict[str, str]]:
        """Build prompt for LLM-driven tool selection.
        
        Args:
            user_message: 用户输入
            available_tools: 可用工具列表（OpenAI function schema 格式）
            context_summary: 上下文摘要
        
        Returns:
            OpenAI format messages
        """
        import json
        
        tools_json = json.dumps(available_tools, ensure_ascii=False, indent=2)
        
        system_prompt = f"""你是 OpenWrite 的主控 Agent。根据用户请求，分析意图并选择合适的工具执行。

## 可用工具
{tools_json}

## 当前上下文
{context_summary or "无额外上下文"}

## 输出要求
你必须输出 JSON 格式，包含以下字段：

```json
{{
  "reasoning": "分析用户意图，解释为什么选择这些工具",
  "selected_tools": [
    {{"name": "工具名称", "args": {{"参数名": "参数值"}}}}
  ],
  "response_to_user": "可选：直接回复用户的话（如无需工具或需要补充说明）"
}}
```

## 规则
1. 如果用户只是闲聊或打招呼，不选择任何工具，直接在 response_to_user 中回复
2. 根据用户意图选择最相关的工具，不要选择无关工具
3. 如果需要多个工具，按执行顺序排列
4. 工具参数根据用户输入合理推断
5. 确保输出是有效的 JSON"""
        
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
