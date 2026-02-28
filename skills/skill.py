"""Skill 数据模型

定义功能模块的标准格式，基于 SKILL.md 规范。

参考:
- https://www.mdskills.ai/specs/skill-md
- https://github.com/anthropics/claude-code/blob/main/plugins
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


@dataclass
class Skill:
    """功能模块数据模型。

    每个 Skill 代表一个独立的功能单元，包含：
    - 元数据（名称、描述、触发器）
    - 能力（工具、提示词、工作流）
    - 内容（SKILL.md 的指令部分）

    Attributes:
        name: 功能名称（唯一标识符）
        description: 功能描述（用于触发匹配）
        content: SKILL.md 的指令内容
        path: 功能目录路径

        version: 版本号
        trigger: 触发命令（如 /outline）
        triggers: 触发关键词列表
        requires: 所需工具列表
        allowed_tools: 允许使用的工具
        metadata: 额外元数据
        location: 来源位置（project/user/builtin）
    """

    # 必需字段
    name: str
    description: str
    content: str
    path: Path

    # 元数据
    version: str = "1.0.0"
    trigger: Optional[str] = None
    triggers: List[str] = field(default_factory=list)
    requires: List[str] = field(default_factory=list)
    allowed_tools: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # 来源位置
    location: str = "project"

    # 缓存
    _prompts_cache: Dict[str, str] = field(default_factory=dict, repr=False)
    _workflows_cache: Dict[str, dict] = field(default_factory=dict, repr=False)

    SKILL_FILE = "SKILL.md"

    @classmethod
    def from_skill_md(
        cls, skill_md_path: Path, location: str = "project"
    ) -> Optional["Skill"]:
        """从 SKILL.md 文件解析功能模块。

        Args:
            skill_md_path: SKILL.md 文件路径
            location: 来源位置

        Returns:
            Skill 实例，解析失败返回 None
        """
        if not skill_md_path.exists():
            return None

        content = skill_md_path.read_text(encoding="utf-8")
        frontmatter, body = cls._parse_frontmatter(content)

        name = frontmatter.get("name")
        description = frontmatter.get("description", "")

        if not name:
            return None

        return cls(
            name=name,
            description=description,
            content=body.strip(),
            path=skill_md_path.parent,
            version=frontmatter.get("version", "1.0.0"),
            trigger=frontmatter.get("trigger"),
            triggers=frontmatter.get("triggers", []) or [],
            requires=frontmatter.get("requires", []) or [],
            allowed_tools=frontmatter.get("allowed-tools", []) or [],
            metadata=frontmatter.get("metadata", {}) or {},
            location=location,
        )

    @staticmethod
    def _parse_frontmatter(content: str) -> tuple[dict, str]:
        """解析 YAML frontmatter。

        Args:
            content: 文件内容

        Returns:
            (frontmatter_dict, body_content)
        """
        pattern = r"^---\s*\n(.*?)\n---\s*\n(.*)$"
        match = re.match(pattern, content.strip(), re.DOTALL)

        if not match:
            return {}, content

        try:
            frontmatter = yaml.safe_load(match.group(1)) or {}
        except yaml.YAMLError:
            frontmatter = {}

        body = match.group(2)
        return frontmatter, body

    def matches_trigger(self, text: str) -> bool:
        """检查文本是否匹配此功能的触发器。

        Args:
            text: 用户输入文本

        Returns:
            是否匹配
        """
        text_lower = text.lower()

        # 检查命令触发器
        if self.trigger and text.strip().startswith(self.trigger):
            return True

        # 检查关键词触发器
        for trigger in self.triggers:
            if trigger.lower() in text_lower:
                return True

        return False

    def get_prompt(self, prompt_name: str) -> Optional[str]:
        """获取指定的提示词模板。

        Args:
            prompt_name: 提示词名称（不含扩展名）

        Returns:
            提示词内容，不存在返回 None
        """
        if prompt_name in self._prompts_cache:
            return self._prompts_cache[prompt_name]

        prompt_path = self.path / "prompts" / f"{prompt_name}.md"
        if prompt_path.exists():
            content = prompt_path.read_text(encoding="utf-8")
            self._prompts_cache[prompt_name] = content
            return content

        # 也支持 .txt 扩展名
        prompt_path_txt = self.path / "prompts" / f"{prompt_name}.txt"
        if prompt_path_txt.exists():
            content = prompt_path_txt.read_text(encoding="utf-8")
            self._prompts_cache[prompt_name] = content
            return content

        return None

    def get_workflow(self, workflow_name: str) -> Optional[dict]:
        """获取指定的工作流定义。

        Args:
            workflow_name: 工作流名称（不含扩展名）

        Returns:
            工作流定义字典，不存在返回 None
        """
        if workflow_name in self._workflows_cache:
            return self._workflows_cache[workflow_name]

        workflow_path = self.path / "workflows" / f"{workflow_name}.yaml"
        if workflow_path.exists():
            with workflow_path.open("r", encoding="utf-8") as f:
                workflow = yaml.safe_load(f) or {}
            self._workflows_cache[workflow_name] = workflow
            return workflow

        return None

    def get_template(self, template_name: str) -> Optional[str]:
        """获取指定的模板文件。

        Args:
            template_name: 模板名称（含扩展名）

        Returns:
            模板内容，不存在返回 None
        """
        template_path = self.path / "templates" / template_name
        if template_path.exists():
            return template_path.read_text(encoding="utf-8")
        return None

    def list_prompts(self) -> List[str]:
        """列出所有可用的提示词名称。"""
        prompts_dir = self.path / "prompts"
        if not prompts_dir.exists():
            return []
        return [p.stem for p in prompts_dir.glob("*.md")] + [
            p.stem for p in prompts_dir.glob("*.txt")
        ]

    def list_workflows(self) -> List[str]:
        """列出所有可用的工作流名称。"""
        workflows_dir = self.path / "workflows"
        if not workflows_dir.exists():
            return []
        return [p.stem for p in workflows_dir.glob("*.yaml")]

    def to_xml(self) -> str:
        """转换为 XML 格式（用于 LLM 上下文）。

        Returns:
            XML 字符串
        """
        trigger_info = f" (trigger: `{self.trigger}`)" if self.trigger else ""
        return f"""<skill name="{self.name}"{trigger_info}>
<description>{self.description}</description>
<path>{self.path}/SKILL.md</path>
</skill>"""

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式。"""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "trigger": self.trigger,
            "triggers": self.triggers,
            "requires": self.requires,
            "allowed_tools": self.allowed_tools,
            "location": self.location,
            "path": str(self.path),
        }
