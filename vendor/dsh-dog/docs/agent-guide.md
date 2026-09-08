# DoG Agent 使用手册(详尽版)

> 适用对象:在 DeepSeek Harness(dsh)会话中运行的 agent。目标:让你**独立、正确地使用 DoG(DAG of Goals)**完成"非形式化目标的自动验收"。
> 对应版本:**dsh-dog v1.0.0**(协议 `schemaVersion` `0.9`)。完整规范见 [SPEC.md](../SPEC.md),设计见 [architecture-0.9.md](architecture-0.9.md),精简入口见 [SKILL.md](../skills/dog-v02-agentic-ci/SKILL.md)。

---

## 0. 这个工具是什么(30 秒版)

**DoG 把"这份东西做好了没"变成"逐项验收,每项都有独立裁判"**:
- 一个**非形式化的总目标**(如"做一份高质量 PPT""写一篇真正的好文章")——没有单一判准、无法一条命令判定
- 你把它拆成多个**可以分别评看的子目标**(每个子目标仍然可以是语义的:"这一页遮挡了吗""这一段有思想吗")
- 每个子目标配一个**独立的 verifier**,由引擎执行、判据是**你的 instruction**(agentic,交隔离子代理用自己的判断力)或**一个宿主脚本**(programmatic,精确规则)
- 全部指标跑完,引擎给出**每个节点的状态、判决证据、失败原因**,以及**总目标过没过/为什么没过**

**关键边界(做之前想好)**:
- 能用一条命令精确判定的 → **不要**放进 DoG(那是普通 CI/脚本)
- **任何分支都不能全是程序化节点**——全部可规则化的部分不属于 DoG;DoG 是判断层
- DoG **不执行**你的开发/生成动作;它只判"东西好不好"(验证先行边界)

---

## 1. 工具表面(完整)

在 dsh 会话中你有以下工具。**常用六个**:`dog_validate` / `dog_create` / `dog_run` / `dog_status` / `dog_wait` / `dog_cancel`;`dog_bind_agent` / `dog_delegate_agent` 是高级绑定工具(通常轮不到你手动用)。

### 1.1 `dog_validate` —— 只校验,不执行
| 项 | 内容 |
|---|---|
| 参数 | `graph`(json,必填):完整的 DoG 图(见 §3) |
| 返回 | `{ valid: true, errors: [], warnings: [] }` 或 `{ valid: false, errors: ["$.nodes.root.kind: ..."], warnings: [] }` |
| 语义 | 静态校验:**不写文件、不捕获对象、不运行任何判定**。错误信息带 JSON 路径,先修到 `valid:true` 再走下一步 |

### 1.2 `dog_create` —— 编译 + 固定对象(可执行图)
| 项 | 内容 |
|---|---|
| 参数 | `graph`(json,必填,与 validate 相同) |
| 返回 | `{ graphId, graphDigest, acceptancePlans: [ {goalId, mode, script?|instruction?, target, inputPath?, digest?, exists?, byteLength? }, … ] }` |
| 语义 | 校验通过才执行;把每个 `target` 的文件**捕获成不可变字节副本**(目录→打包 `.tar`);`exists:false + digest:"missing:…"` 表示引擎从工作区**没找到该对象**(工作区=配置的 `workspaceRoot`,见 §6)——**这是错误,不是"对象不存在"的合法结果**,必须排查后重新 create |
| 注意 | 同一图重复 create 得到**相同 digest**(输入+判据一致);`id` 相同但图内容变 → 新 digest;`graphId`(id)可被多次创建的不同 revision 共用**

### 1.3 `dog_run` —— 启动一次验证(后台)
| 项 | 内容 |
|---|---|
| 参数 | `graphId`(string,必填):`dog_create` 返回的 id |
| 返回 | run 摘要 + `note`:验证在**后台**运行;agentic 叶会 fork verifier Agent(**它们活在本进程**,任何一次性/headless 启动都会在退出时杀死它们——已知问题,不要用;**agentic 验证只能在常驻 web/tui 会话跑**);用 `dog_status` 轮询 |
| 语义 | 立即返回(含 rootState=running);后台执行;**每次 dog_run 创建新 runId** |

### 1.4 `dog_status` —— 读一次当前状态(含证据)
| 项 | 内容 |
|---|---|
| 参数 | `runId`(string,必填) |
| 返回 | `{ runId, graphId, graphDigest, rootState, goals: [ {goalId, state, verifier: {mode}?, evidence?: [...] , defect?} ], revalidated: [...], inherited: [ {goalId, fromRunId, state} ], warning?, generatedAt }` |
| 使用 | 轮询直到 `rootState` 非 `running`;**读 evidence 与 defect 是"为什么失败/通过"的唯一事实源**(见 §4.2 状态解释表) |

### 1.5 `dog_wait` —— 等到终态(推荐路径)
| 项 | 内容 |
|---|---|
| 参数 | `runId`(string,必填);`timeout`(number,可选,建议秒数,非强制) |
| 行为 | **有 job 服务(web/tui):**立即返回 `{runId, graphId, state, jobId, note}`——后台等待任务已注册,**harness 完成时会自动通知你**(那就是等待)。**⚠️ 绝不要对 job 用 `job_output` + `wait:true`**(会被后台通知打断;被打断是预期的,收到通知就继续) |
| 行为 | **无 job 服务(一次性):**立即返回当前状态 `runSummary` + note(仍在 running 就再调用,重复到终态);**每次调用都在保持会话/进程存活**,这正是保护 verifier 子代理的方式 |
| 铁律 | **终态前不要总结/结束**,过早结束会释放正在工作的 verifier 子代理,验证变残局 |

### 1.6 `dog_cancel` —— 取消(记录保留)
| 项 | 内容 |
|---|---|
| 参数 | `runId`(必填);`reason`(可选,人读原因) |
| 返回 | 取消后的 run 摘要(state=cancelled) |
| 语义 | 停止 verifier worker;**部分结果仍可检查**(残局数据保留,同图重跑时已结算叶可被继承) |

### 1.7 高级:绑定/委派工具(一般不用)
- `dog_bind_agent`:把当前会话绑定为一个 goal 的 orchestrator/verifier/reviewer(会话身份由引擎捕获,**模型不能伪造**)。
- `dog_delegate_agent`:启动一个**持续可交互**的 continuable Agent 作为某 goal 的 worker 并绑定(子代理在会话树直接可见)。
- 它们的产出会作为 `agentSessions` 出现在 goal 记录里,供观察谁在判什么。

---

## 2. 一次标准工作流(五步 + 决策)

```
① dog_validate {graph}        → valid:true 才继续;errors 列出全部问题,修完重试
② dog_create   {graph}        → 检查每个 acceptancePlan.input.exists —— false = 工作区对象缺失,回退
③ dog_run      {graphId}      → 拿到 runId
④ dog_wait     {runId}        → 收到完成通知(或轮询 dog_status 到终态)
⑤ 读结果 → 汇报/决策
```

**终态后的决策表**:

| 看到 | 含义 | 你应该 |
|---|---|---|
| `rootState: "success"` | 总目标通过(各硬项全过;断言也未降级) | 汇报通过 + 关键 evidence |
| `rootState: "failure"` | 有 fatal 项失败 | 找 `goals[].state==="failure"` 的节点,读它的 `defect`(失败原因)与 `evidence`(罪名);**向用户转达具体哪个目标、为什么** |
| `rootState: "needs_replan"` | 有节点 `needs_human`(verifier 判不出/证据不足) | **不猜**;如实报告"无法自动判定,原因:…",交用户决断(或改 instruction 后重新 create) |
| `rootState: "partial_success"` | 仅当配置 `allowPartialRoot:true`;部分通过 | 同上,列通过/未通过清单 |
| `rootState: "cancelled"` | 被取消(或宿主重启遗留,自动标记) | 取消原因在 `runtimeWarning`/run 记录;需要时重新 dog_run |
| goal `inherited` | 该叶**对象+判据都没变**,复用了上次判决(0 成本) | 正常;`inherited[].fromRunId` 指向来源 run |
| goal `needs_human` | 判据执行器诚实说"判不了" | 同上,转达 + 理由 |
| goal `blocked` | 依赖项未成功/被依赖失败 | 看它依赖谁(`dependsOn`):被依赖节点失败/未成功 |
| `warning` | `runtimeWarning`(如 revalidate 比例超阈) | 复述即可:提示"变更范围意外地大" |

**质量门禁报告格式(推荐,最后一步输出)**:
```
图: <id> (digest <前 10 位>)
run: <runId>  终态: <rootState>
节点: 每行 goalId | state | 关键 evidence 摘要 / defect
根结果: 通过/不通过 + 一句话原因
```

---

## 3. 图语言(协议 schemaVersion 0.9,完整字段)

### 3.1 顶层 6 字段(全部必填)
| 字段 | 类型 | 说明 |
|---|---|---|
| `schemaVersion` | string | 固定 `"0.9"` |
| `id` | string | ascii id(字母/数字/`._-`);多次 create 同名允许多 revision |
| `root` | string | 总目标节点名(必须存在于 `nodes`;**必须是 composite 且 `constraint:"hard"`**) |
| `nodes` | object | 键=节点 id,值=节点定义(下节) |
| `contains` | array | 归属+优先级边(见 3.3) |
| `dependsOn` | array | 顺序边(见 3.4),可为 `[]` |

### 3.2 节点两种

**leaf(可判定的子目标)**:
```jsonc
{ "kind": "leaf",
  "title": "给人看的名字",
  "constraint": "hard",            // hard: 必须满足;soft: 不满足无碍
  "target": "relative/path.md",    // 工作区内相对路径;或一个目录(引擎打包成 tar)
  "verifier": { … }                 // 二选一(见 3.5)
}
```

**composite(组合/分组)**:
```jsonc
{ "kind": "composite",
  "title": "…",
  "constraint": "hard",
  "target": "relative/path.md",
  "completion": { … },              // 见 3.6
  "verifier": { … }                 // 可选:整体断言,见 3.7
}
```

### 3.3 `contains` 每条边
```jsonc
{ "parent": "root", "child": "no-slop", "required": true, "failure": "fatal" }
```
- `parent`/`child`:两个节点名(parent 必须是 composite)
- `required`: 必须性(对 completion 真值有影响)
- `failure`: 失败传播策略
  - `"fatal"` — 该项失败 = 该组失败(root 组失败 = 总失败)
  - `"tolerable"` — 失败只算"部分问题",不拖垮上一级
  - `"degrade"` — 失败时改用 `degradeTo` 指定的备选子目标(必须同时给 `degradeTo`)

### 3.4 `dependsOn` 每条边(注意方向!)
```jsonc
{ "source": "content-group", "target": "file-nonempty" }
```
**语义:`source` depends on `target` —— source 等 target 先完成**。
❌ 反例(常错):想让"文件检查先跑",写 `{"source":"file-nonempty","target":"content-group"}` 是错的(那是 file-nonempty 等 content-group)。
✅ 正确:`{"source":"content-group","target":"file-nonempty"}`。
**UI 箭头 = target → source(被依赖者指向依赖者)。**

### 3.5 `verifier`(只有两种!)
```jsonc
// A) agentic(大多数语义目标;判据=你的一句话)
{ "mode": "agentic", "instruction": "检查……;你自己决定怎么查;给结论(verdict)与证据(evidence)。" }

// B) programmatic(精确规则;判据=宿主脚本)
{ "mode": "programmatic", "script": "slop-phrases" }   // .js 可省略
```
**没有第三种**!不要写 `id`/`version`/参数模板/证据 schema——那些已不存在(0.9 删除)。

**programmatic 脚本契约**:
- 脚本位于宿主脚本库(`~/.dsh/dog/scripts/`;schemastery 配置 `scriptsDirectory`);**只能引用已存在的**;要新增判据 → 请宿主加脚本,**或改为 agentic**
- 引擎调用:向脚本传对象副本路径(唯一参数)
- 脚本向 **stdout** 输出:**`{"verdict": "pass"|"fail"|"inconclusive", "evidence": <任意 JSON>}`**;**非零退出/输出不可解析 = `inconclusive`**(判不了,不建议当作 pass)

**agentic 契约**:
- instruction 就是判据(引擎把它原样交给一个**隔离的 verifier 子代理**;子代理不知道图、不知道作者过程,自己决定怎么查)
- 子代理按约定往结算文件写 **`{"verdict": "pass|fail|inconclusive", "evidence": <任意 JSON>}`**(0.9 双字段;旧 `settlement/observation` 仍兼容)
- 子代理**可能判 inconclusive**(证据不足/无法定论)→ goal=`needs_human`——**这是设计内的诚实,不是失败**:转达用户,不要硬把 needs_human 说成通过

### 3.6 `completion`(子目标组合)
```jsonc
{ "op": "all",     "items": [ { "op": "ref", "id": "A" }, { "op": "ref", "id": "B" } ] }
{ "op": "any",     "items": […] }                                  // 至少一个过
{ "op": "atLeast", "count": 2, "items": […] }                      // 至少 2 个过
{ "op": "not",     "item": { "op": "ref", "id": "A" } }            // A 没过才算过
{ "op": "ref",     "id": "A" }                                     // 单引用
```

### 3.7 整体断言(composite 可选 verifier)
- 子树**全部结算后**对整组再判一次;**只降不升**:断言 fail → 组 failure;断言 inconclusive → 组 needs_human;断言 pass → 保持子树结论
- **子树已经失败时,断言被跳过**(浪费没有必要;失败原因直接来自子项)
- 典型用途:"每页都合格,但整份 deck 风格割裂""每段都有思想,但作为文章不成立"

---

## 4. 判定结果与状态(完整语义)

### 4.1 节点状态
| state | 含义 | 备注 |
|---|---|---|
| `pending` | 尚未开始 | |
| `running` | 执行中 | 面板/状态轮询可见 |
| `success` | verifier 判 pass | 带 `verification` 记录 |
| `failure` | verifier 判 fail / composite 子树失败 | 带 `defect`(原因)与/或 `verification` |
| `needs_human` | 自动判不了(inconclusive)或需要人审 | **永不猜** |
| `blocked` | 依赖门禁:被依赖目标未成功/未结束 | `defect` 指明是哪个依赖 |
| `cancelled` | run 被取消;宿主重启遗留 run 也会在启动时自动标记 | 已结算数据保留 |
| `invalidated` | 记录被作废(高级/恢复路径) | |
| `partial` | 容忍策略下部分失败 | 只影响父级"部分"判断 |
| `inherited` | 对象+判据未变,复用上次判决 | `inheritedFrom` = 来源 runId |

### 4.2 根状态(rootState)
`success` / `failure` / `needs_replan`(有 needs_human 子项)/ `partial_success`(config `allowPartialRoot`)/ `cancelled` / `running`。

### 4.3 判定记录(每叶完成时)
```jsonc
{ "schemaVersion": "0.1", "goalId": "…", "runId": "…",
  "judgment": { "mode": "agentic", "instructionHash": "sha256:…" },  // 或 { mode:"programmatic", script, scriptDigest }
  "passed": true | false | null,        // null = inconclusive
  "evidence": { … },                     // 任意 JSON(脚本/子代理给)
  "at": "ISO 时间戳" }
```
**"复现"的口径**:见 §5.1——可重构说明"按什么判、判什么、对哪个对象判",**不承诺模型给相同结论**。

---

## 5. 生命周期与复用(重点)

### 5.1 继承(revalidate_select)
- 每次 run 开始,引擎做"重新验证选择":对每个**叶**,比对**判据锚**(对象捕获 digest + instructionHash/脚本身份)与上一次非 running run 的记录;
- **都相同 → `inherited`**(复用上次 verdict+evidence,**0 token**);
- **任一不同 → 重新判定**(新 digest)。
- ⚠️ **对 agentic 这意味着**:改 instruction **一个字** → 重判;**不改** → 永远复用上次判读(模型行为漂移对此不可见——见 §6.4 局限)。

### 5.2 宿主重启 / 残局
- 引擎/宿主重启时,凡遗留 `running` 的 run → **启动即标 `cancelled`**(run 级+每个未终态 goal 级),状态面板立即可见
- **已结算的叶子记录保留**;重跑同图 → 那些叶被继承,只有没跑完的重新判——**这是"接着成果继续"的方式**
- 不要再尝试"原地续跑同一个 run";**新 dog_run 就是续借成果的正道**

### 5.3 取消
`dog_cancel` 停止运行;部分记录保留,同上。

---

## 6. 环境事实(你不改配置,但必须知道)

| 配置键 | 意义 | 你需要注意 |
|---|---|---|
| `dog.workspaceRoot` | 捕获对象的工作区根(对象来源) | 图里 `target` 必须**相对这个根**;绝对路径 = 校验拒绝 |
| `dog.scriptsDirectory` | 程序化脚本库(`~/.dsh/dog/scripts/` 默认) | 只能引用已存在脚本 |
| `dog.storageDirectory` | 存储根(`~/.dsh/dog/`) | 图/runs/artifacts/事件全在这;**不要删**(历史+归档) |
| `dog.maxSandboxBytes` | 单对象捕获上限(默认 64MiB) | 目录 tar 超限会失败 |
| `dog.maxConcurrentVerifications` | **agentic 并发预算**(默认 1) | **程序化叶不受此限制**(条件满足即跑) |
| `dog.allowPartialRoot` | 是否允许根"部分通过" | 默认 false:有容忍失败也按失败处理 |
| `dog.revalidateThreshold` | 继承后重跑比例警告阈值(0.3) | 超限会在 `warning` |
| `dog.gmDigestAlgo` | 判据哈希算法 | 默认 sha256 |

settings 由 **host 维护**(改后重启);**agent 绝不改配置,也不把配置写进图**。

---

## 7. 怎么把 DoG 跑起来(安装与启动)

> 这一节写给"要让 dsh 里出现 DoG 的人"(宿主/运维视角)。agent 只需要知道:`dog_*` 工具**存在于你的工具面**时即可用;它们需要 dsh 是**常驻进程**(web/tui)。

### 7.1 构建插件
```sh
git clone <your-fork-or-repo> dsh-dog && cd dsh-dog
pnpm install
pnpm run check        # = typecheck + 33 tests + build(lib/)
```
产物在 `lib/`(插件的 server+client bundle);`cordis.patch.yml` 是插件入口清单。

### 7.2 安装到 profile
```sh
dsh plugin --profile web add "$PWD"        # 主推荐:UI 面板 + 工具面(常驻)
dsh plugin --profile tui add "$PWD"        # 交互终端(常驻)
```
profile 之间独立;装哪个,哪个才有 DoG。

> **禁止安装/使用 headless profile**:已知问题——headless 是一次性进程,回答完就退出,
> 会杀掉它 fork 的 agentic verifier 子代理(引擎已如实降级为 `needs_human`/中断,但这不是可用路径)。
> 所有 DoG 工作请在 **web / tui(常驻)** 会话中进行。

### 7.3 用户级配置(一次性)
`~/.dsh/settings.yaml` 的 `dog:` 段(字段见 §6)。**由宿主维护**;改完**重启** dsh 生效。配置文件里只有这个,各 profile 共享。

### 7.4 启动与验证
```sh
dsh web --port 3080            # 常驻;日志无 "workspaceRoot must be absolute" 等错误
dsh plugin --profile web --dump-config | grep dsh-dog   # 确认插件已装配(web profile)
```

### 7.5 ⚠️ 运行环境要求(只支持常驻进程)
- **agentic 叶会 fork 常驻 verifier 子代理(活在本进程)**。所以:
  - `dsh web` / `dsh`(tui)= 常驻 → agentic 可跑
  - **任何一次性/会退出的启动方式都不行**(含 headless 已知问题、脚本 `&` 后台进程)——不要用
- 日常做法:在 web 会话里创建+运行。
- 面板(DoG Debugger)在 web 右上/插件槽;只读,不暴露对象字节。

---

## 8. 从 dsh 实例读取结果(工具面之外的读取方式)

> 主路径仍是 **`dog_status` / `dog_wait`**(§1-2)+ **面板**(web,肉眼)。下面是**进程外/取证**读取——宿主机上直接翻开数据。

### 8.1 数据在哪里(全在 `~/.dsh/dog/`)

| 路径 | 内容 | 定位方式 |
|---|---|---|
| `runs/<hash>.json` | 完整 DogRun:`goals`(每叶 `verification`:verdict/evidence/judgment)、`rootState`、`runtimeWarning`、`gmDigests`、`invocation`、`workspaceBaseDir` | 文件名 = `sha256Json(runId)`(hash,见 8.2);或用过滤脚本遍历(8.3)|
| `verifications/<runId>.jsonl` | 每个叶一行 verification(goalId/verdict/evidence/at) | **文件名就是 runId**(最易找!先用它)|
| `runtime-events/<hash>-<hash>.jsonl` | 每个 goal 事件流(goal_started/verifier_started/…/goal_settled,含 attempt/at) | `sha256Json(runId)-sha256Json(goalId)` |
| `graphs/<graphDigest>.json` | 编译后图 + `acceptancePlans`(判据锚:instructionHash/scriptDigest,input.digest) | 从 run 的 `graphDigest` |
| `artifacts/sha256_<digest>.bin/.json` | 捕获对象字节 + 清单(path/digest/byteLength) | 从 plan.input.digest |
| `settlements/<hash>-<hash>.json` | **verifier 结算文件原文**(合成系 `content`,存活期永不再被工作区清理删除) | `sha256Json(runId)-sha256Json(goalId)`;用于回看"当时判了什么/怎么建议的" |
| `graph-index/<hash>.json` / `locks/` | id→digest 索引 / 跨进程文件锁 | 一般不用动 |

### 8.2 定位算法(`sha256Json`)
runs/runtime-events 的文件名用**规范化 JSON 的 SHA-256**(key 递归排序后再序列化):
```bash
node -e 'const c=require("crypto");
const v="<runId>";  // 标量就是它本身
console.log(c.createHash("sha256").update(JSON.stringify(v)).digest("hex"))'
```
对象要排序:用仓库的 `canonicalJson`(递归 key 排序);标量(如 runId 字符串)无差异。

### 8.3 最省事的读法(建议顺序)
1. **按 runId 找 verdicts**:`read ~/.dsh/dog/verifications/<runId>.jsonl`(文件名就是 runId,无需 hash)
2. **按内容找完整 run**:`bash` 一行(SHA 后过滤更直觉):
   ```bash
   python3 -c "
   import json,glob
   for p in glob.glob('/Users/<you>/.dsh/dog/runs/*.json'):
       d=json.load(open(p))
       if d.get('runId','').startswith('<前缀>'):
           print(p); print(json.dumps(d['goals'],ensure_ascii=False)[:2000])
   "
   ```
3. **事件流(需要 hash)**:拿到 runId/goalId 后按 8.2 计算,或 `glob ~/.dsh/dog/runtime-events/*` 按 mtime 找最近文件。

### 8.4 读什么(取证视角)
- "这轮到底判了什么/为什么" → `runs/<hash>.json` 的 `goals[*].verification` + `reason`
- "对象当时是什么字节" → `artifacts/<digest>.bin`(配合 `.json` 清单里的 digest 对齐)
- "谁在什么时间做过什么" → runtime-events;verifier 子代理会话在 `goal.agentSessions`
- "图/判据有没有变" → `graphs/<digest>.json` 的 acceptancePlans;与当前 create 对比

### 8.5 面板(人看)
web 的 DoG Debugger:图修订、run 历史、节点状态+defect、事件流、证据摘要 —— 只读、不暴露对象字节。用鼠标"点开节点"即可;与 §1 工具面数据同源。

---

## 9. 常见错误 + 诊断表(实测集)

| 症状 | 原因 | 处理 |
|---|---|---|
| `$.schemaVersion: expected 0.9` / `unknown field verifierParams` / `verifier.mode: expected one of programmatic, agentic` | 用了 0.2 旧格式图 | 按 §3 重写(只有两种 verifier;无 verifierParams) |
| `dog_create` 返回 `exists:false, digest:"missing:9ed5…"` | 对象在引擎工作区没找到 | 确认文件在 `dog.workspaceRoot` 下且 `target` 相对;若文件存在仍 missing → 工作区配置问题,报宿主 |
| `programmatic script not found in library: …slop-phrases` | 脚本库没有这名(或写错名) | 用库内实际名(`slop-phrases`/`file-non-empty`);要新增需宿主加脚本,或换 agentic |
| 子代理写结算文件后 `path open failed: …does not exist` | `~/.dsh/dog/` 或 workspace 被清理(旧版竞态;v1.0 已修:workspace 存活至 run 结束) | 换新引擎重跑;若复现即 bug,报宿主 |
| 面板 "Refresh failed: …must be a boolean/null / phase is invalid" | 旧数据/旧记录进入快照 | 新引擎已过滤/放宽;若再现,报宿主 |
| `Only message from last completed turn` / 会话"已停止"并停在某一步 | 被引擎释放/中断的子代理会话继续打字(旧版竞态) | v1.0 已消除主因;若看到,忽略该子代理会话,重跑 run |
| 节点一直 `running` 但事件已 settled(旧数据) | 叶结算未即时落盘(旧版) | v1.0 已修;新 run 不会出现 |

---

## 10. 撰写高质量图的实践(必读)

**instruction 怎么写(agentic 判据质量 = 这一切的上限)**:
1. **一句明确的判据**,不要"尽可能……"——写清**标准的边界**:什么算通过、什么不通过;
2. **要求给出证据**:指示"给结论与证据",并规定证据颗粒(逐句/逐段、行号引用)
3. **写给"一无所知但目光锐利"的审查者**:假设它只看到对象本身(它确实只看到对象);把需要背景的概念写进 instruction
4. **负向优先**:如"删掉不改变意思的空洞句"比"句子要有内容"更可操作
5. 一个 leaf **只判一件事**;不要一个 instruction 摞 5 个维度(判据含糊 → 边界难测)

**拆解原则**:
- 大的语义目标(完整性/密度/可读性/气质)→ **agentic**(判断力)
- 可规则化(文件存在、词表命中、页数、尺寸阈值)→ **programmatic**,或甚至**不放进 DoG**
- **每个 composite 之下必须有 agentic 后代**(§0 铁律)
- 需要"各维单独都过、整体又协调"→ 给 composite 配**整体断言**(它们是独立的;它看不到子项 —— 这是防锚定的设计)

**复用/成本**:
- 本地反复微调 → 用同一图 + 改对象;对象+判据不变时叶会 inherited
- 要让**所有**叶重跑(改判据)→ 改 instruction 一个字;或明确告知用户成本
- 大对象(目录)→ 引擎打包 tar;**注意 maxSandboxBytes**

**汇报纪律**:
- `needs_human` **不是通过、不是失败**——用词"无法自动判定,需人工确认"
- inherited 要说明"复用了上次判决(对象与判据未变)"
- 任何"通过"都要带 evidence 摘要(或注明"evidence 见 run <runId>")

---

## 11. 一个可直接抄的完整例子

对象:`harness-article.md`(工作区内);目标:验证这是"真正有质量的文章"(非形式化):

```jsonc
{
  "schemaVersion": "0.9", "id": "article-quality", "root": "root",
  "nodes": {
    "root": { "kind": "composite", "title": "文章质量门禁", "constraint": "hard",
      "target": "harness-article.md",
      "completion": { "op": "all", "items": [
        { "op": "ref", "id": "no-slop" }, { "op": "ref", "id": "dense-fun" },
        { "op": "ref", "id": "readable" }, { "op": "ref", "id": "human-qual" } ] },
      "verifier": { "mode": "agentic",
        "instruction": "把整篇作为整体读一遍:即使每个维度都单独通过,作为一篇完整文章它是否成立(通顺、有立意、结尾收得住)?给结论与证据。" } },
    "no-slop": { "kind": "leaf", "title": "AI-slop 味", "constraint": "hard",
      "target": "harness-article.md",
      "verifier": { "mode": "agentic",
        "instruction": "检查是否有 AI 味儿:模板腔、'不是X,而是Y'式转折、空口号、模糊词、空洞句(删掉不改变意思)。逐句判定,给证据。" } },
    "dense-fun": { "kind": "leaf", "title": "信息密度与趣味", "constraint": "hard",
      "target": "harness-article.md",
      "verifier": { "mode": "agentic",
        "instruction": "检查信息密度与趣味:每段是否有独立思想(主张+证据/实例),是否只是复述堆字;是否旁征博引;有没有'删掉整段也不损失'的废话段。逐段判定,给证据。" } },
    "readable": { "kind": "leaf", "title": "易懂、符合认知规律", "constraint": "hard",
      "target": "harness-article.md",
      "verifier": { "mode": "agentic",
        "instruction": "以只懂基础概念的读者视角检查:生僻概念/缩写是否先定义后使用;段与段之间是否有'桥'(承接/转折),有无硬跳;是否先提到已有成果/常识、再自然引申到新东西;有无跳跃或含糊。给证据。" } },
    "human-qual": { "kind": "leaf", "title": "人类质感", "constraint": "hard",
      "target": "harness-article.md",
      "verifier": { "mode": "agentic",
        "instruction": "检查是否像人类作者的高质量文本:句式长短交替、每段开头不同构、有立场有判断、具体细节而非抽象套话。给证据。" } },
    "phrase-hint": { "kind": "leaf", "title": "模板词提示(辅助)", "constraint": "soft",
      "target": "harness-article.md",
      "verifier": { "mode": "programmatic", "script": "slop-phrases" } }
  },
  "contains": [
    { "parent": "root", "child": "no-slop", "required": true, "failure": "fatal" },
    { "parent": "root", "child": "dense-fun", "required": true, "failure": "fatal" },
    { "parent": "root", "child": "readable", "required": true, "failure": "fatal" },
    { "parent": "root", "child": "human-qual", "required": true, "failure": "fatal" },
    { "parent": "root", "child": "phrase-hint", "required": false, "failure": "tolerable" }
  ],
  "dependsOn": []
}
```

执行:
```
dog_validate { graph: <如上图> }
dog_create   { graph: <如上图> }       // 确认 acceptancePlans 里 5 个目标 input.exists:true
dog_run      { graphId: "article-quality" }
dog_wait     { runId: "<返回值>" }      // 等通知;终态前不总结
```

---

## 12. 使用清单(整页自检)

发送/执行前:
- [ ] 目标确实**非形式化**(否则别用 DoG)
- [ ] 叶子判据单义;agentic instruction 写清标准+证据要求
- [ ] 无全程序化子树
- [ ] `target` 相对路径;对象在 workspaceRoot
- [ ] programmatic 只引用脚本库内名称;其它用 agentic
- [ ] `dependsOn` 方向正确(`source` 依赖 `target`)
- [ ] root 是 hard composite;fatal 链终点在 root(失败一定传到你/用户)
- [ ] 需要整体协调的有 composite 整体断言

执行后:
- [ ] dog_status 读完所有 goal 状态与 evidence
- [ ] needs_human 如实转达;"继承"如实标明
- [ ] 报告每个 fatal 失败的 defect → 用户知道**为什么**
