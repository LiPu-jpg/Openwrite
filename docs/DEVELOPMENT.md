# 工程结构与开发文档

[返回首页](../README.md) · [安装指南](INSTALL.md)

为兼容现有安装、审稿产物和浏览器草稿，内部 npm scope、Schema 版本与存储键继续使用
`@dsh-novel/*` 和 `dsh-novel.*`；这些稳定标识不影响对外产品名。

评审 v2、双 DAG 与模型测试台的跨仓库目标、当前状态和续跑入口统一维护在
[GOAL.md](../GOAL.md)。后续 Goal 应先读取该文件，并以当前工作树和验证日志为准继续。

- **dsh** 负责 agent 编排：OpenWrite 单一创作预设、技能目录、子代理委派、长上下文压缩
- **OpenWrite** 负责小说领域能力：规范阅读顺序、稳定场景结构、章节流水线、六域累加评审（兼容 37 项查询）、伏笔 DAG、正典状态
- **OpenWrite Studio** 在本插件版本中提供无界面的小说领域 HTTP 后端；dsh 是唯一交互壳与编辑工作台

架构与职责划分见 [DESIGN.md](../DESIGN.md)。

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

## 插件开发与维护

建立方法、官方资料、版本升级、安装更新和回退流程见
[维护手册](PLUGIN_MAINTENANCE.md)。本轮工程维护与模型工作台回归证据见 [GOAL.md](../GOAL.md)。

[标准章节审稿 DAG](REVIEW_DAG_FRAMEWORK.md)：一次定义、逐章实例化的六域 37 项审稿框架。
开源写作软件、AI 工具和编辑器插件的对照，以及当前产品差距与验收建议，见
[小说工具调研与改进清单](OPEN_SOURCE_NOVEL_AUDIT.md)。
用户指定的七个项目的固定版本、源码实现和改进优先级，见
[七项目专项对照](TARGETED_NOVEL_PROJECT_REVIEW.md)。
七个框架的社区/源码/测试静态统计、功能成熟度矩阵、各自优势和 OpenWrite 的相对位置，见
[框架优势与统计](FRAMEWORK_ADVANTAGES.md)。
基于现状的实施顺序、跨仓库分工、依赖与验收条件见
[插件完善计划](IMPROVEMENT_PLAN.md)；实际完成状态继续记录在 [GOAL.md](../GOAL.md)。
S1–S6 之后对照七个外部项目的计划/进行中/已完成，见
[学习与完善进度](LEARNING.md)（示例书不在目标内）。

```sh
npm run check:plugin           # 构建、doctor、生命周期、预设、smoke、epochs、组件测试
npm run check                  # 额外校验相邻 OpenWrite 的共享 contracts
npm run doctor -- --profiles    # 只读核对本机 web/headless 是否链接本工作树
```

`check:plugin` 不需要服务、小说或模型凭据，GitHub Actions 也执行此门禁。
真实系统另跑 `scripts/verify.sh` 和 `npm run test:e2e`；E2E 跳过不算运行时通过。

## DoG 集成

`scripts/install.sh` 默认自动获取固定的 `dsh-dog v1.2.0`，保存到
`$DSH_HOME/extensions/dsh-dog`，完成构建并只挂载到 web profile；重复运行会复用该目录。
如需使用已有工作树，可传入 `DSH_DOG_DIR=/path/to/dsh-dog`；明确不安装时设置
`DSH_DOG_AUTO_INSTALL=0`。

安装器会在缺少 `dog:` 配置时写入安全兜底值。DoG v1.2 优先使用发起调用的 dsh 会话
Workspace，所以切换作品会自动切换评审/交付图根目录，无需修改 `workspaceRoot` 或重启。
`novel_review_chapter` 和后台章节评审完成时会自动实例化标准章节审稿 DAG；DoG 只查询
已物化产物，不会重复调用模型。
