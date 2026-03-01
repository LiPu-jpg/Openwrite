"""LLM-Based Intent Classifier — 基于 LLM 的意图分类器。

完全移除硬编码关键词匹配，使用 LLM 理解用户意图。

设计原则：
1. 命令触发器 (/xxx) 仍然直接匹配（用户明确意图）
2. 其他所有输入都交给 LLM 判断
3. LLM 返回结构化的意图决策
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from tools.llm.client import LLMClient
    from tools.llm.router import ModelRouter

logger = logging.getLogger(__name__)


# 意图分类 Prompt 模板
INTENT_CLASSIFICATION_PROMPT = """# 意图识别任务

你是一个创作助手系统的意图识别模块。用户会向你发送消息，你需要判断他们的真实意图。

## 可用的功能模块

{skills_description}

## 用户的对话历史（如果有）

{conversation_history}

## 用户当前消息

"{user_message}"

## 任务

请分析用户的真实意图，返回 JSON 格式的结果：

```json
{
  "intent": "功能名称或 general_chat",
  "confidence": 0.0-1.0,
  "reasoning": "为什么选择这个意图",
  "entity_references": ["提取的实体引用"],
  "should_confirm": true/false
}
```

### 意图判断规则

1. **general_chat**: 用户只是在聊天、打招呼、问问题，没有明确的创作任务
2. **功能名称**: 用户明确想要执行某个创作相关任务
3. **should_confirm**: 当意图不确定时，设为 true 让系统向用户确认

### 注意事项

- 不要过度触发功能，只有用户真的想执行任务时才匹配
- "不要X"、"X在哪里" 这种不应该触发 X 功能
- 考虑上下文，如果用户在对话中提到了相关内容，可能是延续
- 返回的 intent 必须是上述功能名称之一，或者 general_chat

只返回 JSON，不要其他内容。"""


class LLMIntentClassifier:
    """基于 LLM 的意图分类器。

    完全移除硬编码关键词，使用 LLM 理解用户意图。
    """

    def __init__(
        self,
        llm_client: Optional["LLMClient"] = None,
        router: Optional["ModelRouter"] = None,
    ):
        """初始化意图分类器。

        Args:
            llm_client: LLM 客户端
            router: 模型路由器
        """
        self._llm_client = llm_client
        self._router = router
        self._skills_cache: Optional[List[Dict[str, Any]]] = None

    def _get_skills_description(self, skills: List[Any]) -> str:
        """生成功能模块描述。

        Args:
            skills: Skill 对象列表

        Returns:
            格式化的功能描述
        """
        descriptions = []
        for skill in skills:
            triggers = ", ".join(skill.triggers[:3]) if skill.triggers else "无"
            descriptions.append(
                f"- **{skill.name}**: {skill.description[:100]}\n  触发示例: {triggers}"
            )
        return "\n\n".join(descriptions)

    def _format_conversation_history(
        self, history: List[Dict[str, str]], max_turns: int = 5
    ) -> str:
        """格式化对话历史。

        Args:
            history: 消息历史
            max_turns: 最大轮数

        Returns:
            格式化的对话历史
        """
        if not history:
            return "（无对话历史）"

        recent = history[-max_turns * 2 :]  # 最近 N 轮
        lines = []
        for msg in recent:
            role = "用户" if msg.get("role") == "user" else "助手"
            content = msg.get("content", "")[:100]
            lines.append(f"{role}: {content}...")

        return "\n".join(lines)

    def classify(
        self,
        user_message: str,
        skills: List[Any],
        history: Optional[List[Dict[str, str]]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """使用 LLM 分类用户意图。

        Args:
            user_message: 用户消息
            skills: 可用的功能模块列表
            history: 对话历史
            context: 上下文数据

        Returns:
            意图分类结果
        """
        from tools.models.intent import IntentConfidence, TaskIntent

        context = context or {}
        history = history or []

        # 1. 检查命令触发器（快速路径，不调用 LLM）
        for skill in skills:
            if skill.trigger and user_message.strip().startswith(skill.trigger):
                logger.info(f"命令触发器匹配: {skill.trigger}")
                return {
                    "intent": self._map_skill_to_intent(skill.name),
                    "confidence": IntentConfidence.HIGH,
                    "confidence_score": 0.95,
                    "reasoning": f"用户使用了命令触发器 {skill.trigger}",
                    "skill": skill.name,
                    "entity_references": [],
                    "should_confirm": False,
                }

        # 2. 使用 LLM 进行意图识别
        prompt = INTENT_CLASSIFICATION_PROMPT.format(
            skills_description=self._get_skills_description(skills),
            conversation_history=self._format_conversation_history(history),
            user_message=user_message,
        )

        try:
            if self._llm_client and self._router:
                # 使用 LLM
                routes = self._router.get_routes("reasoning")
                response = self._llm_client.complete_with_fallback(
                    messages=[{"role": "user", "content": prompt}],
                    routes=routes,
                )
                llm_output = response.content
            else:
                # 无 LLM，使用简单规则 fallback
                return self._fallback_classification(user_message, skills)

            # 解析 LLM 输出
            result = self._parse_llm_output(llm_output, skills)
            return result

        except Exception as e:
            logger.warning(f"LLM 意图识别失败: {e}")
            return self._fallback_classification(user_message, skills)

    def _parse_llm_output(self, llm_output: str, skills: List[Any]) -> Dict[str, Any]:
        """解析 LLM 输出的 JSON。

        Args:
            llm_output: LLM 返回的文本
            skills: 可用的功能模块

        Returns:
            解析后的意图分类结果
        """
        from tools.models.intent import IntentConfidence, TaskIntent

        # 提取 JSON
        import re

        json_match = re.search(r"```json\s*(.+?)\s*```", llm_output, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = llm_output.strip()

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning(f"JSON 解析失败: {llm_output[:100]}")
            return {
                "intent": TaskIntent.GENERAL_CHAT,
                "confidence": IntentConfidence.LOW,
                "confidence_score": 0.3,
                "reasoning": "LLM 输出解析失败，使用通用对话",
                "entity_references": [],
                "should_confirm": False,
            }

        # 映射意图
        intent_name = data.get("intent", "general_chat")
        if intent_name == "general_chat":
            intent = TaskIntent.GENERAL_CHAT
            skill_name = None
        else:
            intent = self._map_skill_to_intent(intent_name)
            skill_name = intent_name

        # 置信度
        confidence_score = float(data.get("confidence", 0.5))
        if confidence_score >= 0.8:
            confidence = IntentConfidence.HIGH
        elif confidence_score >= 0.5:
            confidence = IntentConfidence.MEDIUM
        else:
            confidence = IntentConfidence.LOW

        return {
            "intent": intent,
            "confidence": confidence,
            "confidence_score": confidence_score,
            "reasoning": data.get("reasoning", ""),
            "skill": skill_name,
            "entity_references": data.get("entity_references", []),
            "should_confirm": data.get("should_confirm", False),
        }

    def _fallback_classification(
        self, user_message: str, skills: List[Any]
    ) -> Dict[str, Any]:
        """Fallback 分类（无 LLM 时使用）。

        Args:
            user_message: 用户消息
            skills: 可用的功能模块

        Returns:
            意图分类结果
        """
        from tools.models.intent import IntentConfidence, TaskIntent

        # 简单的命令检测
        for skill in skills:
            if skill.trigger and user_message.strip().startswith(skill.trigger):
                return {
                    "intent": self._map_skill_to_intent(skill.name),
                    "confidence": IntentConfidence.HIGH,
                    "confidence_score": 0.9,
                    "reasoning": f"命令触发器: {skill.trigger}",
                    "skill": skill.name,
                    "entity_references": [],
                    "should_confirm": False,
                }

        # 无匹配，使用通用对话
        return {
            "intent": TaskIntent.GENERAL_CHAT,
            "confidence": IntentConfidence.LOW,
            "confidence_score": 0.3,
            "reasoning": "无 LLM 可用，默认使用通用对话",
            "entity_references": [],
            "should_confirm": False,
        }

    def _map_skill_to_intent(self, skill_name: str) -> "TaskIntent":
        """将 Skill 名称映射到 TaskIntent。

        Args:
            skill_name: 功能模块名称

        Returns:
            对应的 TaskIntent
        """
        from tools.models.intent import TaskIntent

        mapping = {
            "outline": TaskIntent.OUTLINE_ASSIST,
            "writing": TaskIntent.WRITE_CHAPTER,
            "style": TaskIntent.STYLE_COMPOSE,
            "character": TaskIntent.CHARACTER_CREATE,
            "world": TaskIntent.LORE_QUERY,
            "foreshadowing": TaskIntent.FORESHADOW_PLANT,
            "project": TaskIntent.PROJECT_INIT,
        }

        return mapping.get(skill_name, TaskIntent.GENERAL_CHAT)
