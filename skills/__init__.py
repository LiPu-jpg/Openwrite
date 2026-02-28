"""Skills System — 模块化功能系统

这是 OpenWrite 的功能模块化架构，每个 Skill 是一个自包含的功能单元。

架构设计:
- Skill: 功能模块数据模型（元数据 + 能力）
- SkillRegistry: 功能注册表（发现 + 匹配）
- SkillLoader: 功能加载器（从文件系统加载）
- ToolExecutor: 工具执行器（安全执行工具调用）
"""

from skills.skill import Skill
from skills.skill_registry import SkillRegistry
from skills.skill_loader import SkillLoader

__all__ = ["Skill", "SkillRegistry", "SkillLoader"]
