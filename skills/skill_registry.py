"""Skill Registry — 功能注册表

管理所有已加载的功能模块，提供：
- 注册和发现功能
- 触发器匹配
- 优先级管理（project > user > builtin）
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from skills.skill import Skill

logger = logging.getLogger(__name__)


class SkillRegistry:
    """功能注册表。

    管理所有已加载的功能模块，支持：
    - 按名称查找
    - 按触发器匹配
    - 优先级覆盖（project > user > builtin）

    Usage:
        registry = SkillRegistry()
        registry.register(skill)

        # 按名称查找
        skill = registry.get("outline")

        # 按触发器匹配
        skill = registry.match_trigger("创建大纲")
    """

    # 优先级：数字越小优先级越高
    LOCATION_PRIORITY = {
        "project": 0,  # 项目级最高（覆盖其他）
        "user": 1,  # 用户级次之
        "builtin": 2,  # 内置级最低
    }

    def __init__(self):
        self._skills: Dict[str, Skill] = {}

    def register(self, skill: Skill) -> bool:
        """注册功能模块。

        如果同名功能已存在，根据优先级决定是否覆盖。

        Args:
            skill: 要注册的功能模块

        Returns:
            是否成功注册（被更高优先级覆盖时返回 False）
        """
        existing = self._skills.get(skill.name)

        if existing:
            existing_priority = self.LOCATION_PRIORITY.get(existing.location, 99)
            new_priority = self.LOCATION_PRIORITY.get(skill.location, 99)

            if new_priority >= existing_priority:
                logger.debug(
                    "Skill '%s' not registered (existing '%s' has higher priority)",
                    skill.name,
                    existing.location,
                )
                return False

        self._skills[skill.name] = skill
        logger.info("Registered skill: %s (%s)", skill.name, skill.location)
        return True

    def unregister(self, name: str) -> bool:
        """注销功能模块。

        Args:
            name: 功能名称

        Returns:
            是否成功注销
        """
        if name in self._skills:
            del self._skills[name]
            return True
        return False

    def get(self, name: str) -> Optional[Skill]:
        """获取功能模块。

        Args:
            name: 功能名称

        Returns:
            功能模块，不存在返回 None
        """
        return self._skills.get(name)

    def match_trigger(self, text: str) -> Optional[Skill]:
        """根据文本匹配功能模块。

        遍历所有功能，找到第一个匹配触发器的功能。

        Args:
            text: 用户输入文本

        Returns:
            匹配的功能模块，无匹配返回 None
        """
        best_match: Optional[Skill] = None
        best_score = 0

        for skill in self._skills.values():
            if skill.matches_trigger(text):
                # 计算匹配分数（更多关键词匹配 = 更高分数）
                score = sum(1 for t in skill.triggers if t.lower() in text.lower())
                # 命令触发器额外加分
                if skill.trigger and text.strip().startswith(skill.trigger):
                    score += 10

                if score > best_score:
                    best_score = score
                    best_match = skill

        return best_match

    def list_all(self) -> List[Skill]:
        """列出所有功能模块。"""
        return list(self._skills.values())

    def list_by_location(self, location: str) -> List[Skill]:
        """按位置列出功能模块。

        Args:
            location: 位置类型（project/user/builtin）

        Returns:
            该位置的功能模块列表
        """
        return [s for s in self._skills.values() if s.location == location]

    def get_skills_prompt(self, char_budget: int = 2000) -> str:
        """生成包含所有可用功能的提示词。

        用于注入到主 AI 的系统提示词中。

        Args:
            char_budget: 字符预算上限

        Returns:
            功能列表提示词
        """
        lines = ["# 可用功能\n"]
        total_chars = len(lines[0])

        for skill in sorted(self._skills.values(), key=lambda s: s.name):
            entry = f"- **{skill.name}**: {skill.description[:100]}\n"
            if total_chars + len(entry) > char_budget:
                break
            lines.append(entry)
            total_chars += len(entry)

        lines.append("\n根据用户意图，选择合适的功能执行。")
        return "".join(lines)

    def get_skill_instruction(self) -> str:
        """获取所有功能的指令提示。

        Returns:
            指令提示文本
        """
        instruction = (
            "# Agent Skills\n"
            "The agent skills are a collection of folders of instructions, scripts, "
            "and resources that you can load dynamically to improve performance "
            "on specialized tasks. Each agent skill has a `SKILL.md` file in its "
            "folder that describes how to use the skill. If you want to use a "
            "skill, you MUST read its `SKILL.md` file carefully.\n\n"
        )

        for skill in sorted(self._skills.values(), key=lambda s: s.name):
            trigger_info = f" (`{skill.trigger}`)" if skill.trigger else ""
            instruction += (
                f"## {skill.name}{trigger_info}\n"
                f"{skill.description}\n"
                f'Check "{skill.path}/SKILL.md" for how to use this skill\n\n'
            )

        return instruction

    def __len__(self) -> int:
        return len(self._skills)

    def __contains__(self, name: str) -> bool:
        return name in self._skills


# 全局单例
_global_registry: Optional[SkillRegistry] = None


def get_skill_registry() -> SkillRegistry:
    """获取全局功能注册表。

    Returns:
        全局注册表实例
    """
    global _global_registry
    if _global_registry is None:
        _global_registry = SkillRegistry()
    return _global_registry


def reset_registry() -> None:
    """重置全局注册表。"""
    global _global_registry
    _global_registry = None
