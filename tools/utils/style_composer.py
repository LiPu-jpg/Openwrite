"""Style Composer — merges three-layer style docs into a single generation-ready document.

Layers (ascending priority):
  1. craft/          — universal writing techniques (optional reference)
  2. styles/{id}/    — work-specific style fingerprint (core constraints)
  3. novels/{id}/    — work settings (hard constraints, injected by main system)

User overrides sit above all three layers.

Output: composed/{novel_id}_final.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class StyleLayer:
    """One layer of style documents."""

    name: str
    priority: int  # higher = stronger
    files: Dict[str, str] = field(default_factory=dict)  # filename -> content


@dataclass
class ComposedStyle:
    """Result of style composition."""

    novel_id: str
    style_id: str
    hard_constraints: str
    style_constraints: str
    craft_reference: str
    user_overrides: str
    source_summary: str
    composed_at: str = ""

    def to_markdown(self) -> str:
        """Render the composed style as a markdown document."""
        sections: List[str] = [
            f"# 最终风格文档：{self.novel_id}",
            "",
            f"> 合成时间：{self.composed_at}",
            "",
            "## 来源",
            self.source_summary,
            "",
            "## 硬性约束（不可违反）",
            "",
            self.hard_constraints or "（无硬性约束）",
            "",
            "## 风格约束（应当遵循）",
            "",
            self.style_constraints or "（无风格约束）",
            "",
            "## 可选技法（按需使用）",
            "",
            self.craft_reference or "（无通用技法加载）",
            "",
            "## 用户覆盖",
            "",
            self.user_overrides or "（无用户覆盖）",
        ]
        return "\n".join(sections) + "\n"


class StyleComposer:
    """Loads and composes three-layer style documents."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.craft_dir = project_root / "craft"
        self.styles_dir = project_root / "styles"
        self.novels_dir = project_root / "novels"
        self.composed_dir = project_root / "composed"

    def _load_md_files(self, directory: Path) -> Dict[str, str]:
        """Load all .md files from a directory, return {filename: content}."""
        result: Dict[str, str] = {}
        if not directory.is_dir():
            return result
        for md_file in sorted(directory.glob("*.md")):
            content = md_file.read_text(encoding="utf-8").strip()
            if content:
                result[md_file.stem] = content
        return result

    def load_craft_layer(self) -> StyleLayer:
        """Load universal writing techniques from craft/."""
        files = self._load_md_files(self.craft_dir)
        return StyleLayer(name="通用技法", priority=1, files=files)

    def load_style_layer(self, style_id: str) -> StyleLayer:
        """Load work-specific style fingerprint from styles/{style_id}/."""
        style_dir = self.styles_dir / style_id
        files = self._load_md_files(style_dir)
        return StyleLayer(name=f"作品风格：{style_id}", priority=2, files=files)

    def load_novel_layer(self, novel_id: str) -> StyleLayer:
        """Load work settings (hard constraints) from novels/{novel_id}/."""
        novel_dir = self.novels_dir / novel_id
        files = self._load_md_files(novel_dir)
        return StyleLayer(name=f"作品设定：{novel_id}", priority=3, files=files)

    def _extract_section(self, content: str, heading: str) -> str:
        """Extract content under a specific markdown heading."""
        lines = content.split("\n")
        capturing = False
        captured: List[str] = []
        heading_lower = heading.lower()

        for line in lines:
            stripped = line.strip().lower()
            if stripped.startswith("#") and heading_lower in stripped:
                capturing = True
                continue
            if capturing:
                if stripped.startswith("#") and not stripped.startswith("###"):
                    break
                captured.append(line)

        return "\n".join(captured).strip()

    def _build_hard_constraints(self, novel_layer: StyleLayer) -> str:
        """Extract hard constraints from novel settings layer."""
        sections: List[str] = []

        # Characters — always a hard constraint
        if "characters" in novel_layer.files:
            sections.append("### 角色一致性约束\n")
            sections.append(novel_layer.files["characters"])

        # Worldbuilding rules
        if "worldbuilding_rules" in novel_layer.files:
            sections.append("\n### 世界观规则\n")
            sections.append(novel_layer.files["worldbuilding_rules"])

        # Terminology
        if "terminology" in novel_layer.files:
            sections.append("\n### 术语表\n")
            sections.append(novel_layer.files["terminology"])

        # Scene instances as reference
        if "scene_instances" in novel_layer.files:
            sections.append("\n### 名场面参考\n")
            sections.append(novel_layer.files["scene_instances"])

        return "\n".join(sections)

    def _build_style_constraints(self, style_layer: StyleLayer) -> str:
        """Extract style constraints from the style fingerprint layer."""
        sections: List[str] = []

        # Fingerprint is the core style DNA
        if "fingerprint" in style_layer.files:
            sections.append("### 风格DNA\n")
            sections.append(style_layer.files["fingerprint"])

        # Voice
        if "voice" in style_layer.files:
            sections.append("\n### 叙述者声音\n")
            sections.append(style_layer.files["voice"])

        # Language style
        if "language" in style_layer.files:
            sections.append("\n### 语言风格\n")
            sections.append(style_layer.files["language"])

        # Rhythm
        if "rhythm" in style_layer.files:
            sections.append("\n### 节奏风格\n")
            sections.append(style_layer.files["rhythm"])

        # Humor system
        if "humor" in style_layer.files:
            sections.append("\n### 幽默体系\n")
            sections.append(style_layer.files["humor"])

        # Dialogue craft (style-specific, overrides generic craft)
        if "dialogue_craft" in style_layer.files:
            sections.append("\n### 对话风格\n")
            sections.append(style_layer.files["dialogue_craft"])

        return "\n".join(sections)

    def _build_craft_reference(
        self, craft_layer: StyleLayer, style_layer: StyleLayer
    ) -> str:
        """Build craft reference, excluding files already covered by style layer."""
        sections: List[str] = []
        style_keys = set(style_layer.files.keys())

        for filename, content in craft_layer.files.items():
            # Skip craft files that have style-layer overrides
            if filename in style_keys:
                continue
            sections.append(f"### {filename}\n")
            sections.append(content)
            sections.append("")

        return "\n".join(sections)

    def compose(
        self,
        novel_id: str,
        style_id: str,
        user_overrides: Optional[Dict[str, str]] = None,
        write_output: bool = True,
    ) -> ComposedStyle:
        """Compose all three layers into a single style document.

        Priority: user_overrides > novel settings (hard) > style (core) > craft (optional)
        """
        craft_layer = self.load_craft_layer()
        style_layer = self.load_style_layer(style_id)
        novel_layer = self.load_novel_layer(novel_id)

        hard_constraints = self._build_hard_constraints(novel_layer)
        style_constraints = self._build_style_constraints(style_layer)
        craft_reference = self._build_craft_reference(craft_layer, style_layer)

        override_text = ""
        if user_overrides:
            override_lines: List[str] = []
            for key, value in user_overrides.items():
                override_lines.append(f"- **{key}**：{value}")
            override_text = "\n".join(override_lines)

        source_summary = (
            f"- 作品风格：{style_id}（权重：100%）\n"
            f"- 通用技法：已加载（{len(craft_layer.files)}个文件）\n"
            f"- 作品设定：{novel_id}（{len(novel_layer.files)}个文件）"
        )

        composed = ComposedStyle(
            novel_id=novel_id,
            style_id=style_id,
            hard_constraints=hard_constraints,
            style_constraints=style_constraints,
            craft_reference=craft_reference,
            user_overrides=override_text,
            source_summary=source_summary,
            composed_at=datetime.now().isoformat(),
        )

        if write_output:
            self.composed_dir.mkdir(parents=True, exist_ok=True)
            output_path = self.composed_dir / f"{novel_id}_final.md"
            output_path.write_text(composed.to_markdown(), encoding="utf-8")

        return composed

    def get_composed_path(self, novel_id: str) -> Path:
        """Return the expected path for a composed style document."""
        return self.composed_dir / f"{novel_id}_final.md"

    def load_composed(self, novel_id: str) -> Optional[str]:
        """Load a previously composed style document, if it exists."""
        path = self.get_composed_path(novel_id)
        if path.is_file():
            return path.read_text(encoding="utf-8")
        return None

    def list_available_styles(self) -> List[str]:
        """List all available style IDs under styles/."""
        if not self.styles_dir.is_dir():
            return []
        return sorted(
            d.name
            for d in self.styles_dir.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        )

    def list_available_novels(self) -> List[str]:
        """List all available novel IDs under novels/."""
        if not self.novels_dir.is_dir():
            return []
        return sorted(
            d.name
            for d in self.novels_dir.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        )
