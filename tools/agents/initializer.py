"""Novel initializer — 作品初始化流程。

Phase 7B-3: 用户 init 作品后的第一步：
  1. 建立全篇大致大纲 (MasterOutline)
  2. 基础世界设定 (WorldGraph entities)
  3. 相关人物设定 (TextCharacterProfile)

支持 opt-in LLM 模式：传入 llm_client + router 时使用 LLM，
否则创建骨架结构供用户手动填写。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import yaml

if TYPE_CHECKING:
    from tools.llm.client import LLMClient
    from tools.llm.router import ModelRouter

try:
    from tools.character_state_manager import CharacterStateManager
    from tools.models.character import TextCharacterProfile
    from tools.models.outline import (
        ArcOutline,
        ChapterOutline,
        MasterOutline,
        OutlineHierarchy,
        SectionOutline,
    )
    from tools.world_graph_manager import WorldGraphManager
except ImportError:  # pragma: no cover
    from character_state_manager import CharacterStateManager
    from models.character import TextCharacterProfile
    from models.outline import (
        ArcOutline,
        ChapterOutline,
        MasterOutline,
        OutlineHierarchy,
        SectionOutline,
    )
    from world_graph_manager import WorldGraphManager


@dataclass
class InitResult:
    """作品初始化结果。"""

    novel_id: str
    master_outline: Optional[MasterOutline] = None
    hierarchy: Optional[OutlineHierarchy] = None
    characters: List[TextCharacterProfile] = field(default_factory=list)
    world_entities_created: int = 0
    errors: List[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.master_outline is not None and not self.errors


class NovelInitializer:
    """作品初始化器 — 创建骨架大纲、世界设定、人物档案。"""

    def __init__(
        self,
        project_dir: Path,
        novel_id: str,
        llm_client: Optional["LLMClient"] = None,
        router: Optional["ModelRouter"] = None,
    ):
        self.project_dir = project_dir
        self.novel_id = novel_id
        self._llm_client = llm_client
        self._router = router

        self.base_dir = project_dir / "data" / "novels" / novel_id
        self.outline_dir = self.base_dir / "outline"
        self.hierarchy_file = self.outline_dir / "hierarchy.yaml"
        self.characters_dir = self.base_dir / "characters" / "text_profiles"

        self.char_mgr = CharacterStateManager(
            project_dir=project_dir, novel_id=novel_id
        )
        self.world_mgr = WorldGraphManager(project_dir=project_dir, novel_id=novel_id)

    def initialize(
        self,
        *,
        title: str = "",
        core_theme: str = "",
        ending_direction: str = "",
        world_premise: str = "",
        tone: str = "",
        target_word_count: int = 0,
        key_turns: Optional[List[str]] = None,
        arc_sketches: Optional[List[Dict[str, str]]] = None,
        character_sketches: Optional[List[Dict[str, str]]] = None,
        world_entities: Optional[List[Dict[str, str]]] = None,
    ) -> InitResult:
        """执行完整初始化流程。

        Args:
            title: 书名
            core_theme: 核心主题
            ending_direction: 结局走向
            world_premise: 世界观前提
            tone: 整体基调
            target_word_count: 目标总字数
            key_turns: 全书关键转折列表
            arc_sketches: 篇纲草案列表，每项 {"title", "main_conflict", "resolution"}
            character_sketches: 人物草案列表，每项 {"name", "char_type", ...}
            world_entities: 世界设定实体列表，每项 {"name", "type", "description"}

        Returns:
            InitResult 包含创建的所有结构
        """
        result = InitResult(novel_id=self.novel_id)

        # 确保目录存在
        self.outline_dir.mkdir(parents=True, exist_ok=True)
        self.characters_dir.mkdir(parents=True, exist_ok=True)

        # Step 1: 建立总纲
        try:
            hierarchy = self._create_outline_hierarchy(
                title=title,
                core_theme=core_theme,
                ending_direction=ending_direction,
                world_premise=world_premise,
                tone=tone,
                target_word_count=target_word_count,
                key_turns=key_turns or [],
                arc_sketches=arc_sketches or [],
            )
            result.master_outline = hierarchy.master
            result.hierarchy = hierarchy
            self._save_hierarchy(hierarchy)
        except Exception as exc:
            result.errors.append(f"大纲创建失败: {exc}")

        # Step 2: 建立人物档案
        for sketch in character_sketches or []:
            try:
                profile = self._create_character(sketch)
                result.characters.append(profile)
            except Exception as exc:
                result.errors.append(f"人物创建失败 ({sketch.get('name', '?')}): {exc}")

        # Step 3: 建立世界设定
        for entity_data in world_entities or []:
            try:
                self._create_world_entity(entity_data)
                result.world_entities_created += 1
            except Exception as exc:
                result.errors.append(
                    f"世界设定创建失败 ({entity_data.get('name', '?')}): {exc}"
                )

        return result

    def _create_outline_hierarchy(
        self,
        *,
        title: str,
        core_theme: str,
        ending_direction: str,
        world_premise: str,
        tone: str,
        target_word_count: int,
        key_turns: List[str],
        arc_sketches: List[Dict[str, str]],
    ) -> OutlineHierarchy:
        """创建四级大纲层级骨架。"""
        # 生成篇纲
        arcs: Dict[str, ArcOutline] = {}
        arc_ids: List[str] = []
        sections: Dict[str, SectionOutline] = {}
        chapters: Dict[str, ChapterOutline] = {}

        for i, sketch in enumerate(arc_sketches):
            arc_id = f"arc_{i + 1:03d}"
            arc_ids.append(arc_id)

            # 每篇默认创建一个节和一个章
            sec_id = f"sec_{arc_id}_001"
            ch_id = f"ch_{sec_id}_001"

            sections[sec_id] = SectionOutline(
                section_id=sec_id,
                arc_id=arc_id,
                title=sketch.get("title", f"第{i + 1}篇·第1节"),
                order=1,
                plot_summary=sketch.get("main_conflict", ""),
                chapter_ids=[ch_id],
            )

            chapters[ch_id] = ChapterOutline(
                chapter_id=ch_id,
                section_id=sec_id,
                title=f"第{i + 1}篇·第1节·第1章",
                order=1,
                goals=[sketch.get("main_conflict", "推进剧情")],
            )

            arcs[arc_id] = ArcOutline(
                arc_id=arc_id,
                novel_id=self.novel_id,
                title=sketch.get("title", f"第{i + 1}篇"),
                order=i + 1,
                main_conflict=sketch.get("main_conflict", ""),
                resolution=sketch.get("resolution", ""),
                section_ids=[sec_id],
            )

        # 如果没有提供篇纲草案，创建一个空的默认篇
        if not arc_sketches:
            arc_id = "arc_001"
            sec_id = "sec_arc_001_001"
            ch_id = "ch_sec_arc_001_001_001"
            arc_ids = [arc_id]
            sections[sec_id] = SectionOutline(
                section_id=sec_id,
                arc_id=arc_id,
                title="第1篇·第1节",
                order=1,
                chapter_ids=[ch_id],
            )
            chapters[ch_id] = ChapterOutline(
                chapter_id=ch_id,
                section_id=sec_id,
                title="第1篇·第1节·第1章",
                order=1,
            )
            arcs[arc_id] = ArcOutline(
                arc_id=arc_id,
                novel_id=self.novel_id,
                title="第1篇",
                order=1,
                section_ids=[sec_id],
            )

        master = MasterOutline(
            novel_id=self.novel_id,
            title=title,
            core_theme=core_theme,
            ending_direction=ending_direction,
            key_turns=key_turns,
            world_premise=world_premise,
            tone=tone,
            target_word_count=target_word_count,
            arc_ids=arc_ids,
        )

        return OutlineHierarchy(
            master=master,
            arcs=arcs,
            sections=sections,
            chapters=chapters,
        )

    def _create_character(self, sketch: Dict[str, str]) -> TextCharacterProfile:
        """从草案创建 TextCharacterProfile 并持久化。"""
        name = sketch.get("name", "")
        if not name:
            raise ValueError("人物名不能为空")

        char_id = sketch.get("id", f"char_{name}")
        profile = TextCharacterProfile(
            id=char_id,
            name=name,
            char_type=sketch.get("char_type", "配角"),
            appearance=sketch.get("appearance", ""),
            personality_and_voice=sketch.get("personality_and_voice", ""),
            skills_and_abilities=sketch.get("skills_and_abilities", ""),
            items=sketch.get("items", ""),
            attributes=sketch.get("attributes", ""),
            notes=sketch.get("notes", ""),
            faction=sketch.get("faction", ""),
            aliases=sketch.get("aliases", "").split(",")
            if sketch.get("aliases")
            else [],
        )

        # 持久化为 YAML
        profile_path = self.characters_dir / f"{char_id}.yaml"
        with profile_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(profile.model_dump(), f, allow_unicode=True, sort_keys=False)

        return profile

    def _create_world_entity(self, entity_data: Dict[str, str]) -> None:
        """创建世界设定实体。"""
        name = entity_data.get("name", "")
        if not name:
            raise ValueError("实体名不能为空")

        entity_id = entity_data.get("id", f"entity_{name}")
        self.world_mgr.upsert_entity(
            entity_id=entity_id,
            name=name,
            entity_type=entity_data.get("type", "concept"),
            description=entity_data.get("description", ""),
            tags=entity_data.get("tags", "").split(",")
            if entity_data.get("tags")
            else [],
        )

    def _save_hierarchy(self, hierarchy: OutlineHierarchy) -> None:
        """将大纲层级持久化为 YAML。"""
        data = hierarchy.model_dump()
        with self.hierarchy_file.open("w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)

    def load_hierarchy(self) -> Optional[OutlineHierarchy]:
        """从磁盘加载已有的大纲层级。"""
        if not self.hierarchy_file.exists():
            return None
        with self.hierarchy_file.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return OutlineHierarchy.model_validate(data)

    def load_text_characters(self) -> List[TextCharacterProfile]:
        """加载所有 TextCharacterProfile。"""
        profiles: List[TextCharacterProfile] = []
        if not self.characters_dir.exists():
            return profiles
        for path in sorted(self.characters_dir.glob("*.yaml")):
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            profiles.append(TextCharacterProfile.model_validate(data))
        return profiles
