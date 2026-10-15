# OpenWrite workspace instructions

本文件适用于整个仓库。目标是让 Codex 基于官方资料和当前实现推进 OpenWrite 的 openJiuwen 迁移，并保护既有小说数据与领域契约。

## Project and QA boundaries

- Use `~/my_novel` as the only project for manual, live-server, and browser QA.
- Do not create or open temporary novel projects for manual QA. Extend `~/my_novel`
  with any fixtures needed to exercise new features.
- Automated pytest cases may use isolated temporary directories, but must inject an
  isolated `ProjectRegistry` and must never write those paths to the user's default
  recent-project registry.
- The OpenWrite framework repository and `reference/my_novel` are not active novel
  projects.

- 框架代码根目录、运行时 workspace 和小说项目根目录是不同路径，不得互相代替。
- `OPENWRITE_CORE` 指向包含 `tools/`、`models/` 的引擎检出；工具的 `project_root` 指向小说项目。手动 QA 使用 `~/my_novel` 的实际展开路径。
- 自动化用例须向被测入口注入隔离的 `ProjectRegistry(path=...)`；需要记住临时项目时使用 `allow_ephemeral=True`。不得依赖默认注册表或先污染再清理。
- 历史文档、示例和测试里的 demo 路径不覆盖以上规则。运行脚本前检查硬编码路径、写操作及注册表访问。

## Reading order and evidence

涉及 openJiuwen 迁移、运行时集成或相关排障时，先读：

1. [资料包入口](openjiuwen_docs/README.md)。
2. [版本与兼容边界](openjiuwen_docs/VERSION_NOTES.md)。
3. [OpenWrite 模块对照](openjiuwen_docs/OPENWRITE_MAPPING.md)。
4. [按任务查文档](openjiuwen_docs/READING_GUIDE.md)，仅选择与当前任务相关的指南、API 和源码。

- [历史迁移计划](docs/迁移计划-openjiuwen原生框架.md) 用于理解已有设计与执行记录；其中“已完成”“已验证”等描述必须结合当前代码和运行证据复核。
- 使用 [完整索引](openjiuwen_docs/INDEX.md) 与 [来源清单](openjiuwen_docs/sources.json) 定位固定 commit 原文。不必一次读取全部快照。
- 判断接口行为时，以实际安装版本对应的源码、包元数据和最小验证为依据。文档与实现不一致时，记录差异，不猜测导入路径、参数或配置字段。
- `openjiuwen_docs/upstream/` 是保留原文的参考快照，不能当作完整 SDK、当前运行环境或项目自动加载的技能。不要直接改写上游原文；分析和勘误写在整理说明中。
- 补充或更新资料时保留来源、采集日期、commit、哈希与许可证。`snapshot.py fetch` 只恢复固定快照，不负责升级版本。

## Runtime and dependency compatibility

- 修改框架集成或安装依赖前，核对实际使用的 Python、包名/版本、安装来源、Swarm/Core commit 及相关锁文件。无需为无关的小修改重复检查整个环境。
- 资料中的 Agent Core 与 JiuwenSwarm release 是阅读基线，尚未作为组合验证；Swarm 固定依赖的 Core commit 与包中 Core release 不同。
- JiuwenSwarm 的 release 标签、源码中声明的 `workswarm` 包名/版本、文档中的 `jiuwenswarm` 安装命令不能相互替代。按实际交付安装物确认命令和依赖。
- 快照中的框架要求 Python `>=3.11,<3.14`，OpenWrite 当前声明 `>=3.10`。修改 Python 下限或依赖约束时，同时核对运行环境、项目配置与锁文件。
- 不混用不同版本或 legacy 示例中的 `ReActAgentConfig`、模型配置、`Runner` 和会话接口；不因文档出现新版本就批量升级依赖。

## Migration architecture

默认沿用已有迁移方向：JiuwenSwarm 承担团队运行，SwarmFlow 承担确定性编排，Skills 承载领域流程，MCP 暴露 OpenWrite 引擎能力。领域引擎通过既有 Python 模块复用；改变这一分工须有当前任务的明确需求和验证依据。

| 工作范围 | 当前代码入口 | 优先参考 |
|---|---|---|
| MCP 工具与引擎桥接 | `openwrite-mcp/server.py` | Swarm MCP 配置、Core MCP 工具与传输示例 |
| 多智能体编排 | `openwrite-novel-swarm/scripts/workflow.py`、`roles/` | SwarmFlow 指南、实际依赖版本的 facade/primitives |
| 技能与角色协议 | `openwrite-novel-swarm/`、`openwrite-skills/` | SwarmSkills、官方技能模板和校验器 |
| 领域状态与上下文 | `tools/`、`models/` | 上下文引擎、记忆、权限与恢复文档 |
| 工作台集成 | `tools/studio*.py` | 会话、流式输出、取消和调试追踪文档 |

- Agent Core `Workflow`/`WorkflowAgent` 与 Team 的 SwarmFlow 属于不同编排接口，不混用导入路径或恢复协议。
- `from swarmflow import ...` 由框架运行时映射提供。不要通过安装一个同名第三方包来解决导入问题。
- 保持技能入口、角色输出 schema、`dependencies.yaml`、编排脚本和 MCP 工具名称/参数一致；以当前工具注册和签名核对清单，不依赖历史工具数量。
- 保持写作与评审的角色边界、六域评审契约及确定性聚合规则。处理 schema 无效、结果为 `None`、部分失败、超时、取消、预算耗尽和回炉上限，不把缺失结果视为通过。

## Domain state and write contracts

- 章节正文、人物与世界状态、truth、伏笔 DAG、大纲和 canonical context packet 继续遵循 OpenWrite 的权威领域契约。
- 对话记忆、框架长期记忆和上下文压缩不能直接覆盖小说正典。持久化变更走现有领域服务与写入入口。
- 保留作者批准、变更预览、revision/指纹重验、影响域复核、幂等及项目写锁。角色提示词或 approval 布尔值不能替代服务端校验。
- 不直接编辑生成状态文件来绕过接纳或修订流程。涉及数据格式变更时，明确兼容、迁移和恢复路径。
- 中断与重入须绑定同一项目、章节、产物版本和操作状态；恢复不能重复写章、接纳、结算或导出副作用。
- 当前工作流使用 gate payload 与 approval args；若接入 `human`/`human_session`，验证等待、拒绝、恢复与批准失效的语义后再声明支持持久化审批。

## MCP and async integration

- stdio 的 stdout 只输出协议消息，日志写 stderr；错误应能区分配置、工具参数、领域冲突和执行失败。
- 按实际运行时核对 `mcp.servers`、transport、command、args、cwd、env 和 timeout；不假定常驻服务或 MCP 子进程继承当前 shell 的环境。
- 配置模型或 MCP 时使用变量/占位符与现有配置机制；不得将密钥或含凭证的配置输出到日志、测试产物或版本库。
- 已有部分同步引擎入口内部调用 `asyncio.run`；从异步 MCP 工具调用时保留适当的线程桥接或改为一致的异步调用链，避免嵌套事件循环。
- 使用 `asyncio.to_thread` 时不能假定取消等待会终止线程；核对实际写操作、锁与任务状态，避免取消后重试引发并发写入。

## Implementation and validation

1. 先说明本次修改范围、已发现的差距与可验证的验收标准，然后继续实现；不把阅读资料扩大为无关的全仓库重构。
2. 优先复用现有领域模块和契约，做与目标直接相关的最小修改。
3. 根据改动选择测试：纯逻辑用桩件/单元测试，MCP 接入验证发现与调用，框架接口验证实际运行时，交付闭环再做真实模型和浏览器 QA。
4. 变更涉及持久化、审批或恢复时，覆盖拒绝、过期批准、重复请求、并发冲突、失败与重入等相关分支。
5. 报告修改、实际执行的检查、版本组合与未验证边界。区分静态检查、桩件测试、真实框架调用和真实模型端到端结果。

从仓库根目录使用选定环境的解释器运行检查。按任务选择以下入口：

```bash
python3 openjiuwen_docs/scripts/snapshot.py verify

# Python 自动化测试；优先指定与本次改动相关的文件或用例
python -m pytest tests/ -q
```

- 执行 pytest 前确认所选用例满足项目/注册表隔离规则；有默认注册表副作用的既有用例先修正隔离。
- `openwrite-novel-swarm/tests/test_workflow_stub.py` 与 `openwrite-mcp/tests/test_write_path.py` 含历史机器路径，后者还会写项目数据。核对并适配后才能运行，不能直接作为可移植的默认检查命令。
- 上游 swarmskill 校验器可用于技能结构检查；执行前核对所选版本和输入路径。结构检查通过不能替代运行时兼容验证。
- 不为纯文档或低影响改动无条件运行真实模型、全量端到端测试；未运行的检查及原因如实说明。

## Competition materials

- 涉及参赛方案或演示时阅读 [赛事摘要](openjiuwen_docs/COMPETITION.md)，提交前重新核对官方页面的赛程与要求。
- 区分官方要求、推荐做法与项目设计选择，不编造评分权重、指定 SDK 版本或框架使用限制。
- 用可复现的版本、调用轨迹与产物支持技术描述，不将历史计划或桩件输出写成当前实测结果。
