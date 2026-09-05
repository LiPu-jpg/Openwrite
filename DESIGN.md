# dsh-Openwrite 架构设计

把 OpenWrite 的完整小说创作能力接入 DeepSeek Harness (dsh) 的 agent 运行时：
**OpenWrite 提供无界面的小说领域后端，dsh 负责唯一的 agent 编排、交互壳与创作工作台。**

## 总体架构

```
┌─────────────────────────────┐      ┌──────────────────────────────┐
│ dsh web (127.0.0.1:3080)    │      │ OpenWrite Studio             │
│ agent 控制台 + 创作工作台    │      │ (127.0.0.1:4567)             │
│                             │      │                              │
│  OpenWrite 预设 ─┤  会话      │      │  无界面领域 HTTP 服务         │
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
  全部使用 dsh 的机制。OpenWrite 自带的 ReAct agent 层（旧版 Goethe/Dante Python 循环、
  /api/chat、Studio 助手面板）不参与本方案——草案生成等创作推理由 dsh agent 自身完成，
  OpenWrite 只暴露确定性领域服务（存储、校验、上下文装配、章节流水线、评审）。
- **唯一前端**：dsh web 同时承担对话、编排和创作编辑。Studio UI 不进入默认工作流，
  只保留为外部高级维护出口；所有读写仍经 OpenWrite 修订门控作用于同一事实来源。

## 功能迁移对照（Studio 界面 → dsh 原生机制）

原生融入原则：能力本身成为 dsh 的一等公民（agent 工具 / 原生视图 / 工具卡片），
默认工作流不嵌入 Studio；能力按写作者工作流进入 dsh 原生视图。

| OpenWrite Studio 界面 | dsh 原生形态 | 状态 |
|---|---|---|
| AI 协作（规划与写作） | openwrite agent 预设 + dsh 会话 | ✅ |
| 大纲视图 | 「大纲」原生视图 tab（studio-panel） | ✅ |
| 人物/世界观资产看板 | 「资产」原生视图 tab + `novel_asset_*` 工具 | ✅ |
| 审稿报告 | `novel_review_chapter` 自定义工具卡片 + 评审工具 | ✅ |
| 评审/交付追踪 | 「图谱」中的 Review DAG / Delivery DAG（React Flow + ELK） | ✅ |
| AI 协作 → 任务中心 | 「任务」原生视图 tab + `novel_tasks_*` / `novel_multi_write` 工具 | ✅ |
| 连续性（伏笔 DAG / 关系图谱） | 「图谱」原生视图 tab + `novel_continuity` 工具 | ✅ |
| 资料库（参考作品） | 「资产」tab 资料库分组 + `novel_reference_library_action` 工具 | ✅ |
| 修订提案 | `novel_revisions_*` 工具（应用/驳回/重生成） | ✅ |
| 高级工具（风格/参考库/规则/迁移等） | `novel_source_action` / `novel_reference_library_action` / `novel_rule_action` 等 | ✅ |
| 深度研究 | `novel_research_*` 工具 | ✅ |
| 连续性检查 | `novel_continuity` 工具 | ✅ |
| 模型与设置 | `novel_model_*` 工具 + 「任务」中的框架内模型测试台 | ✅ |
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

- OpenWrite 做成一个 dsh agent 预设（`~/.dsh/.agent-presets/` 下），
  在同一长期会话内按阶段切换规划与写作职责；不再要求跨 preset 切换。
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

工具集（90 个，覆盖 Studio 动作面全部端点；按域分组）：

| 域 | 工具 | 端点 |
|---|---|---|
| 基础读写 | `novel_status` / `novel_review_framework` / `novel_context_preview` / `novel_outline_read` / `novel_reading_order` / `novel_reading_packet` / `novel_chapter_work` / `novel_search` / `novel_doc_read` | GET /api/workspace、/api/review/framework、/api/context、/api/outline、/api/reading-order、/api/reading-packet、/api/chapters/{id}/work-brief、/api/search、/api/document |
| 核心写作 | `novel_outline_edit` / `novel_write_chapter` / `novel_review_chapter` / `novel_doc_write` / `novel_focus` / `novel_export` | POST /api/outline/edit、/api/write、/api/review，PUT /api/document，POST /api/focus，GET /api/export |
| 资产 | `novel_assets_list` / `novel_asset_read` / `novel_asset_create` / `novel_asset_update` / `novel_assets_package_export` / `novel_assets_package_preview` / `novel_assets_package_import` | GET/POST /api/assets*（含 package 导入导出） |
| 伏笔 | `novel_foreshadowing` | POST /api/foreshadowing |
| 场景结构 | `novel_scene_structure` / `novel_chapter_scenes` / `novel_scene_migration_preview` / `novel_scene_migration_apply` / `novel_scene_migration_rollback` / `novel_scene_update` / `novel_scene_move` | GET /api/scenes、/api/chapters/{id}/scenes、/api/scenes/migration-preview；POST /api/scenes/migration/*、/api/scenes/metadata、/api/scenes/move |
| 修订提案 | `novel_revisions_list` / `novel_revision_get` / `novel_revision_create_selection` / `novel_revision_create_from_review` / `novel_revision_apply` / `novel_revision_reject` / `novel_revision_regenerate` | GET /api/revisions*，POST /api/revisions/selection、/from-review、/{rev_*}/apply\|reject\|regenerate |
| 后台任务 | `novel_tasks_list` / `novel_task_get` / `novel_task_create` / `novel_task_cancel` / `novel_task_retry` / `novel_task_confirm` / `novel_multi_write` | GET /api/tasks*，POST /api/tasks、/{tsk_*}/cancel\|retry\|confirm；multi_write 封装 continuous_write 任务 |
| 项目生命周期 | `novel_project_init` / `novel_project_open` / `novel_project_delete` | POST /api/project/init（免项目）、/open（免项目）、/delete |
| 章节/文档/导入 | `novel_chapter_delete` / `novel_chapter_delete_batch` / `novel_doc_create` / `novel_import_preview` / `novel_import` / `novel_sync` / `novel_writing_targets` | POST /api/chapter/delete、/api/chapter/delete-batch、/api/document/create、/api/import*、/api/sync、/api/project/writing-targets |
| 连续性/诊断 | `novel_continuity` / `novel_diagnostics` | GET /api/continuity，POST /api/diagnostics |
| 规划面 | `novel_chapter_run_action` / `novel_rolling_plan_action` / `novel_narrative_forecast_action` / `novel_manuscript_edit_action` | POST /api/chapter-runs-v2、/api/rolling-plans、/api/narrative-forecasts、/api/manuscript-editing（action 分发器） |
| 风格/参考库 | `novel_source_action` / `novel_reference_library_action` / `novel_runtime_skill_action` / `novel_rule_action` | POST /api/source、/api/reference-library、/api/runtime-skills、/api/rules（action 分发器） |
| 深度研究 | `novel_research_status` / `novel_research_report` / `novel_research_settings_save` | GET /api/research、/api/research/reports/{id}，POST /api/research/settings（跑研究用 novel_task_create type=research） |
| 模型配置与横评 | `novel_model_profiles` / `novel_model_benchmark` / `novel_model_configure` / `novel_model_test` / `novel_model_embedding_test` / `novel_model_profile_save` / `novel_model_profile_delete` / `novel_model_routes_save` | GET/POST /api/model*；GET/POST /api/benchmarks* |

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
  图谱内含可筛选、折叠和展开 37 项的评审 DAG 与六阶段交付 DAG；任务区含隔离模型测试台。
  单一 `NovelWorkbenchStore` 集中缓存并每 1.5 秒轮询轻量 revision，revision 变化才刷新资源，
  每 15 秒兜底全量同步；会话头、composer context、
  八类工具卡和 Turn 写操作汇总复用同一状态。

### 3. OpenWrite 单一 agent 预设（`presets/openwrite/`）

每个预设目录：`agent.cordis.yml` + `preset.yml` + `skills/`。

- `presets/openwrite/`：合并 Goethe 规划与 Dante 写作 persona，覆盖规划、资产、
  上下文预检、正文、评审、修订、研究和模型测试；技能目录是原两套技能的并集。

预设经 `scripts/install.sh` 复制到 `~/.dsh/.agent-presets/`（dsh 的用户预设根，
copy-only 语义，不在原地改）。

### 4. 技能移植（`presets/*/skills/`）

从 `/Users/jiaoziang/OpenWrite/skills/` 与 `tools/runtime_skills/` 复制 SKILL.md
目录树，统一随 `openwrite` 预设携带规划、写作、评审、连续性和研究技能。
预设经 `customSkillDirs`（baseUrl 相对路径）自带加载，安装时随预设 rsync。
格式已兼容（name/description frontmatter），无需改写内容。

### 5. 组合与启动（`scripts/`）

- `scripts/install.sh`：构建两个插件 → 复制统一预设到 `~/.dsh/.agent-presets/` →
  初始化 web/headless profile → 把插件 `pnpm add -w` 进 profile 并追加到
  `dsh.profile.bundles`（bundle 路径自动挂载插件行，无需 patch 层；
  各包内 `cordis.patch.yml` 仅作 `--patch` 手动挂载的备用通道）。
- `scripts/dev.sh`：启动 `openwrite studio --port 4567 --project ~/my_novel --no-open`
  + `dsh web`（导出 `NO_PROXY`，本机探活不被系统代理劫持）。
- `scripts/verify.sh`：一键集成验证（服务、领域代理、失效快照、本地 Vditor、无 iframe）；
  `scripts/e2e-web.py`：Playwright 走查面板视图。

### 6. Python 编排器 conductor（`conductor/`，已落地）

uv 环境 + `deepseek-harness-sdk`（自带单文件 Node 运行时，macOS arm64 有 wheel）。
无人值守流水线：按大纲连续写章 → 六域累加评审 → 低质量分、低覆盖率或含 blocker 自动回炉。

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

### 6.1 六域评审进入分层 dsh-dog 查询图

OpenWrite review v2 使用六个质量域（权重合计 100）与一个不计分硬门禁。六域内保留
原 37 个编号作为 `legacy_check_ids`，每个编号恰好归属一次；27 仅属于硬门禁。

质量分从 0 累加，只有带正文证据的 `evaluated` criterion 可以得分。问题不参与扣分，
`critical` 只改变 `gate_status`。`not_applicable` 排除出分母；`inconclusive` 不降低
`quality_score`，但降低 `coverage`。因此执行、质量、覆盖、门禁和交付分别由
`execution_status`、`quality_score`、`coverage`、`gate_status`、`delivery_status` 表达。

`dsh-dog` 只读取并验证 materialized artifact，不调用 OpenWrite 的评审模型：

```text
OpenWrite chapter_review
        │
        ▼
data/novels/{id}/data/dog/reviews/{chapter}/
  review.json       # v2 质量分、覆盖率、门禁、交付状态与六域聚合
  context.json
  domain-*.json
  gate.json
  aggregate.json
  dim_01.json ... dim_37.json
  dog-graph.json    # schemaVersion 0.9
        │
        ▼
dog_create → dog_run → dog_status / dog_wait
```

评审图固定为 47 个节点：root、上下文完整性、六个域 composite、硬门禁、确定性聚合，
以及 37 个 legacy leaves。所有节点使用 `review-record` 程序 verifier；不存在 agentic
复核节点。六域节点汇总 criterion、evidence、issue、模型与 token/耗时，37 个 leaf
保留细粒度查询和历史兼容。缺少合法编号的问题仍进入门禁且不丢证据。

交互式 `novel_review_chapter` 和 conductor 会立即生成该快照；后台
`chapter_review` 任务则在 `novel_task_get` 读取完成态时幂等物化同一格式，保证
同步、托管任务和无人值守三条评审入口都进入同一查询框架。

### 6.2 拆书导入进入 dsh-dog 查询图

`smart_import.py` 在正式导入章节后写出（中途失败也会保留 `partial/failed` manifest）：

```text
data/novels/{id}/data/dog/imports/{IMPORT_ID}/
  import.json       # 来源 digest、AI 预检、章节清单、建模待办
  dog-graph.json
```

图中每个 `chapter-ch_*` leaf 检查对应 Markdown 是否存在且有标题，`manifest`
leaf 检查章节数量与 target 是否一致；根节点保留 agentic 聚合断言，报告
`error`、`aiCheck` 和 `construction.nextActions`。这使拆书错误、AI 预检异常和“尚未建
大纲/资产/正典索引”进入同一个可查询结果，但不让 DoG 直接写入 OpenWrite。

安装脚本会把 `scripts/dog/*.js` 复制到 DoG 的
`~/.dsh/dog/scripts/`（评审、交付与拆书导入 verifier）。拆书导入仍可使用其独立的 agentic run，
不放入 `smart_import.py` 的 headless 子流程。安装脚本会自动获取、构建并挂载固定版本的
dsh-dog，同时在缺少配置时写入 `~/.dsh/settings.yaml` 的 `dog.workspaceRoot` 兜底值
（也可用 `DSH_DOG_WORKSPACE_ROOT=/path/to/novel` 覆盖）。dsh-dog v1.2 优先使用调用会话
的 Workspace，因此作品切换无需编辑配置或重启。由于 graph 的 target 是相对于
OpenWrite 项目根目录的路径，DoG 设置应由宿主配置（示例）：

```yaml
dog:
  workspaceRoot: /absolute/path/to/my_novel
  scriptsDirectory: dog/scripts
```

### 6.3 章节交付总图与修订闭环

写章、评审和修订操作会幂等重建：

```text
data/novels/{id}/data/dog/deliveries/{chapter}/
  delivery.json
  writing.json
  review.json
  revision.json
  application.json
  rereview.json
  closure.json
  dog-graph.json

writing → review → revision → application → rereview → closure
```

交付图直接读取 OpenWrite 的 canonical manuscript、review 和 revision 文件。当前正文
SHA 必须与 review 的 `source_revision` 一致；应用修订会令旧评审 `stale`，此时
`application=applied`、`rereview=required`、`closure=rereview_required`，不会因提案已经
`applied` 就误判成功。只有修订后复评通过，`closure=closed` 且
`readyForDelivery=true`。

`conductor/pipeline.py` 在写章、应用修订和每轮评审后刷新交付图；交互工具和后台
`chapter_write` / `chapter_review` / `revision_from_review` 任务也返回 `dog_delivery`。
DoG 仍只负责验收与取证，不生成提案、不应用修订、不重新评审正文。

### 6.4 只读图 API 与框架内模型测试

Studio 提供 `GET /api/dog/graphs?chapter=ch_NNN`，只读取 review/delivery graph、manifest
和节点 record。缺失或损坏 record 以空/缺失数据返回，不触发 verifier 或模型。

模型横评使用 `POST /api/benchmarks` 创建 `model_benchmark` 后台任务，使用
`GET /api/benchmarks` 和 `GET /api/benchmarks/{run_id}` 查询。一次运行冻结同一
`novel_context_preview` packet 和 SHA-256，经 OpenWrite model profile、run-scoped
profile activation 与 LiteLLM-compatible gateway 调用多个写作/独立评审模型。
`execution_mode=framework` 是默认模式：每个候选与重复轮次拥有独立的完整小说工作区，
通过公共 `execute_write_chapter` 和 `execute_review_chapter` 入口运行生产上下文装配、写章、
状态结算、记忆/工作流/Chapter Run V2、正文提交与评审。`execution_mode=creative` 仅保留为
显式裸写诊断模式，不代表框架内表现。两种模式均不修改全局 routes；framework 的正文
只提交到候选沙箱，不覆盖正典正文。artifact 隔离写入：

```text
data/novels/{id}/data/benchmarks/bench_*.json
```

framework 工作区位于
`data/novels/{id}/data/benchmarks/{run_id}/workspaces/{candidate_id}/project/`，复制时排除源
作品已有的 `data/benchmarks`，避免递归嵌套。artifact 记录执行模式、公共入口、工作区、
Chapter Run V2、profile/实际响应 model、上下文 hash、prompt/rubric version、字数、finish
reason、token/reasoning token、延迟、成本和错误。provider 失败属于 reliability failure，
不产生伪造的低质量分；失败候选也保留 Run V2 阶段、失败阶段和安全错误码。只有生产
`commit` 完成的候选才在同一沙箱中进入 `execute_review_chapter`；序列化前移除所有
credential。

usage 契约将 OpenRouter `usage.cost` 和 LiteLLM `response_cost` 归一为
`cost_usd`，并用 `cost_reported` 区分明确 `$0` 与未知费用。artifact summary 分别汇总
输入、输出、推理 token、已报告费用小计及费用覆盖数。UI 的 `/ 1M tokens` 为按单次真实
总费用和总 token 计算的综合有效价，不代表 provider 目录的独立输入/输出单价；旧 artifact
缺少费用来源字段时显示 `—`。

## 目录结构
```
dsh-novel/
├── DESIGN.md                  # 本文档
├── README.md                  # 使用说明
├── GOAL.md                    # 跨仓库目标、状态、凭据引用和验证日志
├── packages/openwrite-bridge/ # TS 桥接插件：90 个 novel_* 工具
├── packages/studio-panel/     # dsh web 原生工作台（3 tab、章节任务、场景双序、双 DAG、模型测试台）
├── presets/openwrite/         # OpenWrite 全流程 agent 预设（含自带 skills/）
├── scripts/install.sh, dev.sh, verify.sh, e2e-web.py
└── conductor/                 # Python 编排器（任务驱动流水线 + SDK 指导会话）
```

## 验证计划

1. 契约层：OpenWrite pytest 覆盖评分、HTTP、benchmark 隔离和 golden fixtures；
   `npm run test:dog` 覆盖 Python/TypeScript 图一致性、无环和 stale review。
2. 插件层：bridge build + smoke 验证 90 个工具、场景与章节任务、benchmark list/get/run、proxy、任务压缩，
   再用 `dsh --profile web --dump-config` 确认插件加载。
3. 端到端：只对 `~/my_novel` 启动 Studio 与 dsh，用 Playwright 验证桌面/移动双 DAG、
   37 项展开、blocker 过滤、详情和模型测试任务；同时检查画布非空、节点不重叠和文字不溢出。

## 风险与边界

- dsh 处于 developer preview（0.1.0-rc），patch/预设 schema 可能随版本变动；
  插件只依赖 `ctx.tools`/`defineTool` 稳定面。
- 写章耗时可达数分钟：bridge 的 `timeoutMs` 与 dsh 工具超时策略都要放宽。
- OpenWrite 写操作有修订门控与项目写锁；bridge 不做任何绕过，全部走 HTTP 动作面。
- 评审 v2 需要 OpenWrite 与本仓库协同改动；边界仍由版本化 HTTP/artifact 契约隔离，
  Python/TypeScript parity 测试防止两侧漂移。
- 最终质量阈值尚需 10–20 章真实人工标注校准；合成 golden fixtures 只验证契约，不能
  代替人工判断或据此直接启用生产门禁。当前 Review v2 明确记录
  `threshold_calibration.status=uncalibrated` 与
  `production_gate_status=disabled_uncalibrated`；未校准时程序拒绝开启生产门禁。
