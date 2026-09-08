# 调查:跨进程会话冷加载导致 `interrupted-tool-result` 伪中断注入

日期:2026-08-23
结论:**dsh 内核问题(与任何插件无关)**。headless 进程运行长工具时,另一个进程(web)打开同一会话详情会触发会话"冷加载 + 崩溃修复",向**正在运行的会话日志**注入伪 `interrupted-tool-result`,导致 UI/模型看到"工具中断/失败",而引擎实际正常完成。

---

## 1. 现象

- 主 agent 回合在等待长工具(`job_output wait:true` / `bash sleep 25`)时:
  - 会话日志在同一毫秒出现 `tool/result`(`id: interrupted-tool-result-...`,`ToolOutcomeUnknownError`)
  - 随后 `step/end` + `turn/end { reason: interrupted }`
  - **但不是真失败**:后台工具继续运行,真实结果在 N 秒后补入日志(`tool/result` 无 error),回合继续并最终 `turn/end { completed }`——引擎没有死,日志被"伪中断"污染(同一 callId 出现两条 `tool/result`)。
- UI 把该占位渲染成红色"失败/已停止"文案(因为 `isError: true`),用户以为会话被真实停止。

## 2. 根因链(源码级)

1. **唯一定义**:`interrupted-tool-result` 全部库中只有一处生成——`@deepseek-ai/dsh-session/lib/types/repair.js` 的 `interruptedTurnClosers(events)`:
   - 扫描事件流,若日志尾部是**未闭合 turn 且有 pending 工具调用(assistant 的 tool-call 块已记录但无 tool/result)**,则合成:
     - `tool/result`(interrupted,`isError: true`, `TOOL_OUTCOME_UNKNOWN`/`TOOL_NOT_STARTED`)
     - `step/end` + `turn/end { reason: "interrupted" }`
   - 注释原文:用于 **crash tail 恢复**("a valid committed prefix, possibly with a crash tail")——**设计目标是崩溃恢复,没有"会话仍活跃"的判断**。
2. **触发入口**:`@deepseek-ai/dsh-session-persistence/lib/index.js`:
   - `SessionPersistence.load(id)` / `adopt(id)` / `prepare(id)` → `prepareCore(id)`(注释:`Read, repair in memory, validate, and freeze one cold source once`)。
   - 当该会话**在本进程 ctx 中不是 live**(`ctx.sessions.get(id) === undefined`)时走冷加载;冷加载即调用 `interruptedTurnClosers` 修复"未闭合尾部"。
3. **跨进程并发**:headless 进程持有 live 会话并在执行长工具;web 进程(不同 ctx)因 UI 打开该会话详情而 `load(id)` → 它不认为该会话 live → 冷加载 → `prepareCore` → repair 合成伪中断事件,并**落盘进同一会话日志**;主引擎随后写入真实结果 → 出现同 callId 双 result。
4. **UI 文案**:repair 合成的 `tool-result` `isError: true`,前端将其渲染为失败/中断。

## 3. 复现(纯官方,无任何插件)

### 实验记录

| 实验 | headless | web | 打开会话详情 | interrupted 注入 |
|---|---|---|---|---|
| B0 (session-e301) | headless-bare(官方) | 无 | - | ✗ |
| b1ls2 (**session-be7e**) | headless-bare | web-bare(3081) | **是** | **✓ 17:11:59 同一毫秒注入;17:12:24 真实结果;completed** |
| b1ls3/b1ls4/b1ls5 | headless-bare | - | - | 模型未执行 bash(直答);实验无效 |
| b1ls6 (**session-e316**) | headless-bare | **web-bare(3081,纯官方)** | **是** | **✓ 17:15:00 同一毫秒注入;17:15:25 真实结果;17:15:26 completed** |

b1ls6 日志(`session-e316`)为最终铁证:

```
82  17:15:00  tool/call  bash(command: sleep 25)
83  17:15:00  tool/result  interrupted-tool-result ... TOOL_OUTCOME_UNKNOWN   ← 同一毫秒
85  17:15:00  turn/end  { reason: interrupted }
83  17:15:25  tool/result  (no output), error={}                              ← 25s 后真实结果补回
113 17:15:26  turn/end  { reason: completed }                                 ← 引擎正常完成
```

### 复现步骤(PR 附件可用)

1. 建 `headless-bare` profile:`bundles: [@deepseek-ai/dsh-base, @deepseek-ai/dsh-headless]`(无插件)
2. 建 `web-bare` profile:`bundles: [@deepseek-ai/dsh-base, @deepseek-ai/dsh-web-app]`(无插件),启动(如 3081)
3. headless 任务:"第一且唯一一步:调用 bash 工具,命令为 sleep 25。调用完成后即可结束任务。直接输出没有任何工具调用的话任务不完整,所以必须调用 bash。"
4. bash 开始后(约 10-15 秒),用 web UI(另一进程)打开该会话详情
5. 打开瞬间 → 会话日志出现 `interrupted-tool-result`(`ToolOutcomeUnknownError`);25 秒后真实 `tool/result` 补入,`turn/end { completed }`

## 4. 修复建议(PR 要点)

1. **`dsh-session-persistence` `prepareCore`/`load`**:冷加载前检测会话是否仍被**活跃 writer** 持有(官方已有 heartbeat / tornMarker / revision 机制),活跃则**跳过 `interruptedTurnClosers`**,返回"运行中"标记或只读视图,不做修复。
2. **修复事件禁止持久化**:`interruptedTurnClosers` 合成结果仅限内存视图;`commitPrepared` 在"存在活跃 writer"时不得写盘——杜绝同 callId 双 `tool/result` 的不变量破坏。
3. **`dsh-web-app` 会话详情 API**:对活跃中的会话走 live 只读投影(`loadLiveSnapshot` 已有),**绝不冷 load 一个正在运行的会话**。

## 5. 现场对照

- 2026-08-23 16:52 主会话(`session-f8421af9`):`job_output wait:true` 调用同一毫秒注入 interrupted;89 秒后真实结果;回合随后 completed——与上述复现完全同模式(当时 web UI 正打开该会话,用户在看)。
- 期间曾误判为"工具 wait 语义""通知注入打断"等,均被时序与源码排除(通知晚 89 秒才到;`interrupted-tool-result` 全库唯一生成点=repair)。
