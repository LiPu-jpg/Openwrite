"""上下文构建器 - 组装生成所需的所有上下文

这是上下文组装的核心组件，负责：
1. 加载大纲窗口（前后 N 章）
2. 识别并加载出场角色
3. 查询伏笔状态（待回收/已埋下）
4. 合成三层风格架构
5. 提取相关世界观规则
6. Token 预算管理和动态压缩
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
import yaml
import re

logger = logging.getLogger(__name__)

# Import from sibling models
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from models.outline import OutlineNode, OutlineNodeType, OutlineHierarchy
from models.character import CharacterCard, CharacterProfile, CharacterTier
from models.style import StyleProfile, VoicePattern, LanguageStyle, RhythmStyle
from models.context_package import (
    GenerationContext,
    ForeshadowingState,
    WorldRules,
)
from .truth_manager import TruthFilesManager
from .chapter_memory import ChapterMemoryStore
from .frontmatter import parse_toml_front_matter
from .outline_cache import deserialize_outline_hierarchy
from .shared_documents import render_indexed_document, resolve_shared_document_path
from .source_sync import ensure_runtime_fresh
from .outline_parser import OutlineMdParser


class ContextBuilder:
    """上下文构建器

    负责组装 Writer/Reviewer/Stylist agents 所需的完整上下文。

    Usage:
        builder = ContextBuilder(project_root=Path.cwd(), novel_id="my_novel")
        context = builder.build_generation_context(
            chapter_id="ch_005",
            window_size=5
        )
        prompt_context = context.to_prompt_context()
    """

    # Token 预算分配
    MAX_TOKENS = 24000  # 留 8k 给生成
    BUDGET_OUTLINE = 5000
    BUDGET_CHARACTERS = 3000
    BUDGET_FORESHADOWING = 2000
    BUDGET_STYLE = 8000
    BUDGET_WORLD = 3000
    BUDGET_RECENT = 3000

    def __init__(self, project_root: Path, novel_id: str, reference_style: str = ""):
        """初始化构建器

        Args:
            project_root: 项目根目录（包含 craft/, data/）
            novel_id: 当前小说 ID
            reference_style: 项目内提取风格源 ID（对应 data/novels/{id}/data/sources/{name}/style/）
        """
        self.project_root = project_root.resolve()
        self.novel_id = novel_id
        self.reference_style = reference_style

        # 数据路径（仅支持新布局）
        self.novel_dir = project_root / "data" / "novels" / novel_id
        self.src_dir = self.novel_dir / "src"
        self.data_dir = self.novel_dir / "data"
        self.ref_style_dir = (
            self.data_dir / "sources" / reference_style / "style" if reference_style else None
        )
        self.craft_dir = project_root / "craft"

        # 真相文件管理器
        self.truth_manager = TruthFilesManager(project_root, novel_id)
        self.chapter_memory = ChapterMemoryStore(project_root, novel_id)

        # 缓存
        self._outline_cache: Optional[Dict[str, Any]] = None
        self._hierarchy_cache: Optional[OutlineHierarchy] = None

    def build_generation_context(self, chapter_id: str, window_size: int = 5) -> GenerationContext:
        """构建生成上下文 - 主入口

        Args:
            chapter_id: 目标章节 ID
            window_size: 大纲窗口大小（前后 N 章）

        Returns:
            完整的 GenerationContext 对象
        """
        # 1. 加载大纲
        hierarchy = self._load_outline_hierarchy()

        # 2. 加载大纲窗口
        outline_window = self._get_outline_window(chapter_id, window_size, hierarchy)
        current_chapter = self._get_current_chapter(chapter_id, hierarchy)

        # 3. 加载出场角色
        active_characters = self._get_active_characters(chapter_id, hierarchy)

        # 4. 加载伏笔状态
        foreshadowing = self._get_foreshadowing_state(chapter_id)

        # 5. 合成风格
        style_profile = self._build_style_stack()

        # 6. 加载世界观
        world_rules = self._get_world_rules(chapter_id, hierarchy)

        # 7. 加载最近文本
        recent_text = self._get_recent_chapters(chapter_id, limit=2)

        # 8. 提取章节目标 + 戏剧位置
        chapter_goals: List[str] = []
        target_words = 6000
        emotion_arc = ""
        dramatic_context: Dict[str, str] = {}
        if current_chapter:
            chapter_goals = current_chapter.goals
            target_words = (
                current_chapter.word_count_target
                or current_chapter.estimated_words
                or 6000
            )
            emotion_arc = current_chapter.emotional_arc or ""

        # 从节/篇获取戏剧弧线上下文
        if hierarchy and hasattr(hierarchy, "get_dramatic_context"):
            dramatic_context = hierarchy.get_dramatic_context(chapter_id)

        # 9. 加载运行时状态文件
        truth = self.truth_manager.load_truth_files()
        chapter_summaries = self.chapter_memory.render_context(chapter_id, max_chars=4000)

        # 10. pending_hooks 现在从 foreshadowing state 获取
        # 伏笔状态已在前面加载到 foreshadowing 变量中
        pending_hooks_str = ""
        if foreshadowing and hasattr(foreshadowing, "pending"):
            pending_hooks_str = "\n".join(
                [
                    f"- [{n.get('id', '?')}] {n.get('content', '')[:50]}..."
                    for n in foreshadowing.pending[:10]
                ]
            )

        # 11. 构建 context
        context = GenerationContext(
            novel_id=self.novel_id,
            chapter_id=chapter_id,
            author_intent=self._load_story_control("author_intent.md", max_chars=3000),
            creative_focus=self._load_story_control("current_focus.md", max_chars=2400),
            outline_window=outline_window,
            current_chapter=current_chapter,
            active_characters=active_characters,
            foreshadowing=foreshadowing,
            style_profile=style_profile,
            world_rules=world_rules,
            recent_text=recent_text,
            chapter_goals=chapter_goals,
            target_words=target_words,
            emotion_arc=emotion_arc,
            dramatic_context=dramatic_context,
            current_state=truth.current_state,
            foreshadowing_summary=pending_hooks_str,
            ledger=truth.ledger,
            relationships=truth.relationships,
            chapter_summaries=chapter_summaries,
        )

        # 12. 动态压缩（如果超限）
        context = self._compress_if_needed(context)

        return context

    def _load_story_control(self, filename: str, *, max_chars: int) -> str:
        """加载人类维护的书级控制面，不读取运行态草稿。"""
        path = self.src_dir / "story" / filename
        if not path.exists():
            return ""
        try:
            text = path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""
        return text[:max_chars]

    def _load_outline_hierarchy(self) -> OutlineHierarchy:
        """加载大纲层级结构"""
        freshness = ensure_runtime_fresh(self.project_root, self.novel_id)
        if freshness.get("auto_synced"):
            self._hierarchy_cache = None

        if self._hierarchy_cache:
            return self._hierarchy_cache

        outline_src = self.src_dir / "outline.md"
        if outline_src.exists():
            text = self._load_text(outline_src)
            if text.strip():
                hierarchy = OutlineMdParser().parse(text, self.novel_id)
                self._hierarchy_cache = hierarchy
                return hierarchy

        hierarchy_path = self.data_dir / "hierarchy.yaml"
        if not hierarchy_path.exists():
            return OutlineHierarchy(novel_id=self.novel_id)

        data = self._load_yaml(hierarchy_path)
        hierarchy = self._parse_hierarchy_yaml(data)
        self._hierarchy_cache = hierarchy
        return hierarchy

    def _parse_hierarchy_yaml(self, data: Dict[str, Any]) -> OutlineHierarchy:
        """解析 hierarchy.yaml 为 OutlineHierarchy"""
        return deserialize_outline_hierarchy(data, self.novel_id)

    def _get_outline_window(
        self, chapter_id: str, window_size: int, hierarchy: OutlineHierarchy
    ) -> List[OutlineNode]:
        """获取大纲窗口（前后 N 章）"""
        return hierarchy.get_chapter_window(chapter_id, window_size)

    def _get_current_chapter(
        self, chapter_id: str, hierarchy: OutlineHierarchy
    ) -> Optional[OutlineNode]:
        """获取当前章节"""
        return hierarchy.get_node(chapter_id)

    def _get_active_characters(
        self, chapter_id: str, hierarchy: OutlineHierarchy
    ) -> List[CharacterProfile]:
        """获取出场角色

        1. 从章节大纲中提取 involved_characters
        2. 加载对应的 CharacterProfile（静态信息）
        3. 从真相文件合并动态状态（位置/状态/目标）
        """
        profiles: List[CharacterProfile] = []

        # 从章节获取涉及的角色
        chapter = hierarchy.get_node(chapter_id)
        if not chapter:
            return profiles

        character_ids = list(chapter.involved_characters)
        if not character_ids:
            section = hierarchy.get_parent_section(chapter_id)
            if section:
                agg: List[str] = []
                for ch_id in section.children_ids:
                    node = hierarchy.get_node(ch_id)
                    if node and node.involved_characters:
                        agg.extend(node.involved_characters)
                character_ids = list(dict.fromkeys(agg))

        profiles_dir = self.src_dir / "characters"
        if not character_ids:
            chapter_text = "\n".join(
                [
                    chapter.title,
                    chapter.summary,
                    chapter.content_focus,
                    *chapter.goals,
                    *chapter.beats,
                    *chapter.hooks,
                ]
            )
            for profile_path in sorted(profiles_dir.glob("*.md")):
                profile = self._parse_character_profile(
                    profile_path, profile_path.stem
                )
                if not profile:
                    continue
                identifiers = {
                    profile_path.stem,
                    profile.character_id,
                    profile.name,
                }
                if any(
                    identifier and identifier in chapter_text
                    for identifier in identifiers
                ):
                    character_ids.append(profile.name or profile.character_id)

        if not character_ids:
            return profiles

        # 加载角色档案（静态信息）
        cards_dir = self.data_dir / "characters" / "cards"

        for char_id in character_ids:
            # 尝试加载 profile (markdown)
            profile_path = resolve_shared_document_path(profiles_dir, char_id) or (
                profiles_dir / f"{char_id}.md"
            )
            if profile_path.exists():
                profile = self._parse_character_profile(profile_path, profile_path.stem)
                if profile:
                    profiles.append(profile)
                    continue

            # 尝试加载 card (yaml)
            card_path = cards_dir / f"{char_id}.yaml"
            if card_path.exists():
                card_data = self._load_yaml(card_path)
                profile = self._card_to_profile(card_data, char_id)
                if profile:
                    profiles.append(profile)

        # 从真相文件获取动态状态并合并
        if profiles:
            self._merge_dynamic_character_state(profiles)

        return profiles

    def _merge_dynamic_character_state(self, profiles: List[CharacterProfile]):
        """从真相文件合并角色的动态状态

        动态信息（当前位置、当前状态、当前目标）从真相文件读取，
        而不是从静态的角色档案读取。
        """
        # 加载真相文件
        truth_manager = self.truth_manager
        truth = truth_manager.load_truth_files()

        # 从 current_state.md 解析角色动态状态
        dynamic_states = self._parse_current_state_for_characters(truth.current_state, truth.relationships)

        # 合并到 profiles
        for profile in profiles:
            char_id = profile.character_id
            if char_id in dynamic_states:
                state = dynamic_states[char_id]
                profile.current_location = state.get("location", "")
                profile.current_status = state.get("status", "")
                # current_location 和 current_status 会用于 to_context_text()

    def _parse_current_state_for_characters(
        self, current_state: str, relationships: str
    ) -> Dict[str, Dict[str, str]]:
        """从真相文件解析角色的动态状态

        Returns:
            {char_id: {"location": "...", "status": "...", "goal": "..."}}
        """
        result: Dict[str, Dict[str, str]] = {}

        if not current_state:
            return result

        # 简单解析 current_state.md 中的角色状态
        # 格式示例：
        # | 主角位置 | 青河镇 |
        # | 主角状态 | 筑基初期 |

        # 提取角色状态表（简化版）
        for line in current_state.split("\n"):
            # 匹配 | 角色位置 | 值 | 或 | 角色状态 | 值 |
            match = re.match(r"\|\s*([^\s]+)\s*\|\s*([^\|]+)\s*\|", line)
            if match:
                key = match.group(1).strip()
                value = match.group(2).strip()

                # 判断是哪个角色的状态
                # 格式：主角位置、配角状态 等
                if "位置" in key or "location" in key.lower():
                    # 尝试推断角色名
                    char_name = key.replace("位置", "").replace("Location", "").strip()
                    if char_name not in result:
                        result[char_name] = {}
                    result[char_name]["location"] = value
                elif "状态" in key or "status" in key.lower():
                    char_name = key.replace("状态", "").replace("Status", "").strip()
                    if char_name not in result:
                        result[char_name] = {}
                    result[char_name]["status"] = value

        # 如果没解析到，尝试从 relationships 解析
        if not result and relationships:
            # 从 relationships 解析关系和位置
            result = self._parse_character_matrix(relationships)

        return result

    def _parse_character_matrix(self, character_matrix: str) -> Dict[str, Dict[str, str]]:
        """从 character_matrix.md 解析角色状态

        格式示例：
        ### 主角状态
        | 字段 | 值 |
        | 位置 | 青河镇 |
        | 状态 | 筑基初期 |
        """
        result: Dict[str, Dict[str, str]] = {}
        current_char = None

        for line in character_matrix.split("\n"):
            # 匹配 ### 角色名 格式
            heading_match = re.match(r"^#{1,4}\s*([^\s#]+)\s*(?:状态)?", line)
            if heading_match:
                current_char = heading_match.group(1).strip()
                if current_char not in result:
                    result[current_char] = {}

            # 匹配 | 字段 | 值 | 格式
            if current_char:
                match = re.match(r"\|\s*([^\s|]+)\s*\|\s*([^\|]+)\s*\|", line)
                if match:
                    field_name = match.group(1).strip()
                    field_value = match.group(2).strip()
                    if field_name in ["位置", "Location", "状态", "Status"]:
                        result[current_char][field_name] = field_value

        return result

    def _parse_character_profile(self, path: Path, char_id: str) -> Optional[CharacterProfile]:
        """解析 markdown 格式的角色档案"""
        if not path.exists():
            return None

        text = self._load_text(path)
        if not text:
            return None

        meta, body = parse_toml_front_matter(text)
        name = str(meta.get("name", "")).strip() or self._extract_md_heading(body) or char_id

        tier_raw = str(meta.get("tier", "")).strip()
        tier_values = {t.value: t for t in CharacterTier}
        tier = tier_values.get(tier_raw, CharacterTier.MINOR)

        backstory = self._extract_md_section(body, "背景") or self._extract_md_section(body, "background")
        appearance = self._extract_md_section(body, "外貌") or self._extract_md_section(body, "appearance")
        personality = self._extract_md_list(body, "性格") or self._extract_md_list(body, "personality")

        return CharacterProfile(
            character_id=str(meta.get("id", "")).strip() or char_id,
            name=name,
            tier=tier,
            summary=str(meta.get("summary", "")).strip(),
            backstory=backstory,
            appearance=appearance,
            personality=personality,
            faction=str(meta.get("faction", "")).strip(),
            tags=list(meta.get("tags", [])) if isinstance(meta.get("tags"), list) else [],
            detail_refs=list(meta.get("detail_refs", []))
            if isinstance(meta.get("detail_refs"), list)
            else [],
            related=list(meta.get("related", [])) if isinstance(meta.get("related"), list) else [],
        )

    def _card_to_profile(
        self, card_data: Dict[str, Any], char_id: str
    ) -> Optional[CharacterProfile]:
        """将卡片数据转换为 Profile"""
        if not card_data:
            return None

        static = card_data.get("static", card_data)

        return CharacterProfile(
            character_id=char_id,
            name=static.get("name", char_id),
            tier=CharacterTier(static.get("tier"))
            if static.get("tier") in [t.value for t in CharacterTier]
            else CharacterTier.MINOR,
            summary=static.get("brief", ""),
            appearance=static.get("appearance", ""),
            backstory=static.get("background", ""),
            personality=static.get("personality", []),
            faction=static.get("faction", ""),
            related=static.get("relationships", []),
        )

    def _get_foreshadowing_state(self, chapter_id: str) -> ForeshadowingState:
        """获取伏笔状态

        从 foreshadowing/dag.yaml 加载：
        - pending: 待回收（需要在当前或后续章节回收）
        - planted: 已埋下（当前章节之前埋下）
        - resolved: 已回收
        """
        state = ForeshadowingState()

        # 尝试从多个位置加载伏笔数据
        # 1. 从 foreshadowing/dag.yaml
        dag_path = self.data_dir / "foreshadowing" / "dag.yaml"
        if dag_path.exists():
            dag_data = self._load_yaml(dag_path)
            state = self._parse_foreshadowing_dag(dag_data, chapter_id)
            if state.pending or state.planted:
                return state

        # 2. 从大纲的 key_foreshadowing 字段
        hierarchy_path = self.data_dir / "hierarchy.yaml"
        if hierarchy_path.exists():
            outline_data = self._load_yaml(hierarchy_path)
            fore_data = outline_data.get("key_foreshadowing", [])
            if fore_data:
                state = self._parse_outline_foreshadowing(fore_data, chapter_id)

        return state

    def _parse_foreshadowing_dag(
        self, dag_data: Dict[str, Any], chapter_id: str
    ) -> ForeshadowingState:
        """解析伏笔 DAG 数据"""
        state = ForeshadowingState()

        nodes_raw = dag_data.get("nodes", [])
        if isinstance(nodes_raw, dict):
            nodes_list = list(nodes_raw.values())
        else:
            nodes_list = nodes_raw

        # 解析章节序号
        current_idx = self._parse_chapter_index(chapter_id)

        for node in nodes_list:
            if not isinstance(node, dict):
                continue
            status = node.get("status", "埋伏")
            planted_in = node.get("created_at", node.get("planted_in", ""))
            target_chapter = node.get("target_chapter", "")

            planted_idx = self._parse_chapter_index(planted_in)
            target_idx = self._parse_chapter_index(target_chapter)

            if status == "已收" or status == "resolved":
                state.resolved.append(node)
            elif status == "待收" or status == "pending":
                state.pending.append(node)
            elif planted_idx > 0 and planted_idx < current_idx:
                state.planted.append(node)
            elif target_idx >= current_idx:
                state.pending.append(node)

        return state

    def _parse_outline_foreshadowing(
        self, fore_data: List[Dict[str, Any]], chapter_id: str
    ) -> ForeshadowingState:
        """从大纲中解析伏笔数据"""
        state = ForeshadowingState()

        current_idx = self._parse_chapter_index(chapter_id)

        for item in fore_data:
            planted_in = item.get("planted_in", "")
            recovered_in = item.get("recovered_in", "")

            planted_idx = self._parse_chapter_index(planted_in)
            recovered_idx = self._parse_chapter_index(recovered_in)

            fore_item = {
                "id": item.get("id", ""),
                "description": item.get("description", ""),
                "planted_in": planted_in,
                "recovered_in": recovered_in,
            }

            if recovered_idx > 0 and recovered_idx < current_idx:
                state.resolved.append(fore_item)
            elif planted_idx > 0 and planted_idx < current_idx:
                if recovered_idx == 0 or recovered_idx >= current_idx:
                    state.planted.append(fore_item)
                    if recovered_idx > 0:
                        state.pending.append(fore_item)

        return state

    def _parse_chapter_index(self, chapter_id: str) -> int:
        """解析章节 ID 中的序号"""
        if not chapter_id:
            return 0
        match = re.search(r"(\d+)", chapter_id)
        return int(match.group(1)) if match else 0

    def _build_style_stack(self) -> StyleProfile:
        """合成三层风格架构

        Layer 1: craft/ - 通用写作技法
        Layer 2: data/novels/{id}/data/sources/{name}/style/ - 用户提取风格源
        Layer 3: data/novels/{id}/ - 作品设定（角色/世界观/自身风格）
        """
        profile = StyleProfile(novel_id=self.novel_id)

        # 1. 加载通用技法 (craft/)
        craft_rules = self._load_craft_rules()
        profile.craft_rules = craft_rules

        # 2. 加载项目内提取风格源
        voice, language, rhythm = self._load_reference_style()
        if voice:
            profile.voice = voice
        if language:
            profile.language = language
        if rhythm:
            profile.rhythm = rhythm

        # 3. 加载作品设定 (data/novels/{id}/)
        work_setting = self._load_work_setting()
        profile.work_setting = work_setting

        # 4. 加载禁用词
        banned = self._load_banned_phrases()
        profile.banned_phrases = banned

        return profile

    def _load_craft_rules(self) -> List[str]:
        """加载通用写作技法"""
        rules: List[str] = []

        if not self.craft_dir.exists():
            return rules

        # 加载 craft/ 下的技法文件
        craft_files = [
            "dialogue_craft.md",
            "scene_craft.md",
            "rhythm_craft.md",
        ]

        for filename in craft_files:
            path = self.craft_dir / filename
            if path.exists():
                text = self._load_text(path)
                # 提取二级标题作为规则
                headings = re.findall(r"^##\s+(.+)$", text, re.MULTILINE)
                rules.extend(headings[:5])  # 每个文件最多5条

        return rules[:20]  # 总共最多20条

    def _load_reference_style(
        self,
    ) -> tuple[Optional[VoicePattern], Optional[LanguageStyle], Optional[RhythmStyle]]:
        """加载项目内提取风格源（从 data/novels/{id}/data/sources/{name}/style/ 读取）"""
        voice = None
        language = None
        rhythm = None

        if not self.ref_style_dir or not self.ref_style_dir.exists():
            return voice, language, rhythm

        # 加载 voice
        voice_path = self.ref_style_dir / "voice.md"
        if voice_path.exists():
            text = self._load_text(voice_path)
            voice = VoicePattern(
                narrator_voice=self._extract_md_section(text, "叙述者")[:500],
                pov_style=self._extract_md_section(text, "POV")[:200],
            )

        # 加载 language
        language_path = self.ref_style_dir / "language.md"
        if language_path.exists():
            text = self._load_text(language_path)
            language = LanguageStyle(
                sentence_patterns=self._extract_md_list(text, "句式"),
                vocabulary_preferences=self._extract_md_list(text, "词汇"),
                metaphor_style=self._extract_md_section(text, "比喻")[:200],
            )

        # 加载 rhythm
        rhythm_path = self.ref_style_dir / "rhythm.md"
        if rhythm_path.exists():
            text = self._load_text(rhythm_path)
            rhythm = RhythmStyle(
                scene_pacing=self._extract_md_section(text, "节奏")[:200],
                tension_patterns=self._extract_md_list(text, "张力"),
            )

        return voice, language, rhythm

    def _load_work_setting(self) -> Dict[str, str]:
        """加载作品设定（从 data/novels/{id}/ 读取）"""
        setting: Dict[str, str] = {}

        if not self.data_dir.exists():
            return setting

        world_path = self.src_dir / "world" / "rules.md"
        if world_path.exists():
            setting["worldbuilding"] = render_indexed_document(
                self._load_text(world_path),
                default_meta={
                    "name": "世界规则",
                    "summary": "作品的底层规则、限制与未知项。",
                    "detail_refs": ["力量体系", "社会规则", "物理法则", "禁忌与未知"],
                },
                max_chars=1000,
            )

        # 加载术语表
        term_path = self.src_dir / "world" / "terminology.md"
        if term_path.exists():
            setting["terminology"] = render_indexed_document(
                self._load_text(term_path),
                default_meta={
                    "name": "术语表",
                    "summary": "作品内高频术语与概念定义。",
                    "detail_refs": ["术语表"],
                },
                max_chars=500,
            )

        profiles_dir = self.src_dir / "characters"
        if profiles_dir.exists():
            chars_text = []
            for p in sorted(profiles_dir.glob("*.md"))[:5]:
                chars_text.append(
                    render_indexed_document(
                        self._load_text(p),
                        default_meta={"name": p.stem},
                        max_chars=300,
                    )
                )
            if chars_text:
                setting["characters"] = "\n---\n".join(chars_text)

        return setting

    def _load_banned_phrases(self) -> List[str]:
        """加载禁用词列表"""
        banned: List[str] = []

        # 从 humanization.yaml 加载
        human_path = self.craft_dir / "humanization.yaml"
        if human_path.exists():
            data = self._load_yaml(human_path)
            # 提取禁用词
            phrases = data.get("banned_phrases", [])
            banned.extend([p.get("phrase", p) if isinstance(p, dict) else p for p in phrases[:30]])

        # 从作品合成风格加载
        composed_path = self.data_dir / "style" / "composed.md"
        if composed_path.exists():
            text = self._load_text(composed_path)
            # 提取禁用段落的条目
            items = self._extract_md_list(text, "禁用")
            banned.extend(items[:20])

        return list(set(banned))[:50]  # 去重，最多50个

    def _get_world_rules(self, chapter_id: str, hierarchy: OutlineHierarchy) -> WorldRules:
        """获取相关世界观规则

        加载顺序：
        1. world/rules.md — 世界底层规则（力量体系、社会规则、物理法则）
        2. world/terminology.md — 术语表
        3. world/entities/*.md — 实体（通过 world_query.py 解析）
        4. 章节大纲的 involved_settings
        """
        rules = WorldRules()

        world_dir = self.src_dir / "world"
        if not world_dir.exists():
            return rules

        # 1. 从 world/rules.md 加载世界规则
        rules_path = world_dir / "rules.md"
        if rules_path.exists():
            text = self._load_text(rules_path)
            # 提取 ## 标题下的列表项作为约束
            headings = re.findall(r"^##\s+(.+)$", text, re.MULTILINE)
            # 提取每个 section 下的关键规则（以 - 开头的行）
            rule_items = re.findall(r"^[-*]\s+(.+)$", text, re.MULTILINE)
            rules.constraints.extend(rule_items[:20])

        # 2. 从 world/entities/*.md 加载实体
        entities_dir = world_dir / "entities"
        if entities_dir.exists():
            try:
                from tools.world_query import list_entities, get_relations_graph

                entity_list = list_entities(self.novel_id, project_root=self.project_root)
                rules.entities = entity_list
                graph = get_relations_graph(self.novel_id, project_root=self.project_root)
                rules.relations = graph.get("relations", [])
            except ImportError:
                pass

        # 3. 从章节大纲的 involved_settings 补充
        chapter = hierarchy.get_node(chapter_id)
        if chapter and chapter.involved_settings:
            rules.constraints.extend(chapter.involved_settings)

        return rules

    def _get_recent_chapters(self, chapter_id: str, limit: int = 2) -> str:
        """获取最近章节文本（用于连贯性）"""
        texts: List[str] = []

        manuscript_dir = self.data_dir / "manuscript"
        if not manuscript_dir.exists():
            return ""

        # 解析当前章节序号
        current_idx = self._parse_chapter_index(chapter_id)
        if current_idx == 0:
            return ""

        # 查找前面的章节
        for i in range(current_idx - 1, max(0, current_idx - limit - 1), -1):
            # 尝试多种文件名格式
            patterns = [
                f"ch_{i:03d}.md",
                f"ch_{i:03d}_*.md",
                f"chapter_{i:03d}.md",
                f"{i:03d}.md",
            ]
            for pattern in patterns:
                matches = sorted(manuscript_dir.rglob(pattern))
                if matches:
                    text = self._load_text(matches[0])
                    if text:
                        # 只取最后 500 字符
                        texts.insert(0, text[-500:] if len(text) > 500 else text)
                    break

        return "\n\n...\n\n".join(texts)

    def _compress_if_needed(self, context: GenerationContext) -> GenerationContext:
        """动态压缩上下文

        如果 token 超限，按优先级压缩：
        1. 截断 recent_text
        2. 压缩 style_profile
        3. 减少角色历史
        """
        estimated_tokens = context.estimate_tokens()

        if estimated_tokens <= self.MAX_TOKENS:
            return context

        # 1. 截断 recent_text
        if len(context.recent_text) > 300:
            context.recent_text = context.recent_text[-300:]
            estimated_tokens = context.estimate_tokens()
            if estimated_tokens <= self.MAX_TOKENS:
                return context

        # 2. 减少大纲窗口
        if len(context.outline_window) > 3:
            context.outline_window = context.outline_window[-3:]
            estimated_tokens = context.estimate_tokens()
            if estimated_tokens <= self.MAX_TOKENS:
                return context

        # 3. 减少角色数量
        if len(context.active_characters) > 3:
            context.active_characters = context.active_characters[:3]

        return context

    def _estimate_tokens(self, text: str) -> int:
        """估算文本 token 数

        中文 token 比例约 1 字 ≈ 1.5~2 token（偏保守估算）。
        英文/数字约 1 token ≈ 4 字符。
        混合文本维持偏保守估算以避免超限。
        """
        if not text:
            return 0
        # 统计中文字符和非中文字符
        chinese_chars = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        other_chars = len(text) - chinese_chars
        # 中文: ~1.5 token/字; 英文: ~0.25 token/字符
        return int(chinese_chars * 1.5 + other_chars * 0.25)

    def _load_yaml(self, path: Path) -> Dict[str, Any]:
        """安全加载 YAML 文件"""
        if not path.exists():
            return {}
        try:
            with path.open("r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning("加载 YAML 失败 %s: %s", path, e)
            return {}

    def _load_text(self, path: Path) -> str:
        """加载文本文件"""
        if not path.exists():
            return ""
        try:
            return path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("加载文本失败 %s: %s", path, e)
            return ""

    def _extract_md_heading(self, text: str) -> str:
        """提取 markdown 一级标题"""
        match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        return match.group(1).strip() if match else ""

    def _extract_md_section(self, text: str, section_name: str) -> str:
        """提取 markdown 指定章节内容"""
        pattern = rf"^##\s+[^\n]*{section_name}[^\n]*\n(.*?)(?=\n##|\Z)"
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL | re.MULTILINE)
        return match.group(1).strip() if match else ""

    def _extract_md_list(self, text: str, section_name: str) -> List[str]:
        """提取 markdown 指定章节的列表项"""
        section = self._extract_md_section(text, section_name)
        if not section:
            return []
        items = re.findall(r"^[-*]\s+(.+)$", section, re.MULTILINE)
        return [item.strip() for item in items]

    def _get_pov_character(self, chapter: Optional[OutlineNode]) -> Optional[str]:
        """从章节大纲中提取 POV 角色"""
        if not chapter:
            return None

        # 尝试从 involved_characters 的第一个角色获取
        if chapter.involved_characters:
            return chapter.involved_characters[0]

        # 尝试从 summary 中提取
        if chapter.summary:
            # 简单匹配 "视角：XXX" 或 "POV：XXX"
            match = re.search(r"(?:视角|POV)[：:]\s*(.+?)(?:\n|$)", chapter.summary)
            if match:
                return match.group(1).strip()

        return None
