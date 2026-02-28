"""Character query helpers.

提供角色查询功能，包括：
- 获取角色当前状态
- 获取角色时间线
- 获取角色关系

Usage:
    from skills.character.tools import CharacterQuery

    query = CharacterQuery(project_dir=Path.cwd(), novel_id="my_novel")
    state = query.get_current_state("李逍遥")
    timeline = query.get_timeline("李逍遥")
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class CharacterSummary(BaseModel):
    """角色摘要，用于简化查询结果。"""

    id: str
    name: str
    tier: str
    location: str = "未知"
    realm: str = "凡人"
    statuses: List[str] = []
    key_items: List[str] = []


class CharacterQuery:
    """角色查询工具。

    提供统一的角色信息查询接口。

    Args:
        project_dir: 项目根目录
        novel_id: 小说 ID

    Usage:
        query = CharacterQuery(project_dir=Path.cwd(), novel_id="my_novel")
        state = query.get_current_state("李逍遥")
    """

    def __init__(
        self,
        project_dir: Optional[Path] = None,
        novel_id: str = "my_novel",
    ):
        self.project_dir = project_dir or self._find_project_dir()
        self.novel_id = novel_id
        self.characters_dir = (
            self.project_dir / "data" / "novels" / self.novel_id / "characters"
        )
        self.text_profiles_dir = self.characters_dir / "text_profiles"

    def _find_project_dir(self) -> Path:
        """查找项目根目录。"""
        cwd = Path.cwd()
        for parent in [cwd] + list(cwd.parents):
            if (parent / "data" / "novels").exists() and (parent / "tools").exists():
                return parent
        return cwd

    def _load_yaml(self, path: Path) -> Dict[str, Any]:
        """加载 YAML 文件。"""
        if not path.exists():
            return {}
        import yaml

        with path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def get_current_state(self, name: str) -> Dict[str, Any]:
        """获取角色当前状态。

        Args:
            name: 角色名称

        Returns:
            角色状态信息
        """
        # 首先尝试使用旧的 CharacterStateManager
        try:
            from tools.character_state_manager import CharacterStateManager

            manager = CharacterStateManager(
                project_dir=self.project_dir,
                novel_id=self.novel_id,
            )
            card = manager.get_character_card(name=name)
            state = manager.rebuild_state(character_id=card.static.id)
            return {
                "id": card.static.id,
                "name": card.static.name,
                "tier": card.static.tier,
                "state": state.model_dump(),
                "dynamic_profile": card.dynamic_profile,
                "snapshot": card.current_snapshot,
            }
        except Exception:
            pass

        # 回退到直接读取文本档案
        return self._get_text_profile(name)

    def _get_text_profile(self, name: str) -> Dict[str, Any]:
        """获取文本优先档案。"""
        # 尝试匹配角色名
        if not self.text_profiles_dir.exists():
            return {"error": f"Character not found: {name}"}

        for profile_file in self.text_profiles_dir.glob("*.yaml"):
            data = self._load_yaml(profile_file)
            if data.get("name") == name:
                return {
                    "id": data.get("id", profile_file.stem),
                    "name": name,
                    "tier": data.get("char_type", "未知"),
                    "text_profile": data,
                }

        return {"error": f"Character not found: {name}"}

    def get_timeline(self, name: str) -> List[Dict[str, Any]]:
        """获取角色时间线。

        Args:
            name: 角色名称

        Returns:
            时间线事件列表
        """
        try:
            from tools.character_state_manager import CharacterStateManager

            manager = CharacterStateManager(
                project_dir=self.project_dir,
                novel_id=self.novel_id,
            )
            card = manager.get_character_card(name=name)
            timeline = manager.get_timeline(character_id=card.static.id)
            return [mutation.model_dump() for mutation in timeline]
        except Exception:
            return []

    def get_relationships(self, name: str) -> List[Dict[str, Any]]:
        """获取角色关系。

        Args:
            name: 角色名称

        Returns:
            关系列表
        """
        state = self.get_current_state(name)
        if "error" in state:
            return []

        # 从卡片中获取关系
        try:
            from tools.character_state_manager import CharacterStateManager

            manager = CharacterStateManager(
                project_dir=self.project_dir,
                novel_id=self.novel_id,
            )
            card = manager.get_character_card(name=name)
            return [r.model_dump() for r in card.relationships]
        except Exception:
            return []

    def list_characters(
        self,
        tier: Optional[str] = None,
    ) -> List[CharacterSummary]:
        """列出所有角色。

        Args:
            tier: 角色层级过滤（可选）

        Returns:
            角色摘要列表
        """
        summaries = []

        if not self.text_profiles_dir.exists():
            return summaries

        for profile_file in self.text_profiles_dir.glob("*.yaml"):
            data = self._load_yaml(profile_file)
            char_tier = data.get("char_type", "")

            if tier and tier != char_tier:
                continue

            summaries.append(
                CharacterSummary(
                    id=data.get("id", profile_file.stem),
                    name=data.get("name", profile_file.stem),
                    tier=char_tier,
                    location=data.get("attributes", ""),
                    realm="",
                    statuses=[],
                    key_items=[],
                )
            )

        return summaries

    def get_character_context(
        self,
        name: str,
        max_chars: int = 500,
    ) -> str:
        """获取角色上下文文本。

        用于 AI 上下文的角色信息摘要。

        Args:
            name: 角色名称
            max_chars: 最大字符数

        Returns:
            角色上下文文本
        """
        state = self.get_current_state(name)

        if "error" in state:
            return f"角色 {name} 不存在"

        # 如果有文本档案，使用 to_context_text
        if "text_profile" in state:
            from tools.models.character import TextCharacterProfile

            profile = TextCharacterProfile(**state["text_profile"])
            return profile.to_context_text(max_chars)

        # 否则生成简化摘要
        parts = [f"【{state.get('name', name)}】"]
        parts.append(f"类型：{state.get('tier', '未知')}")

        if "state" in state:
            s = state["state"]
            if s.get("location"):
                parts.append(f"位置：{s['location']}")
            if s.get("realm"):
                parts.append(f"境界：{s['realm']}")

        text = "\n".join(parts)
        if max_chars and len(text) > max_chars:
            return text[:max_chars] + "…"
        return text
