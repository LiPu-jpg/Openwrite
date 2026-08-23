# dsh-novel 架构设计

把 OpenWrite 的完整小说创作能力接入 DeepSeek Harness (dsh) 的 agent 运行时：
**OpenWrite 提供无界面的小说领域后端，dsh 负责唯一的 agent 编排、交互壳与创作工作台。**

## 总体架构

```
┌─────────────────────────────┐      ┌──────────────────────────────┐
│ dsh web (127.0.0.1:3080)    │      │ OpenWrite Studio             │
│ agent 控制台 + 创作工作台    │      │ (127.0.0.1:4567)             │
│                             │      │                              │
│  goethe 预设 ──┐            │      │  无界面领域 HTTP 服务         │
│  dante 预设 ───┤  会话      │      │  存储 / 校验 / 流水线         │
│  (persona +   │            │      │                              │
│   技能 + 工具) │            │      │  HTTP 动作面 (POST /api/*)   │
└──────┬────────┼────────────┘      └──────────────┬───────────────┘
       │        │ ctx.tools                        │ X-OpenWrite-Studio: 1
       │        ▼                                  ▼
       │  ┌────────────────────────────────────────────────┐
       └──│ openwrite-bridge 插件 (TS, defineTool × N)      │
          │  novel_* 工具 → fetch → Studio HTTP API         │
          └──────────────────────┬─────────────────────────┘
                                 ▼
                  NovelApplicationService (OpenWrite 唯一应用边界)
                                 ▼
                  data/novels/{id}/{src,data}  (单一事实来源)
```

职责划分原则：

- **领域逻辑零搬迁**：大纲、写作、评审、伏笔、风格等全部仍由 OpenWrite 实现，
  dsh 侧只有薄桥接。OpenWrite 升级后桥接只需跟进 HTTP 契约。
- **agent 唯一归属 dsh**：persona、技能目录、子代理委派、会话持久化、长上下文压缩
  全部使用 dsh 的机制。OpenWrite 自带的 ReAct agent 层（Goethe/Dante Python 循环、
  /api/chat、Studio 助手面板）不参与本方案——草案生成等创作推理由 dsh agent 自身完成，
  OpenWrite 只暴露确定性领域服务（存储、校验、上下文装配、章节流水线、评审）。
- **唯一前端**：dsh web 同时承担对话、编排和创作编辑。Studio UI 不进入默认工作流，
  只保留为外部高级维护出口；所有读写仍经 OpenWrite 修订门控作用于同一事实来源。

## 功能迁移对照（Studio 界面 → dsh 原生机制）

原生融入原则：能力本身成为 dsh 的一等公民（agent 工具 / 原生视图 / 工具卡片），
默认工作流不嵌入 Studio；能力按写作者工作流进入 dsh 原生视图。

| OpenWrite Studio 界面 | dsh 原生形态 | 状态 |
|---|---|---|
| AI 协作（Goethe/Dante 聊天） | goethe/dante agent 预设 + dsh 会话 | ✅ |
| 大纲视图 | 「大纲」原生视图 tab（studio-panel） | ✅ |
| 人物/世界观资产看板 | 「资产」原生视图 tab + `novel_asset_*` 工具 | ✅ |
| 审稿报告 | `novel_review_chapter` 自定义工具卡片 + 评审工具 | ✅ |
| AI 协作 → 任务中心 | 「任务」原生视图 tab + `novel_tasks_*` / `novel_multi_write` 工具 | ✅ |
| 连续性（伏笔 DAG / 关系图谱） | 「图谱」原生视图 tab + `novel_continuity` 工具 | ✅ |
| 资料库（参考作品） | 「资产」tab 资料库分组 + `novel_reference_library_action` 工具 | ✅ |
| 修订提案 | `novel_revisions_*` 工具（应用/驳回/重生成） | ✅ |
| 高级工具（风格/参考库/规则/迁移等） | `novel_source_action` / `novel_reference_library_action` / `novel_rule_action` 等 | ✅ |
| 深度研究 | `novel_research_*` 工具 | ✅ |
| 连续性检查 | `novel_continuity` 工具 | ✅ |
| 模型与设置 | `novel_model_*` 工具 | ✅ |
| 项目搜索 | `novel_search` 工具 | ✅ |
| 滚动大纲 / 叙事预测 | `novel_rolling_plan_action` / `novel_narrative_forecast_action` | ✅ |
| 总览仪表盘 + 正文编辑器（Vditor） | 「创作」三栏工作台 + 本地 Vditor + 上下文/审稿/修订检查器 | ✅ |
| 导入/导出 | `novel_import*` / `novel_export` 工具 | ✅ |
| 项目初始化/切换 | `novel_project_init` / `novel_project_open` 工具 | ✅ |

刻意不迁移：OpenWrite 的内部 agent 会话层（`/api/chat`、`/api/agent/*`）——
agent 运行时唯一归属 dsh，见职责划分原则。

## 选用的 dsh 模式

主模式：**Agent 预设（agent preset）+ 自定义插件 + Web profile**。
辅助模式：Python SDK（`deepseek-harness-sdk`）用于自动化编排（conductor）。

- goethe / dante 做成两个 dsh agent 预设（`~/.dsh/.agent-presets/` 下），
  各自携带 persona、精选工具集和技能目录；在 dsh web 建会话时选择。
- dante 预设内通过 `dsh-tool-subagent` 额外挂载一个 `subagent_goethe` 委派工具
  （dsh 的子代理不能跨预设，但可按工具实例配置 persona + toolFilter，
  正好表达"Dante 写作时向 Goethe 咨询规划"的关系）。
- 技能复用 OpenWrite 现成的 SKILL.md（dsh 技能格式与之兼容，
  `metadata.openwrite` 扩展字段会被忽略，无副作用）。

## 组件清单

### 1. openwrite-bridge 插件（`packages/openwrite-bridge/`）

TS 插件，`apply(ctx)` 中 `ctx.tools.register(defineTool({...}))` 注册一组
`novel_*` 工具，内部用 `fetch` 调用 Studio HTTP 动作面（遵守 `exec.signal` 超时）。
配置经 Schemastery `Config` 校验：

| 配置项 | 默认 | 说明 |
|---|---|---|
| `baseUrl` | `http://127.0.0.1:4567` | Studio 地址 |
| `timeoutMs` | `600000` | 单工具超时（写章耗时长） |
| `outputDir` | 系统临时目录下 `openwrite-exports/` | 导出文件保存目录 |

工具集（62 个，覆盖 Studio 动作面全部端点；按域分组）：

| 域 | 工具 | 端点 |
|---|---|---|
| 基础读写 | `novel_status` / `novel_context_preview` / `novel_outline_read` / `novel_search` / `novel_doc_read` | GET /api/workspace、/api/context、/api/outline、/api/search、/api/document |
| 核心写作 | `novel_outline_edit` / `novel_write_chapter` / `novel_review_chapter` / `novel_doc_write` / `novel_focus` / `novel_export` | POST /api/outline/edit、/api/write、/api/review，PUT /api/document，POST /api/focus，GET /api/export |
| 资产 | `novel_assets_list` / `novel_asset_read` / `novel_asset_create` / `novel_asset_update` / `novel_assets_package_export` / `novel_assets_package_preview` / `novel_assets_package_import` | GET/POST /api/assets*（含 package 导入导出） |
| 伏笔 | `novel_foreshadowing` | POST /api/foreshadowing |
| 修订提案 | `novel_revisions_list` / `novel_revision_get` / `novel_revision_create_selection` / `novel_revision_create_from_review` / `novel_revision_apply` / `novel_revision_reject` / `novel_revision_regenerate` | GET /api/revisions*，POST /api/revisions/selection、/from-review、/{rev_*}/apply\|reject\|regenerate |
| 后台任务 | `novel_tasks_list` / `novel_task_get` / `novel_task_create` / `novel_task_cancel` / `novel_task_retry` / `novel_task_confirm` / `novel_multi_write` | GET /api/tasks*，POST /api/tasks、/{tsk_*}/cancel\|retry\|confirm；multi_write 封装 continuous_write 任务 |
| 项目生命周期 | `novel_project_init` / `novel_project_open` / `novel_project_delete` | POST /api/project/init（免项目）、/open（免项目）、/delete |
| 章节/文档/导入 | `novel_chapter_delete` / `novel_doc_create` / `novel_import_preview` / `novel_import` / `novel_sync` / `novel_writing_targets` | POST /api/chapter/delete、/api/document/create、/api/import*、/api/sync、/api/project/writing-targets |
| 连续性/诊断 | `novel_continuity` / `novel_diagnostics` | GET /api/continuity，POST /api/diagnostics |
| 规划面 | `novel_chapter_run_action` / `novel_rolling_plan_action` / `novel_narrative_forecast_action` / `novel_manuscript_edit_action` | POST /api/chapter-runs-v2、/api/rolling-plans、/api/narrative-forecasts、/api/manuscript-editing（action 分发器） |
| 风格/参考库 | `novel_source_action` / `novel_reference_library_action` / `novel_runtime_skill_action` / `novel_rule_action` | POST /api/source、/api/reference-library、/api/runtime-skills、/api/rules（action 分发器） |
| 深度研究 | `novel_research_status` / `novel_research_report` / `novel_research_settings_save` | GET /api/research、/api/research/reports/{id}，POST /api/research/settings（跑研究用 novel_task_create type=research） |
| 模型配置 | `novel_model_profiles` / `novel_model_configure` / `novel_model_test` / `novel_model_embedding_test` / `novel_model_profile_save` / `novel_model_profile_delete` / `novel_model_routes_save` | GET/POST /api/model* |

刻意不桥接：`/api/chat` 与 `/api/agent/session*`（agent 层完全归 dsh）、
`/api/agents`、`/api/agent/activity`（OpenWrite 原生 agent 的运行面）、
`/api/health`（存活探针，连通性由 `novel_status` 覆盖）。

### 2. studio-panel 前端插件（`packages/studio-panel/`）

dsh web 的 client 插件，把 Studio 的关键界面原生融入会话 UI（细节见包内 README）：

- **Host 领域边界**：`openwrite-bridge` 的 `NovelDomainService` 独占 Studio HTTP 客户端，
  同时提供同源 API 代理、轻量失效快照/SSE 兼容出口与配置出口。`studio-panel` host 半边只提供随包
  Vditor 静态文件。
- **Client 半边**：三个 `conversation.view` 工作台——创作（章节树 + 正文编辑器 +
  检查器）、资料（资产/大纲/图谱/研究/搜索内部导航）、任务（后台任务/研究/导入导出）。
  单一 `NovelWorkbenchStore` 集中缓存并每 1.5 秒轮询轻量 revision，revision 变化才刷新资源，
  每 15 秒兜底全量同步；会话头、composer context、
  八类工具卡和 Turn 写操作汇总复用同一状态。

### 3. 双 agent 预设（`presets/goethe/`、`presets/dante/`）

每个预设目录：`agent.cordis.yml` + `preset.yml` + `skills/`。

- `presets/goethe/`：persona 移植自 OpenWrite `DEFAULT_GOETHE_SYSTEM_PROMPT`
  （规划 Agent：收敛灵感/人物/设定/大纲，正文交给 Dante）。
  工具集：bridge 中的读类 + 大纲/资产/伏笔工具 + dsh 基础检索工具；
  技能：oh-story-long-scan、foreshadowing-system、novel-creator 等。
- `presets/dante/`：persona 移植自 `DEFAULT_DANTE_SYSTEM_PROMPT`
  （正文创作 Agent：预检→写章→评审→结算；资产不齐时回退 Goethe）。
  工具集：bridge 写章/评审/上下文/文档工具 + `subagent_goethe` 委派工具；
  技能：oh-story-long-write、oh-story-deslop、oh-story-review、dialogue 等。

预设经 `scripts/install.sh` 复制到 `~/.dsh/.agent-presets/`（dsh 的用户预设根，
copy-only 语义，不在原地改）。

### 4. 技能移植（`presets/*/skills/`）

从 `/Users/jiaoziang/OpenWrite/skills/` 与 `tools/runtime_skills/` 复制 SKILL.md
目录树，按预设分工拆分随包携带：goethe 带 foreshadowing-system、novel-creator、
oh-story-long-analyze/scan、style-system、world-query；dante 带 dialoguequality、
novel-reviewer、oh-story-long-write/deslop/review、truth-validation、workflow-manager。
预设经 `customSkillDirs`（baseUrl 相对路径）自带加载，安装时随预设 rsync。
格式已兼容（name/description frontmatter），无需改写内容。

### 5. 组合与启动（`scripts/`）

- `scripts/install.sh`：构建两个插件 → 复制预设到 `~/.dsh/.agent-presets/` →
  初始化 web/headless profile → 把插件 `pnpm add -w` 进 profile 并追加到
  `dsh.profile.bundles`（bundle 路径自动挂载插件行，无需 patch 层；
  各包内 `cordis.patch.yml` 仅作 `--patch` 手动挂载的备用通道）。
- `scripts/dev.sh`：启动 `openwrite studio --port 4567 --project ~/my_novel --no-open`
  + `dsh web`（导出 `NO_PROXY`，本机探活不被系统代理劫持）。
- `scripts/verify.sh`：一键集成验证（服务、领域代理、失效快照、本地 Vditor、无 iframe）；
  `scripts/e2e-web.py`：Playwright 走查面板视图。

### 6. Python 编排器 conductor（`conductor/`，已落地）

uv 环境 + `deepseek-harness-sdk`（自带单文件 Node 运行时，macOS arm64 有 wheel）。
无人值守流水线：按大纲连续写章 → 37 维评审 → 低于阈值/含 blocker 自动回炉。

架构要点（v2，实测迭代后的稳定形态）：

- **长操作全部走 OpenWrite 后台任务系统**（POST /api/tasks 提交 chapter_write /
  chapter_review / revision_from_review，轮询 GET /api/tasks/{id} 的 phase 与
  result）。同步端点 /api/write、/api/review 把执行期耦合进 HTTP 请求生命周期，
  客户端超时即孤儿化服务端任务并占住项目写锁——实测长评审（分批审计 + 截断
  二分重试可达小时级）必翻车，故弃用。托管任务由服务端持有生命周期，
  预算超时由 conductor 显式 cancel，recoverable 失败走任务原生 retry。
- **回炉 = 修订闭环**：/api/write 拒绝重写成稿章节（409），改走
  revision_from_review 任务 → regenerate → apply。客户端先做锚点预过滤
  （evidence.quote 须在正文中唯一出现，镜像服务端 _resolve_issue_anchor 规则），
  regenerate 会派生新提案（旧提案转 rejected），应用最新的 proposed 提案。
- **手稿路径含 arc 段**（data/manuscript/arc_XXX/ch_NNN.md），从 workspace 快照解析。
- 可选 --agent-guidance：dsh SDK 起 bundled 运行时会话把评审 JSON 综合成改写指导
  （cordis.yml 为最小组合；无需自定义插件载体——生产 exe 编译期内置插件集，
  自定义闭包需重建 deploy root，收益不抵成本，刻意不做）。

实测记录（~/my_novel）：ch_001~005 全流程跑通；ch_003 经修订回炉 0 分 → 35 分
（blocker 人设矛盾被精准修复）。上游问题（OpenWrite 仓库，未动）：ch_004 评审系统性
输出截断——模型无视单维度契约产出跨维度大 JSON 直至 finish=length，单维批无法再二分；
且 chapter_pipeline.execute_review_chapter 兜底异常丢弃 exc.code，任务里只记到通用
OPERATION_FAILED 而非 MODEL_OUTPUT_TRUNCATED（可观测性缺陷）。

## 目录结构
```
dsh-novel/
├── DESIGN.md                  # 本文档
├── README.md                  # 使用说明
├── packages/openwrite-bridge/ # TS 桥接插件：62 个 novel_* 工具
├── packages/studio-panel/     # dsh web 原生工作台（3 tab + 8 类工具卡）
├── presets/goethe/            # Goethe 规划 agent 预设（含自带 skills/）
├── presets/dante/             # Dante 写作 agent 预设（含自带 skills/）
├── scripts/install.sh, dev.sh, verify.sh, e2e-web.py
└── conductor/                 # Python 编排器（任务驱动流水线 + SDK 指导会话）
```

## 验证计划

1. 桥接层：`curl` 直连 Studio 端点冒烟（无需 LLM）。
2. 插件层：`dsh --profile web --dump-config` 确认插件行加载；headless 跑一次
   `novel_status` 工具调用（需 DEEPSEEK_API_KEY，已具备）。
3. 端到端：dsh web 中以 dante 预设对 `~/my_novel` 完成
   "看状态 → 预览上下文 → 写一章 → 评审"（遵守 OpenWrite AGENTS.md：
   手动/实机 QA 只用 `~/my_novel`）。

## 风险与边界

- dsh 处于 developer preview（0.1.0-rc），patch/预设 schema 可能随版本变动；
  插件只依赖 `ctx.tools`/`defineTool` 稳定面。
- 写章耗时可达数分钟：bridge 的 `timeoutMs` 与 dsh 工具超时策略都要放宽。
- OpenWrite 写操作有修订门控与项目写锁；bridge 不做任何绕过，全部走 HTTP 动作面。
- 不在 OpenWrite 仓库内做任何改动；本仓库自包含，仅通过 HTTP 契约耦合。
