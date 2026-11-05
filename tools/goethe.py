"""Goethe 长会话规划 Shell。"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .agent.confirmation import (
    guard_confirmable_executors,
    is_explicit_mutation_confirmation,
    remember_document_edit_previews,
    remember_relation_previews,
)
from .agent.goethe_session_state import (
    GoetheSessionState,
    GoetheSessionStateStore,
    GoetheSessionTurn,
)
from .agent.manuscript_safety import manual_chapter_delete_guidance
from .agent.react import OPENWRITE_TOOLS, ReActAgent, ToolDefinition
from .agent.toolkits import GOETHE_DIRECT_TOOLKIT
from .outline_contract import OUTLINE_MARKDOWN_CONTRACT
from .runtime_skills import (
    RuleCompiler,
    RuntimeSkillResolver,
    extract_explicit_skill_mentions,
    render_runtime_context,
)
from .shared_documents import CHARACTER_MARKDOWN_CONTRACT

logger = logging.getLogger(__name__)

EXIT_COMMANDS = {"退出", "quit", "exit", "q"}

GOETHE_TOOL_DESCRIPTIONS: dict[str, str] = {
    "get_status": "读取当前书籍状态与运行信息。",
    "get_context": "读取章节上下文与近期材料。",
    "query_library": "按作品核心、角色和设定浏览资料目录。",
    "list_chapters": "列出已存在章节。",
    "get_truth_files": "读取运行态真相文件。",
    "query_world": "查询设定实体；保留该名称用于兼容现有工作流。",
    "get_world_relations": "查询世界关系与关联。",
    "edit_world_relation": "预览或确认一个带 revision 校验的增量关系修改。",
    "get_outline_structure": "读取卷、幕、节、章树和下一章建议，不修改文件。",
    "edit_outline_structure": (
        "按 revision 增量修改卷、幕、节、章；confirm=false 预览 diff，"
        "用户明确确认后才以 confirm=true 写入；新增或补全内容必须遵守系统提示中的大纲写入契约。"
    ),
    "summarize_ideation": "汇总当前灵感与讨论，形成共识摘要。",
    "confirm_ideation_summary": (
        "持久化用户对当前想法汇总的明确确认；可继续执行同句中的大纲生成请求。"
    ),
    "generate_foundation_draft": (
        "生成背景、基础设定、卷纲、初始状态与伏笔 DAG 草案；只写 planning。"
    ),
    "confirm_foundation": (
        "仅在用户明确确认后，将基础设定草案晋升到 canonical，并初始化 truth 与伏笔 DAG。"
    ),
    "generate_character_draft": (
        "生成符合 OpenWrite 角色文档结构的完整草案；只写 planning。"
    ),
    "confirm_character_draft": (
        "仅在用户明确确认后，校验并晋升指定角色草案到 src/characters。"
    ),
    "generate_outline_draft": (
        "只在尚无大纲时按系统提示中的大纲写入契约生成首版完整草稿；不会直接写入 src。"
    ),
    "read_outline": "读取已确认大纲的原文窗口和 revision；局部修改前必须先调用。",
    "stage_outline_edits": (
        "分批暂存大纲修改并返回累计 diff。重写完整幕、节、章时使用简单的 "
        "section_heading/new_text；长范围使用 start_text/end_text/new_text，"
        "中间原文无需复制；改短句时才使用 old_text/new_text。"
        "每批最多 8 个修改且载荷不超过 12000 字符；不会写入 src。"
    ),
    "confirm_outline_edits": "仅在用户明确确认后，将待确认大纲补丁写入 src/outline.md。",
    "discard_outline_edits": "用户拒绝修改时丢弃待确认大纲补丁，不改变 src。",
    "extract_style_source": "从用户提供文本提取风格来源。",
    "extract_setting_source": "从用户提供文本提取设定来源。",
    "review_source_pack": "审阅已提取的来源包。",
    "promote_source_pack": "将来源包晋升到可写资产。",
    "list_reference_library": "列出本机私有参考库的作品、结构确认和拆解状态，不读取整本原文。",
    "review_reference_source": "读取单部参考作品的证据结论和结构化资产索引，不读取整本原文。",
    "review_reference_profile": "读取证据化参考画像候选、冲突和排除项，用于和用户讨论取舍。",
    "preview_reference_adoption": (
        "按目标、风格维度、主辅角色和适用范围生成项目采纳 diff，不写入项目。"
    ),
    "apply_reference_adoption": "仅在用户明确确认后应用刚生成的采纳预览并重新编译项目风格。",
    "prepare_dante_handoff": "检查当前资产是否满足切换到 Dante 的条件，并生成交接产物。",
}


def is_exit_command(text: str) -> bool:
    return text.strip().lower() in EXIT_COMMANDS


def build_prompt_session(history=None, *, prompt_style: dict[str, str] | None = None):
    try:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.history import InMemoryHistory
        from prompt_toolkit.styles import Style
    except ImportError:
        logger.warning("prompt_toolkit not installed, falling back to basic input() shell")

        class FallbackPromptSession:
            def prompt(self, text: str) -> str:
                return input(text)

        return FallbackPromptSession()

    history = history or InMemoryHistory()
    style = Style.from_dict(prompt_style or {"prompt": "#ansibrightblue bold"})
    return PromptSession(history=history, style=style)


def build_goethe_prompt_session(history=None):
    return build_prompt_session(history=history)


def build_goethe_tool_layers(project_root: Path, novel_id: str | None = None) -> dict[str, object]:
    """构建 Goethe 工具分层视图，便于测试与 shell 复用。"""
    from .agent.tool_layers import build_goethe_tool_layers as _build

    return _build(project_root, novel_id)


@dataclass
class GoetheResult:
    """Goethe 运行结果。"""

    success: bool
    project_path: Path | None = None
    novel_id: str | None = None
    error: str | None = None
    exit_reason: str = ""
    turns_processed: int = 0
    startup: object | None = None


@dataclass
class GoetheStartupSnapshot:
    session_state: GoetheSessionState
    recovery_prompt: str


DEFAULT_GOETHE_SYSTEM_PROMPT = f"""你是 OpenWrite 的 Goethe，长期会话规划 Agent。

你的职责是汇总灵感、提出建议、收敛人物/设定/大纲，并把确认后的资产整理成可写内容。
正文推进交给 Dante。项目目录通常已由 Studio 或 `openwrite init` 创建，你不负责建目录。
项目身份上下文中的“当前作品”是已配置的书名；有该信息时直接使用它，绝不把小说 ID 当作书名，
也不要再次询问书名。

首次冷启动时，按这个顺序引导用户（可合并提问，但不要跳过）：
1. 书名、题材/类型、一句话核心冲突
2. 想要的基调与风格（克制/热血/悬疑等）与必须避免的套路
3. 作者意图与背景（可先草案）
4. 主要人物（至少主角）
5. 当前可写范围大纲（至少到章级）
6. 资产成熟后调用 prepare_dante_handoff，再提示用户切换 Dante

大纲修改必须遵守以下 ReAct 流程：
1. 普通问答、讨论、分析和征求建议只回复用户，不调用任何会修改大纲的工具。
2. 只有用户明确要求“生成大纲”且当前没有已确认大纲时，才能调用 generate_outline_draft。
   summarize_ideation 返回 next_action=confirm_ideation_summary 后，用户明确确认时必须先调用
   confirm_ideation_summary，并把用户完整确认原文传入 text；若同句还要求生成大纲，该动作会继续推进。
3. 已有大纲时绝不整篇重写或覆盖。先调用 read_outline 取得当前 revision，再调用 stage_outline_edits。
   重写完整幕、节、章时优先传 section_heading/new_text：section_heading 只需使用现有 Markdown 标题
   （例如“### 第2节：准备期”），系统会自动替换该标题下直到下一个同级标题前的正文，不要复制旧正文。
   无法用标题定位的长范围，使用 start_text/end_text/new_text：首尾各取一小段
   能唯一定位的文字，系统替换包含两个锚点在内的整个范围，中间原文不需要复制。
   禁止为长段、整章或整节提交 old_text。只有修改单句或短段落时才使用
   精确 old_text/new_text；即使模型误传了过长 old_text，系统也会尝试自动提取首尾锚点。
   未提及内容必须逐字保留。
   涉及整卷重排、超过 4 节或补齐大量章节时，必须按幕或最多 4 节分批：每批最多 8 个 edits，
   定位文本与 new_text 合计不超过 12000 字符。非最后一批设置 final_batch=false，
   并使用工具返回的 draft_revision 作为下一批 base_revision；不要重复已完成批次。
   存在 pending draft 后，大纲内容
   只能用 read_outline 读取，禁止用 read_project_document 读取 src/outline.md，因为后者属于通用
   canonical 文档接口。
   最后一批才设 final_batch=true。
4. stage_outline_edits 只累计暂存到同一份草稿。所有批次完成后，向用户展示累计 diff 摘要并等待确认；
   不得在同一轮自动调用 confirm_outline_edits，除非用户原始请求明确说“直接应用/无需确认”。
5. 只有用户明确说“确认应用、采用这版、写入大纲”等肯定表达时，才能调用
   confirm_outline_edits。否定、犹豫或继续讨论时不得调用。
6. 用户说取消、不要这版或放弃修改时，调用 discard_outline_edits。
7. 工具返回 revision 冲突或标题不存在时，重新 read_outline；长范围定位失败时，
   从 read_outline 返回内容中重新选择唯一的 start_text/end_text，不要改回长 old_text。
   短文本模式的 old_text_not_found 返回
   details.suggested_old_text 且未截断时，优先逐字复用该字段，并使用错误结果中的 revision 重试。
   不得凭记忆改写 old_text，也不得退回整篇生成覆盖。
8. 判断卷/幕/节/章位置或下一章时使用 get_outline_structure；它只读，不替代 src/outline.md。
9. 最终回复必须面向用户总结结果、diff 摘要和下一步，不要输出“old_text、扩大块、
   清理残留、重试补丁”等内部工具调试或补丁策略碎片。

关系修改遵守同样的确认边界：先调用 edit_world_relation 且 confirm=false 展示 diff；只有用户明确
确认后，才可使用预览返回的 base_revision 再次调用并设置 confirm=true。普通讨论不得写入关系。
当用户要求把人物与出身地点、能力设定、组织、物品或概念联系起来时，先用
search_relation_targets/get_world_relations 定位候选，再用 edit_world_relations(confirm=false)
批量预览；relations 必须优先使用查询返回的正式实体 ID。只有用户明确确认后才传回
preview_token/preview_tokens 并 confirm=true 写入，不得重新生成 relations。
修改已有角色、地点、能力设定、故事资料或正文时，先 read_project_document 读取 revision，
再 edit_project_document(confirm=false) 预览 diff；长范围使用唯一的 start_text/end_text，
短句才使用 old_text；只有用户明确确认后才仅使用预览返回的
preview_token 和 confirm=true 写入，不得重新生成 path/edits。
草案工具（generate_foundation_draft / generate_character_draft / generate_outline_draft）
只写 planning 草案，不直接当作最终 src 真源；晋升或确认前必须让用户过目。
基础设定草案由 confirm_foundation 晋升；角色草案由 confirm_character_draft 晋升。
这两个确认工具只能在用户明确采用当前草案时调用，不能在生成草案的同一轮自动调用。
用户要求删除已写正文、现有章节或全部章节时，不得调用大纲编辑或文档编辑工具绕过，
也不得声称重写 src/outline.md 可以删除正文；应引导用户到 Studio 正文页，
从最新章节开始点击“删除正文”并按章节 ID 手动确认。

参考作品工作流必须保持私有库与项目正典隔离：使用 list_reference_library、
review_reference_source 和 review_reference_profile 读取证据与结构化候选，不读取或复述整本参考原文。
讨论采用与否时先给出理由，
再调用 preview_reference_adoption 生成 diff；不得在同一轮自动调用 apply_reference_adoption，
除非用户原始请求明确要求直接应用。只有用户明确确认当前预览时，才能携带 preview_id 和
confirm=true 调用 apply_reference_adoption。Dante 只消费确认后生成的 composed.md，不能替用户
选择参考作品。参考模式中的人物、专名和专属设定不能直接晋升为项目正典。

剧情多线推演是 Goethe 的规划职责。用户要求比较多个未来走向时，先调用
manage_narrative_forecast(action=list) 读取可选大纲章节；若用户尚未明确分歧所在章节，先让用户选择，
不得自行猜测。随后调用 action=create 并传入 anchor_chapter_id，固化以该章为锚点的正典上下文，
再严格按返回 brief 生成相互隔离、互斥的分支，并在同一轮调用 action=stage 保存结构化结果。
推演是非正史规划材料；不要替用户选择。
只有用户明确指定某个 branch_id 时才调用 action=select，选择结果也不得直接改大纲或正文。
若用户随后要求应用已选分支，仍须使用大纲读取、暂存 diff 和明确确认的正常流程。

{OUTLINE_MARKDOWN_CONTRACT}

{CHARACTER_MARKDOWN_CONTRACT}
"""


def _build_goethe_tool_definitions(
    allowed_tools: set[str] | None = None,
) -> list[ToolDefinition]:
    direct_tool_defs = [
        tool for tool in OPENWRITE_TOOLS if tool.name in GOETHE_DIRECT_TOOLKIT
    ]

    action_tool_defs = [
        ToolDefinition(
            name="summarize_ideation",
            description=GOETHE_TOOL_DESCRIPTIONS["summarize_ideation"],
            parameters={"type": "object", "properties": {}},
        ),
        ToolDefinition(
            name="confirm_ideation_summary",
            description=GOETHE_TOOL_DESCRIPTIONS["confirm_ideation_summary"],
            parameters={
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "用户本轮完整确认原文",
                    },
                },
                "required": ["text"],
            },
            required=["text"],
        ),
        ToolDefinition(
            name="generate_foundation_draft",
            description=GOETHE_TOOL_DESCRIPTIONS["generate_foundation_draft"],
            parameters={
                "type": "object",
                "properties": {
                    "request_text": {"type": "string", "description": "规划请求"},
                },
            },
        ),
        ToolDefinition(
            name="confirm_foundation",
            description=GOETHE_TOOL_DESCRIPTIONS["confirm_foundation"],
            parameters={
                "type": "object",
                "properties": {
                    "confirm": {
                        "type": "boolean",
                        "description": "用户明确确认当前草案时必须为 true",
                    },
                },
                "required": ["confirm"],
            },
            required=["confirm"],
        ),
        ToolDefinition(
            name="generate_character_draft",
            description=GOETHE_TOOL_DESCRIPTIONS["generate_character_draft"],
            parameters={
                "type": "object",
                "properties": {
                    "request_text": {"type": "string", "description": "角色生成请求"},
                },
            },
        ),
        ToolDefinition(
            name="confirm_character_draft",
            description=GOETHE_TOOL_DESCRIPTIONS["confirm_character_draft"],
            parameters={
                "type": "object",
                "properties": {
                    "character_id": {
                        "type": "string",
                        "description": "generate_character_draft 返回的角色草案 ID",
                    },
                    "confirm": {
                        "type": "boolean",
                        "description": "用户明确确认当前草案时必须为 true",
                    },
                },
                "required": ["character_id", "confirm"],
            },
            required=["character_id", "confirm"],
        ),
        ToolDefinition(
            name="generate_outline_draft",
            description=GOETHE_TOOL_DESCRIPTIONS["generate_outline_draft"],
            parameters={
                "type": "object",
                "properties": {
                    "request_text": {"type": "string", "description": "大纲生成请求"},
                },
            },
        ),
        ToolDefinition(
            name="read_outline",
            description=GOETHE_TOOL_DESCRIPTIONS["read_outline"],
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "目标标题或关键词，例如“第六章”；优先使用",
                    },
                    "start_line": {"type": "integer", "description": "可选起始行"},
                    "end_line": {"type": "integer", "description": "可选结束行"},
                },
            },
        ),
        ToolDefinition(
            name="stage_outline_edits",
            description=GOETHE_TOOL_DESCRIPTIONS["stage_outline_edits"],
            parameters={
                "type": "object",
                "properties": {
                    "base_revision": {
                        "type": "string",
                        "description": "read_outline 返回的当前编辑版本 revision",
                    },
                    "edits": {
                        "type": "array",
                        "description": "本批按顺序执行的章节或短文本修改，最多 8 个",
                        "items": {
                            "type": "object",
                            "properties": {
                                "old_text": {
                                    "type": "string",
                                    "description": (
                                        "仅改单句/短段时使用：从 read_outline 复制的原文"
                                    ),
                                },
                                "section_heading": {
                                    "type": "string",
                                    "description": (
                                        "重写完整幕/节/章时优先使用：现有 Markdown 标题，"
                                        "如 ### 第2节：准备期；无需提交旧正文"
                                    ),
                                },
                                "start_text": {
                                    "type": "string",
                                    "description": (
                                        "长范围替换的起点锚点；只需一小段能唯一定位的原文"
                                    ),
                                },
                                "end_text": {
                                    "type": "string",
                                    "description": (
                                        "长范围替换的终点锚点；替换范围包含起止锚点"
                                    ),
                                },
                                "new_text": {
                                    "type": "string",
                                    "description": (
                                        "section_heading 模式下为标题下的新正文；"
                                        "范围模式下替换首尾锚点及中间内容；"
                                        "old_text 模式下为短文本替换；空字符串表示清空"
                                    ),
                                },
                                "replace_all": {
                                    "type": "boolean",
                                    "description": "仅在明确需要替换所有匹配时设为 true",
                                },
                            },
                            "required": ["new_text"],
                        },
                    },
                    "batch_label": {
                        "type": "string",
                        "description": "本批范围，例如“第一幕”或“第5-8节”",
                    },
                    "final_batch": {
                        "type": "boolean",
                        "description": "全部批次完成时为 true；仍有后续批次时必须为 false",
                    },
                },
                "required": ["base_revision", "edits", "final_batch"],
            },
            required=["base_revision", "edits", "final_batch"],
        ),
        ToolDefinition(
            name="confirm_outline_edits",
            description=GOETHE_TOOL_DESCRIPTIONS["confirm_outline_edits"],
            parameters={"type": "object", "properties": {}},
        ),
        ToolDefinition(
            name="discard_outline_edits",
            description=GOETHE_TOOL_DESCRIPTIONS["discard_outline_edits"],
            parameters={"type": "object", "properties": {}},
        ),
        ToolDefinition(
            name="extract_style_source",
            description=GOETHE_TOOL_DESCRIPTIONS["extract_style_source"],
            parameters={
                "type": "object",
                "properties": {
                    "source_id": {"type": "string", "description": "来源 ID"},
                    "source": {"type": "string", "description": "来源文本或文件路径"},
                },
                "required": ["source_id", "source"],
            },
            required=["source_id", "source"],
        ),
        ToolDefinition(
            name="extract_setting_source",
            description=GOETHE_TOOL_DESCRIPTIONS["extract_setting_source"],
            parameters={
                "type": "object",
                "properties": {
                    "source_id": {"type": "string", "description": "来源 ID"},
                    "source": {"type": "string", "description": "来源文本或文件路径"},
                },
                "required": ["source_id", "source"],
            },
            required=["source_id", "source"],
        ),
        ToolDefinition(
            name="review_source_pack",
            description=GOETHE_TOOL_DESCRIPTIONS["review_source_pack"],
            parameters={
                "type": "object",
                "properties": {
                    "source_id": {"type": "string", "description": "来源 ID"},
                },
                "required": ["source_id"],
            },
            required=["source_id"],
        ),
        ToolDefinition(
            name="promote_source_pack",
            description=GOETHE_TOOL_DESCRIPTIONS["promote_source_pack"],
            parameters={
                "type": "object",
                "properties": {
                    "source_id": {"type": "string", "description": "来源 ID"},
                    "target": {
                        "type": "string",
                        "description": "晋升目标: style, setting, world, all",
                    },
                },
                "required": ["source_id"],
            },
            required=["source_id"],
        ),
        ToolDefinition(
            name="list_reference_library",
            description=GOETHE_TOOL_DESCRIPTIONS["list_reference_library"],
            parameters={"type": "object", "properties": {}},
        ),
        ToolDefinition(
            name="review_reference_source",
            description=GOETHE_TOOL_DESCRIPTIONS["review_reference_source"],
            parameters={
                "type": "object",
                "properties": {
                    "source_id": {"type": "string", "description": "私有参考库中的作品 ID"},
                },
                "required": ["source_id"],
            },
            required=["source_id"],
        ),
        ToolDefinition(
            name="review_reference_profile",
            description=GOETHE_TOOL_DESCRIPTIONS["review_reference_profile"],
            parameters={
                "type": "object",
                "properties": {
                    "profile_id": {"type": "string", "description": "Studio 生成的参考画像 ID"},
                },
                "required": ["profile_id"],
            },
            required=["profile_id"],
        ),
        ToolDefinition(
            name="preview_reference_adoption",
            description=GOETHE_TOOL_DESCRIPTIONS["preview_reference_adoption"],
            parameters={
                "type": "object",
                "properties": {
                    "profile_id": {"type": "string"},
                    "selections": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "item_id": {"type": "string"},
                                "target": {
                                    "type": "string",
                                    "enum": ["style", "rules", "inspiration", "setting_candidates"],
                                },
                                "dimension": {
                                    "type": "string",
                                    "enum": [
                                        "narration",
                                        "language",
                                        "dialogue",
                                        "rhythm",
                                        "emotion",
                                        "structure",
                                        "craft",
                                        "avoid",
                                    ],
                                },
                                "role": {
                                    "type": "string",
                                    "enum": ["primary", "auxiliary", "validation_only", "avoid"],
                                },
                                "scope": {
                                    "type": "string",
                                    "enum": ["project", "arc", "chapter"],
                                },
                                "scope_id": {"type": "string"},
                                "adapted_claim": {"type": "string"},
                            },
                            "required": ["item_id", "target"],
                        },
                    },
                },
                "required": ["profile_id", "selections"],
            },
            required=["profile_id", "selections"],
        ),
        ToolDefinition(
            name="apply_reference_adoption",
            description=GOETHE_TOOL_DESCRIPTIONS["apply_reference_adoption"],
            parameters={
                "type": "object",
                "properties": {
                    "preview_id": {"type": "string"},
                    "confirm": {"type": "boolean"},
                },
                "required": ["preview_id", "confirm"],
            },
            required=["preview_id", "confirm"],
        ),
        ToolDefinition(
            name="prepare_dante_handoff",
            description=GOETHE_TOOL_DESCRIPTIONS["prepare_dante_handoff"],
            parameters={"type": "object", "properties": {}},
        ),
    ]
    combined = direct_tool_defs + action_tool_defs
    if allowed_tools is None:
        return combined
    return [tool for tool in combined if tool.name in allowed_tools]


class GoetheChatAgent:
    """Goethe 长会话规划 Agent。"""

    def __init__(
        self,
        project_root: Path | None = None,
        novel_id: str | None = None,
        *,
        session_store: GoetheSessionStateStore | None = None,
        prompt_session_factory: Callable[[], Any] | None = None,
        llm_client_factory: Callable[[], Any] | None = None,
        react_agent: Any | None = None,
        tool_layer_factory: Callable[[Path], dict[str, object]] | None = None,
        activity_callback: Callable[[dict[str, Any]], None] | None = None,
        prompt_text: str = "\n🌿 Goethe> ",
    ):
        self.project_root = Path(project_root or Path.cwd()).resolve()
        self.novel_id = novel_id or self._load_novel_id()
        self.session_store = session_store or GoetheSessionStateStore(
            self.project_root, self.novel_id
        )
        self.prompt_session_factory = (
            prompt_session_factory
            or (lambda: build_goethe_prompt_session(history=None))
        )
        self.llm_client_factory = llm_client_factory or self._build_default_llm_client
        self.tool_layer_factory = tool_layer_factory or build_goethe_tool_layers
        self.activity_callback = activity_callback
        self.prompt_text = prompt_text
        self._react_agent = react_agent
        self._react_agent_factory = (
            self._build_default_react_agent if react_agent is None else None
        )
        self._tool_layers: dict[str, object] | None = None
        self.session_state: GoetheSessionState | None = None
        self.recovery_prompt: str = ""
        self.startup_snapshot: GoetheStartupSnapshot | None = None
        self._active_user_instruction = ""

        if self._react_agent is not None:
            self._ensure_react_agent_surface(self._react_agent)

    def startup(self) -> GoetheStartupSnapshot:
        session_state = self.session_store.load_or_create()
        self.session_state = session_state
        self.recovery_prompt = self.build_recovery_prompt()
        self.startup_snapshot = GoetheStartupSnapshot(
            session_state=session_state,
            recovery_prompt=self.recovery_prompt,
        )
        return self.startup_snapshot

    def build_recovery_prompt(self) -> str:
        session_state = self._require_session_state()
        onboarding = self._load_onboarding_snapshot()
        is_first_run = not (
            session_state.conversation_summary
            or session_state.recent_turns
            or session_state.last_action
        )

        if is_first_run:
            lines = [
                "Goethe 首次规划会话。",
                "建议顺序：1) 书名与题材 2) 一句话冲突 3) 风格与禁忌 "
                "4) 背景/人物/大纲 5) 交接 Dante",
            ]
        else:
            lines = [
                "Goethe 已恢复，可以继续上次的长期规划会话。",
                f"会话: {session_state.session_id} / active_agent={session_state.active_agent}",
            ]

        project_identity = self._project_identity_context(onboarding)
        if project_identity:
            lines.append(project_identity)
        if onboarding.get("missing_labels"):
            lines.append("当前资产缺口: " + "、".join(onboarding["missing_labels"]))
        if onboarding.get("suggested_first_message"):
            lines.append(f"可引导用户从这句话开始: {onboarding['suggested_first_message']}")
        if session_state.conversation_summary:
            lines.append(f"会话摘要: {session_state.conversation_summary}")
        if session_state.working_memory:
            memory_bits = ", ".join(
                f"{key}={value}" for key, value in session_state.working_memory.items()
            )
            lines.append(f"工作记忆: {memory_bits}")
        if session_state.recent_turns:
            recent_lines = [
                f"{turn.role}: {turn.content}"
                for turn in session_state.recent_turns[-4:]
            ]
            lines.append("最近轮次:\n" + "\n".join(recent_lines))
        if session_state.open_questions:
            lines.append("未决问题: " + "；".join(session_state.open_questions))
        if session_state.recent_files:
            lines.append("最近文件: " + "；".join(session_state.recent_files))
        if session_state.last_action:
            lines.append(f"最近动作: {session_state.last_action}")
        return "\n".join(lines)

    def _load_onboarding_snapshot(self) -> dict[str, Any]:
        try:
            from tools.novel_workspace import build_onboarding_checklist

            return build_onboarding_checklist(self.project_root, self.novel_id)
        except Exception:
            return {}

    def _project_identity_context(self, onboarding: dict[str, Any]) -> str:
        """Build the authoritative title/ID context shared with the shell and model."""
        title = str(onboarding.get("title") or "").strip()
        novel_id = str(onboarding.get("novel_id") or self.novel_id or "").strip()
        if title:
            identity = f"当前作品：{title}（小说 ID：{novel_id}）"
            return (
                f"{identity}。书名以“当前作品”为准；不要把小说 ID 当作书名，"
                "也不要再次询问已经提供的书名。"
            )
        if novel_id:
            return f"当前小说 ID：{novel_id}"
        return ""

    def run(self) -> GoetheResult:
        startup = self.startup()
        session = self.prompt_session_factory()
        react_agent = self._get_react_agent()

        print("\n" + "=" * 50)
        print("   OpenWrite Goethe 长会话规划 Agent")
        print("   (输入 '退出'、'quit'、'exit' 或 'q' 可结束对话)")
        print("=" * 50)
        print(startup.recovery_prompt)

        turns_processed = 0
        while True:
            try:
                user_input = session.prompt(self.prompt_text).strip()
            except KeyboardInterrupt:
                state = self._require_session_state()
                state.last_action = "keyboard_interrupt"
                self.session_store.save(state)
                return GoetheResult(
                    success=True,
                    exit_reason="keyboard_interrupt",
                    turns_processed=turns_processed,
                    startup=startup,
                    project_path=self._project_path(),
                    novel_id=self.novel_id,
                )

            if not user_input:
                continue

            if is_exit_command(user_input):
                state = self._require_session_state()
                state.last_action = "exit"
                self.session_store.save(state)
                print("\n好的，随时欢迎回来！")
                return GoetheResult(
                    success=True,
                    exit_reason=user_input,
                    turns_processed=turns_processed,
                    startup=startup,
                    project_path=self._project_path(),
                    novel_id=self.novel_id,
                )

            if self._should_use_handoff_shortcut(user_input):
                self._append_user_turn(user_input)
                handoff = self.prepare_dante_handoff()
                if handoff.get("ok"):
                    self._append_assistant_turn(
                        "Goethe 已完成交接，可以切换到 Dante 继续正文创作。"
                    )
                    self.session_store.save(self._require_session_state())
                    print(f"\n✅ Goethe 已完成交接: {handoff.get('handoff_markdown_path')}")
                    return GoetheResult(
                        success=True,
                        exit_reason="handoff_dante",
                        turns_processed=turns_processed,
                        startup=startup,
                        project_path=self._project_path(),
                        novel_id=self.novel_id,
                    )
                blocked_items = handoff.get("missing_items", [])
                blocked_text = (
                    "、".join(str(item) for item in blocked_items)
                    if blocked_items
                    else "未知"
                )
                self._append_assistant_turn(f"暂时不能交接给 Dante，还缺少：{blocked_text}。")
                self.session_store.save(self._require_session_state())
                print(f"\n⚠️ 还不能切到 Dante，缺少: {blocked_text}")
                continue

            self._append_user_turn(user_input)
            state = self._require_session_state()
            state.last_action = "chat"
            self.session_store.save(state)
            response_text = manual_chapter_delete_guidance(user_input)
            if response_text:
                state.last_action = "manual_chapter_delete_guidance"
            else:
                try:
                    response_text = self._run_react_agent(react_agent, user_input)
                except Exception:
                    state.last_action = "react_error"
                    self.session_store.save(state)
                    raise

            if response_text:
                self._append_assistant_turn(response_text)
                print(f"\n🤖 Goethe: {response_text}")
            self.session_store.save(self._require_session_state())
            turns_processed += 1

    def respond(self, user_input: str) -> str:
        """Process one persisted Goethe turn for non-terminal clients."""
        text = str(user_input or "").strip()
        if not text:
            raise ValueError("消息不能为空")
        if self.session_state is None:
            self.startup()
        self._active_user_instruction = text
        if self._should_use_handoff_shortcut(text):
            self._append_user_turn(text)
            handoff = self.prepare_dante_handoff()
            if handoff.get("ok"):
                response_text = "Goethe 已完成交接，可以切换到 Dante 继续正文创作。"
                self._append_assistant_turn(response_text)
                self.session_store.save(self._require_session_state())
                return response_text
            missing = "、".join(
                str(item) for item in handoff.get("missing_items", [])
            ) or "必要资产"
            response_text = f"暂时不能交接给 Dante，还缺少：{missing}。"
            self._append_assistant_turn(response_text)
            self.session_store.save(self._require_session_state())
            return response_text
        self._append_user_turn(text)
        state = self._require_session_state()
        state.last_action = "chat"
        self.session_store.save(state)
        response_text = manual_chapter_delete_guidance(text)
        if response_text:
            state.last_action = "manual_chapter_delete_guidance"
            self._active_user_instruction = ""
        else:
            try:
                response_text = self._run_react_agent(self._get_react_agent(), text)
            except Exception:
                state.last_action = "react_error"
                self.session_store.save(state)
                raise
        if response_text:
            self._append_assistant_turn(response_text)
        self.session_store.save(self._require_session_state())
        return response_text

    def prepare_dante_handoff(self) -> dict[str, Any]:
        layers = self._load_tool_layers()
        action_executors = layers.get("action_tool_executors", {})
        if isinstance(action_executors, dict) and "prepare_dante_handoff" in action_executors:
            payload = action_executors["prepare_dante_handoff"]({})
        else:
            payload = {
                "action": "prepare_dante_handoff",
                "ok": False,
                "blocked": True,
                "error": "handoff_action_unavailable",
                "message": "未找到 Goethe handoff action。",
                "next_action": "continue_planning",
                "missing_items": [],
            }

        if self.session_state is not None and payload.get("ok"):
            self.session_state.last_action = "handoff_dante"
            self.session_store.save(self.session_state)
        return payload

    def _build_default_llm_client(self) -> Any:
        from .llm import LLMClient, LLMConfig

        return LLMClient(LLMConfig.from_env())

    def _build_default_react_agent(self) -> ReActAgent:
        client = self.llm_client_factory()
        allowed_tools, runtime_prompt = self._runtime_surface()
        react_agent = ReActAgent(
            client=client,
            model=client.config.model,
            tools=_build_goethe_tool_definitions(allowed_tools),
            system_prompt=f"{DEFAULT_GOETHE_SYSTEM_PROMPT}\n\n{runtime_prompt}",
            max_turns=20,
            activity_callback=self.activity_callback,
        )
        combined = self._combined_tool_executors()
        if combined:
            react_agent._register_tool_executors(combined)
        return react_agent

    def _get_react_agent(self) -> Any:
        if self._react_agent is None:
            self._react_agent = self._react_agent_factory()
        self._ensure_react_agent_surface(self._react_agent)
        return self._react_agent

    def _ensure_react_agent_surface(self, react_agent: Any) -> None:
        if react_agent is None:
            return

        allowed_tools, runtime_prompt = self._runtime_surface()
        canonical_tools = {
            tool.name: tool for tool in _build_goethe_tool_definitions(allowed_tools)
        }
        if hasattr(react_agent, "tools"):
            if self._react_agent_factory is not None:
                react_agent.tools = list(canonical_tools.values())
            else:
                existing_tools = list(getattr(react_agent, "tools", []) or [])
                merged_tools = []
                seen: set[str] = set()
                for tool in existing_tools:
                    tool_name = getattr(tool, "name", "")
                    if not tool_name:
                        merged_tools.append(tool)
                        continue
                    canonical_tool = canonical_tools.get(tool_name)
                    if canonical_tool is not None:
                        merged_tools.append(canonical_tool)
                        seen.add(tool_name)
                    else:
                        merged_tools.append(tool)
                for tool_name, canonical_tool in canonical_tools.items():
                    if tool_name not in seen and all(
                        getattr(tool, "name", "") != tool_name for tool in merged_tools
                    ):
                        merged_tools.append(canonical_tool)
                react_agent.tools = merged_tools

        if self._react_agent_factory is not None and hasattr(react_agent, "system_prompt"):
            react_agent.system_prompt = f"{DEFAULT_GOETHE_SYSTEM_PROMPT}\n\n{runtime_prompt}"

        if self._combined_tool_executors() and hasattr(react_agent, "_register_tool_executors"):
            react_agent._register_tool_executors(self._combined_tool_executors())
        if hasattr(react_agent, "activity_callback"):
            react_agent.activity_callback = self.activity_callback

    def _run_react_agent(self, react_agent: Any, instruction: str) -> str:
        self._active_user_instruction = instruction
        try:
            self._ensure_react_agent_surface(react_agent)
            result = react_agent.run(
                instruction,
                context_messages=self._build_context_messages(include_recent_turns=False),
            )
            if inspect.isawaitable(result):
                result = asyncio.run(result)
            if result is None:
                return ""
            if isinstance(result, str):
                return result.strip()
            if hasattr(result, "content"):
                return str(getattr(result, "content", "")).strip()
            if isinstance(result, dict):
                return str(result.get("content", "")).strip()
            return str(result).strip()
        finally:
            self._active_user_instruction = ""

    def _build_context_messages(self, *, include_recent_turns: bool = True) -> list[Any]:
        from .llm import Message

        session_state = self._require_session_state()
        context_messages: list[Any] = []

        project_identity = self._project_identity_context(self._load_onboarding_snapshot())
        if project_identity:
            context_messages.append(Message("assistant", project_identity))

        if session_state.conversation_summary:
            context_messages.append(
                Message("assistant", f"会话摘要: {session_state.conversation_summary}")
            )

        if session_state.working_memory:
            memory_bits = ", ".join(
                f"{key}={value}" for key, value in session_state.working_memory.items()
            )
            context_messages.append(Message("assistant", f"工作记忆: {memory_bits}"))

        recent_turns = session_state.recent_turns
        if not include_recent_turns and recent_turns:
            recent_turns = recent_turns[:-1]

        if recent_turns:
            recent_lines = [f"{turn.role}: {turn.content}" for turn in recent_turns]
            context_messages.append(
                Message("assistant", "最近轮次:\n" + "\n".join(recent_lines))
            )

        if session_state.open_questions:
            context_messages.append(
                Message("assistant", "未决问题: " + "；".join(session_state.open_questions))
            )

        if session_state.recent_files:
            context_messages.append(
                Message("assistant", "最近文件: " + "；".join(session_state.recent_files))
            )

        if session_state.last_action:
            context_messages.append(Message("assistant", f"最近动作: {session_state.last_action}"))

        return context_messages

    def _combined_tool_executors(self) -> dict[str, Callable[[dict[str, Any]], Any]]:
        layers = self._load_tool_layers()
        combined: dict[str, Callable[[dict[str, Any]], Any]] = {}
        tool_executors = layers.get("tool_executors", {})
        action_tool_executors = layers.get("action_tool_executors", {})
        if isinstance(tool_executors, dict):
            combined.update(tool_executors)
        if isinstance(action_tool_executors, dict):
            combined.update(action_tool_executors)
        combined = remember_document_edit_previews(
            combined,
            working_memory=lambda: (
                self.session_state.working_memory if self.session_state is not None else {}
            ),
            persist=lambda: (
                self.session_store.save(self.session_state)
                if self.session_state is not None
                else None
            ),
            instruction=lambda: self._active_user_instruction,
        )
        combined = remember_relation_previews(
            combined,
            working_memory=lambda: (
                self.session_state.working_memory if self.session_state is not None else {}
            ),
            persist=lambda: (
                self.session_store.save(self.session_state)
                if self.session_state is not None
                else None
            ),
            instruction=lambda: self._active_user_instruction,
        )
        return guard_confirmable_executors(
            combined,
            instruction=lambda: self._active_user_instruction,
        )

    def _confirm_outline_if_explicit(
        self,
        executor: Callable[[dict[str, Any]], Any],
        args: dict[str, Any],
    ) -> Any:
        if not is_explicit_mutation_confirmation(self._active_user_instruction):
            return {
                "action": "confirm_outline_edits",
                "ok": False,
                "blocked": True,
                "error": "explicit_user_confirmation_required",
                "message": "尚未收到用户对待确认大纲 diff 的明确应用指令，src 未修改。",
                "next_action": "request_outline_confirmation",
            }
        return executor(args)

    @staticmethod
    def _looks_like_explicit_outline_confirmation(text: str) -> bool:
        return is_explicit_mutation_confirmation(text)

    def _load_tool_layers(self) -> dict[str, object]:
        if self._tool_layers is None:
            try:
                self._tool_layers = dict(
                    self.tool_layer_factory(self.project_root, self.novel_id)
                )
            except TypeError:
                self._tool_layers = dict(self.tool_layer_factory(self.project_root))
        return self._tool_layers

    def _runtime_surface(self) -> tuple[set[str], str]:
        layers = self._load_tool_layers()
        resolution = layers.get("runtime_resolution")
        resolver = RuntimeSkillResolver(self.project_root)
        available = set(resolver.discover()[0])
        explicit = tuple(
            skill_id
            for skill_id in extract_explicit_skill_mentions(
                self._active_user_instruction
            )
            if skill_id in available
        )
        if explicit:
            baseline = {tool.name for tool in _build_goethe_tool_definitions()}
            resolution = resolver.resolve(
                agent="goethe",
                task="planning",
                base_tools=baseline,
                explicit_skills=explicit,
            )
        if resolution is None:
            return (
                {tool.name for tool in _build_goethe_tool_definitions()},
                "",
            )
        allowed_tools = set(getattr(resolution, "allowed_tools", ()) or ())
        rules = RuleCompiler(self.project_root).active()
        return allowed_tools, render_runtime_context(resolution, rules)

    def _should_use_handoff_shortcut(self, text: str) -> bool:
        if not self._looks_like_handoff_request(text):
            return False
        if self._looks_like_explicit_outline_confirmation(text):
            return False
        try:
            from .agent.book_state import BookStateError, BookStateStore

            # Strict read: `load_or_create` quarantines a damaged file and returns
            # a fresh state, which reads as "nothing pending" and would unlock
            # the shortcut past a confirmation the author never gave.
            state = BookStateStore(self.project_root, self.novel_id).load_strict()
        except Exception:
            # Fail closed: an unreadable book state means we cannot know whether
            # an outline scope is still awaiting the author's confirmation, and
            # the shortcut bypasses exactly that gate.
            return False
        return not bool(str(state.pending_confirmation or "").strip())

    def _append_user_turn(self, content: str) -> None:
        state = self._require_session_state()
        state.recent_turns.append(GoetheSessionTurn(role="user", content=content))
        self.session_store.append_turn("user", content)

    def _append_assistant_turn(self, content: str) -> None:
        state = self._require_session_state()
        state.recent_turns.append(GoetheSessionTurn(role="assistant", content=content))
        self.session_store.append_turn("assistant", content)

    def _project_path(self) -> Path:
        return self.project_root / "data" / "novels" / self.novel_id

    def _load_novel_id(self) -> str:
        config = self._load_config()
        novel_id = str(config.get("novel_id", "current")).strip()
        return novel_id or "current"

    def _load_config(self) -> dict[str, Any]:
        config_path = self.project_root / "novel_config.yaml"
        if not config_path.exists():
            fallback = self.project_root / "data" / "novels" / "current" / "novel_config.yaml"
            if not fallback.exists():
                return {}
            config_path = fallback
        try:
            import yaml

            data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _require_session_state(self) -> GoetheSessionState:
        if self.session_state is None:
            raise RuntimeError("Goethe session has not been started")
        return self.session_state

    def _looks_like_handoff_request(self, text: str) -> bool:
        lowered = str(text or "").strip().lower()
        if not lowered:
            return False
        if any(
            tool_name in lowered
            for tool_name in ("get_goethe_handoff", "prepare_dante_handoff")
        ):
            return False
        return any(
            token in lowered
            for token in ("切到 dante", "切换到 dante", "开始写正文", "handoff", "交接给 dante")
        )

def run_goethe() -> int:
    """运行 Goethe 长会话规划 Shell。"""
    config_path = Path.cwd() / "novel_config.yaml"
    if not config_path.exists():
        print(
            "❌ 当前目录不是小说项目。\n"
            "请先运行 `openwrite init <novel_id>` 或 `openwrite studio` 创建作品，"
            "再进入 Goethe 规划会话。"
        )
        return 1
    agent = GoetheChatAgent()
    result = agent.run()

    if result.success:
        if result.novel_id:
            print(f"\n✨ Goethe 会话已结束: {result.novel_id}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(run_goethe())
