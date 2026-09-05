# dsh / OpenWrite Workspace Integration Goal

> 状态：实施中（2026-08-31）——wire contract 已定稿于
> `docs/WORKSPACE_CONTEXT_CONTRACT.md`，OpenWrite 多 root 管理、bridge 路由与
> 面板融合正在按本文阶段 B–E 落地，验证证据汇总进 `GOAL.md`。  
> 用途：作为下一阶段实现的唯一工作区隔离规格，也可直接复制本文末尾的 Goal Prompt 给另一个 AI 执行。  
> 范围：dsh-novel 与本地 OpenWrite Studio 的 Workspace 绑定、路由、前端状态和验收。  
> 本文不授权删除正文、营销素材、benchmark 数据或任何凭据。

## 1. 用户要解决的问题

用户在 dsh 中选中一个 Workspace 后，OpenWrite 必须只服务这个 Workspace 的目录。切换 dsh Workspace 时，以下所有能力必须一起切换：

- 正文、章节、导入和写作流程
- 评审、修订、交付与评审 DAG
- 后台任务、Chapter Run、DoG 产物和 benchmark
- 搜索索引、研究资料、资产、伏笔和正典状态
- Studio-panel 的章节列表、任务列表、图、SSE/轮询缓存和当前选中章节

当前截图中的“小说项目”下拉框不是 dsh 原生 Workspace 选择器，而是 OpenWrite 的全局最近项目列表。因此新建或切换 dsh Workspace 后，旧的 OpenWrite 项目仍会出现并继续被加载。这是上下文模型没有融合，不是单纯的 UI 文案问题。

## 2. 已核实的当前实现

### dsh-novel

- `scripts/dev.sh` 启动一个固定的 Studio：`openwrite studio --project "$PROJECT" --port 4567`，然后启动 `dsh web`。
- `packages/openwrite-bridge/src/index.ts` 默认 `baseUrl` 为 `http://127.0.0.1:4567`。
- `packages/openwrite-bridge/src/domain.ts` 在插件生命周期内只创建一个 `NovelDomainService` 和一个 `StudioClient`；代理、工具和失效事件都共享它。
- `packages/openwrite-bridge/src/tools.ts` 的工具调用使用同一 client，尚未把调用会话的 Workspace root 作为请求上下文。
- `packages/studio-panel/src/client/HeaderChrome.tsx` 调用 `/api/project/list`、`/api/project/open`、`/api/project/init`。它展示的是 OpenWrite registry，不是 dsh Workspace 列表；新建时发送相对的 `project_path`，可能在当前项目内生成嵌套目录。
- `packages/studio-panel/src/client/OperationsView.tsx` 仍提供同一套独立的项目切换/新建流程。
- `packages/studio-panel/src/client/api.ts` 的浏览器请求只经过 `/studio-panel/api`，没有明确的当前 session/workspace 身份。
- `packages/studio-panel/src/client/WorkbenchStore.ts`、`workbench-epochs.ts` 已有资源 epoch、SSE 和轮询降级，但 epoch 目前只表示单一 Studio 的资源变化；切换 root 时没有统一的 context epoch/清空屏障。
- dsh 依赖的原生 Workspace UI 已提供 `useWorkspaces`、`useSessions`、目录选择、Workspace 创建/连接和 session 绑定。Workspace 由 canonical path 和稳定 id 区分；Session header 含不可变 `cwd`。

### OpenWrite

- `OpenWrite/tools/studio_application.py` 在进程内持有 `launch_root`、可变 `project_root`、项目级服务、锁和 `_task_runner`。
- `_activate_project()` 会重建服务并改变同一个 Application 的全局状态；`/api/project/open` 调用它。两个并发请求或两个浏览器 session 不能安全地共享这个 mutable singleton。
- 相对初始化路径以 `launch_root` 为基准解析；这正是当前 `project_path: novelId` 导致嵌套项目的根源。
- `/api/project/list` 来自 `~/.config/openwrite/recent_projects.yaml`，它是 OpenWrite 的 legacy 最近项目注册表，不是 dsh Workspace 身份来源。
- Studio 的 task runner、revision、research、benchmark、LightRAG、review store 等服务均以 `project_root` 构造；后台 task 若不固定 root，轮询或结果物化可能漂移。
- OpenWrite 已有 framework-root 检测和 onboarding 语义，框架仓库不可当作私人小说项目。

### 当前本机状态（仅作上下文）

- dsh Web：`http://127.0.0.1:3080`。
- Studio：`http://127.0.0.1:4567`，当前启动时绑定 `/Users/jiaoziang/my_novel`。
- 正式项目目前保留 `/Users/jiaoziang/my_novel`；其他临时目录已移入回收站。
- `my_novel` 的 `data/benchmarks` 约占 497 MB；benchmark 工作区和正式正文必须继续分开。
- review-v2、共享 schema/codegen、DoG、epoch 和前端测试已有用户改动/提交，后续实现必须在其上增量工作。

## 3. 目标契约（必须实现）

### 3.1 单一身份

1. dsh Workspace 的 canonical absolute path 是唯一 root identity；稳定 Workspace id 是 UI/会话引用，不能替代路径校验。
2. 一个已初始化 dsh Workspace 与一个 OpenWrite project root 一一对应。项目根目录应包含 `novel_config.yaml`；未初始化目录只能进入显式 onboarding。
3. `dsh-novel` 框架仓库、空 root、相对 root、路径穿越、无法 canonicalize 的 symlink 目标、没有权限的目录都不能静默成为小说项目。
4. OpenWrite legacy recent-project registry 可以保留以兼容直接 CLI 使用，但不能决定 dsh 当前上下文，也不能作为浏览器的 Workspace 列表。

### 3.2 请求上下文

所有 Studio 请求必须有明确且可审计的 Workspace context：

```text
{ workspace_id, workspace_root, session_id?, context_epoch }
```

- Bridge 工具：从实际调用会话的 `exec.agent.session.header.cwd` 派生 canonical root，并通过受控的 StudioClient 请求上下文发送；不能使用插件启动 cwd 或固定 fallback 覆盖它。
- 浏览器面板：使用 dsh 当前 session/workspace 的标准 props/hooks；代理请求必须能可靠识别当前 session，不接受用户任意输入的 root 作为授权依据。
- Studio：校验 root 的 canonical path、目录存在性、OpenWrite 配置/初始化状态、framework boundary 和授权映射；拒绝缺失/不一致 context，错误需带稳定 code。
- 不能通过全局 mutable “当前项目”字段在不同请求之间切换来实现路由。

### 3.3 按 root 隔离的运行时

优先实现一个进程内的 Workspace/Project Manager：

- `root -> 独立 StudioApplication/context`，每个 context 有自己的 task runner、locks、revision/invalidation channel、service instances 和缓存。
- 请求开始时选择 context；请求结束后不得改变其他 root 的状态。
- task 创建时持久化 canonical root、workspace id、context epoch；查询、取消、重试、结果物化和重启恢复均按该 identity 校验。
- SSE/轮询失效事件必须带 root/workspace identity；客户端只消费当前 context 的事件。
- 若多租户 Application 改造成本经评估不可接受，可采用每 Workspace 一个 Studio 进程，但必须有端口分配、进程生命周期、崩溃恢复、映射持久化、浏览器动态代理和清理机制。不能把单一固定 Studio + mutable project switch 作为最终方案。

### 3.4 初始化与兼容

- 新建作品流程先用 dsh 原生目录 picker 选取/创建真实目录，再 `workspace.create({ path: canonicalPath })`，最后在该绝对路径执行 OpenWrite 初始化并连接 Workspace。
- 禁止默认将 `novel_id` 拼在当前小说目录后面；禁止相对 `project_path`。
- 当前 Workspace 是有效 OpenWrite 项目时，面板显示只读的当前 Workspace 状态；当前 Workspace 未初始化时显示 onboarding，不列出或自动恢复旧项目。
- 直接执行 `openwrite studio --project ...` 的 CLI 模式继续可用；legacy `/api/project/open`、`/api/project/list` 的兼容行为需经过明确边界设计，不得影响 dsh 路由。

## 4. 推荐实现路径

### 阶段 A：建立 context 规格与探针（先做）

1. 阅读当前 dsh 版本的 Workspace、Session、web proxy、slot props 类型，确认：
   - 工具调用中 `exec.agent.session.header.cwd` 的真实类型和生命周期；
   - 浏览器当前 session/workspace 能从哪些标准 props/hooks 得到；
   - HTTP 代理能否安全携带 session id，是否已有受信 envelope/header；
   - Workspace 注册/创建/连接的官方动作名称和返回时序。
2. 写出一份小型 context wire contract（建议 JSON/header + server-side lookup），明确缺失、非法、未知 Workspace、root 与 session 不匹配时的错误码。
3. 增加只读诊断接口（例如 `/api/workspace/context`），返回 workspace id、canonical root、初始化状态、novel id、context epoch，不返回凭据和正文。

### 阶段 B：OpenWrite 多 root 管理

1. 在 `OpenWrite/tools/` 增加 Project/Workspace Manager，封装 canonicalize、framework-root 拒绝、初始化检查、按 root 创建/缓存 Application。
2. 让 Studio HTTP handler 在每个请求解析并验证 context，再把请求分派给对应 Application；不要让 handler 直接调用共享 `server.app.project_root`。
3. 把 background task 的 root identity 作为持久化契约；验证 task API、review/benchmark/DoG 结果和重启恢复。
4. 将 invalidation/revision 从单一全局计数改为 per-context；必要时保留全局监控，但浏览器消费必须按 context 过滤。
5. 保持 `/api/project/*` legacy API 的 CLI 兼容性：在无 dsh context 的直接 Studio 调用中仍以启动项目为默认，但有 dsh context 时必须拒绝跨 root open/switch。

### 阶段 C：bridge context 路由

1. 扩展 `StudioClient` 支持 request-scoped `WorkspaceContext`，所有 GET/POST/PUT/download 都携带 context。
2. `NovelDomainService` 不再只有一个无上下文 client；采用 context-aware client factory 或按 root 的安全 client cache。
3. 更新 `tools.ts` 每个工具入口，使用调用 agent session 的 cwd 派生 context；对无 agent/session 的调用明确失败。
4. 更新 web proxy：从受信 dsh session/workspace 绑定解析 context，再转发到 Studio；不要相信浏览器任意 `workspace_root` 字段。
5. 将 config、API proxy、SSE、invalidation snapshot 都变成当前 context 语义；切换 context 时旧 stream 必须关闭或标记过期。

### 阶段 D：前端融合

1. 删除/禁用 `HeaderChrome.tsx` 与 `OperationsView.tsx` 中基于 `/project/list` 的项目切换器和相对路径新建表单。
2. 接入 dsh 原生 Workspace picker/list；显示当前 Workspace 名称及路径标识，必要时提供 onboarding 状态，而不是 OpenWrite recent 项目菜单。
3. 创建作品走目录 picker -> workspace create -> OpenWrite init -> connect/select -> context epoch 更新的单一流程。
4. `WorkbenchStore` 增加 context identity/epoch：context 变化时先清空章节、任务、DAG、图、当前章节和错误状态，再允许新 root 的请求提交；旧请求返回不得覆盖新 snapshot。
5. 所有视图（Graph/DAG、Tasks、Benchmark、Models、Research、Library、Search、Review）按 context epoch 重挂载或取消旧请求；localStorage key 必须包含 workspace id/root hash，避免跨项目恢复章节。
6. SSE 与轮询必须携带/绑定当前 context；断线降级不能回退到旧 root。

### 阶段 E：安全、迁移与文档

1. 对 canonical path 做边界测试：相对路径、`..`、绝对路径、symlink、framework root、文件路径、不可读目录、重复 basename。
2. 明确旧 registry 的迁移策略：只用于 CLI 最近项目展示/兼容，不自动注入 dsh 当前 Workspace。
3. 更新 `scripts/dev.sh` 和 README：说明 dsh Workspace 是主入口；固定 `--project` 只作为兼容/单项目启动模式；不要记录任何 API key。
4. 为运行时诊断、日志、错误 payload 做脱敏；不得输出凭据、完整 Authorization、正文内容或临时 key。

## 5. 文件级检查范围

### dsh-novel（预期修改）

- `scripts/dev.sh`
- `packages/openwrite-bridge/src/index.ts`
- `packages/openwrite-bridge/src/client.ts`
- `packages/openwrite-bridge/src/domain.ts`
- `packages/openwrite-bridge/src/tools.ts`
- `packages/studio-panel/src/client/api.ts`
- `packages/studio-panel/src/client/HeaderChrome.tsx`
- `packages/studio-panel/src/client/OperationsView.tsx`
- `packages/studio-panel/src/client/WorkbenchStore.ts`
- `packages/studio-panel/src/client/workbench-epochs.ts`
- `packages/studio-panel/src/client/index.ts` 及必要的 slot/props 适配
- dsh bridge/panel tests、E2E fixtures、README/GOAL 状态记录

### OpenWrite（预期修改）

- `tools/studio_application.py`
- `tools/studio.py` / `tools/studio_http.py`（以实际入口为准）
- 新增 `tools/workspace_manager.py` 或等价模块
- task runner/store、project registry、invalidation/revision 相关模块
- `tests/test_studio*.py`、任务/benchmark/DoG/HTTP 测试

先阅读并适配现有用户改动，尤其是 review-v2、schema codegen、DoG、epoch 和前端 runner；不得用旧版本覆盖这些改动。`assets/marketing/` 不是本任务范围，禁止删除或回退。

## 6. 测试矩阵

### Python / OpenWrite

- 两个临时 root 各有同名章节：读取、写入、评审、搜索、资产、DAG、benchmark 结果完全分离。
- 两个 root 的 Application/service/task runner 独立；并发请求不会互换 `project_root`。
- 缺失/非法 context、root 与 workspace/session 不匹配、framework root、symlink escape 全部拒绝并返回稳定错误码。
- task 创建后重启/轮询/取消/重试/结果物化仍固定原 root。
- legacy project API 在无 dsh context 下保持兼容，在有 context 下不能跨 root 切换。
- 初始化只接受 canonical absolute target，不产生 `project/project_id` 嵌套。
- per-context revision/SSE 不串流；旧 context 事件不会污染新 context。

### TypeScript / bridge

- 从 `exec.agent.session.header.cwd` 得到 canonical root；无 session 时拒绝而不是 fallback。
- 每种 StudioClient 请求均带 context；proxy 和 domain service 不共享可变 current project。
- 两个并发 session 的工具调用、任务查询和下载互不串数据。
- browser proxy 的 context 来源是受信 session/workspace 绑定，而非任意 URL/body root。

### React / component

- Workspace 切换立即清空旧章节/任务/DAG，旧请求迟到不覆盖新状态。
- context epoch 使 GraphView、DAG、Tasks、Benchmark、Models、Research 等重新取数。
- localStorage、SSE、轮询、AbortController 均按 workspace/session 隔离。
- 面板不再调用 `/project/list` 作为主选择器；无效 Workspace 显示 onboarding。

### Live E2E

用两个临时真实目录 A/B：

1. 注册为两个 dsh Workspace，并分别初始化 OpenWrite。
2. 在 A/B 创建同名章节和可识别的不同内容。
3. 切换 session/workspace，验证 `/api/workspace/context` root、章节、搜索、评审、DAG、任务和 benchmark 产物。
4. 在 A 写作，在 B 评审；检查磁盘 hash 和任务 artifact 只落在对应目录。
5. 切换后旧内容不短暂闪现；刷新后仍恢复当前 dsh Workspace。
6. desktop `1440x1000` 与 mobile `390x844` 均无横向溢出，服务不可达时保留现有 probe-gated skip 语义。

## 7. 验收标准

只有同时满足以下条件才算完成：

- dsh Workspace 是唯一主上下文；OpenWrite recent registry 不再改变 dsh 当前项目。
- 任意时刻每个请求、任务、事件和 UI snapshot 都能回答“属于哪个 canonical root”。
- A/B 并发和切换测试通过，正文、评审、DAG、任务、搜索、benchmark 无交叉。
- framework root、未初始化 root、非法路径和无 context 均 fail closed。
- 面板没有独立的 OpenWrite 项目切换/相对路径新建入口；新建作品一定先创建/连接 dsh Workspace。
- Studio 重启、页面刷新、SSE 断线、旧请求迟到均不会恢复或显示错误项目。
- 直接 CLI `openwrite studio --project ...` 仍可用。
- OpenWrite 全量 pytest、dsh build、bridge smoke、contracts/DoG/epoch/components/E2E 门禁通过；新增测试证据写入 `GOAL.md`。
- review-v2 production gate 继续保持 `disabled_uncalibrated`；本任务不修改真实正式章节。

## 8. 非目标与安全约束

- 不在本阶段启用 review-v2 production gate，也不代替 10–20 章人工校准。
- 不修改真实正式章节、用户研究资料或 `assets/marketing/`。
- 不读取、打印、复制、提交或删除临时 OpenRouter key；验收使用脱敏/假凭据。
- 不删除 benchmark 工作区数据；只确保它们按 root 隔离。
- 不回退用户已有未提交改动。
- 不以全局 singleton 保存 current project 解决并发问题。
- 不要求删除 OpenWrite legacy registry，除非先完成兼容性设计和迁移测试。
- 所有路径使用 canonical absolute path；所有错误 fail closed。

## 9. 回滚与兼容策略

- 每个阶段使用独立、可回滚的提交；先落 context 诊断和测试，再切换默认路由。
- 保留单项目 CLI 启动路径作为 fallback，但 dsh 集成路径由 feature flag 或明确配置控制，不能隐式混用。
- 若多 root manager 尚未稳定，允许暂时只支持一个显式绑定 Workspace，并对第二个并发 root 返回明确的 `WORKSPACE_NOT_READY`，不能错误复用第一个 root。
- 数据迁移只新增 metadata/索引，不重写正文；旧任务若没有 root identity，应标记为不可安全恢复并要求用户重新运行。

## 10. 交付格式

实现 AI 必须最终报告：

1. 实际采用的架构及放弃备选方案的原因。
2. 修改文件和关键契约/API 字段。
3. 每个隔离场景的测试命令与结果。
4. live A/B E2E 的磁盘/hash 证据。
5. 兼容性、迁移、残余风险和未完成项。
6. `GOAL.md` 状态与验证日志更新。

不得用“测试通过”替代 A/B root 隔离证据，也不得声称人工 review-v2 校准已完成。

---

## 可直接复制给另一个 AI 的 Goal Prompt

你在 `/Users/jiaoziang/dsh-novel` 工作，同时可读取本地 `/Users/jiaoziang/OpenWrite`。请先完整阅读：

- `/Users/jiaoziang/dsh-novel/docs/WORKSPACE_INTEGRATION_GOAL.md`
- `/Users/jiaoziang/dsh-novel/GOAL.md`
- dsh Workspace/Session/slot/proxy 的实际类型与 README
- `packages/openwrite-bridge/src/{index,client,domain,tools}.ts`
- `packages/studio-panel/src/client/{api,HeaderChrome,OperationsView,WorkbenchStore,workbench-epochs}.ts(x)`
- `/Users/jiaoziang/OpenWrite/tools/studio_application.py` 及 Studio HTTP/task/project registry 测试

目标：实现“dsh Workspace 是唯一工作区身份，OpenWrite 全部能力按该 Workspace canonical root 隔离并随切换而切换”。不能只修 UI 下拉框。

执行顺序：

1. 先做只读探索，确认 dsh 当前 session/workspace 身份如何进入工具调用和浏览器请求；写出 context wire contract、错误码和诊断接口设计。
2. 为 OpenWrite 实现按 canonical root 的 Project/Workspace Manager 和独立 Application context。禁止用全局 mutable `current project`；task、SSE、revision、search、DAG、benchmark、DoG 都必须带 root identity。
3. 让 bridge 工具从 `exec.agent.session.header.cwd` 派生 root，让浏览器代理从受信 dsh session/workspace 绑定派生 root；Studio 拒绝缺失、非法、未授权或不匹配 context。
4. 删除面板基于 `/project/list` 的主切换器和相对路径新建流程，接入 dsh 原生 Workspace picker/list。新建必须是目录选择/创建 -> `workspace.create` -> 绝对路径 OpenWrite init -> connect/select -> context epoch。
5. 给 WorkbenchStore、SSE、轮询、AbortController 和 localStorage 加 context identity/epoch 屏障；切换时清空旧数据，迟到请求不能覆盖新 root。
6. 完成 Python、TypeScript、React 和 live Playwright A/B 两目录测试，证明同名章节、写作、评审、任务、DAG、搜索、benchmark 以及磁盘产物都不串库。
7. 保持 CLI `openwrite studio --project ...` 兼容；review-v2 production gate 仍为 `disabled_uncalibrated`；不改正文、不碰 `assets/marketing/`、不处理或暴露任何真实 key；不要回退已有用户改动。

实现要求：

- 所有路径 canonical absolute；framework root、相对路径、路径穿越、symlink escape、无效目录 fail closed。
- legacy recent project registry 只能作为 CLI 兼容信息，不能覆盖 dsh 当前 Workspace。
- 对未初始化 Workspace 显示 onboarding，不静默回退到旧项目。
- 后台 task 创建后固定 root，重启/轮询/取消/重试/结果物化不能漂移。
- 每一步先加测试和诊断，再切默认行为；保持提交小而可回滚。

完成时必须报告实际架构、修改文件、context/API 契约、A/B 隔离证据、全部测试命令与结果、迁移/残余风险，并更新 `GOAL.md`。如果某项无法安全实现，明确返回阻塞原因和已验证证据，不要用固定 Studio 或旧项目 fallback 冒充完成。
