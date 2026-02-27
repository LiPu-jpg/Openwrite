---
name: openwrite-overview
description: >
  OpenWrite 项目全局概览。当需要理解项目整体架构、Agent 管线流程、
  数据模型关系、CLI 命令体系，或进行跨模块修改时加载此 skill。
  触发词：architecture, 架构, pipeline, 管线, agent, CLI, simulate,
  模拟, chapter, 章节, lore, 伏笔, foreshadowing, character, 人物
globs:
  - "tools/**"
  - "tests/**"
  - "data/**"
  - "AGENTS.md"
  - "PLAN.md"
---

# OpenWrite 项目全局概览

## 1. 项目定位

CLI 驱动的多 Agent 协作小说创作系统。核心能力：

- 人物管理（双层档案：简卡 + 动态主档）
- 世界观图谱（实体/关系/冲突检查）
- 大纲与伏笔（DAG 管理 + 环检测）
- 章节模拟（多 Agent 管线生成）
- 风格系统（三层架构 + 迭代收敛）

技术栈：Python 3.10+ / Pydantic v2 / Typer / Rich / NetworkX / PyYAML / LiteLLM（opt-in）

## 2. Agent 管线

```
Director.plan(chapter_id, novel_id, style_id?)
  │
  ├─ 上下文压缩（ContextCompressor）
  ├─ 路由决策（strict_lore? style_aware?）
  ├─ 生成 generation_instructions
  │
  ▼
Librarian.generate_chapter(instructions)
  │
  ├─ 节拍生成（beat generation）
  ├─ 结构化草稿（structured draft）
  │
  ▼
LoreChecker.check_draft(draft, novel_id)
  │
  ├─ 单章检查（关键词/场景/人物一致性）
  ├─ 跨章节检查（位置/库存/伏笔连续性）
  ├─ 宽松模式 / 严格模式
  │
  ▼ (如果 lore 失败 → 重写循环)
  │
  ▼ [可选]
Stylist.polish(draft, style_profile?)
  │
  ├─ AI 痕迹检测（50+ banned phrases）
  ├─ 节奏验证（段落长度变化率）
  ├─ 声音一致性检查
  ├─ 分类评分（0.0~1.0）
  │
  ▼ [可选，需 --style-analysis]
Reader.read_batch() → StyleDirector.analyze()
  │
  ├─ 批量阅读 + 三层抽取
  ├─ 分层差异分析
  ├─ 收敛判定
  └─ 文档更新建议
```

### Agent 职责速查

| Agent | 文件 | 核心方法 | 行数 |
|-------|------|----------|------|
| Director | `tools/agents/director.py` | `plan()` | 365 |
| Librarian | `tools/agents/librarian.py` | `generate_chapter()` | 722 |
| LoreChecker | `tools/agents/lore_checker.py` | `check_draft()`, `check_cross_chapter()` | 420+ |
| Stylist | `tools/agents/stylist.py` | `check_style()`, `polish()` | 500+ |
| Reader | `tools/agents/reader.py` | `read_batch()` | 668 |
| StyleDirector | `tools/agents/style_director.py` | `analyze()` | 705 |
| Simulator | `tools/agents/simulator.py` | `simulate_chapter()` | 420+ |
| LLMClient | `tools/llm/client.py` | `complete()`, `complete_with_fallback()` | 194 |
| ModelRouter | `tools/llm/router.py` | `get_routes()` | 97 |
| PromptBuilder | `tools/llm/prompts.py` | `director_plan()`, `librarian_generate()` 等 | 241 |

## 3. 数据模型

### Pydantic 模型位置

| 模型 | 文件 | 用途 |
|------|------|------|
| `StyleProfile` | `tools/models/style.py` | 风格档案（质量指标、禁用短语、声音） |
| `ForeshadowingEdge` | `tools/models/foreshadowing.py` | 伏笔节点（DAG 边） |

### 运行时数据结构

```
data/novels/{novel_id}/
├── outline/          # 大纲章节（YAML）
├── characters/
│   ├── cards/        # 简卡（YAML）
│   └── profiles/     # 动态主档（Markdown）
├── world/            # 世界观实体/关系
├── foreshadowing/    # 伏笔 DAG 数据
└── manuscript/       # 生成的章节草稿
```

## 4. CLI 命令体系

### 主命令

```bash
python3 -m tools.cli --help
```

### 子命令组

| 子命令组 | 前缀 | 功能 |
|----------|------|------|
| 通用 | `init` | 初始化小说项目 |
| 人物 | `character` | create, mutate, snapshot, query, profile |
| 世界观 | `world` | entity-add, relation-add, list, check |
| 大纲 | `outline` | init, create, list |
| 伏笔 | `foreshadowing` | add, list, check, statistics |
| 模拟 | `simulate` | chapter（主入口） |
| 风格 | `style` | compose, list, read-batch, iterate, profile |

### 常用命令示例

```bash
# 初始化
python3 -m tools.cli init my_novel

# 人物
python3 -m tools.cli character create 李逍遥 --tier 主角
python3 -m tools.cli character query 李逍遥 --novel-id my_novel

# 模拟章节
python3 -m tools.cli simulate chapter --id ch_003 --novel-id my_novel
python3 -m tools.cli simulate chapter --id ch_003 --novel-id my_novel \
  --strict-lore --style-id 术师手册 --style-analysis

# 风格（详见 style-system skill）
python3 -m tools.cli style compose --novel-id 术师手册
```

## 5. 模块依赖关系

```
cli.py
├── agents/simulator.py      ← 编排入口（传递 llm_client/router 给各 Agent）
│   ├── agents/director.py   ← 路由 + 压缩（opt-in LLM 决策）
│   │   └── utils/context_compressor.py
│   ├── agents/librarian.py  ← 生成（节拍规则 + LLM 扩写）
│   ├── agents/lore_checker.py ← 审查（规则 + LLM 语义审查）
│   ├── agents/stylist.py    ← 润色（规则 + LLM 润色）
│   │   └── models/style.py  ← StyleProfile
│   ├── agents/reader.py     ← 阅读
│   └── agents/style_director.py ← 分析
├── llm/                     ← LLM 集成层
│   ├── client.py            ← LiteLLM 封装 + 重试/fallback
│   ├── router.py            ← 任务类型路由器
│   ├── config.py            ← 配置模型 + YAML 加载
│   └── prompts.py           ← Agent Prompt 模板
├── utils/style_composer.py   ← 合成
├── graph/foreshadowing_dag.py ← 伏笔 DAG
├── checks/foreshadowing_checker.py
├── parsers/markdown_parser.py
├── queries/outline_query.py
├── queries/character_query.py
├── character_state_manager.py
└── world_graph_manager.py
├── agents/simulator.py      ← 编排入口
│   ├── agents/director.py   ← 路由 + 压缩
│   │   └── utils/context_compressor.py
│   ├── agents/librarian.py  ← 生成
│   ├── agents/lore_checker.py ← 审查
│   ├── agents/stylist.py    ← 润色
│   │   └── models/style.py  ← StyleProfile
│   ├── agents/reader.py     ← 阅读
│   └── agents/style_director.py ← 分析
├── utils/style_composer.py   ← 合成
├── graph/foreshadowing_dag.py ← 伏笔 DAG
├── checks/foreshadowing_checker.py
├── parsers/markdown_parser.py
├── queries/outline_query.py
├── queries/character_query.py
├── character_state_manager.py
└── world_graph_manager.py
```

## 6. 测试结构

```bash
tests/
├── test_all.py              # 12 tests — 基础功能
├── test_style_system.py     # 11 tests — 风格合成 + Stylist
├── test_phase4.py           # 24 tests — Reader + StyleDirector + Librarian
├── test_phase5.py           # 19 tests — 迭代循环 + 跨章节 + 压缩
└── test_llm.py              # 18 tests — LLM 配置/路由/Client/Agent 分支
# 运行
python3 -m pytest -q          # 84 tests expected
```

## 7. 开发注意事项

### 必须遵守

- 所有函数签名必须有 type hints
- 数据模型用 Pydantic BaseModel，不用 dataclass
- 不允许空 catch 块，不允许 `# type: ignore`
- 导入顺序：stdlib → third-party → local
- 文档字符串：中文，Google style
- 修改后运行 `python3 -m pytest -q` 确认 84 tests 通过

### 当前状态

- 所有 Agent 支持 opt-in LLM 模式（Strangler Fig 模式）
- LLM 调用失败时自动 fallback 到规则引擎
- Phase 1-5 + 6A + 6B 全部完成
- 待推进：世界图谱高级功能、Web 应用

### 跨模块修改检查清单

1. 修改 Agent → 检查 `simulator.py` 是否需要同步更新
2. 修改数据模型 → 检查所有引用该模型的 Agent
3. 修改 CLI → 确认 Typer sub-app 注册正确
4. 新增文件 → 更新 `__init__.py` 导出
5. 修改风格系统 → 同时参考 `style-system` skill
