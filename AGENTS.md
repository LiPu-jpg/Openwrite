# OpenWrite — AI 辅助小说创作系统

## 项目概述

CLI + Web 驱动的多 Agent 协作小说创作系统。Python + Pydantic + FastAPI + Typer + Rich。

基于 **Skill 模块系统** 的智能创作助手，支持 LLM 集成（opt-in）和规则引擎双模式。

## 技术栈

- Python 3.14+
- Pydantic v2（数据模型）
- FastAPI + Jinja2（Web 应用）
- Typer（CLI 框架）
- Rich（终端输出）
- NetworkX（图结构）
- PyYAML（配置/数据）
- LiteLLM（多模型 LLM 网关，opt-in）

---

## 构建与测试命令

```bash
# 安装依赖
pip install -r requirements.txt

# 运行全部测试（384 tests expected）
python3 -m pytest -q

# 运行单个测试文件
python3 -m pytest tests/test_workflow.py -v

# 运行单个测试函数
python3 -m pytest tests/test_llm.py::test_router_get_routes -v

# 运行带覆盖率报告
python3 -m pytest --cov=tools --cov-report=term-missing

# CLI 入口
python3 -m tools.cli --help

# 启动 Web 应用
python3 -m tools.web
# 访问 http://localhost:8000
```

---

## 项目结构约定

```
OpenWrite/
├── AGENTS.md                    # AI Agent 开发指南（本文档）
├── README.md                    # 项目说明文档
├── requirements.txt             # Python 依赖
├── llm_config.yaml              # LLM 配置（自动生成，gitignored）
│
├── tools/                       # Python 源码
│   ├── cli.py                   # CLI 入口（Typer app）
│   │
│   ├── agents/                  # Agent 实现（~6600 行）
│   │   ├── director.py          # DirectorAgent（1906 行）
│   │   ├── director_v2.py       # SkillBasedDirector（1958 行）
│   │   ├── librarian.py         # LibrarianAgent（770 行）
│   │   ├── lore_checker.py      # LoreCheckerAgent（461 行）
│   │   ├── stylist.py           # StylistAgent（548 行）
│   │   ├── reader.py            # ReaderAgent（738 行）
│   │   ├── style_director.py    # StyleDirectorAgent（781 行）
│   │   ├── simulator.py         # SimulatorAgent（533 行）
│   │   ├── initializer.py       # InitializerAgent（337 行）
│   │   └── pipeline_v2.py       # PipelineV2（516 行）
│   │
│   ├── models/                  # Pydantic 数据模型
│   │   ├── outline.py           # OutlineHierarchy, OutlineNode
│   │   ├── character.py         # CharacterCard, CharacterProfile
│   │   ├── style.py             # StyleProfile, VoicePattern
│   │   ├── context_package.py   # GenerationContext
│   │   ├── workflow.py          # WorkflowDefinition, WorkflowPhase
│   │   └── intent.py            # IntentDecision, DirectorResponse, ConversationSession
│   │
│   ├── llm/                     # LLM 集成层（~1500 行）
│   │   ├── client.py            # LLMClient（331 行）
│   │   ├── config.py            # LLMConfig（109 行）
│   │   ├── router.py            # ModelRouter（100 行）
│   │   ├── tool_schema.py       # ToolSchema（495 行）
│   │   └── prompts.py           # Prompts（475 行）
│   │
│   ├── utils/                   # 工具函数
│   │   ├── style_composer.py    # StyleComposer
│   │   ├── compressor.py        # ProgressiveCompressor
│   │   └── outline_serializer.py # OutlineMdSerializer
│   │
│   ├── parsers/                 # Markdown 解析器
│   │   └── outline_md_parser.py # OutlineMdParser
│   │
│   ├── graph/                   # 图结构
│   │   ├── foreshadowing_dag.py # ForeshadowingDAG
│   │   └── world_graph.py       # WorldGraph
│   │
│   ├── checks/                  # 逻辑检查
│   │   └── lore_checks.py       # LoreChecker 规则
│   │
│   ├── queries/                 # 查询接口
│   │   └── queries.py           # 数据查询 API
│   │
│   └── web/                     # Web 应用
│       ├── __init__.py          # FastAPI app + 路由（67+ API）
│       ├── templates/           # Jinja2 模板（11 个）
│       └── static/              # CSS/JS 静态资源
│
├── skills/                      # Skill 模块系统
│   ├── skill.py                 # Skill 数据模型
│   ├── skill_registry.py        # 功能注册表
│   ├── skill_loader.py          # 文件系统加载器
│   ├── tools/executor.py        # 统一工具执行器（13 个工具）
│   ├── outline/                 # 大纲功能模块
│   ├── writing/                 # 写作功能模块
│   ├── style/                   # 风格功能模块
│   ├── character/               # 角色功能模块
│   ├── foreshadowing/           # 伏笔功能模块
│   ├── world/                   # 世界观功能模块
│   └── project/                 # 项目管理功能模块
│
├── craft/                       # 通用写作技法（跨作品）
├── styles/{作品名}/              # 作者/作品风格指纹
├── novels/{作品名}/              # 作品设定（硬性约束）
├── data/novels/{id}/            # 运行时数据
│   ├── outline/
│   ├── characters/
│   ├── world/
│   ├── foreshadowing/
│   └── manuscript/
├── data/sessions/               # 会话持久化数据
├── docs/                        # 文档
└── tests/                       # pytest 测试（16 文件，384 测试）
```

---

## 编码规范

### 类型注解
- 所有函数签名**必须**有 type hints
- 使用 `Optional[T]` 而非 `T | None`（兼容 Python 3.9）
- 使用 `list[T]` 而非 `List[T]`（Python 3.9+）

### 数据模型
- 使用 Pydantic `BaseModel`，不用 `dataclass`
- 字段必须有类型注解和默认值或 `Field()`
- 使用 `Field(default_factory=list)` 处理可变默认值

### 错误处理
- **禁止**空 catch 块：`except Exception: pass`
- **禁止**类型抑制：`# type: ignore`
- **禁止**任意类型：`as any`
- 使用具体异常类型，提供有意义的错误消息

### 导入顺序
```python
# 1. 标准库
from pathlib import Path
from typing import Dict, List, Optional

# 2. 第三方库
import yaml
from pydantic import BaseModel, Field

# 3. 本地模块
from tools.models.outline import OutlineHierarchy
```

### 文档字符串
- 中文，Google style
- 模块级文档在文件开头
- 类和公共方法必须有 docstring

```python
def generate_chapter(self, chapter_id: str, context: Dict[str, str]) -> str:
    """生成章节草稿。
    
    Args:
        chapter_id: 章节标识符
        context: 上下文信息字典
    
    Returns:
        生成的章节文本
    """
```

### 命名约定
- 文件名：snake_case（`outline_md_parser.py`）
- 类名：PascalCase（`OutlineHierarchy`）
- 函数/方法：snake_case（`parse_outline_md`）
- 常量：UPPER_SNAKE_CASE（`RECENT_TEXT_MAX = 1000`）
- 私有方法：_leading_underscore（`_extract_yaml_block`）

---

## Agent 架构

### 协作关系图

```
用户请求
    │
    ▼
SkillBasedDirector ──► 意图识别 + Skill 匹配
    │
    ├─ [有工作流]
    │   └─ ToolExecutor.execute() ──► 统一工具调用
    │
    └─ [无工作流]
        └─ LLM 生成响应 / 通用对话
```

### Pipeline V2 流程

```
Director (上下文组装)
    ↓
Writer (章节生成)
    ↓
Reviewer (逻辑检查，只读)
    ↓
User Review (人工审核确认) ← 关键环节！
    ↓
Stylist (风格润色，可选)
```

### Agent 职责

| Agent | 职责 | 文件 | 行数 |
|-------|------|------|------|
| DirectorAgent | 主控导演、上下文压缩、路由、风格感知指令 | `director.py` | 1906 |
| SkillBasedDirector | 基于 Skill 的主控 Agent（新架构） | `director_v2.py` | 1958 |
| LibrarianAgent | 上下文感知节拍生成、结构化草稿、智能重写 | `librarian.py` | 770 |
| LoreCheckerAgent | 逻辑审查 + 跨章节一致性 | `lore_checker.py` | 461 |
| StylistAgent | AI 痕迹检测、节奏验证、声音一致性 | `stylist.py` | 548 |
| ReaderAgent | 批量阅读原著、三层抽取 | `reader.py` | 738 |
| StyleDirectorAgent | 分层差异分析、偏差检测、收敛追踪 | `style_director.py` | 781 |
| SimulatorAgent | 全流程编排、风格系统对接 | `simulator.py` | 533 |
| InitializerAgent | 项目初始化 | `initializer.py` | 337 |
| PipelineV2 | 带人工审核的完整流程 | `pipeline_v2.py` | 516 |

---

## Skill 模块系统

### 架构说明

Skill 系统实现了**动态功能发现**，替代硬编码的工具链：

```
skills/
├── skill.py              # Skill 数据模型
├── skill_registry.py     # 功能注册表（触发器匹配、优先级管理）
├── skill_loader.py       # 文件系统加载器
├── tools/executor.py     # 统一工具执行器（13个工具）
├── outline/              # 大纲功能模块
├── writing/              # 写作功能模块
├── style/                # 风格功能模块
├── character/            # 角色功能模块
├── foreshadowing/        # 伏笔功能模块
├── world/                # 世界观功能模块
└── project/              # 项目管理功能模块
```

### 核心能力

- `SkillRegistry.match_trigger(text)` — 动态意图匹配
- `ToolExecutor.execute(tool_name, args)` — 统一工具调用接口
- 优先级覆盖机制：project > user > builtin

### 7 个功能模块

| 模块 | 功能 | 工具 |
|------|------|------|
| outline | 大纲管理 | parser, serializer, validator |
| writing | 章节写作 | beat_generator, draft_generator |
| style | 风格分析 | composer, analyzer |
| character | 角色管理 | CRUD + 时间线 |
| foreshadowing | 伏笔管理 | DAG 操作 |
| world | 世界观 | 实体/关系管理 |
| project | 项目管理 | 初始化、配置 |

---

## Web 应用路由

### 页面路由（11 模板）

| 路由 | 功能 | 模板 |
|------|------|------|
| `/` | 仪表盘 | `dashboard.html` |
| `/chat` | 统一对话界面（支持会话历史管理） | `chat.html` |
| `/novels/new` | 新建项目 | `novel_new.html` |
| `/outline` | 大纲编辑器 | `outline_editor.html` |
| `/editor` | 章节编辑器 + AI 助手 | `editor.html` |
| `/characters` | 人物管理 | `characters.html` |
| `/world` | 世界观图谱 | `world.html` |
| `/foreshadowing` | 伏笔 DAG | `foreshadowing.html` |
| `/style` | 风格分析 | `style.html` |
| `/timeline` | 叙事时间线 | `timeline.html` |
| `/settings` | LLM 配置 | `settings.html` |

### API 端点（67+）

- **Workflow API** (5): 工作流列表、详情、启动、对话、注册表摘要
- **Pipeline V2 API** (4): 启动、状态、SSE 流、批准
- **Session API** (4): 会话列表、详情、删除、新建
- **Outline API** (15): 完整的 CRUD + 导入导出
- **Character API** (10): CRUD + 时间线 + 快照
- **World API** (8): 实体、关系、冲突检查
- **Foreshadowing API** (8): DAG 管理、状态统计
- **Style API** (6): 合成、分析、档案
- **Settings API** (5): LLM 配置管理

---

## 会话管理系统

### 会话生命周期

```
用户发送消息
    │
    ▼
process_request() 
    │
    ├─ 获取/创建 session
    ├─ 添加用户消息 (role: user)
    ├─ 意图识别 + 工作流执行
    ├─ 添加 agent 回复 (role: assistant)
    │
    └─ 检查是否需要保存
        │
        ├─ message_history >= 2 → 保存到 data/sessions/{id}.json
        └─ message_history < 2 → 仅内存，不持久化
```

### 会话数据模型

```python
class ConversationSession(BaseModel):
    session_id: str
    novel_id: Optional[str] = None
    context_data: Dict[str, Any] = {}
    workflow_context: Dict[str, Any] = {}
    message_history: List[Dict[str, str]] = []
    max_history: int = 20
    created_at: str
    updated_at: str
```

---

## 三层风格架构

优先级：`用户偏好覆盖 > 作品设定（硬性约束）> 作品风格（核心约束）> 通用技法（可选参考）`

| 层级 | 目录 | 约束力 | 说明 |
|------|------|--------|------|
| 通用技法 | `craft/` | 可选参考 | 场景结构、信息揭示策略、张力模型 |
| 作品风格 | `styles/{作品}/` | 应当遵循 | 叙述声音、幽默体系、语言偏好、节奏 |
| 作品设定 | `novels/{作品}/` | 不可违反 | 角色一致性、术语、世界观规则 |

---

## LLM 配置

### 多模型池配置（`llm_config.yaml`）

```yaml
enabled: true
models:
  Claude-Opus-4.6:
    model: claude-opus-4-6
    api_base: https://aws.d68.fun/v1/messages
    api_key_env: CLAUDE_API_KEY
    max_tokens: 80000
  Kimi-K2.5:
    model: kimi-k2.5
    api_base: https://api.moonshot.cn/v1/chat/completions
    api_key_env: KIMI_API_KEY
    max_tokens: 16000

routes:
  reasoning:    # Director 决策
    models: [Claude-Opus-4.6, GLM-4.7, DeepSeek]
    primary_index: 0
  generation:   # Writer 生成
    models: [Kimi-K2.5, MiniMax-M2.5, ChatGPT-5.3]
    primary_index: 0
```

### 环境变量设置

```bash
export KIMI_API_KEY=sk-xxx
export CLAUDE_API_KEY=sk-xxx
export GLM_API_KEY=sk-xxx
export DEEPSEEK_API_KEY=sk-xxx
export MINIMAX_API_KEY=sk-xxx
```

---

## 测试覆盖

### 测试统计

| 指标 | 数值 |
|------|------|
| 测试总数 | 384 |
| 测试文件 | 16 |
| Skip/xfail | 0 |

### 测试分布

| 类别 | 测试数 | 文件 |
|------|--------|------|
| Phase 7 功能 | 59 | `test_phase7.py` |
| 工作流集成 | 38 | `test_workflow.py` |
| Director V2 | 35 | `test_director_v2.py` |
| 世界图谱高级 | 43 | `test_world_advanced.py` |
| 叙事生成 | 27 | `test_narrative.py` |
| Phase 4-6 | 63 | 多文件 |
| 工具测试 | 54 | 写作/大纲/风格 |
| 集成测试 | 59 | LLM/Web/CLI |

---

## 注意事项

- 修改 Agent 后**必须**运行 `python3 -m pytest -q` 确认 384 tests 全部通过
- 不要删除或修改 `craft/`、`styles/`、`novels/` 下的 `.md` 数据文件
- CLI 命令注册在 `tools/cli.py` 的 Typer sub-app 中
- Web API 端点在 `tools/web/__init__.py`
- LLM 集成采用 Strangler Fig 模式：所有 Agent 保留规则引擎 fallback
- API key 通过环境变量注入，不存储在配置文件中
- `.env` 文件已添加到 `.gitignore`，不会泄露 API keys

---

## 项目状态

- **当前阶段**: Phase 7+ 完成 + Web 对话功能优化
- **生产级完备性**: 93%
- **主流程**: `Director → Writer → Reviewer → User → Stylist(可选)` (Pipeline V2)
- **风格系统**: 三层架构已就位
- **LLM 集成**: 多模型池 + 任务类型路由
- **现有测试**: 384 passed，0 skipped

---

*最后更新: 2026-03-02（第五期报告）*
