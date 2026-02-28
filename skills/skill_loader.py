"""Skill Loader — 功能加载器

从文件系统发现和加载功能模块。

搜索路径（按优先级排序）：
1. skills/ (项目级)
2. ~/.openwrite/skills/ (用户级)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional, Tuple

from skills.skill import Skill
from skills.skill_registry import SkillRegistry, get_skill_registry

logger = logging.getLogger(__name__)


class SkillLoader:
    """功能加载器。

    从文件系统发现和加载功能模块。

    Usage:
        loader = SkillLoader(project_root=Path.cwd())
        registry = loader.load_all()

        # 或者加载到现有注册表
        loader.load_all(registry=existing_registry)
    """

    SKILL_FILE = "SKILL.md"

    def __init__(
        self,
        project_root: Optional[Path] = None,
        skills_dir: str = "skills",
    ):
        """初始化加载器。

        Args:
            project_root: 项目根目录，默认当前目录
            skills_dir: 技能目录名，默认 "skills"
        """
        self.project_root = Path(project_root) if project_root else Path.cwd()
        self.home_dir = Path.home()
        self.skills_dir = skills_dir

    def get_search_paths(self) -> List[Tuple[Path, str]]:
        """获取所有搜索路径。

        Returns:
            列表，每项为 (路径, 位置类型)
        """
        paths = [
            (self.project_root / self.skills_dir, "project"),
            (self.home_dir / ".openwrite" / self.skills_dir, "user"),
        ]
        return paths

    def discover_skills(self, skills_dir: Path, location: str) -> List[Skill]:
        """发现目录中的所有功能模块。

        Args:
            skills_dir: 技能目录
            location: 位置类型

        Returns:
            发现的功能模块列表
        """
        if not skills_dir.exists():
            logger.debug("Skills directory does not exist: %s", skills_dir)
            return []

        skills = []

        for item in skills_dir.iterdir():
            if not item.is_dir():
                continue

            # 跳过特殊目录
            if item.name.startswith("_") or item.name.startswith("."):
                continue

            # 跳过 tools 目录（不是技能）
            if item.name == "tools":
                continue

            skill_md = item / self.SKILL_FILE
            if skill_md.exists():
                skill = Skill.from_skill_md(skill_md, location)
                if skill:
                    skills.append(skill)
                    logger.debug("Discovered skill: %s at %s", skill.name, item)
            else:
                logger.debug("No SKILL.md found in: %s", item)

        return skills

    def load_all(self, registry: Optional[SkillRegistry] = None) -> SkillRegistry:
        """从所有搜索路径加载功能模块。

        Args:
            registry: 现有注册表，为 None 时使用全局注册表

        Returns:
            加载后的注册表
        """
        if registry is None:
            registry = get_skill_registry()

        total_loaded = 0

        for search_path, location in self.get_search_paths():
            skills = self.discover_skills(search_path, location)

            for skill in skills:
                if registry.register(skill):
                    total_loaded += 1

        logger.info(
            "Loaded %d skills from %d paths", total_loaded, len(self.get_search_paths())
        )
        return registry

    def load_skill(self, skill_name: str) -> Optional[Skill]:
        """加载指定的功能模块。

        Args:
            skill_name: 功能名称

        Returns:
            加载的功能模块，不存在返回 None
        """
        for search_path, location in self.get_search_paths():
            skill_dir = search_path / skill_name
            skill_md = skill_dir / self.SKILL_FILE

            if skill_md.exists():
                skill = Skill.from_skill_md(skill_md, location)
                if skill:
                    return skill

        return None

    def reload(self, registry: Optional[SkillRegistry] = None) -> SkillRegistry:
        """重新加载所有功能模块。

        清空注册表后重新加载。

        Args:
            registry: 现有注册表

        Returns:
            重新加载后的注册表
        """
        if registry is None:
            registry = get_skill_registry()

        # 清空现有注册
        registry._skills.clear()

        return self.load_all(registry)
