# OpenWrite - AI 辅助小说创作系统

基于 Web + CLI 的多 Agent 协作系统，帮助作者创作长篇小说。

## 项目进度看板（截至 2026-02-28）

- 当前阶段：`Phase 7 完成` — Web 应用已上线，多模型池配置系统已实现
- 主流程：`Director → Writer → Reviewer → User → Stylist(可选)` (Pipeline V2)
- 风格系统：三层架构（craft/通用技法 → styles/作者风格 → novels/作品设定）已就位
- LLM 集成：多模型池 + 任务类型路由（支持 6 个预设模型，4 种任务类型）
- 现有测试：`python3 -m pytest -q`，当前 `230 passed`
- 架构说明文档：`docs/CURRENT_ARCHITECTURE.md`

### 已完成能力

- 人物双层档案：`cards/*.yaml` 简卡 + `profiles/*.md` 动态主档（自由格式）
- 人物时间线（文本优先）：自由备注时间线、可选结构化变更、摘要重建、卷快照
- 世界观图谱（基础版）：实体/关系管理、图谱摘要、冲突检查
- 伏笔 DAG：节点管理、状态统计、待回收伏笔读取、DFS 环检测
- Markdown 标记解析：`fs`、`fs-recover`、`char`、`scene`
- Agent 模拟命令（Director → Librarian → LoreChecker，Stylist 可选接入）
- LoreChecker 结构化检查（宽松/严格双模式 + 跨章节一致性）
- 跨章节检查：角色位置连续性、物品库存一致性、逾期伏笔检测
- 风格三层架构：通用技法 + 作者风格指纹 + 作品设定约束
- 风格合成器：三层文档自动合成为最终生成指令
- StyleProfile：结构化风格档案（Pydantic），自动加载到 Stylist
- Reader Agent：批量阅读原著、三层抽取（craft/style/novel）
- StyleDirector Agent：分层差异分析、偏差检测、收敛追踪
- Stylist Agent：AI 痕迹检测、节奏验证、声音一致性、分类评分
- Director Agent：上下文压缩（优先级加权预算分配）、路由、风格感知指令
- Librarian Agent：上下文感知节拍生成、结构化草稿、智能重写
- ContextCompressor：优先级加权预算分配、句边界截断、跨段去重
- Reader/Director 风格迭代循环（已完成《术师手册》3批Reader + 1周期Director）
- Web 应用：FastAPI + Jinja2 + IDE 风格深色主题
- 四级大纲层级：总纲 → 篇纲 → 节纲 → 章纲（OutlineHierarchy 模型）
- Markdown 大纲双向同步：outline.md ↔ hierarchy.yaml
- Pipeline V2：渐进式上下文压缩 + 人工审核环节
- 文本人物档案：TextCharacterProfile（纯文本描述）
- 多模型池配置：Web UI 管理 6 个预设模型（Claude/Gemini/GLM/Kimi/DeepSeek/MiniMax）
- 任务类型路由：reasoning/generation/review/style 四种任务独立配置模型链
- 小说项目初始化：Web UI 创建项目、设定、角色

- LLM 集成层：多模型池 + 任务路由器 + 自动 fallback
- Director/Librarian/LoreChecker/Stylist 均支持 opt-in LLM 模式
- LoreChecker LLM 发现默认为 advisory（警告），不阻断流程

### 尚未开始

- 世界观图谱高级功能：复杂规则推理、跨章节冲突检查、可视化
- 大纲管理前端：outline.md 编辑器页面（API 已就绪）

## 快速开始

### 方式一：Web 应用（推荐）

#### 1. 启动 Web 服务

```bash
python3 -m tools.web
# 访问 http://localhost:8000
```

#### 2. 配置 LLM 模型（可选）

访问 `/settings` 页面：

**模型池管理**：
- 系统预填充 6 个模型（Claude Opus 4.6、Gemini 3 Pro、GLM-4.7、Kimi K2.5、DeepSeek、MiniMax M2.5）
- 填写 API Key 环境变量名（如 `CLAUDE_API_KEY`）
- 可添加/删除/编辑模型

**任务路由配置**：
- **reasoning**（Director 调度决策）：推荐 Claude Opus 4.6
- **generation**（Writer 文本生成）：推荐 Kimi K2.5 或 MiniMax M2.5
- **review**（Reviewer 逻辑审查）：推荐 Claude Opus 4.6
- **style**（Stylist 风格润色）：推荐 Kimi K2.5
- 每个任务可选择多个模型作为备选链

**设置环境变量**：
```bash
export CLAUDE_API_KEY=sk-xxx
export KIMI_API_KEY=sk-yyy
export GLM_API_KEY=sk-zzz
# ... 其他模型的 API Key
```

**保存配置**：
- 点击"保存配置"按钮
- 配置持久化到 `llm_config.yaml`
- 下次打开自动加载

#### 3. 创建小说项目

访问 `/novels/new` 页面：

1. 填写基本信息：
   - 小说 ID（英文、数字、下划线，如 `my_novel`）
   - 标题、作者、目标字数
   - 核心主题、世界前提、基调、结局走向

2. 添加初始角色：
   - 点击"添加角色"
   - 填写角色名、类型（主角/重要配角/普通配角/龙套）、简介

3. 点击"创建项目"

#### 4. 开始创作

- **仪表盘** (`/`)：查看项目统计
- **人物** (`/characters`)：管理角色档案
- **伏笔** (`/foreshadowing`)：管理伏笔 DAG
- **世界观** (`/world`)：管理实体和关系
- **风格** (`/style`)：风格分析和合成
- **编辑器** (`/editor`)：章节编辑和模拟生成

---

### 方式二：CLI 命令行

#### 1. 安装依赖

```bash
pip install -r requirements.txt
```

#### 2. 初始化项目

```bash
python3 -m tools.cli init my_novel
```

#### 3. 创建人物

```bash
python3 -m tools.cli character create 李逍遥 --tier 主角
python3 -m tools.cli character create 林月如 --tier 重要配角
```

#### 4. 模拟章节生成

```bash
# 基础模拟
python3 -m tools.cli simulate chapter --id ch_003 --novel-id my_novel
# 严格 Lore 检查
python3 -m tools.cli simulate chapter --id ch_003 --novel-id my_novel --strict-lore
# 启用 LLM 模式（需要配置 llm_config.yaml + 环境变量）
python3 -m tools.cli simulate chapter --id ch_003 --novel-id my_novel --use-llm
```

#### 5. 风格系统

```bash
# 合成三层风格文档
python3 -m tools.cli style compose --novel-id 术师手册 --style-id 术师手册
# 批量阅读原著并提取风格
python3 -m tools.cli style read-batch --file path/to/text.txt --novel-id 术师手册
# 查看结构化风格档案
python3 -m tools.cli style profile --novel-id 术师手册
```

## 项目结构

```
openwrite/
├── craft/                       # 通用写作技法（跨作品通用）
│   ├── dialogue_craft.md
│   ├── information_reveal.md
│   ├── pov_techniques.md
│   ├── scene_structures.md
│   └── ...
├── styles/                      # 作者/作品风格指纹
│   └── 术师手册/
│       ├── fingerprint.md         # 风格DNA
│       ├── voice.md               # 叙述者声音
│       ├── language.md            # 语言风格
│       ├── rhythm.md              # 节奏风格
│       ├── humor.md               # 幽默体系
│       ├── dialogue_craft.md      # 对话风格
│       ├── iteration_g.md       # 迭代记录
│       └── reader_notes/          # Reader Agent 完整笔记
├── novels/                      # 作品设定（硬性约束）
│   └── 术师手册/
│       ├── characters.md          # 角色设定
│       ├── worldbuilding_rules.md # 世界观规则
│       ├── terminology.md         # 术语表
│       ├── scene_instances.md     # 名场面实例
│       ├── initial.md             # 大纲
│       └── notes.md               # 大纲注意事项
├── composed/                    # 风格合成输出
├── data/                        # 运行时数据
│   ├── novels/{novel_id}/         # 小说项目数据
│   │   ├── outline/
│   │   ├── characters/
│   │   ├── world/
│   │   ├── foreshadowing/
│   │   └── manuscript/
│   └── reference_books/           # 参考原著分块
├── tools/                       # Python 工具
│   ├── cli.py                     # CLI 入口
│   ├── models/                    # 数据模型
│   ├── parsers/                   # Markdown 解析
│   ├── agents/                    # Agent 模拟
│   ├── llm/                       # LLM 集成层（多模型池、路由、Prompt）
│   ├── queries/                   # 查询接口
│   ├── graph/                     # 图结构
│   ├── checks/                    # 逻辑检查
│   ├── utils/                     # 工具函数
│   └── web/                       # Web 应用
│       ├── templates/             # Jinja2 模板
│       └── static/                # CSS/JS 静态资源
├── docs/
│   ├── CURRENT_ARCHITECTURE.md    # 架构说明
│   ├── prompts/                   # Agent Prompt 模板
│   │   ├── PROMPT_READER.md
│   │   ├── PROMPT_DIRECTOR.md
│   │   ├── COMPOSE_RULES.md
│   │   └── task.md
│   └── archive/                   # 历史进度报告
├── tests/                       # 测试
├── llm_config.yaml              # LLM 配置（自动生成）
└── requirements.txt
```

## 三层风格架构

```
用户偏好覆盖 > 作品设定（硬性约束） > 作品风格（核心约束） > 通用技法（可选参考）
```

| 层级 | 目录 | 作用 | 约束力 |
|------|------|------|--------|
| 通用技法 | `craft/` | 场景结构、信息揭示策略、张力模型 | 可选参考 |
| 作品风格 | `styles/{作品}/` | 叙述声音、幽默体系、语言偏好、节奏 | 应当遵循 |
| 作品设定 | `novels/{作品}/` | 角色一致性、术语、世界观规则 | 不可违反 |

## Agent 架构

| Agent | 职责 | 代码量 |
|--------|------|--------|
| Director | 主控导演、上下文压缩（ContextCompressor）、路由、风格感知指令 | 231 行 |
| Librarian | 上下文感知节拍生成、结构化草稿、智能重写 | 565 行 |
| LoreChecker | 逻辑审查（关键词/场景/人物）+ 跨章节一致性（位置/库存/伏笔） | 330+ 行 |
| Stylist | AI 痕迹检测、节奏验证、声音一致性、分类评分、StyleProfile 集成 | 418 行 |
| Reader | 批量阅读原著、三层抽取（craft/style/novel）、大纲事件提取 | 668 行 |
| StyleDirector | 分层差异分析、偏差检测、收敛追踪、文档更新建议 | 705 行 |
| Simulator | 全流程编排、风格系统对接、跨章节预检、可选风格后分析 | 403 行 |

## 开发状态

- [x] Phase 0: 架构设计
- [x] Phase 1: 基础工具
- [x] Phase 2: 大纲与伏笔（含 DAG 环检测）
- [x] Phase 3: 人物与状态（双层档案、时间线、快照）
- [x] Phase 4: 世界观图谱（基础版：实体/关系/冲突检查）
- [x] Phase 5: Agent 模拟（全 Agent 实装、跨章节检查、上下文压缩、风格集成）
- [x] 风格系统：三层架构 + 合成器 + StyleProfile + Reader/Director 迭代循环
- [x] Phase 6A: Style Skill 打包（.agents/skills/）
- [x] Phase 6B: LLM 集成（多模型池、任务路由、全 Agent opt-in）
- [ ] Phase 6C: 世界图谱高级功能
- [x] Phase 7: Web 应用（FastAPI + 多模型配置 + 项目初始化）

## 许可证

MIT License
