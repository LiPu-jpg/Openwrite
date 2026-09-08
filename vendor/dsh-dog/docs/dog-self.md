# dsh-dog 自身 DoG(基线蓝图 & 备忘录)

> 轻量版:这是「要求清单 + DoG 蓝图 + 执行约定」的备忘录。
> 不是可立即 `dog_create` 的运行图:每个程序化叶子执行时需把验证结果绑定为 artifact(如 test-report、audit-log),每个 composite 至少补一个 agentic 叶子(契约待挂:如 `doc.review` 或直接路由 human in the loop)。
> 建立日期:2026-08-23(基于彼时对话中用户验收标准与实测修正)。

## §1 严格要求清单(用户/宿主验收标准)

以下是被明确要求或从实测修正中沉淀的硬性标准,任何改动不得违反:

| # | 要求 | 依据 |
|---|------|------|
| R1 | **配置与 profile 解耦**:插件配置(artifactRoots/artifactBindings/存储/上限)只存在于 `~/.dsh/settings.yaml` 的 `dog:` 命名空间;任何 profile 的 `cordis.patch.yml` 不得含 `dsh-dog` 的 `config` 块 | 用户指出 profile 是 dsh 启动层,与插件配置不是一个层级;迁移后 4 个 profile 已清空 |
| R2 | **不向 Agent 暴露部署层**:skill 中不得出现 `dsh --profile`/`--host`/`--port` 启动命令;profile 只作为「宿主环境事实」陈述;agent 只需用工具 | 用户改造 skill 的明确要求;当前 SKILL.md 已零命令残留 |
| R3 | **引擎时序正确**:engine 惰性构造(首次工具调用时才建),保证 settings attach 后 bindings 已决;不得再在 attach 前构造出空绑定 | 本次修复的根因(unknown host artifact binding deck 两连) |
| R4 | **验证三态与证据绑定**:pass/fail/inconclusive 必须带 observation 证据;无证据 → inconclusive → needs_human | DoG v0.2 语义 |
| R5 | **确定性检查用程序化,主观/视觉用 agentic,其余 human in the loop**;建图者与验证者分离,验证者上下文隔离(干净 session,只读 artifact + 写 settlement) | DoG 信任边界 |
| R6 | **图结构纪律**:root 必须 hard;leaf 必须有 verifier;composite 不能有 verifier;completion AST 仅 `ref/all/any/not/atLeast`;未知字段(含 `merge`)拒绝;每个 composite 至少一个非程序化后代 | schema-0.2 规则 |
| R7 | **增量语义**:程序化叶子 GM 摘要+契约版本双匹配才 `inherited`;agentic 永远重跑 | DoG v0.2 增量 |
| R8 | **失败传播**:tolerable→partial、fatal→failure、degrade→兄弟替代;根节点不允许失败 → 根失败必须 human in the loop | 用户设计决策 |
| R9 | **命名语义化**:宿主 binding id、goal id 等命名要向作者/用户可解释(如 `deck` = xpipeann-deck.pptx 需在设置/文档中明示对应文件) | 用户对「deck 是什么」的质疑 |
| R10 | **交付健康**:`bun run check`(typecheck+test+build)全绿才是完成;契约测试必须在注入 bug 时挂 | 工程惯例 |
| R11 | **存储与监督**:全部状态在 `~/.dsh/dog`(追加写、immutable snapshot);30s 心跳、孤儿 reap、新 run supersede 同图旧 running | DoG v0.2 |

## §2 DoG 蓝图(goal 层,root=做好 dsh-dog)

> 注意:goal 节点只写「要达成什么」,不写实现条款。
> 细则(如 root 必须 hard、completion AST 仅 `ref/all/any/not/atLeast`、未知字段拒绝、无 merge)是 **spec 条款**,
> 在叶子验证时作为规则引用,自身不成为节点。

```
root(all): 做好 dsh-dog(可信、可交付、可自证)
├─ G-统一:规范-实现-文档三方一致
│   ├─ G1-1 spec 与实现一致(SPEC.md 条款 ↔ 代码/测试行为)
│   ├─ G1-2 skill 与实现一致(SKILL.md 工具面/契约/语义真实可用)
│   └─ G1-3 配置说明与真实配置源一致(settings `dog:` 段唯一源,文档/示例不漂移)
├─ G-自举:项目能通过自身的 agentic CI(DoG)
│   ├─ G2-1 自身图合法可构建(dog_create 通过)
│   ├─ G2-2 自身验证可运行(程序化叶子全绿 + 报告成形)
│   ├─ G2-3 自身验证可由人类审查(doc/命名/可读性,human in the loop)
│   └─ G2-4 验收产物可交付(CI 报告/证据可溯源)
├─ G-正确性:核心验证语义可信
│   ├─ G3-1 验证结果可信(三态 + 证据绑定,无证据不判 pass)
│   ├─ G3-2 失败语义正确(容忍/传播/降级/根不容忍)
│   ├─ G3-3 增量语义正确(双匹配才继承,agentic 必重跑)
│   └─ G3-4 验证过程可信(隔离工作区、快照不可变、无 merge)
├─ G-架构:边界干净、生命周期正确
│   ├─ G4-1 配置与 profile 解耦(plugin 配置不落 profile)
│   ├─ G4-2 部署层对 agent 不可见(skill 无启动命令/配置细节)
│   └─ G4-3 引擎生命周期正确(settings 就绪后绑定才可决,惰性构造)
├─ G-交付:可发布状态
    ├─ G5-1 全量检查全绿(typecheck+test+build)
    ├─ G5-2 测试有验证力(注入 bug 会被契约测试抓住)
    └─ G5-3 运行环境兼容(宿主 dsh 版本 / Node 20/22)
└─ G-运行:运行平稳且高效(以实际运行轨迹为准)
    ├─ G6-1 已见轨迹无矛盾点(审计真实会话/trace:不存在让模型困惑或卡死的矛盾)
    ├─ G6-2 文档之间同步(SPEC/SKILL/README/architecture 交叉一致,无互相矛盾的表述)
    ├─ G6-3 无低效冗余路径(快速路径照抄即通;无浪费的预检/重复读取/重复构建)
    └─ G6-4 稳定性监督有效(心跳/超时/孤儿处理不卡 run;并发上限与资源匹配)
```

## §3 节点表(每个子目标是「达成」,验证时才引用条款)

| Goal | 达成判定(验证方式) | 关键规则引用(§1 对应条目) |
|------|--------------------|--------------------------|
| G1-1 | SPEC 条款与实现逐条对齐(程序化:审计清单+测试) | R6/Schema 条款 |
| G1-2 | SKILL.md 工具面 = 实际注册工具(程序化:对拍清单) | R2 |
| G1-3 | settings `dog:` 段与文档示例一致(程序化:对拍) | R1 |
| G2-1 | 自身蓝图(§2 此图)能 `dog_create`(程序化入 CI) | R6 |
| G2-2 | 自身 run 程序化叶子全绿、根成功(程序化+agentic) | R3,R10 |
| G2-3 | 人工审查文档/命名/可读性(human in the loop) | R9 |
| G2-4 | 验收报告为可溯源 artifact(程序化:文件+sha256) | R8,R11 |
| G3-1 | 三态+证据契约测试覆盖(注入无证据场景必挂) | R4 |
| G3-2 | 失败传播矩阵测试(容忍/降级/根) | R8 |
| G3-3 | 增量双匹配测试(inherited/重跑) | R7 |
| G3-4 | 隔离与快照测试(越界/篡改必挂) | R5,R11 |
| G4-1 | grep 断言:profile 无 dsh-dog config;settings 唯一源 | R1 |
| G4-2 | grep 断言:skill 零 `--profile/--host/--port` | R2 |
| G4-3 | 集成断言:bindings 首用时已决(日志/测试) | R3 |
| G5-1 | `bun run check` 全绿(CI 产物) | R10 |
| G5-2 | 契约测试有效性(bug 注入实验) | R10 |
| G5-3 | 宿主兼容冒烟(两个 profile 环境) | R11 |
| G6-1 | 真实运行轨迹审计(agentic/human:找矛盾/困惑点,如工具冲突、字段不一致、prompt 歧义) | R2 |
| G6-2 | 文档交叉对拍(程序化:矛盾表述扫描;human 复核) | R1,R2 |
| G6-3 | 轨迹轮次统计对比(程序化:session JSONL 轮次/token,异常高于基线即告警) | R10 |
| G6-4 | 监督机制测试(心跳/孤儿/supersede;资源上限跑满验证) | R11 |

完成逻辑:每个 composite `all`;failure 策略:机器可判的叶子 `fatal`,human 审查叶子 `tolerable`(标记 partial 不阻塞机器结论)。

## §4 执行约定(一轮迭代)

1. 改动 → `bun run check`(typecheck + test + build)全绿
2. 按 §2 图逐项打点:S1–S4、V1–V4、W1–W3、C1–C3、T1–T2、D1–D2、K1–K2 由测试/断言覆盖;C4 在 dog-solo profile 冒烟;D3/K3 由人工抽查
3. 任何新增行为 → 先补契约测试(D2 原则:注入 bug 必须能被测试抓住)再加功能
4. 配置变化 → 只改 settings.yaml `dog:` 段(备份 + 改后重启宿主进程);图/SKILL.md 同步更新
5. 记忆沉淀 → 完成后更新本文件「当前状态」节

## §5 当前状态(2026-08-23)

- [x] R1 迁移完成:4 个 profile 的 dsh-dog config 已清空;settings.yaml `dog:` 段生效(日志:bindings=release-evidence/escalation-evidence/deck)
- [x] R2 skill 修订:零启动命令残留;改为「宿主环境事实」
- [x] R3 惰性引擎:lib 已构建、3080(pid 3038)已重启;真实图 validate→create→run 全链路通过(ppt-agentic-demo,runId 48661c74)
- [x] R4–R8 语义基线:已由 core/plugin/agentic-runner/verifier-file 测试覆盖
- [ ] G2-3/G2-4 的 human-in-the-loop 契约定未挂(下次真实执行前补齐)
- [ ] R9 命名说明:已在 settings.yaml 注释与本文档 §1 明确;若改 id 需同步图
