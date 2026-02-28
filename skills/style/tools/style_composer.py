"""Style Composer for skills/style/ — 合并多层风格文档为最终生成指令。

核心功能：
1. 加载三层风格文档（craft/style/novels）
2. 解决冲突（优先级：用户覆盖 > 作品设定 > 作品风格 > 通用技法）
3. 合并去重
4. 输出最终风格文档
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml


@dataclass
class StyleLayer:
    """风格层。"""

    name: str
    priority: int  # 越高优先级越高
    source_path: str
    content: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ComposedStyle:
    """合成后的风格。"""

    novel_id: str
    style_id: str
    composed_at: str

    # 各层内容
    hard_constraints: Dict[str, Any] = field(default_factory=dict)  # 作品设定
    style_constraints: Dict[str, Any] = field(default_factory=dict)  # 作品风格
    craft_reference: Dict[str, Any] = field(default_factory=dict)  # 通用技法
    user_overrides: Dict[str, Any] = field(default_factory=dict)  # 用户覆盖

    # 合并后的最终内容
    final_content: Dict[str, Any] = field(default_factory=dict)

    # 来源追踪
    sources: List[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        """转换为 Markdown 格式。

        Returns:
            Markdown 字符串
        """
        lines: List[str] = [
            f"# 最终风格文档：{self.novel_id}",
            "",
            f"> 合成时间：{self.composed_at}",
            f"> 来源：{', '.join(self.sources)}",
            "",
            "---",
            "",
            "## 1. 硬性约束（不可违反）",
            "",
            "> 来源：novels/{id}/",
            "",
            self._dict_to_markdown(self.hard_constraints),
            "",
            "---",
            "",
            "## 2. 风格约束（应当遵循）",
            "",
            "> 来源：styles/{id}/ + 问询生成",
            "",
            self._dict_to_markdown(self.style_constraints),
            "",
            "---",
            "",
            "## 3. 可选技法（按需使用）",
            "",
            "> 来源：craft/",
            "",
            self._dict_to_markdown(self.craft_reference),
            "",
            "---",
            "",
            "## 4. 用户覆盖",
            "",
            "> 来源：用户自定义",
            "",
            self._dict_to_markdown(self.user_overrides) or "（无用户覆盖）",
            "",
            "---",
            "",
            "## 5. 文本人化规则（去AI味）",
            "",
            self._get_humanization_section(),
            "",
            "---",
            "",
            "## 6. 生成检查清单",
            "",
            "在生成文本后，检查以下要点：",
            "",
            "- [ ] 是否违反硬性约束？",
            "- [ ] 风格约束是否遵循？",
            "- [ ] 是否有AI味表达？",
            "- [ ] 节奏是否符合设定？",
            "- [ ] 对话风格是否一致？",
        ]

        return "\n".join(lines)

    def _dict_to_markdown(self, data: Dict[str, Any], indent: int = 0) -> str:
        """将字典转换为 Markdown。

        Args:
            data: 数据字典
            indent: 缩进级别

        Returns:
            Markdown 字符串
        """
        lines: List[str] = []
        prefix = "  " * indent

        for key, value in data.items():
            if isinstance(value, dict):
                lines.append(f"{prefix}### {key}")
                lines.append(self._dict_to_markdown(value, indent + 1))
            elif isinstance(value, list):
                lines.append(f"{prefix}**{key}**:")
                for item in value:
                    if isinstance(item, str):
                        lines.append(f"{prefix}- {item}")
                    elif isinstance(item, dict):
                        lines.append(self._dict_to_markdown(item, indent + 1))
            else:
                lines.append(f"{prefix}**{key}**: {value}")

        return "\n".join(lines)

    def _get_humanization_section(self) -> str:
        """获取文本人化规则部分。

        Returns:
            人化规则 Markdown
        """
        humanization = self.craft_reference.get("humanization", {})

        lines: List[str] = [
            "> 来源：craft/humanization.yaml",
            "",
        ]

        # 禁用词库
        banned_words = humanization.get("banned_words", [])
        if banned_words:
            lines.append("### 5.1 禁用词库")
            lines.append("")
            for word in banned_words[:20]:  # 限制数量
                lines.append(f"- `{word}`")
            if len(banned_words) > 20:
                lines.append(f"- ... 共 {len(banned_words)} 个")
            lines.append("")

        # AI 常见表达
        ai_phrases = humanization.get("ai_phrases", [])
        if ai_phrases:
            lines.append("### 5.2 AI常见表达（避免使用）")
            lines.append("")
            for phrase in ai_phrases[:15]:
                lines.append(f"- `{phrase}`")
            if len(ai_phrases) > 15:
                lines.append(f"- ... 共 {len(ai_phrases)} 个")
            lines.append("")

        # 自然化规则
        rules = humanization.get("naturalization_rules", [])
        if rules:
            lines.append("### 5.3 自然不完美规则")
            lines.append("")
            for rule in rules[:10]:
                lines.append(f"- {rule}")

        return "\n".join(lines)


class StyleComposer:
    """风格合成器。"""

    # 优先级定义
    PRIORITY_CRAFT = 1
    PRIORITY_STYLE = 2
    PRIORITY_NOVEL = 3
    PRIORITY_USER = 4

    def __init__(self, project_root: Path):
        """初始化风格合成器。

        Args:
            project_root: 项目根目录
        """
        self.project_root = project_root
        self.craft_dir = project_root / "craft"
        self.styles_dir = project_root / "styles"
        self.novels_dir = project_root / "novels"
        self.composed_dir = project_root / "composed"

    def load_craft_layer(self) -> StyleLayer:
        """加载通用技法层。

        Returns:
            通用技法层
        """
        content: Dict[str, Any] = {}

        # 加载 humanization.yaml
        humanization_path = self.craft_dir / "humanization.yaml"
        if humanization_path.exists():
            with open(humanization_path, "r", encoding="utf-8") as f:
                content["humanization"] = yaml.safe_load(f) or {}

        # 加载其他 .md 文件
        for md_file in self.craft_dir.glob("*.md"):
            file_content = md_file.read_text(encoding="utf-8").strip()
            if file_content:
                content[md_file.stem] = {"raw_content": file_content}

        return StyleLayer(
            name="通用技法",
            priority=self.PRIORITY_CRAFT,
            source_path="craft/",
            content=content,
        )

    def load_style_layer(self, style_id: str) -> StyleLayer:
        """加载作品风格层。

        Args:
            style_id: 风格 ID

        Returns:
            作品风格层
        """
        content: Dict[str, Any] = {}
        style_dir = self.styles_dir / style_id

        if not style_dir.exists():
            return StyleLayer(
                name="作品风格",
                priority=self.PRIORITY_STYLE,
                source_path=f"styles/{style_id}/",
                content=content,
            )

        # 加载 fingerprint.yaml
        fingerprint_path = style_dir / "fingerprint.yaml"
        if fingerprint_path.exists():
            with open(fingerprint_path, "r", encoding="utf-8") as f:
                content["fingerprint"] = yaml.safe_load(f) or {}

        # 加载其他 .yaml 文件
        for yaml_file in style_dir.glob("*.yaml"):
            if yaml_file.stem != "fingerprint":
                with open(yaml_file, "r", encoding="utf-8") as f:
                    content[yaml_file.stem] = yaml.safe_load(f) or {}

        # 加载 .md 文件
        for md_file in style_dir.glob("*.md"):
            file_content = md_file.read_text(encoding="utf-8").strip()
            if file_content:
                content[md_file.stem] = {"raw_content": file_content}

        return StyleLayer(
            name="作品风格",
            priority=self.PRIORITY_STYLE,
            source_path=f"styles/{style_id}/",
            content=content,
        )

    def load_novel_layer(self, novel_id: str) -> StyleLayer:
        """加载作品设定层。

        Args:
            novel_id: 小说 ID

        Returns:
            作品设定层
        """
        content: Dict[str, Any] = {}
        novel_dir = self.novels_dir / novel_id

        if not novel_dir.exists():
            return StyleLayer(
                name="作品设定",
                priority=self.PRIORITY_NOVEL,
                source_path=f"novels/{novel_id}/",
                content=content,
            )

        # 加载 style/fingerprint.yaml
        fingerprint_path = novel_dir / "style" / "fingerprint.yaml"
        if fingerprint_path.exists():
            with open(fingerprint_path, "r", encoding="utf-8") as f:
                content["fingerprint"] = yaml.safe_load(f) or {}

        # 加载其他设定文件
        for md_file in novel_dir.glob("*.md"):
            file_content = md_file.read_text(encoding="utf-8").strip()
            if file_content:
                content[md_file.stem] = {"raw_content": file_content}

        return StyleLayer(
            name="作品设定",
            priority=self.PRIORITY_NOVEL,
            source_path=f"novels/{novel_id}/",
            content=content,
        )

    def compose(
        self,
        novel_id: str,
        style_id: Optional[str] = None,
        user_overrides: Optional[Dict[str, Any]] = None,
    ) -> ComposedStyle:
        """合成风格。

        Args:
            novel_id: 小说 ID
            style_id: 风格 ID（可选，默认使用小说专属风格）
            user_overrides: 用户覆盖（可选）

        Returns:
            合成后的风格
        """
        # 确定使用的风格 ID
        if not style_id:
            style_id = novel_id

        # 加载各层
        craft_layer = self.load_craft_layer()
        style_layer = self.load_style_layer(style_id)
        novel_layer = self.load_novel_layer(novel_id)

        # 提取内容
        hard_constraints = self._extract_hard_constraints(novel_layer)
        style_constraints = self._extract_style_constraints(style_layer, novel_layer)
        craft_reference = craft_layer.content

        # 应用用户覆盖
        final_overrides = user_overrides or {}

        # 合并最终内容
        final_content = self._merge_layers(
            craft_layer.content,
            style_constraints,
            hard_constraints,
            final_overrides,
        )

        # 构建结果
        composed = ComposedStyle(
            novel_id=novel_id,
            style_id=style_id,
            composed_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            hard_constraints=hard_constraints,
            style_constraints=style_constraints,
            craft_reference=craft_reference,
            user_overrides=final_overrides,
            final_content=final_content,
            sources=[
                f"craft/",
                f"styles/{style_id}/",
                f"novels/{novel_id}/",
            ],
        )

        return composed

    def _extract_hard_constraints(self, novel_layer: StyleLayer) -> Dict[str, Any]:
        """从作品设定层提取硬性约束。

        Args:
            novel_layer: 作品设定层

        Returns:
            硬性约束字典
        """
        constraints: Dict[str, Any] = {}

        # 从 fingerprint 提取
        fingerprint = novel_layer.content.get("fingerprint", {})
        if fingerprint:
            # 禁用清单
            if "banned" in fingerprint:
                constraints["banned"] = fingerprint["banned"]

            # 核心设定
            if "core" in fingerprint:
                constraints["core"] = fingerprint["core"]

        # 从其他设定文件提取
        for key, value in novel_layer.content.items():
            if key not in ["fingerprint"] and isinstance(value, dict):
                if "raw_content" not in value or len(value) > 1:
                    constraints[key] = value

        return constraints

    def _extract_style_constraints(
        self, style_layer: StyleLayer, novel_layer: StyleLayer
    ) -> Dict[str, Any]:
        """从作品风格层提取风格约束。

        Args:
            style_layer: 作品风格层
            novel_layer: 作品设定层（用于合并专属风格）

        Returns:
            风格约束字典
        """
        constraints: Dict[str, Any] = {}

        # 从 style_layer 提取
        fingerprint = style_layer.content.get("fingerprint", {})
        if fingerprint:
            if "features" in fingerprint:
                constraints["features"] = fingerprint["features"]
            if "reference_style" in fingerprint:
                constraints["reference_style"] = fingerprint["reference_style"]

        # 从 novel_layer 的专属风格合并
        novel_fingerprint = novel_layer.content.get("fingerprint", {})
        if novel_fingerprint:
            # 作品专属风格优先
            if "features" in novel_fingerprint:
                existing_features = constraints.get("features", {})
                existing_features.update(novel_fingerprint["features"])
                constraints["features"] = existing_features

        # 加载其他风格文件
        for key, value in style_layer.content.items():
            if key not in ["fingerprint"]:
                constraints[key] = value

        return constraints

    def _merge_layers(
        self,
        craft: Dict[str, Any],
        style: Dict[str, Any],
        novel: Dict[str, Any],
        user: Dict[str, Any],
    ) -> Dict[str, Any]:
        """合并所有层。

        Args:
            craft: 通用技法
            style: 作品风格
            novel: 作品设定
            user: 用户覆盖

        Returns:
            合并后的字典
        """
        merged: Dict[str, Any] = {}

        # 按优先级从低到高合并
        # 1. 通用技法
        self._deep_merge(merged, craft)

        # 2. 作品风格
        self._deep_merge(merged, style)

        # 3. 作品设定
        self._deep_merge(merged, novel)

        # 4. 用户覆盖（最高优先级）
        self._deep_merge(merged, user)

        return merged

    def _deep_merge(self, base: Dict[str, Any], override: Dict[str, Any]) -> None:
        """深度合并字典。

        Args:
            base: 基础字典（会被修改）
            override: 覆盖字典
        """
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self._deep_merge(base[key], value)
            else:
                base[key] = value

    def save_composed(self, composed: ComposedStyle) -> Path:
        """保存合成后的风格。

        Args:
            composed: 合成后的风格

        Returns:
            保存的文件路径
        """
        # 确保目录存在
        self.composed_dir.mkdir(parents=True, exist_ok=True)

        # 保存 Markdown
        md_path = self.composed_dir / f"{composed.novel_id}_final.md"
        md_path.write_text(composed.to_markdown(), encoding="utf-8")

        # 同时保存 YAML 版本
        yaml_path = self.composed_dir / f"{composed.novel_id}_final.yaml"
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.dump(
                composed.final_content,
                f,
                allow_unicode=True,
                default_flow_style=False,
            )

        return md_path


def compose_style(
    project_root: Path,
    novel_id: str,
    style_id: Optional[str] = None,
    user_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[ComposedStyle, Path]:
    """便捷函数：合成风格并保存。

    Args:
        project_root: 项目根目录
        novel_id: 小说 ID
        style_id: 风格 ID（可选）
        user_overrides: 用户覆盖（可选）

    Returns:
        (合成后的风格, 保存路径)
    """
    composer = StyleComposer(project_root)
    composed = composer.compose(novel_id, style_id, user_overrides)
    path = composer.save_composed(composed)
    return composed, path
