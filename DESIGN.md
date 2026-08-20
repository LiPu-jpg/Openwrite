# dsh-novel 架构设计

把 OpenWrite 的完整小说创作能力接入 DeepSeek Harness (dsh) 的 agent 运行时：
**dsh 负责 agent 编排（预设、子代理、技能、长上下文），OpenWrite 负责小说领域能力（大纲、章节流水线、评审、正典状态），Studio 继续担当文本编辑器。**

## 总体架构

```
┌─────────────────────────────┐      ┌──────────────────────────────┐
│ dsh web (127.0.0.1:3080)    │      │ OpenWrite Studio             │
│ agent 控制台                 │      │ (127.0.0.1:4567)             │
│                             │      │                              │
│  goethe 预设 ──┐            │      │  文本编辑器 / 大纲树 / 资产  │
│  dante 预设 ───┤  会话      │      │  / 修订 / 导出               │
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
  嵌入模式下 Studio 的内置 agent 入口会被皮肤隐藏，保证只有一个 agent 界面。
- **双前端并存**：dsh web 是对话/编排控制台；Studio 是稿件编辑器与资产看板。
  两者读写同一份 `data/novels/{id}`，经 OpenWrite 的修订门控保证一致。

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

### 2. 双 agent 预设（`presets/goethe/`、`presets/dante/`）

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

### 3. 技能移植（`skills/`）

从 `/Users/jiaoziang/OpenWrite/skills/` 与 `tools/runtime_skills/` 复制 SKILL.md
目录树到本仓库 `skills/`，由两个预设的 `customSkillDirs` 引用。
格式已兼容（name/description frontmatter），无需改写内容。

### 4. 组合与启动（`overlays/`、`scripts/`）

- `overlays/dsh-novel.patch.yml`：dsh patch 层，insert bridge 插件行
  （开发期指向构建产物 JS 的绝对路径）。
- `scripts/install.sh`：构建插件 → 复制预设到 `~/.dsh/.agent-presets/` →
  幂等写入 patch。
- `scripts/dev.sh`：启动 `openwrite studio --port 4567 --project ~/my_novel --no-open`
  + `dsh web`（或开发期 `pnpm --dir ~/DSH dsh web --patch ...`）。

### 5. Python 编排器 conductor（`conductor/`，第二阶段）

用 uv 建 Python ≥3.10 环境，装 `deepseek-harness-sdk`（自带单文件 Node 运行时，
macOS arm64 有 wheel）。职责：无人值守流水线，例如"按大纲连续写 N 章，
每章写完自动评审，低于阈值自动回炉"，通过 SDK 起 dante 预设会话驱动。
注意 SDK 的生产 exe 运行时插件集是编译期内置的，自定义插件需
`runtime_bin` 指向 dev node 载体——conductor 会用源码/开发载体启动。

## 目录结构

```
dsh-novel/
├── DESIGN.md                  # 本文档
├── README.md                  # 使用说明
├── packages/openwrite-bridge/ # TS 桥接插件（构建产物 lib/）
├── presets/goethe/            # Goethe 规划 agent 预设
├── presets/dante/             # Dante 写作 agent 预设
├── skills/                    # 移植自 OpenWrite 的 SKILL.md 树
├── overlays/dsh-novel.patch.yml
├── scripts/install.sh, dev.sh
└── conductor/                 # (二阶段) Python SDK 编排器
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
