"""Tool Schema Generation — 将 Skills 和 ToolExecutor 工具转换为 LLM 可理解的结构。

支持将两种来源的工具转换为 OpenAI-compatible tool schemas：
1. Skill 模块（来自 skills/skill_registry.py）
2. ToolExecutor 工具（来自 skills/tools/executor.py）

生成的 schema 用于 LLM function calling 或 prompt injection。
"""

from __future__ import annotations

import inspect
import logging
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

if TYPE_CHECKING:
    from skills.skill import Skill
    from skills.skill_registry import SkillRegistry
    from skills.tools.executor import ToolExecutor

logger = logging.getLogger(__name__)


def skill_to_tool_schema(skill: "Skill") -> Dict[str, Any]:
    """将 Skill 转换为 OpenAI-compatible tool schema。

    Args:
        skill: Skill 对象（来自 skills/skill.py）

    Returns:
        OpenAI function schema dict
    """
    properties: Dict[str, Any] = {}
    required: List[str] = []

    # 常见参数定义
    common_params = {
        "chapter_id": {"type": "string", "description": "章节标识符（如 ch_001）"},
        "novel_id": {"type": "string", "description": "小说项目 ID"},
        "objective": {"type": "string", "description": "任务目标或描述"},
        "name": {"type": "string", "description": "名称（角色名、实体名等）"},
        "text": {"type": "string", "description": "待处理的文本内容"},
        "draft": {"type": "string", "description": "草稿文本"},
        "strict": {"type": "boolean", "description": "是否启用严格模式"},
        "action": {
            "type": "string",
            "description": "操作类型",
            "enum": ["check", "polish", "create", "modify", "query"],
        },
    }

    # 根据 skill 名称推断参数
    skill_name_lower = skill.name.lower()

    if "chapter" in skill_name_lower or "write" in skill_name_lower:
        properties["chapter_id"] = common_params["chapter_id"]
        properties["objective"] = common_params["objective"]
        required.append("chapter_id")

    if "outline" in skill_name_lower:
        properties["chapter_id"] = common_params["chapter_id"]
        properties["objective"] = common_params["objective"]

    if "character" in skill_name_lower:
        properties["name"] = common_params["name"]

    if "foreshadow" in skill_name_lower:
        properties["chapter_id"] = common_params["chapter_id"]

    if "style" in skill_name_lower or "stylist" in skill_name_lower:
        properties["text"] = common_params["text"]
        properties["action"] = common_params["action"]
        required.append("text")

    if "lore" in skill_name_lower or "check" in skill_name_lower:
        properties["draft"] = common_params["draft"]
        properties["strict"] = common_params["strict"]
        required.append("draft")

    # 添加通用 novel_id 参数
    properties["novel_id"] = common_params["novel_id"]

    return {
        "type": "function",
        "function": {
            "name": skill.name,
            "description": skill.description[:200]
            if skill.description
            else f"执行 {skill.name} 功能",
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


def executor_tool_to_schema(tool_name: str, tool_func: Callable) -> Dict[str, Any]:
    """将 ToolExecutor 工具转换为 OpenAI-compatible tool schema。

    从函数签名和 docstring 推断参数结构。

    Args:
        tool_name: 工具名称
        tool_func: 工具处理函数

    Returns:
        OpenAI function schema dict
    """
    docstring = tool_func.__doc__ or ""
    description = docstring.split("\n\n")[0].strip()[:200]

    sig = inspect.signature(tool_func)
    properties: Dict[str, Any] = {}
    required: List[str] = []

    type_mapping = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        list: "array",
        dict: "object",
    }

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue

        param_type = "string"
        if param.annotation != inspect.Parameter.empty:
            param_type = type_mapping.get(param.annotation, "string")

        param_desc = f"参数: {param_name}"
        if docstring:
            args_section = docstring.split("Args:")
            if len(args_section) > 1:
                args_text = args_section[1].split("\n\n")[0]
                for line in args_text.split("\n"):
                    if line.strip().startswith(param_name):
                        param_desc = (
                            line.split(":", 1)[-1].strip()
                            if ":" in line
                            else line.strip()
                        )
                        break

        properties[param_name] = {
            "type": param_type,
            "description": param_desc[:100],
        }

        if param.default == inspect.Parameter.empty:
            required.append(param_name)

    _enhance_tool_properties(tool_name, properties)

    return {
        "type": "function",
        "function": {
            "name": tool_name,
            "description": description or f"执行 {tool_name} 工具",
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


def _enhance_tool_properties(tool_name: str, properties: Dict[str, Any]) -> None:
    """增强已知工具的参数描述（原地修改）。"""
    enhancements = {
        "read_file": {
            "path": {"description": "文件路径（相对于项目根目录）"},
            "encoding": {"description": "文件编码，默认 utf-8"},
        },
        "write_file": {
            "path": {"description": "文件路径（仅限 data/novels/ 目录）"},
            "content": {"description": "要写入的文件内容"},
            "create_dirs": {"description": "是否自动创建目录，默认 True"},
        },
        "search_content": {
            "query": {"description": "搜索查询字符串"},
            "scope": {
                "description": "搜索范围: all/outline/characters/world/manuscript"
            },
            "max_results": {"description": "最大返回结果数"},
        },
        "query_outline": {
            "chapter_id": {"description": "章节 ID（可选，不指定则返回全部）"},
            "arc_id": {"description": "篇章 ID（可选）"},
        },
        "query_characters": {
            "character_id": {"description": "角色 ID（可选）"},
            "tier": {"description": "角色层级: 主角/重要配角/配角/龙套"},
        },
        "query_foreshadowing": {
            "node_id": {"description": "伏笔节点 ID（可选）"},
            "status": {"description": "状态: pending/planted/recovered"},
        },
    }

    if tool_name in enhancements:
        for prop_name, enhancement in enhancements[tool_name].items():
            if prop_name in properties:
                properties[prop_name].update(enhancement)


def get_all_tool_schemas(
    skill_registry: Optional["SkillRegistry"] = None,
    tool_executor: Optional["ToolExecutor"] = None,
    include_skills: bool = True,
    include_executor_tools: bool = True,
    char_budget: int = 8000,
) -> List[Dict[str, Any]]:
    """聚合所有可用工具的 schema。

    Args:
        skill_registry: SkillRegistry 实例（可选）
        tool_executor: ToolExecutor 实例（可选）
        include_skills: 是否包含 Skills
        include_executor_tools: 是否包含 ToolExecutor 工具
        char_budget: 字符预算上限（用于截断）

    Returns:
        工具 schema 列表
    """
    schemas: List[Dict[str, Any]] = []
    total_chars = 0

    if include_skills and skill_registry is not None:
        for skill in skill_registry.list_all():
            schema = skill_to_tool_schema(skill)
            schema_str = str(schema)
            if total_chars + len(schema_str) > char_budget:
                logger.debug("Tool schema char budget exceeded, truncating")
                break
            schemas.append(schema)
            total_chars += len(schema_str)

    if include_executor_tools and tool_executor is not None:
        for tool_info in tool_executor.list_tools():
            tool_name = tool_info.get("name", "")
            if not tool_name:
                continue

            handler = tool_executor._tools.get(tool_name)
            if not handler:
                continue

            schema = executor_tool_to_schema(tool_name, handler)
            schema_str = str(schema)
            if total_chars + len(schema_str) > char_budget:
                logger.debug("Tool schema char budget exceeded, truncating")
                break
            schemas.append(schema)
            total_chars += len(schema_str)

    return schemas


def get_director_tool_schemas() -> List[Dict[str, Any]]:
    """获取 Director 可用的工具 schemas。

    Director 使用固定的工具集：
    - outline_assist, write_chapter, lore_checker, stylist
    - character_query, foreshadow_query
    - read_file, query_*, search_content

    Returns:
        工具 schema 列表
    """
    director_tools = [
        {
            "name": "outline_assist",
            "description": "大纲辅助：根据章节目标生成节拍列表",
            "parameters": {
                "type": "object",
                "properties": {
                    "chapter_id": {"type": "string", "description": "章节标识符"},
                    "objective": {"type": "string", "description": "章节目标"},
                },
                "required": ["chapter_id"],
            },
        },
        {
            "name": "write_chapter",
            "description": "章节写作：Pipeline 生成章节（Librarian → LoreChecker → Stylist）",
            "parameters": {
                "type": "object",
                "properties": {
                    "chapter_id": {"type": "string", "description": "章节标识符"},
                    "objective": {"type": "string", "description": "章节目标"},
                    "use_stylist": {
                        "type": "boolean",
                        "description": "是否启用风格润色",
                    },
                    "strict_lore": {
                        "type": "boolean",
                        "description": "是否启用严格逻辑检查",
                    },
                },
                "required": ["chapter_id"],
            },
        },
        {
            "name": "lore_checker",
            "description": "逻辑审查：检查草稿的角色一致性、世界观一致性、伏笔一致性",
            "parameters": {
                "type": "object",
                "properties": {
                    "draft": {"type": "string", "description": "待审查的草稿文本"},
                    "strict": {"type": "boolean", "description": "是否启用严格模式"},
                },
                "required": ["draft"],
            },
        },
        {
            "name": "stylist",
            "description": "风格润色：消除 AI 痕迹，调整节奏，确保声音一致性",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "待润色的文本"},
                    "action": {
                        "type": "string",
                        "enum": ["check", "polish"],
                        "description": "操作类型",
                    },
                },
                "required": ["text"],
            },
        },
        {
            "name": "character_query",
            "description": "角色查询：获取角色的当前状态",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "角色名称"},
                },
                "required": ["name"],
            },
        },
        {
            "name": "foreshadow_query",
            "description": "伏笔查询：获取待回收的伏笔列表",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
        {
            "name": "read_file",
            "description": "读取项目文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件路径（相对于项目根目录）",
                    },
                },
                "required": ["path"],
            },
        },
        {
            "name": "query_outline",
            "description": "查询大纲数据",
            "parameters": {
                "type": "object",
                "properties": {
                    "chapter_id": {"type": "string", "description": "章节 ID（可选）"},
                    "arc_id": {"type": "string", "description": "篇章 ID（可选）"},
                },
                "required": [],
            },
        },
        {
            "name": "query_characters",
            "description": "查询角色数据",
            "parameters": {
                "type": "object",
                "properties": {
                    "character_id": {
                        "type": "string",
                        "description": "角色 ID（可选）",
                    },
                    "tier": {"type": "string", "description": "角色层级"},
                },
                "required": [],
            },
        },
        {
            "name": "query_foreshadowing",
            "description": "查询伏笔数据",
            "parameters": {
                "type": "object",
                "properties": {
                    "node_id": {"type": "string", "description": "伏笔节点 ID（可选）"},
                    "status": {"type": "string", "description": "状态过滤"},
                },
                "required": [],
            },
        },
        {
            "name": "search_content",
            "description": "全文搜索",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索查询"},
                    "scope": {"type": "string", "description": "搜索范围"},
                    "max_results": {"type": "integer", "description": "最大结果数"},
                },
                "required": ["query"],
            },
        },
    ]

    schemas = []
    for tool in director_tools:
        schemas.append({"type": "function", "function": tool})

    return schemas


def format_tools_for_prompt(
    schemas: List[Dict[str, Any]], format_type: str = "markdown"
) -> str:
    """将工具 schemas 格式化为 prompt 文本。

    Args:
        schemas: 工具 schema 列表
        format_type: 格式类型（markdown/json/xml）

    Returns:
        格式化后的文本
    """
    import json

    if format_type == "json":
        return json.dumps(schemas, ensure_ascii=False, indent=2)

    if format_type == "xml":
        lines = ["<tools>"]
        for schema in schemas:
            func = schema.get("function", {})
            name = func.get("name", "unknown")
            desc = func.get("description", "")
            lines.append(f'  <tool name="{name}">')
            lines.append(f"    <description>{desc}</description>")
            params = func.get("parameters", {}).get("properties", {})
            if params:
                lines.append("    <parameters>")
                for pname, pinfo in params.items():
                    ptype = pinfo.get("type", "string")
                    pdesc = pinfo.get("description", "")
                    lines.append(
                        f'      <param name="{pname}" type="{ptype}">{pdesc}</param>'
                    )
                lines.append("    </parameters>")
            lines.append("  </tool>")
        lines.append("</tools>")
        return "\n".join(lines)

    # Default: markdown
    lines = ["# 可用工具\n"]
    for schema in schemas:
        func = schema.get("function", {})
        name = func.get("name", "unknown")
        desc = func.get("description", "")
        lines.append(f"## {name}\n{desc}\n")

        params = func.get("parameters", {}).get("properties", {})
        required = func.get("parameters", {}).get("required", [])

        if params:
            lines.append("\n**参数:**")
            for pname, pinfo in params.items():
                ptype = pinfo.get("type", "string")
                pdesc = pinfo.get("description", "")
                req_mark = " (必需)" if pname in required else ""
                lines.append(f"- `{pname}` ({ptype}){req_mark}: {pdesc}")

        lines.append("")

    return "\n".join(lines)
