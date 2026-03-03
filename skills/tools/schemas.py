"""Tool Schemas — 工具的 JSON Schema 定义

用于 Function Calling，让 LLM 知道有哪些工具可用。
"""

from __future__ import annotations

from typing import Any, Dict, List

# Director 可用的工具定义（OpenAI Function Calling 格式）
DIRECTOR_TOOLS: List[Dict[str, Any]] = [
    # 文件操作
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "读取项目中的文件内容。可以读取大纲、角色、草稿等文件。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件路径，相对于项目根目录。例如: data/novels/my_novel/outline/outline.md",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "写入文件内容。用于创建大纲、角色、草稿等文件。路径相对于项目根目录。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "文件路径，相对于项目根目录。例如: data/novels/my_novel/outline/hierarchy.yaml",
                    },
                    "content": {
                        "type": "string",
                        "description": "文件内容。对于 YAML 文件，使用 YAML 格式；对于 Markdown 文件，使用 Markdown 格式。",
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    # 数据查询
    {
        "type": "function",
        "function": {
            "name": "query_outline",
            "description": "查询章节大纲。获取故事结构、章节概要等信息。",
            "parameters": {
                "type": "object",
                "properties": {
                    "chapter_id": {
                        "type": "string",
                        "description": "章节ID（可选），例如 ch_001。不提供则返回整个大纲概览。",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_characters",
            "description": "查询角色信息。获取角色的属性、状态、关系等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "角色名称（可选）。不提供则返回所有角色列表。",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_world",
            "description": "查询世界观设定。获取地点、势力、物品、概念等实体信息。",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_type": {
                        "type": "string",
                        "description": "实体类型（可选）: location, faction, item, concept, event",
                    },
                    "name": {"type": "string", "description": "实体名称（可选）"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_foreshadowing",
            "description": "查询伏笔信息。获取已埋设的伏笔、状态、目标章节等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "伏笔状态（可选）: planted（已埋）, growing（待收）, recovered（已回收）",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_style",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    # 子 Agent 调用
    {
        "type": "function",
        "function": {
            "name": "call_writer",
            "description": "调用 Writer Agent 生成章节草稿。使用 Librarian 的节拍生成能力创作内容。",
            "parameters": {
                "type": "object",
                "properties": {
                    "chapter_id": {
                        "type": "string",
                        "description": "章节ID，例如 ch_001"
                    },
                    "objective": {
                        "type": "string",
                        "description": "写作目标，例如 '推进主线：主角遭遇挑战'"
                    },
                    "context_keys": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要加载的上下文，可选: outline, characters, foreshadowing, world, style"
                    }
                },
                "required": ["chapter_id", "objective"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "call_reviewer",
            "description": "调用 LoreChecker Agent 进行逻辑一致性检查。检查时间线、战力体系、角色行为等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "要检查的内容（通常是草稿文本）"
                    },
                    "check_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "检查类型，可选: timeline, power, character, all"
                    }
                },
                "required": ["content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "call_stylist",
            "description": "调用 Stylist Agent 进行风格润色。去除 AI 痕迹，调整节奏，确保声音一致性。",
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "要润色的内容"
                    },
                    "style_id": {
                        "type": "string",
                        "description": "风格ID（可选），不提供则使用默认风格"
                    }
                },
                "required": ["content"]
            }
        }
    },
    # Skill 调用
    {
        "type": "function",
        "function": {
            "name": "use_skill",
            "description": "使用指定的功能模块（Skill）。Skill 是预定义的创作能力，包含提示词和工作流。",
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "enum": ["writing", "outline", "character", "world", "foreshadowing", "style", "project"],
                        "description": "功能模块名称"
                    },
                    "action": {
                        "type": "string",
                        "description": "要执行的操作，例如: generate, create, query, analyze"
                    },
                    "parameters": {
                        "type": "object",
                        "description": "操作参数（根据不同的 skill 和 action 而不同）"
                    }
                },
                "required": ["skill_name", "action"]
            }
        }
    },
]

# 子 Agent 工具（不在 ToolExecutor 中，由 Director 直接处理）
SUB_AGENT_TOOLS = ["call_writer", "call_reviewer", "call_stylist"]

# Skill 工具
SKILL_TOOLS = ["use_skill"]

# 所有需要 Director 特殊处理的工具
DIRECTOR_SPECIAL_TOOLS = SUB_AGENT_TOOLS + SKILL_TOOLS

def get_tools_description() -> str:
    """获取工具的文本描述（用于系统提示词）。"""
    lines = ["## 可用工具\n"]
    for tool in DIRECTOR_TOOLS:
        func = tool["function"]
        lines.append(f"- **{func['name']}**: {func['description'][:60]}...")
    return "\n".join(lines)
