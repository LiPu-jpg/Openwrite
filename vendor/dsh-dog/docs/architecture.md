# DoG v0.2 — 架构

本文是 [`SPEC.md`](../SPEC.md) 的执行分层对应,回答三个问题:

1. **模块结构是什么**,哪些节点是程序、哪些是 Agent、哪些是人(§1,`diagrams/architecture.svg`);
2. **每个边界交换什么**,什么格式,由哪个 schema 约束(§2,`diagrams/exchange.svg`);
3. **一次运行如何端到端流动**,每一阶段由谁执行(§3,`diagrams/flow.svg`)。

颜色图例(三张图通用):

| 颜色 | 含义 |
|---|---|
| 绿 | 人(项目负责人) |
| 紫 | LLM Agent 会话(上下文隔离) |
| 蓝 | 程序(宿主代码,确定性) |
| 橙 | 开发 Agent(DoG 之外,抽象) |
| 青 | 现有 CI 流水线(DoG 之外) |
| 灰 | 持久化存储 |

---

## 1. 模块结构

`diagrams/architecture.svg`

三层、一条边界:

- **外部 — 开发侧**:开发 Agent(抽象)与现有 CI 流水线。两者都不出现在 DoG 内部,唯一耦合是产物绑定路径(入)与 `dog_run` / `dog_status` 报告(出)。
- **外部 — 验收侧**:项目负责人。始终拥有目标并确认图。
- **DoG 核心(DSH 插件)**:
  - **工具面**(`dog_validate`、`dog_create`、`dog_run`、`dog_status`、`dog_bind_agent`、`dog_delegate_agent`)— 程序;
  - **Schema 层** — 五个 `schemas/schema-0.2/*.json` 契约。任何载荷在解析或持久化前先在这里校验;
  - **编译器**(图解析 + 静态规则,含纯程序化子树规则、验收计划编译、验证契约解析)— 程序;
  - **调度器**(依赖门禁、隔离工作区池、增量选择)— 程序;
  - **验证执行**:
    - *确定性契约*(`file.exists` 等)— 程序,在隔离工作区内;
    - *Agentic 契约*(`vision.overlap` 等)— 验证 Agent(LLM 会话,上下文隔离,仅 `allowedTools`)在隔离工作区内;
  - **Grounding 提取器** — 程序(宿主注册),`gmDigest` 的唯一来源;
  - **规划 Agent / 覆盖率评审** — 建图时期使用的 LLM Agent,不参与运行期;
  - **存储**(graphs、runs、verifications、artifacts、runtime-events)— 程序,追加写 + 内容寻址;
  - **WebUI 调试器** — 只读程序,基于快照 RPC。

要记住的不变量:运行期唯一会启动的 Agent 是验证 Agent,其余运行期阶段全部是程序。

## 2. 数据交换链路

`diagrams/exchange.svg`

五个规范载荷,各由一个 JSON Schema 约束;另有三条内容寻址字节流。

| 交换 | 生产者 → 消费者 | 格式 | Schema |
|---|---|---|---|
| 图输入 | 规划 Agent → 编译器 | JSON | `graph.schema.json` |
| 运行记录 | 引擎 → 存储 / 状态读取 | JSON | `run.schema.json` |
| 验证记录 | 验证执行 → 存储 | JSONL(每行一个对象) | `verification.schema.json` |
| 运行时事件 | 引擎 → 存储 | JSONL(每行一个对象) | `runtime-event.schema.json` |
| CI 报告 | 引擎 → 开发 Agent / 外部 CI | JSON | `report.schema.json` |
| 产物快照 | 绑定路径 → 产物存储 | 字节 | 内容寻址(`sha256`) |
| 证据对象 | 验证 Agent → 产物存储 | 字节 + JSON 引用 | 契约 `evidenceSchemaId` |
| GM | 提取器 → 引擎 → 运行记录 | JSON(规范化)→ `gmDigest` | 提取器 schema + `gmDigestAlgo` |

规则:不符合所声明 schema 的载荷,在解析或持久化前即被拒绝(关闭式失败)。结构校验在程序侧;`date-time` 字段使用标准 `format`,需要 format 感知校验器。

## 3. 运行流程

`diagrams/flow.svg`

流程刻意分阶段,使得失败结算永远不会停止无关验证(§9.1):传播是**结果**的事,调度是**最大化已完成验证**的事。

```text
建图(人 + 规划 Agent)→ 覆盖率评审(Agent)→ 人确认
→ 编译(程序)→ capture(程序)→ revalidate_select(提取器 + 程序)
→ verify(调度:确定性=程序 / agentic=验证 Agent,隔离工作区)
→ recompute(程序,所有受影响路径)→ 人审(如需)
→ report(程序,机器可读)→ terminal(程序)
→ 开发 Agent 消费报告 → 提交新产物 → 新一轮
```

各阶段要点(细节见 SPEC §16):

- `revalidate_select` 仅凭 GM 摘要 + 契约版本决定重跑或 `inherited`;图边从不决定重验证,`non_programmatic` 叶子无条件重跑。
- `verify` 中每个就绪节点在互斥工作区内运行;失败节点永不取消无关就绪节点。
- `report` 携带 `revalidated` / `inherited` / `warning`;当一次提交触发的重跑数超过 `revalidateThreshold` 时给出阈值警告。
- 开发 Agent 永不调度任何东西、永不改图、只接收 `dog_run` 摘要或完整 `dog_status` 报告。
