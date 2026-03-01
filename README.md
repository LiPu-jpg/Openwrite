# OpenWrite - AI 辅助小说创作系统

基于 Web + CLI 的多 Agent 协作系统，帮助作者创作长篇小说。

## 项目进度看板（截至 2026-03-02）

- **当前阶段**: `Phase 7 完成 + Skill 架构重构完成`
- **生产级完备性**: 92%
- **主流程**: `Director → Writer → Reviewer → User → Stylist(可选)` (Pipeline V2)
- **风格系统**: 三层架构（craft/通用技法 → styles/作者风格 → novels/作品设定）已就位
- **LLM 集成**: 多模型池 + 任务类型路由（支持 6 个预设模型，4 种任务类型）
- **现有测试**: `python3 -m pytest -q`，当前 **378 passed**，0 skipped
- **架构说明文档**: `docs/CURRENT_ARCHITECTURE.md`、`AGENTS.md`

### 已完成能力

**核心架构**：
- ✅ Skill 模块系统 — 7 个功能模块（outline/writing/style/character/foreshadowing/world/project）
- ✅ SkillBasedDirector — 基于 Skill 的主控 Agent，动态意图匹配 + 工作流驱动
- ✅ Pipeline V2 — 渐进式上下文压缩 + 人工审核环节
- ✅ 统一对话界面 — `/chat` 页面，支持工作流对话
- ✅ LLM 集成层 — 多模型池 + 任务路由器 + 自动 fallback
- ✅ Tool Schema 生成 — OpenAI-compatible schemas

**Agent 实现**（10 个 Agent，~8000 行代码）：
- ✅ DirectorAgent — 主控导演、上下文压缩、路由、风格感知指令
- ✅ SkillBasedDirector — 基于 Skill 的新架构主控
- ✅ LibrarianAgent — 上下文感知节拍生成、结构化草稿、智能重写
- ✅ LoreCheckerAgent — 逻辑审查（宽松/严格双模式）+ 跨章节一致性
- ✅ StylistAgent — AI 痕迹检测、节奏验证、声音一致性
- ✅ ReaderAgent — 批量阅读原著、三层抽取（craft/style/novel）
- ✅ StyleDirectorAgent — 分层差异分析、偏差检测、收敛追踪
- ✅ SimulatorAgent — 全流程编排、风格系统对接
- ✅ InitializerAgent — 项目初始化
- ✅ PipelineV2 — 带人工审核的完整流程

**数据结构**：
- ✅ 人物双层档案：`cards/*.yaml` 简卡 + `profiles/*.md` 动态主档
- ✅ 人物时间线（文本优先）：自由备注时间线、可选结构化变更
- ✅ 世界观图谱（基础版）：实体/关系管理、图谱摘要、冲突检查
- ✅ 伏笔 DAG：节点管理、状态统计、待回收伏笔读取、DFS 环检测
- ✅ 四级大纲层级：总纲 → 篇纲 → 节纲 → 章纲
- ✅ Markdown 大纲双向同步：outline.md ↔ hierarchy.yaml

**风格系统**：
- ✅ 风格三层架构：通用技法 + 作者风格指纹 + 作品设定约束
- ✅ 风格合成器：三层文档自动合成为最终生成指令
- ✅ StyleProfile：结构化风格档案（Pydantic）
- ✅ Reader/Director 风格迭代循环

**Web 应用**（11 模板，67+ API）：
- ✅ 统一对话界面 `/chat`
- ✅ 章节编辑器 `/editor` + AI 助手
- ✅ LLM 配置 `/settings`
- ✅ 人物管理 `/characters`
- ✅ 伏笔 DAG `/foreshadowing`
- ✅ 世界观图谱 `/world`
- ✅ 风格分析 `/style`
- ✅ 新建项目 `/novels/new`

### 待改进项

| 优先级 | 问题 | 计划 |
|--------|------|------|
| 🔴 高 | `/novels/new` 路由缺失 | Phase 8 修复 |
| 🟡 中 | 旧 `simulator.py` 待废弃 | 迁移到 Pipeline V2 |
| 🟡 中 | LLM 无流式响应支持 | Phase 8 添加 |
| 🟡 中 | 世界图谱可视化未完成 | Phase 9 规划 |
| 🟢 低 | Token 使用统计缺失 | Phase 9 规划 |

---

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
export DEEPSEEK_API_KEY=sk-aaa
export MINIMAX_API_KEY=sk-bbb
```

**保存配置**：
- 点击"保存配置"按钮
- 配置持久化到 `llm_config.yaml`
- 下次打开自动加载

#### 3. 统一对话界面

访问 `/chat` 页面：

- 支持自然语言输入
- 自动意图识别 + Skill 匹配
- 工作流驱动执行
- 支持大纲管理、章节写作、风格分析等

#### 4. 创建小说项目

访问 `/novels/new` 页面：

1. 填写基本信息：小说 ID、标题、作者、目标字数、核心主题
2. 添加初始角色：角色名、类型、简介
3. 点击"创建项目"

#### 5. 各功能页面

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

---

## 项目结构

```
OpenWrite/
├── AGENTS.md                    # AI Agent 开发指南
├── README.md                    # 项目说明（本文件）
├── requirements.txt             # Python 依赖
├── llm_config.yaml              # LLM 配置（自动生成）
│
├── tools/                       # Python 源码
│   ├── cli.py                   # CLI 入口
│   ├── agents/                  # Agent 实现（~8000 行）
│   │   ├── director.py          # DirectorAgent（1906 行）
│   │   ├── director_v2.py       # SkillBasedDirector（1142 行）
│   │   ├── librarian.py         # LibrarianAgent（770 行）
│   │   ├── lore_checker.py      # LoreCheckerAgent（461 行）
│   │   ├── stylist.py           # StylistAgent（548 行）
│   │   ├── reader.py            # ReaderAgent（738 行）
│   │   ├── style_director.py    # StyleDirectorAgent（781 行）
│   │   ├── simulator.py         # SimulatorAgent（533 行）
│   │   ├── initializer.py       # InitializerAgent（337 行）
│   │   └── pipeline_v2.py       # PipelineV2（516 行）
│   ├── models/                  # Pydantic 数据模型
│   ├── llm/                     # LLM 集成层（~1500 行）
│   ├── utils/                   # 工具函数
│   ├── parsers/                 # Markdown 解析器
│   ├── graph/                   # 图结构
│   ├── checks/                  # 逻辑检查
│   ├── queries/                 # 查询接口
│   └── web/                     # Web 应用
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
├── craft/                       # 通用写作技法（跨作品通用）
│   ├── dialogue_craft.md
│   ├── information_reveal.md
│   ├── language_craft.md
│   ├── pov_techniques.md
│   ├── rhythm_craft.md
│   ├── scene_structures.md
│   ├── tension_patterns.md
│   └── humanization.yaml
│
├── styles/                      # 作者/作品风格指纹
│   └── 术师手册/
│       ├── fingerprint.md       # 风格 DNA
│       ├── voice.md             # 叙述者声音
│       ├── language.md          # 语言风格
│       ├── rhythm.md            # 节奏风格
│       ├── humor.md             # 幽默体系
│       ├── dialogue_craft.md    # 对话风格
│       ├── iteration_log.md     # 迭代记录
│       └── reader_notes/        # Reader Agent 完整笔记
│
├── novels/                      # 作品设定（硬性约束）
│   └── 术师手册/
│       ├── characters.md        # 角色设定
│       ├── worldbuilding_rules.md # 世界观规则
│       ├── terminology.md       # 术语表
│       ├── scene_instances.md   # 名场面实例
│       ├── initial.md           # 大纲
│       └── notes.md             # 大纲注意事项
│
├── data/                        # 运行时数据
│   ├── novels/{novel_id}/       # 小说项目数据
│   │   ├── outline/
│   │   ├── characters/
│   │   ├── world/
│   │   ├── foreshadowing/
│   │   └── manuscript/
│   ├── reference_books/         # 参考原著分块
│   └── sessions/                # 会话数据
│
├── docs/                        # 文档
│   ├── CURRENT_ARCHITECTURE.md  # 架构说明
│   ├── ARCHITECTURE_REFACTOR.md # 重构规划
│   ├── prompts/                 # Agent Prompt 模板
│   ├── workflows/               # 工作流文档
│   └── archive/                 # 历史进度报告
│
├── tests/                       # pytest 测试（16 文件，378 测试）
│
└── 报告文件
    ├── 第一期报告.md
    ├── 第二期报告.md
    ├── 第三期报告.md
    └── 第四期报告.md
```

---

## 三层风格架构

```
用户偏好覆盖 > 作品设定（硬性约束） > 作品风格（核心约束） > 通用技法（可选参考）
```

| 层级 | 目录 | 作用 | 约束力 |
|------|------|------|--------|
| 通用技法 | `craft/` | 场景结构、信息揭示策略、张力模型 | 可选参考 |
| 作品风格 | `styles/{作品}/` | 叙述声音、幽默体系、语言偏好、节奏 | 应当遵循 |
| 作品设定 | `novels/{作品}/` | 角色一致性、术语、世界观规则 | 不可违反 |

---

## Agent 架构

| Agent | 职责 | 代码量 |
|--------|------|--------|
| DirectorAgent | 主控导演、上下文压缩、路由、风格感知指令 | 1906 行 |
| SkillBasedDirector | 基于 Skill 的主控 Agent（新架构） | 1142 行 |
| LibrarianAgent | 上下文感知节拍生成、结构化草稿、智能重写 | 770 行 |
| LoreCheckerAgent | 逻辑审查 + 跨章节一致性 | 461 行 |
| StylistAgent | AI 痕迹检测、节奏验证、声音一致性 | 548 行 |
| ReaderAgent | 批量阅读原著、三层抽取 | 738 行 |
| StyleDirectorAgent | 分层差异分析、偏差检测、收敛追踪 | 781 行 |
| SimulatorAgent | 全流程编排、风格系统对接 | 533 行 |
| InitializerAgent | 项目初始化 | 337 行 |
| PipelineV2 | 带人工审核的完整流程 | 516 行 |

---

## Skill 模块系统

7 个功能模块，实现动态功能发现：

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

## 开发状态

- [x] Phase 0: 架构设计
- [x] Phase 1: 基础工具
- [x] Phase 2: 大纲与伏笔（含 DAG 环检测）
- [x] Phase 3: 人物与状态（双层档案、时间线、快照）
- [x] Phase 4: 世界观图谱（基础版）
- [x] Phase 5: Agent 模拟（全 Agent 实装）
- [x] Phase 6A: Style Skill 打包
- [x] Phase 6B: LLM 集成（多模型池、任务路由）
- [x] Phase 7: Web 应用（FastAPI + 多模型配置）
- [x] Phase 7+: Skill 架构重构（SkillBasedDirector + 统一对话界面）
- [ ] Phase 8: 稳定化与优化（流式响应、性能优化）
- [ ] Phase 9: 高级功能（世界图谱可视化、插件系统）

---

## 开发命令速查

```bash
# 运行测试
python3 -m pytest -q                    # 全部测试（378 expected）
python3 -m pytest tests/test_workflow.py -v  # 单文件
python3 -m pytest --cov=tools           # 带覆盖率

# 启动服务
python3 -m tools.web                    # Web 应用（http://localhost:8000）
python3 -m tools.cli --help             # CLI 帮助

# 项目管理
python3 -m tools.cli init my_novel      # 初始化项目
python3 -m tools.cli character create 姓名 --tier 主角  # 创建人物

# 模拟生成
python3 -m tools.cli simulate chapter --id ch_001 --novel-id my_novel

# 风格系统
python3 -m tools.cli style compose --novel-id 术师手册 --style-id 术师手册
```

---

## 许可证

MIT License

---

*最后更新: 2026-03-02（第四期报告）*
