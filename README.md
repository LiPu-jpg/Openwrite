# dsh-Openwrite

[OpenWrite](https://github.com/LiPu-jpg/Openwrite) 是本团队的小说创作核心项目；
**dsh-Openwrite 是 OpenWrite 的 DeepSeek Harness 插件版本**，将同一套长篇小说创作能力接入
[DeepSeek Harness (dsh)](https://github.com/deepseek-ai/deepseek-harness) 的 agent 运行时和原生工作台。

为兼容现有安装、审稿产物和浏览器草稿，内部 npm scope、Schema 版本与存储键继续使用
`@dsh-novel/*` 和 `dsh-novel.*`；这些稳定标识不影响对外产品名。

评审 v2、双 DAG 与模型测试台的跨仓库目标、当前状态和续跑入口统一维护在
[GOAL.md](GOAL.md)。后续 Goal 应先读取该文件，并以当前工作树和验证日志为准继续。

- **dsh** 负责 agent 编排：OpenWrite 单一创作预设、技能目录、子代理委派、长上下文压缩
- **OpenWrite** 负责小说领域能力：规范阅读顺序、稳定场景结构、章节流水线、六域累加评审（兼容 37 项查询）、伏笔 DAG、正典状态
- **OpenWrite Studio** 在本插件版本中提供无界面的小说领域 HTTP 后端；dsh 是唯一交互壳与编辑工作台

架构与职责划分见 [DESIGN.md](DESIGN.md)。

## 组件

| 路径 | 说明 |
|---|---|
| `packages/openwrite-bridge/` | dsh 插件：90 个 `novel_*` 工具，覆盖 Studio HTTP 动作面并提供隔离模型横评与脱敏 trace |
| `packages/studio-panel/` | dsh web 原生工作台：创作 / 资料 / 任务，含规范章节导航、连续审读、场景双序、正文编辑器、双 DAG、模型测试台与工具卡 |
| `presets/openwrite/` | OpenWrite 全流程 agent 预设（规划/资产/写章/评审/修订） |
| `scripts/install.sh` | 构建插件、安装预设到 `~/.dsh/.agent-presets/`、插件装进 dsh profile |
| `scripts/dev.sh` | 一键启动 OpenWrite Studio + dsh web |
| `scripts/verify.sh` | 一键集成验证（服务、领域代理、失效快照、本地编辑器资源、无 iframe） |
| `conductor/` | Python 编排器：无人值守连续写章 → 六域评审 → 修订/应用/复评闭环（走 OpenWrite 后台任务系统；详见 DESIGN.md §6） |

## 快速开始

前置：Node ≥ 22.19、npm、pnpm、rsync、[uv](https://docs.astral.sh/uv/)，
以及本地 OpenWrite 源码（默认相邻 `../OpenWrite`，可用 `OPENWRITE_DIR` 指定）和一个小说项目
（默认 `~/my_novel`）。
安装和离线验证不调用模型；使用创作 Agent 时配置 `DEEPSEEK_API_KEY` 或 dsh 凭据。

```sh
scripts/install.sh   # 一次性安装（幂等）
scripts/dev.sh       # 启动两端服务
```

当前兼容基线为 **DSH 0.1.0-rc.7 / Cordis 4.0.1**，三个依赖锁文件一起维护。
安装器使用 `npm ci` 和官方插件命令，重复运行可修复漏登记的 bundle。
启动器在退出/Ctrl-C 时清理自己启动的两端进程；已有同端口服务会阻止重复启动。

## 插件开发与维护

建立方法、官方资料、版本升级、安装更新和回退流程见
[维护手册](docs/PLUGIN_MAINTENANCE.md)。本轮工程维护与模型工作台回归证据见 [GOAL.md](GOAL.md)。

[标准章节审稿 DAG](docs/REVIEW_DAG_FRAMEWORK.md)：一次定义、逐章实例化的六域 37 项审稿框架。
开源写作软件、AI 工具和编辑器插件的对照，以及当前产品差距与验收建议，见
[小说工具调研与改进清单](docs/OPEN_SOURCE_NOVEL_AUDIT.md)。
用户指定的七个项目的固定版本、源码实现和改进优先级，见
[七项目专项对照](docs/TARGETED_NOVEL_PROJECT_REVIEW.md)。
七个框架的社区/源码/测试静态统计、功能成熟度矩阵、各自优势和 OpenWrite 的相对位置，见
[框架优势与统计](docs/FRAMEWORK_ADVANTAGES.md)。
基于现状的实施顺序、跨仓库分工、依赖与验收条件见
[插件完善计划](docs/IMPROVEMENT_PLAN.md)；实际完成状态继续记录在 [GOAL.md](GOAL.md)。

```sh
npm run check:plugin           # 构建、doctor、生命周期、预设、smoke、epochs、组件测试
npm run check                  # 额外校验相邻 OpenWrite 的共享 contracts
npm run doctor -- --profiles    # 只读核对本机 web/headless 是否链接本工作树
```

`check:plugin` 不需要服务、小说或模型凭据，GitHub Actions 也执行此门禁。
真实系统另跑 `scripts/verify.sh` 和 `npm run test:e2e`；E2E 跳过不算运行时通过。

## 可选 DoG 集成

如需启用分层评审/交付 DoG 查询，先准备朋友的 `dsh-dog` 工作树，再执行
`DSH_DOG_DIR=/path/to/dsh-dog scripts/install.sh`；它只安装 web profile，
并不会把 dsh-dog 源码复制进本项目。
安装脚本会先构建该工作树，再挂载插件。
安装时会把 `dog.workspaceRoot` 写入 `~/.dsh/settings.yaml`；默认是本项目根目录，
也可用 `DSH_DOG_WORKSPACE_ROOT=/path/to/novel scripts/install.sh` 指定。已有 `dog:`
配置不会被覆盖，切换项目时需手动修改该字段并重启 dsh。

然后打开 http://127.0.0.1:3080 ，新建会话时选择 **OpenWrite 创作** 预设。
会话头部只增加「创作 / 资料 / 任务」三个工作流 tab；
正文编辑、大纲、资产、图谱、研究、搜索与后台任务全部在 dsh 原生界面完成。

## Workspace 模型

dsh Workspace 是唯一的工作区身份：agent 工具调用按会话的不可变 `cwd`、浏览器
面板按当前 session 绑定的 Workspace，都把请求路由到该 Workspace canonical root
对应的独立 OpenWrite 应用实例（任务、评审、搜索、DAG、benchmark、DoG 产物全部
按 root 隔离）。切换 dsh Workspace 即切换全部能力；OpenWrite 的 legacy 最近项目
列表只用于直接 CLI（`openwrite studio --project ...`）兼容，不能改变 dsh 当前
上下文。新建作品的唯一路径是：dsh 目录选择/创建 → `workspace.create` → 在该
绝对路径初始化 OpenWrite（同时创建该作品目录的独立 Git 仓库）→ 连接 Workspace。契约细节见
[docs/WORKSPACE_CONTEXT_CONTRACT.md](docs/WORKSPACE_CONTEXT_CONTRACT.md)。

## 工作方式

1. 在 **OpenWrite 创作** 会话里先收敛灵感、人物、世界观与大纲（所有写入经 OpenWrite
   修订门控，重要改动先出 diff 再确认），再在同一会话中写正文。
   正文和正典使用 `novel_document_change_plan`；大纲、资产、创作重点、伏笔和写作目标
   使用 `novel_structured_change_plan`。两者都由服务端保存不可变预览、在确认时重验源
   revision，并返回只对已确认结果有效的安全撤销 token。
   正文区按 canonical reading order 切章和连续审读，计划未写章节保留在大纲中但不会被
   当作可读正文；搜索结果只有在 document ID 与完整 revision 都仍匹配时才开放改单行。
2. 写正文时执行 `novel_context_preview` 预检上下文包 →
   `novel_write_chapter` 写章 → `novel_review_chapter` 六域累加评审。
   每次评审同时生成 `data/novels/{id}/data/dog/reviews/{chapter}/dog-graph.json`；
   通过 `novel_task_create(type=chapter_review)` 启动的后台评审，也会在
   `novel_task_get` 读到完成态时生成同样的图；
   图的顶层是上下文完整性、六个质量域、硬门禁和确定性聚合，六域下可展开原 37 项，
   查询 criterion、证据、问题、覆盖率和继承状态。DoG 只查询已生成的 artifact，
   不重新调用模型评审。
   写章、评审和 `novel_revision_*` 操作还会维护
   `data/novels/{id}/data/dog/deliveries/{chapter}/dog-graph.json`：它把正文、
   `writing → review → revision → application → rereview → closure` 六阶段串成章节交付总图；
   正文 SHA 改变后旧评审立即 stale，修订应用后必须复评通过才算交付。
   DoG 的 `workspaceRoot` 需要指向 OpenWrite 项目根目录。
   资产不齐时 Agent 会回到规划阶段补齐，不需要切换会话。
   拆书导入则先执行 `conductor/smart_import.py`，对输出的
   `data/novels/{id}/data/dog/imports/{IMPORT_ID}/dog-graph.json` 做 DoG 验收；
   验收通过后继续在同一 Agent 中建立大纲、角色、世界观、进度和正典事件，最后重新评审。
3. 无人值守批量生产用 **conductor**（需 Studio 在跑）：
   `cd conductor && .venv/bin/python pipeline.py --chapters next --limit 3`——
   连续写章 → 六域评审 → 低质量分/低覆盖率/含 blocker 自动经修订闭环回炉；
   `--review-only` / `--rework` / `--agent-guidance` 见模块 docstring 与 DESIGN.md §6。
4. 在「资料 → 图谱」查看可缩放、筛选和展开的评审 DAG/交付 DAG；节点详情显示
   质量分、覆盖率、门禁、证据、模型、token 和耗时。
5. 在「任务 → 模型测试」选择多个写作 profile、独立评审 profile、重复次数、目标字数、
   并发数和执行模式。默认「真实写作框架」会为每个候选建立完整作品沙箱，并进入
   OpenWrite 公共写章、状态结算、正文提交、Chapter Run V2 与正式评审流程；「裸写诊断」
   只用于排查模型原始输出。测试固定同一上下文 hash，结果隔离写入
   `data/novels/{id}/data/benchmarks/`，不会改变全局路由或正式正文。结果页分别展示输入、
   输出、推理 token 和服务商实际报告的费用；明确 `$0` 与未知费用分开，`/ 1M tokens`
   仅表示本次调用的综合有效价。
6. 在「创作」中精修稿件并处理审稿/修订，在「资料」维护正典，在「任务 → 导入与导出」
   处理旧稿、项目迁移和成稿。作者旧稿先冻结源文件，再确认可编辑的分章预览；中断后从
   已完成阶段继续，发布前不会进入正式正文。导出先选择“完整备份”或“交付成品”：备份会
   显示接纳/评审警告但仍可下载，交付会把结构、元数据、正文事实和评审问题作为阻断项。
   完整作品档案列出纳入、排除、缺失文件和校验和；恢复前必须选择新路径，检查 ID/引用
   重写与冲突，旧任务只归档、不自动续跑。在「资料 → 大纲 → 原生场景结构」可先只读
   预览旧正文分场，再显式确认迁移；场景用稳定 ID 分别维护阅读顺序与故事时间、人物/地点/
   事件引用，并以 scene、源章和目标章 revision 保护元数据和跨章移动。过期结构可重新预览
   锚定，交付会阻断 stale/ambiguous，备份始终回退到完整正文。Studio 只作为头部溢出菜单
   中的高级维护出口。

## 许可

桥接插件与预设代码沿用 OpenWrite 的 Apache-2.0；`presets/*/skills/` 下 oh-story-*
技能保留其原有 MIT 许可（见各目录 LICENSE）。
