"""建筑师 Agent

AI 辅助创建大纲、世界观、角色设定。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .outline_contract import OUTLINE_JSON_FIELDS
from .writing_targets import normalize_writing_targets

logger = logging.getLogger(__name__)


@dataclass
class FoundationResult:
    """基础设定生成结果"""

    story_bible: str
    volume_outline: str
    book_rules: str
    current_state: str
    foreshadowing_seed: str
    warnings: list[str] = field(default_factory=list)

    @property
    def pending_hooks(self) -> str:
        """兼容旧字段名。"""
        return self.foreshadowing_seed


@dataclass
class ChapterOutline:
    """章节大纲"""

    number: int
    title: str
    summary: str
    dramatic_position: str  # 起/承/转/合/过渡
    content_focus: str
    goals: list[str] = field(default_factory=list)
    estimated_words: int = 0
    involved_characters: list[str] = field(default_factory=list)
    involved_settings: list[str] = field(default_factory=list)
    emotional_arc: str = ""
    beats: list[str] = field(default_factory=list)
    hooks: list[str] = field(default_factory=list)


class ArchitectAgent:
    """建筑师 Agent

    AI 辅助创建：
    - 世界观设定
    - 大纲规划
    - 写作规则
    - 初始状态

    用法:
        architect = ArchitectAgent(ctx)
        result = await architect.generate_foundation(
            title="我的修仙小说",
            genre="xianxia",
            brief="一个普通少年的修仙之路"
        )
    """

    GENRE_GUIDES = {
        "unspecified": (
            "题材未指定：必须以作者简述和现有已确认资产为准，"
            "不得擅自套用仙侠、都市等类型模板"
        ),
        "xuanhuan": "玄幻：东方仙侠世界，修炼境界（金丹、元婴等），门派纷争，奇遇流",
        "xianxia": "仙侠：修真文明，飞剑法宝，炼丹炼器，人与天地争斗",
        "urban": "都市：现代都市背景，异能/风水/相术等都市传说",
        "litrpg": "游戏异界：游戏系统降临，等级副本，技能装备",
        "sci-fi": "科幻：星际文明，未来科技，赛博朋克",
        "horror": "恐怖：悬疑惊悚，灵异事件",
        "system-apocalypse": "系统末日：末日降临，系统觉醒，生存挣扎",
        "isekai": "异世界：转生异界，种田/冒险/魔法",
        "cultivation": "修真：同仙侠但更注重个人修炼",
        "dungeon-core": "地下城核心：成为地下城意识体",
        "tower-climber": "塔爬：攀登高塔，每层不同挑战",
        "progression": "进阶流：主角实力稳步提升",
        "romantasy": "浪漫幻想：奇幻背景的浪漫故事",
        "cozy": "温馨流：轻松日常，节奏舒缓",
    }

    def __init__(self, agent_ctx: Any):
        """初始化建筑师

        Args:
            agent_ctx: Agent 上下文
        """
        self.ctx = agent_ctx
        self.log = logger.getChild("architect")

    def generate_foundation(
        self,
        title: str,
        genre: str = "xuanhuan",
        brief: str = "",
        platform: str = "番茄",
        *,
        include_foreshadowing: bool = True,
    ) -> FoundationResult:
        """生成基础设定

        Args:
            title: 书名
            genre: 题材
            brief: 创作简述（作者自己的想法）
            platform: 目标平台

        Returns:
            FoundationResult 包含所有设定文件
        """
        self.log.info(f"Generating foundation for '{title}' ({genre})")

        # 获取题材指南
        genre_guide = self.GENRE_GUIDES.get(genre, self.GENRE_GUIDES["xuanhuan"])

        # 生成世界观
        story_bible = self._generate_story_bible(title, genre, genre_guide, brief)

        # 生成卷纲
        volume_outline = self._generate_volume_outline(title, genre, story_bible, brief)

        # 生成写作规则
        book_rules = self._generate_book_rules(title, genre, brief)

        # 生成初始状态
        current_state = self._generate_current_state(title, genre, story_bible, brief)

        warnings: list[str] = []
        foreshadowing_seed = ""
        if include_foreshadowing:
            try:
                foreshadowing_seed = self._generate_foreshadowing_seed(
                    title, volume_outline
                )
            except Exception as exc:  # noqa: BLE001 - auxiliary draft degrades safely
                self.log.warning("Foreshadowing draft skipped: %s", exc)
                warnings.append("foreshadowing_generation_failed")

        return FoundationResult(
            story_bible=story_bible,
            volume_outline=volume_outline,
            book_rules=book_rules,
            current_state=current_state,
            foreshadowing_seed=foreshadowing_seed,
            warnings=warnings,
        )

    async def generate_outline(
        self,
        title: str,
        genre: str,
        story_bible: str,
        target_chapters: int = 100,
    ) -> list[ChapterOutline]:
        """生成章节大纲

        Args:
            title: 书名
            genre: 题材
            story_bible: 世界观设定
            target_chapters: 目标章节数

        Returns:
            章节大纲列表
        """
        from tools.llm import Message

        targets = self._writing_targets()

        system_prompt = (
            "你是一个专业的小说大纲师。根据世界观设定，设计章节大纲。\n\n"
            + OUTLINE_JSON_FIELDS
            + f"""

输出 JSON 格式：
```json
[
  {{
    "number": 1,
    "title": "章节标题",
    "summary": "章节内容概要（约{targets['outline_chapter_words']}字）",
    "dramatic_position": "起/承/转/合/过渡",
    "content_focus": "本章核心内容",
    "goals": ["目标1", "目标2"],
    "estimated_words": {targets['chapter_words']},
    "involved_characters": ["规范角色名"],
    "involved_settings": ["规范设定名"],
    "emotional_arc": "戒备 -> 动摇 -> 决意",
    "beats": ["场景切入", "冲突升级", "关键选择", "章末钩子"],
    "hooks": ["下一章承接的问题"]
  }}
]
```

每5章为一个"节"，节内有起承转合。每章正文目标为 {targets['chapter_words']} 字，
每个章纲说明约 {targets['outline_chapter_words']} 字。确保剧情有起伏。
只返回 JSON。"""
        )

        user_prompt = f"""书名：{title}
题材：{genre}
目标章节数：{target_chapters}

世界观设定：
{story_bible[:2000]}

请生成{target_chapters}章的大纲。"""

        try:
            content = self._chat_required(
                messages=[
                    Message("system", system_prompt),
                    Message("user", user_prompt),
                ],
                temperature=0.5,
                max_tokens=8192,
                label="chapter outline",
            )

            return self._parse_chapter_outline(content, target_chapters)
        except Exception as e:
            self.log.error(f"Outline generation failed: {e}")
            return []

    async def generate_character(
        self,
        name: str,
        role: str,
        genre: str,
        story_bible: str = "",
    ) -> str:
        """生成角色设定

        Args:
            name: 角色名
            role: 角色定位（主角/配角/反派等）
            genre: 题材
            story_bible: 世界观（可选）

        Returns:
            角色设定 Markdown
        """
        from tools.llm import Message

        system_prompt = """你是 OpenWrite 的专业小说角色设计师。
根据给定信息，设计可直接进入角色资产库的完整角色正文。

只输出 Markdown 正文，不要代码围栏或 TOML front matter。必须使用以下结构：
# 角色名
## 基本信息
## 背景
## 外貌
## 性格
## 与主角关系
## 说话风格
## 当前戏剧用途
## 特殊能力

每个章节都要填写可执行的具体内容；未知项明确写“无”或“待作者确认”，不要省略标题。
保持角色真实立体，有优点也有缺点，并与已提供的世界观一致。"""

        user_prompt = f"""角色名：{name}
角色定位：{role}
题材：{genre}

世界观设定（如果有）：
{story_bible[:1000]}

请设计这个角色的详细设定。"""

        try:
            content = self._chat_required(
                messages=[
                    Message("system", system_prompt),
                    Message("user", user_prompt),
                ],
                temperature=0.7,
                max_tokens=4096,
                label="character",
            )

            if content.lstrip().startswith("# "):
                return content
            return f"# {name}\n\n{content}"
        except Exception as e:
            self.log.error(f"Character generation failed: {e}")
            return f"# {name}\n\n角色生成失败：{e}"

    def _generate_story_bible(self, title: str, genre: str, genre_guide: str, brief: str) -> str:
        """生成世界观设定"""
        from tools.llm import Message

        system_prompt = """你是一个专业的网络小说世界观设计师。

根据以下信息，生成完整的**世界观设定文档**，包括：

1. **世界背景**：世界是什么样的（东方/西方/现代/异世界等）
2. **核心设定**：力量体系、社会结构、地理环境等
3. **主要势力**：门派/组织/国家等
4. **金手指/主角设定**：主角的特殊能力或机遇
5. **配角设定**：2-3个重要配角
6. **核心冲突**：故事的主要矛盾

格式要求：
- 使用 Markdown
- 层次分明，用 ## 标注章节
- 内容详实但不冗长
- 方便后续写作参考"""

        user_prompt = f"""书名：{title}
题材：{genre}
题材特点：{genre_guide}

作者的想法（如果有）：
{brief}

请生成世界观设定。"""

        content = self._chat_required(
            messages=[
                Message("system", system_prompt),
                Message("user", user_prompt),
            ],
            temperature=0.7,
            max_tokens=8192,
            label="story bible",
        )

        return content

    def _generate_volume_outline(self, title: str, genre: str, story_bible: str, brief: str) -> str:
        """生成卷纲"""
        from tools.llm import Message

        targets = self._writing_targets()

        system_prompt = f"""你是一个专业的小说大纲师。

根据世界观设定，生成**卷纲（总大纲）**。

格式要求：
- 分为若干"篇"（Arc），每篇 15-30 章
- 每篇在标题后用普通散文概括核心冲突、转折点和结果
- 每篇内分为若干"节"（Section），每节 5 章左右
- 每节用普通散文概括主要事件、推进过程和结果
- 每卷说明约 {targets['outline_volume_words']} 字，每幕说明约 {targets['outline_act_words']} 字
- 每节说明约 {targets['outline_section_words']} 字
- 每个章纲说明约 {targets['outline_chapter_words']} 字
- 每章必须标注 `> 预估字数: {targets['chapter_words']}`

示例结构：
```
## 第一篇：入门（1-20章）

主角为进入宗门参加拜师考验，在受挫后识破考题的真正目的，最终通过考验并正式入门。

### 第一节（1-5章）

主角通过拜师考验进入宗门，在接连受挫后找到破局办法，并决定留下继续修行。
```

用 Markdown 输出。"""

        user_prompt = f"""书名：{title}
题材：{genre}

世界观设定：
{story_bible[:2000]}

作者想法：
{brief}

请生成卷纲。"""

        content = self._chat_required(
            messages=[
                Message("system", system_prompt),
                Message("user", user_prompt),
            ],
            temperature=0.5,
            max_tokens=8192,
            label="volume outline",
        )

        return content

    def _writing_targets(self) -> dict[str, int]:
        project_root = str(getattr(self.ctx, "project_root", "") or "").strip()
        if not project_root:
            return normalize_writing_targets({})
        config_path = Path(project_root).expanduser() / "novel_config.yaml"
        try:
            config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            config = {}
        stored = config.get("writing_targets") if isinstance(config, dict) else {}
        return normalize_writing_targets(stored)

    def _generate_book_rules(self, title: str, genre: str, brief: str) -> str:
        """生成写作规则"""
        from tools.llm import Message

        system_prompt = """你是一个专业的小说编辑。

根据以下信息，生成**写作规则文档**，明确：
1. 主角性格锁定（不能崩）
2. 行为约束（什么不能做）
3. 题材禁忌（什么不能写）
4. 文风要求（什么风格）

格式简洁，用列表即可。"""

        user_prompt = f"""书名：{title}
题材：{genre}

作者想法：
{brief}

请生成写作规则。"""

        content = self._chat_required(
            messages=[
                Message("system", system_prompt),
                Message("user", user_prompt),
            ],
            temperature=0.3,
            max_tokens=2048,
            label="book rules",
        )

        return f"# {title} 写作规则\n\n{content}"

    def _generate_current_state(self, title: str, genre: str, story_bible: str, brief: str) -> str:
        """生成初始状态"""
        from tools.llm import Message

        system_prompt = """你是一个小说设定专家。

根据世界观设定，生成**初始状态卡**（第0章状态）。

格式用表格：
| 字段 | 内容 |
|------|------|
| 当前章节 | 0 |
| 当前位置 | xxx |
| 主角状态 | xxx |
| 当前目标 | xxx |
| 当前限制 | xxx |
| 当前敌我 | xxx |
| 当前冲突 | xxx |

简洁填写即可。"""

        user_prompt = f"""世界观设定：
{story_bible[:1500]}

请生成初始状态卡。"""

        content = self._chat_required(
            messages=[
                Message("system", system_prompt),
                Message("user", user_prompt),
            ],
            temperature=0.3,
            max_tokens=2048,
            label="current state",
        )

        return f"# 当前状态（第0章）\n\n{content}"

    def _generate_foreshadowing_seed(self, title: str, volume_outline: str) -> str:
        """生成伏笔列表"""
        from tools.llm import Message

        system_prompt = """你是一个小说伏笔专家。

根据大纲，识别并列出**主要伏笔**。

只输出可被 OpenWrite 伏笔 DAG 直接解析的 YAML，不要 Markdown 表格、标题或代码围栏：
nodes:
  f001:
    id: f001
    content: 伏笔的客观内容
    weight: 8
    layer: 主线
    status: 埋伏
    created_at: ch_003
    target_arc: arc_001
    target_section: sec_003
    target_chapter: ch_015
    tags: [悬念]
edges: []
status:
  f001: 埋伏

识别 5-10 个核心伏笔即可。每个 nodes 键必须等于节点 id；weight 为 1-10；
status 使用“埋伏/待收/已收/废弃”；章节 ID 使用 ch_001 格式。没有边时输出空数组。
伏笔应该在合适时机回收，不要埋太多。"""

        user_prompt = f"""大纲：
{volume_outline[:2000]}

请列出主要伏笔。"""

        content = self._chat_required(
            messages=[
                Message("system", system_prompt),
                Message("user", user_prompt),
            ],
            temperature=0.3,
            max_tokens=2048,
            label="foreshadowing",
        )

        return content

    def _chat_required(
        self,
        *,
        messages: list[Any],
        temperature: float,
        max_tokens: int,
        label: str,
    ) -> str:
        """Retry one transient empty/error response before failing the draft."""

        last_error: Exception | None = None
        for attempt in range(2):
            try:
                response = self.ctx.client.chat(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                content = str(getattr(response, "content", "") or "").strip()
                if content:
                    return content
                last_error = RuntimeError(f"{label} model response was empty")
            except Exception as exc:  # noqa: BLE001 - retry provider transients once
                last_error = exc
            self.log.warning(
                "%s generation attempt %s returned no usable content",
                label,
                attempt + 1,
            )
        raise RuntimeError(f"{label} generation failed after retry") from last_error

    def _generate_pending_hooks(self, title: str, volume_outline: str) -> str:
        """兼容旧方法名。"""
        return self._generate_foreshadowing_seed(title, volume_outline)

    def _parse_chapter_outline(self, content: str, target_count: int) -> list[ChapterOutline]:
        """解析章节大纲"""
        import json
        import re

        try:
            json_match = re.search(r"\[.*\]", content, re.DOTALL)
            if json_match:
                items = json.loads(json_match.group(0))
                outlines = []
                for item in items:
                    outlines.append(
                        ChapterOutline(
                            number=item.get("number", 0),
                            title=item.get("title", ""),
                            summary=item.get("summary", ""),
                            dramatic_position=item.get("dramatic_position", "起"),
                            content_focus=item.get("content_focus", ""),
                            goals=item.get("goals", []),
                            estimated_words=item.get("estimated_words", 0),
                            involved_characters=item.get("involved_characters", []),
                            involved_settings=item.get("involved_settings", []),
                            emotional_arc=item.get("emotional_arc", ""),
                            beats=item.get("beats", []),
                            hooks=item.get("hooks", []),
                        )
                    )
                return outlines
        except json.JSONDecodeError:
            self.log.warning("Failed to parse chapter outline JSON")

        return []
