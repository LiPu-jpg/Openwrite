# Workspace Context Wire Contract

> 状态：已实施（2026-08-31）
> 配套文档：`docs/WORKSPACE_INTEGRATION_GOAL.md`（目标与验收）、`GOAL.md`（验证日志）。
> 本文是 dsh-novel ↔ OpenWrite Studio 之间 Workspace context 的唯一契约定义。

## 1. 身份模型

- **唯一 root identity** = dsh Workspace 的 canonical absolute path（`fs.realpath` 之后）。
- `workspace_id`（dsh `WorkspaceId`，UUID）只是 UI/会话引用，不能替代路径校验。
- 一个已初始化 dsh Workspace 对应一个 OpenWrite project root（含 `novel_config.yaml`）。
- `context_epoch`：per-root 单调递增整数。Studio 端每次 context 模式成功写（2xx POST/PUT，含 `project/init`）后 bump；bridge 端为每个 root 维护失效 revision。客户端用它丢弃过期状态，不用于授权。

## 2. 三条入口的 context 来源

### 2.1 Agent 工具调用（openwrite-bridge tools）

- 来源：`exec.agent?.session?.header?.cwd`（dsh `SessionHeader.cwd`，创建时 stamped、不可变）。
- `exec.agent` 缺失、session 缺失或 cwd 缺失 → **fail closed**，抛 `WORKSPACE_CONTEXT_MISSING`，绝不回退到插件启动 cwd 或固定项目。
- bridge 对 cwd 做 `realpath` 规范化后作为 `workspace_root`，连同 `session_id`、`callId`、`rootCallId` 和工具名一起放进请求 header（见 §3）。

### 2.2 浏览器面板（studio-panel → bridge web proxy）

- 浏览器只发送 **workspace_id**（和可选 session_id），**从不发送路径**：
  - `X-Dsh-Workspace-Id: <workspaceId>`（所有 `/studio-panel/api` 请求必需）
  - `X-Dsh-Session-Id: <sessionId>`（可选，审计）
  - SSE/轮询：`/studio-panel/events?workspace=<id>`、`/studio-panel/invalidation.json?workspace=<id>`
- proxy（host 进程内）用受信注册表解析：`ctx.workspaceRegistry.get(WorkspaceId(id))?.path`。
  浏览器无法借此注入任意路径——id→path 映射完全在 host 侧完成；伪造 id 最多选到另一个已注册 dsh Workspace。
- 解析失败 → 400 `WORKSPACE_UNKNOWN`；缺 header → 400 `WORKSPACE_CONTEXT_MISSING`；registry 服务不可用 → 503 `WORKSPACE_REGISTRY_UNAVAILABLE`（fail closed）。
- proxy 转发时改发 §3 的 OpenWrite context header。

### 2.3 Studio HTTP（OpenWrite）

- 有 `X-OpenWrite-Workspace-Root` → context 模式，按 canonical root 路由到独立的 per-root `StudioApplication`。
- 无该 header → legacy 模式，路由到 launch app（`openwrite studio --project ...` 的启动项目），CLI 与 Studio 原生页面行为不变。

## 3. OpenWrite context header（bridge/proxy → Studio）

```text
X-OpenWrite-Workspace-Root: <canonical absolute path>   # context 模式必需
X-OpenWrite-Workspace-Id:   <dsh workspace id>          # 可选，审计
X-OpenWrite-Session-Id:     <dsh session id>            # 可选，审计
X-OpenWrite-Context-Epoch:  <int>                       # 可选，客户端观测 epoch，诊断
X-OpenWrite-Tool-Call-Id:   <dsh call id>               # Agent 工具调用时提供，审计关联
X-OpenWrite-Root-Call-Id:   <dsh root call id>          # Agent 工具调用时提供，调用树关联
X-OpenWrite-Tool-Name:      <novel_* tool name>         # Agent 工具调用时提供，审计关联
```

后三个字段不参与 Workspace 授权。OpenWrite 将它们与 Studio `request_id` 一并写入作品内脱敏
operation trace，用于把 dsh 工具调用关联到领域变更。

校验规则（Studio `tools/workspace_manager.py`，全部 fail closed）：

- expanduser 后非绝对 → 400 `WORKSPACE_ROOT_INVALID`（reason=`not_absolute`）
- 任何 segment 为 `..` → 400 `WORKSPACE_ROOT_INVALID`（reason=`traversal`）
- `os.path.realpath` 规范化（symlink 由此消解，canonical 结果即身份）
- 不存在 → `not_found`；非目录 → `not_directory`；不可读/不可进入 → `not_readable`
- framework root（`pyproject.toml` name=openwrite + `tools/studio.py`）→ 403 `WORKSPACE_FRAMEWORK_ROOT`
- 目标与另一个已激活 root 存在任一方向的嵌套关系 → 400 `WORKSPACE_ROOT_INVALID`（reason=`nested`）；检查同时覆盖“新 root 在旧 root 内”和“旧 root 在新 root 内”。
- 无 `novel_config.yaml` 且路由不允许未初始化 → 428 `WORKSPACE_NOT_INITIALIZED`

## 4. 错误码总表

| code | HTTP | 含义 |
|---|---|---|
| `WORKSPACE_CONTEXT_MISSING` | 400 | 需要 context 的入口缺 workspace root/id（bridge 工具无 session/cwd 同码） |
| `WORKSPACE_ROOT_INVALID` | 400 | 相对路径、`..`、不存在、非目录、不可读、嵌套（details.reason 区分） |
| `WORKSPACE_FRAMEWORK_ROOT` | 403 | root 是 OpenWrite 框架仓库 |
| `WORKSPACE_NOT_INITIALIZED` | 428 | root 未初始化（允许显式 onboarding 的路由除外） |
| `WORKSPACE_SWITCH_FORBIDDEN` | 409 | context 模式调用 `/api/project/open` 或 `/api/project/delete` |
| `WORKSPACE_CONTEXT_MISMATCH` | 409 | init 的 project_path ≠ context root；task 记录 root ≠ store root |
| `WORKSPACE_UNKNOWN` | 400 | proxy 侧 workspace_id 不在 dsh 注册表 |
| `WORKSPACE_REGISTRY_UNAVAILABLE` | 503 | proxy 侧 host workspaceRegistry 服务缺失 |

错误 payload 沿用 Studio 现有 `{error, code, details, request_id}` 结构；proxy 侧用 `{error, code}`。

## 5. 路由语义

### context 模式

- 每个 canonical root 懒建并缓存一个独立 `StudioApplication`（独立 task runner、写锁、revision、服务缓存；用户级 model profile/settings 与 reference library 按设计共享）。即使 context root 等于 Studio 的 `launch_root`，也必须新建独立 context app；legacy default app 只能服务无 context 请求，二者不可别名。
- context app 不持有 `ProjectRegistry`（`None`），绝不写 legacy recent-project registry。
- `/api/project/open`、`/api/project/delete` → 409 `WORKSPACE_SWITCH_FORBIDDEN`。
- `/api/project/init`：允许未初始化 root；payload `project_path` 必须 canonicalize 到 context root（否则 409 `WORKSPACE_CONTEXT_MISMATCH`）；相对路径直接 400。
- `/api/project/list`：只读 legacy registry 信息，不影响路由；面板不再使用。
- `/api/reading-order*`、`/api/chapters/{id}/work-brief` 与 `/api/scenes*`：全部从当前 context app 的 canonical root 重新投影；移动、场景迁移、元数据与跨章操作使用该 root 内的 exact revision/CAS，成功写入后只失效同 root 客户端。

### legacy 模式（无 context header）

- 一切保持原行为：launch app 为默认，`/api/project/open` 可切换 default app 的 current project（CLI 单用户兼容路径）；该 mutable default app 永不作为 context app 使用。

## 6. 诊断接口

`GET /api/workspace/context`：

- context 模式：`{mode: "workspace", workspace_id, workspace_root, initialized, novel_id, context_epoch}`
- legacy 模式：`{mode: "legacy", workspace_root, initialized, novel_id}`
- 不返回凭据、正文或绝对路径以外的敏感信息。

## 7. 后台 task 身份

- `TaskStore` 创建记录时自动持久化 `workspace_root`（取 store 自身 project_root）。
- context 模式创建的记录额外持久化 `workspace_id`、`session_id`、`context_epoch`（请求线程 thread-local 传入；执行线程不依赖它）。
- `recover_interrupted`：记录 root ≠ store root → 标记 failed（`WORKSPACE_CONTEXT_MISMATCH`），不可恢复重跑。
- get/cancel/retry：记录 root ≠ store root → 409 `WORKSPACE_CONTEXT_MISMATCH`。
- 轮询/取消/重试/结果物化全部发生在 per-root app 内，结构上不可能漂移。

## 8. 失效传播（bridge → 浏览器）

- `NovelDomainService` 维护 per-root revision（`Map<root, {revision, lastMutation}>`）。
- SSE 连接按 `?workspace=<id>` 解析并绑定 root；`invalidate` 事件带 `{workspace_root, revision, resource, path}`，只发给匹配 root 的连接。
- `invalidation.json?workspace=<id>` 返回该 root 的快照。
- 浏览器 WorkbenchStore 按当前 context 过滤事件；context 切换时关闭旧流、重置 revision 基线。

## 9. 前端 context 屏障

- WorkbenchStore 持有 `{workspaceId, root, generation}`；`setContext` 变化时：bump generation、清空章节/任务/DAG/图/当前章节/错误、abort 在途请求、关闭旧 SSE、重置 revision 基线、按新 workspace 重连并刷新。
- 迟到的旧 generation 响应一律丢弃。
- localStorage key 全部带 workspace 后缀：`dsh-novel.<key>.<workspaceId>`。
- 面板不再调用 `/api/project/list`；新建流程固定为：目录选择/创建 → `workspace.create` → context 模式 `/api/project/init`（绝对 canonical path，初始化时创建该作品目录的独立 Git 仓库）→ `connectWorkspace`/`sessions.open` → `setContext`。
