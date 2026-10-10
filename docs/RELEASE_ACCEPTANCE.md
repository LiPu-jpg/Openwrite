# 发布验收记录

## CI 运行范围

仅修改 README.md 或 docs 下的 Markdown 文档时，跳过插件维护与跨平台发布验收。预设、技能、脚本、依赖、资源和工作流变更仍触发检查；混合文档与代码的提交也照常检查。开发分支通过 PR 检查，避免同一提交在分支 push 与 PR 上重复执行；主分支合并后保留验收，两个工作流均可手动触发。发布必须使用完整验收通过的产物，跳过检查不能作为发布通过的证据。

新建作品的验收请求最多等待 60 秒（原为 15 秒），保留成功耗时和失败诊断；不重试写请求，超时仍失败。此调整容纳慢速运行器，不代表初始化耗时问题已被修复。

## 0.2.18

<!-- TODO: 发布后回填 PR、CI、Release 链接与 SHA -->

修正 0.2.17 的 `auto:cheapest`：真实 Key 实测发现 OpenRouter 上部分免费模型没有 `:free` 后缀（`inclusionai/ling-3.1-flash` 定价 0/0），会被低价策略选中；免费模型可用性不稳定，Core 5.8.9（native-core `d0a75e30047c28c99af909e1b85b07190abb1fb7`）把零价模型一并排除，`auto:cheapest` 现在落在付费低价模型上。回归测试补充零价排除断言，9/9 通过。

Core 5.8.9 由 `native-core` 分支干净树 `pip wheel` 构建，manifest 三处已回填。

## 0.2.17

[GitHub Release](https://github.com/LiPu-jpg/Openwrite/releases/tag/v0.2.17) 已发布，直接使用[完整 CI](https://github.com/LiPu-jpg/Openwrite/actions/runs/38057362486)验收的同一份包。来源提交 `de2cacb`，npm 包 SHA-256 为 `da2a0b2ae264392f7d0f8c5d6c98de08cd0497f8a761bf0c96f9a43ce95771c5`。六组原生平台/Node、源码安装、alpha 兼容及三代宿主客户端共 12 份报告全部通过；Release 四份附件的校验值已与 CI `validated-release` 产物逐一核对。合并来源 [PR #72](https://github.com/LiPu-jpg/Openwrite/pull/72)。npm `dsh-openwrite@0.2.17` 已发布到官方 registry（registry.npmjs.org），`latest` 已更新到 0.2.17；从官方 registry 无认证重新下载后，SHA-256 与上述 CI 包一致。

新增自动选模（Core 5.8.8，native-core `a7f4d8769de7496cb18b9d6dc38872c60fa5517a`）：档案模型名支持 `auto:cheapest`（实时拉取 `/models` 价格目录，过滤后取总价最低，缓存一小时、失败回退过期缓存）与 `auto:popular`（OpenRouter `openrouter/auto`）。解析在 `resolve`/`resolve_profile` 统一发生，结果写入 `auto_select` 字段；静态模型档案不受影响。新增 9 项回归测试全部通过（比价规则、缓存命中、过期缓存兜底、目录不可用报错、popular 非 OpenRouter 拒绝、未知策略拒绝、静态档案零网络）；档案/连接测试/工作室相关面 227 项通过（2 项失败为 native-core 预存在的 `test_real_litellm_backend_accepts_openwrite_request_shape_without_network` 与 `test_studio_outline_task_uses_planning_snapshot_and_validated_artifact` 漂移，与本版无关）。真实 OpenRouter Key 实测：`auto:popular` 路由到 `qwen/qwen3.8-flash` 返回 200。

Core 5.8.8 由 `native-core` 分支干净树 `pip wheel` 构建，manifest 的 `core_version`、`wheel.sha256`、`sources.core.commit` 已同步。

## 0.2.16

[GitHub Release](https://github.com/LiPu-jpg/Openwrite/releases/tag/v0.2.16) 已发布，直接使用[完整 CI](https://github.com/LiPu-jpg/Openwrite/actions/runs/38048767150)验收的同一份包。来源提交 `d490715`，npm 包 SHA-256 为 `d6b0e798a7ad4bffa894b5373b72f080e41254ff23030a58029189e92f5dcf5e`。六组原生平台/Node、源码安装、alpha 兼容及三代宿主客户端共 12 份报告全部通过；Release 四份附件的校验值已与 CI `validated-release` 产物逐一核对。合并来源 [PR #71](https://github.com/LiPu-jpg/Openwrite/pull/71)。npm `dsh-openwrite@0.2.16` 已发布到官方 registry（registry.npmjs.org），`latest` 已更新到 0.2.16；从官方 registry 无认证重新下载后，SHA-256 与上述 CI 包一致。

补漏 #64/#67 持久化缺口：E2E 实测发现 0.2.15 对"字数精简重试耗尽后保稿"只覆盖了运行内存态——`WritingResult` 未携带 `length_out_of_range`/`length_warning`，流水线写草稿产物时这两个标记与 `validation_issues` 均丢失，产物里 flags 为空。Core 5.8.7（`61bd75326702dbb0fa657df04aaaa79986369890`）在 `WritingResult` 上补齐两个字段并从 creative 结果填充，草稿产物持久化这两个标记，`validation_issues` 以 dataclasses 序列化落盘；新增草稿产物持久化回归测试与字段默认值测试，相关面 110 项通过。

Core 5.8.7 由 `native-core` 分支干净树 `pip wheel` 构建，manifest 的 `core_version`、`wheel.sha256`、`sources.core.commit` 已同步。

## 0.2.15

[GitHub Release](https://github.com/LiPu-jpg/Openwrite/releases/tag/v0.2.15) 已发布，直接使用[完整 CI](https://github.com/LiPu-jpg/Openwrite/actions/runs/38038338548)验收的同一份包。来源提交 `d56b566`，SHA-256 为 `e558078c77c92186f198eea7c1cbaf17fb9f5939f9c2ae0c6953adc6256b36a7`。六组原生平台/Node、源码安装、alpha 兼容及三代宿主客户端共 12 份报告全部通过；Release 四份附件的校验值已与 CI `validated-release` 产物逐一核对。合并来源 [PR #70](https://github.com/LiPu-jpg/Openwrite/pull/70)。npm `dsh-openwrite@0.2.15` 已发布，`latest` 已更新到 0.2.15；从公共 npm registry 无认证重新下载后，SHA-256 与上述 CI / Release 包一致。Core 5.8.6 由 `native-core` 分支 `6613bf9245ac08a80c9d49d64530b2c443fa7cf9` 干净树构建，manifest 的 `sources.core.commit` 已回填。

修复 #63/#66 Windows 残留 `project.lock` 永久阻断写章/审稿：Core 5.8.6 用 Windows 正确的进程存活探测（`OpenProcess`/`GetExitCodeProcess`）替换 POSIX 语义的 `os.kill(pid, 0)`——后者在 Windows 上被解释为发送 `CTRL_C_EVENT`（值为 0），对死进程抛 `OSError [WinError 87]` 且不被现有捕获分支覆盖，导致残留锁 100% 无法自愈。死进程持有的锁现在自动判陈旧并清理；存活探测本身失败时按"初始化宽限后视为陈旧"兜底，不再卡死写作。锁占用报错携带 operation、pid、起始时间与锁文件路径；写章/审稿不再预置 `model` 阶段标签，文件锁失败不会被误报为"模型生成失败"（阶段由流水线在真正生成时上报）。

修复 #64/#67 `continuous_write` 单章失败即整队终止：`max_failures` 此前只在值为 1 时生效（首次失败 `1 < 2` 直接 `raise`），现在循环按已完成章节数驱动，未达上限记录该章失败并继续下一章，达到上限优雅返回 `max_failures_reached`，结果附带 `failed_chapters`；`TaskCancelled` 与取消检查仍会立即中止队列。字数精简重试耗尽后不再丢弃初稿：最后一版正文标记 `length_out_of_range`/`length_warning` 保留为草稿并产生一条字数告警 issue。

修复 #68 横评进行中详情接口恒 400：产物契约 `model_benchmark_v1` 的 `status` 枚举补齐 `running`/`cancelling`/`cancelled`（schema 源 + Python/TS 生成物同步，codegen `--check` 通过），实时快照与取消终态均可通过校验。

修复 #69 推理模型评审输出预算锁死 4096：观察到 usage 含 reasoning tokens 后评审与安全门的输出预算地板抬到 16384（仍受模型配置与上下文窗上限约束）；截断后先按翻倍预算原批重试一次，仍失败才二分，且二分时不再沿用旧地板。思维链按调用计费，旧逻辑下拆分救不回来。

引擎回归：新增 12 项回归测试（锁陈旧清理/占用上下文/宽限兜底、契约实时态、预算地板、continuous_write 容错与上限），`test_managed_runtime`/`test_embedding_runtime`/`test_model_connection_test` 三件套 33/33 通过，相关面 71/72（1 项失败为 native-core 上预存在的 `test_production_write_failure_returns_run_v2_provenance` 漂移，与本版无关）；wheel 由 native-core 干净树 `pip wheel` 构建，顺带补齐 5.8.5 漂移 wheel 缺失的 httpx `InvalidProxy` getattr 容错（7a08855）。

#65 部分落地：README 记录界面语言切换（Settings → General → Language），persona 增加语言跟随约定。英文 persona/skills 全集与后端信息英文化留待后续，issue 保持打开。

## 0.2.14

[GitHub Release](https://github.com/LiPu-jpg/Openwrite/releases/tag/v0.2.14) 已发布，直接使用[完整 CI](https://github.com/LiPu-jpg/Openwrite/actions/runs/37679578150)验收的同一份包。来源提交 `f62f268bd2c74badc8af56ad4896164c5403def2`，SHA-256 为 `b61b2d98bac0235cb23361b2aa593e287bb47a2db24669c9893ef8e27e173549`。六组原生平台/Node、源码安装、alpha 兼容及三代宿主客户端共 11 份报告全部通过；Release 四份附件的校验值已与 CI `validated-release` 产物逐一核对。合并来源 [PR #62](https://github.com/LiPu-jpg/Openwrite/pull/62)，#60、#61 随之关闭。npm `dsh-openwrite@0.2.14` 已发布，`latest` 已更新到 0.2.14；从公共 npm registry 无认证重新下载后，SHA-256 与上述 CI / Release 包一致。

修复 #60 系统代理场景下 `NO_PROXY` 含 `[::1]` 导致所有模型连接测试误报"服务商拒绝了请求"：桥接层 `buildChildEnv()` 转发前剥掉带方括号的 IPv6 字面量，Core 5.8.5 把 httpx 客户端构造期异常归类为本地配置错误（HTTP 412），`Studio request failed` 附带 `error.cause`。

修复 #61 Embedding 连接测试在请求线程里懒加载 numpy 把后端变成"活着但不服务"的僵尸：Core 5.8.5 启动主线程预热 numpy、后台线程预热 fastembed，`run_embedding_probe()` 硬超时 `timeout_seconds + 30 s`，收尾限时 10 秒超时强制退出；桥接层复用就绪连接前做带超时的 `/api/health` 探活，探活失败的僵尸进程强制终止并自动恢复，子进程 stderr 落盘 `state/logs/backend.log`（末尾 64 KiB）。

新增回归覆盖 no_proxy 消毒矩阵、僵尸连接探活恢复、stderr 落盘、错误分类矩阵与探测硬超时；wheel 重打包后全量 RECORD 哈希校验（498 文件）与 manifest 一致性检查通过。CI 另修复 apt 镜像加固（pin 到 https archive.ubuntu.com + 连接超时），消除 ubuntu 运行器镜像故障导致的矩阵腿卡死。Windows 上的依赖预热与僵尸恢复链路本机未复测，保留 0.2.13 的同一限制；DSH 核心 `dsh-http-proxy` 向 `NO_PROXY` 注入 `[::1]` 的治本修复仍需向 DeepSeek Harness Desktop 团队转达。

## 0.2.13

修复 #57 的只读 POST 失效循环。Core 5.8.4 在 HTTP action 契约声明是否改变公开状态，通过 `X-OpenWrite-Mutated` 统一驱动浏览器代理与 Agent 客户端；旧 Core 的正文版本和批注查询保留兼容处理。保存、批注写入及恢复版本按 manuscript 资源通知，批注读取不再监听无关的 workspace 失效。

新增回归覆盖连续只读请求不增加 invalidation revision、SSE 和 Core context_epoch；真实写入仍增加序号。创作页验证重复 workspace 事件不会反复请求批注，实际编辑会刷新，切换作品清空旧批注并忽略迟到响应。[完整 CI](https://github.com/LiPu-jpg/Openwrite/actions/runs/37483398522) 全部通过，六组原生平台/Node、源码安装、alpha 兼容及三代宿主客户端共 11 份报告均绑定同一产物。来源提交 `72d19c1a1494da13b5b89d652746e13f13e90e1a`，SHA-256 为 `091dcb7201a88240d8282ef31526d7d88f6d63a390d0813a39f580f9be990a58`。[GitHub Release](https://github.com/LiPu-jpg/Openwrite/releases/tag/v0.2.13) 已发布并核对四份附件的校验值；npm 本次发布认证已过期（404），等待重新验证，`latest` 暂时仍为 0.2.12。

#50、#57 已随 [PR #59](https://github.com/LiPu-jpg/Openwrite/pull/59) 合并关闭。#50 报告的预设注册、主视图挂载、会话导航及托管模型配置问题已由 0.2.12 修复，并经三代精确 Web 宿主和原生 Windows 安装检查验证。Windows Electron 的实机启动/恢复尚未复测，该限制继续保留；本版不将其计为已通过的验收。

## 0.2.12

[GitHub Release](https://github.com/LiPu-jpg/Openwrite/releases/tag/v0.2.12) 已发布，直接使用[完整 CI](https://github.com/LiPu-jpg/Openwrite/actions/runs/37389772004)验收的同一份包。来源提交 a349ea964e43d75f9fc98d1f83354a237bc2ff51，SHA-256 为 2545031292d80689f80d4c0d8c99e007c18ff0c477d662e2813cf67bc876246c。六组原生平台/Node、源码安装、alpha 兼容及三代宿主客户端共 11 份报告全部通过；详见 Release 的 release-acceptance.json。npm `dsh-openwrite@0.2.12` 和 GitHub Release 均已发布，`latest` 已更新到 0.2.12；从公共 npm registry 无认证重新下载后，SHA-256 与上述 CI / Release 包一致。合并后的[主分支完整 CI](https://github.com/LiPu-jpg/Openwrite/actions/runs/37390503895)也已通过。

本版修复 #50–#52 的 0.2 宿主兼容问题及 #54 阅读模式刷新闪烁，纳入 #53 的导航和会话作用域改动，并保留旧宿主的预设插件。

- Core 5.8.3：模型连接测试使用所选配置的输出预算；108 项 Core 回归通过。
- 本地 297 项组件测试、50 项 DoG 测试通过。三代精确宿主的浏览器流程纳入正式发布门禁：选择目录、预设选择、会话导航、工作台标签、点击创作后实际渲染、DoG 面板与插件共存。该客户端检查使用后端就绪及未初始化响应替身；原生后端安装和作品初始化由独立平台任务验证。
- 完整 CI 和唯一产物校验已通过；合并提交 60949df412f10be004fe6bb5b4fb992dd65c3c60 的 tree 与 CI 来源一致。Windows Electron 桌面端尚未实机复测，真实模型验证未运行。

## 0.2.11

[Release](https://github.com/LiPu-jpg/Openwrite/releases/tag/v0.2.11) 使用 [完整 CI](https://github.com/LiPu-jpg/Openwrite/actions/runs/37012171411) 验收的同一份包，来源提交为 39454dbcd14ea672c6d9fa25eddea26f8ea71591，SHA-256 为 d11f2a3e9abbd0aaaaa42d5ffb4268e9c192f608236178a48cd112d09e03f1f9。六组原生平台、源码安装及精确 alpha 宿主验收均通过；对该产物另完成精确 0.2.0-rc.2 Web 客户端启动验证。npm `dsh-openwrite@0.2.11` 和 GitHub Release 均已发布，`latest` 已更新到 0.2.11；从公共 npm registry 重新下载后，SHA-256 与上述 Release 包一致。

- 修复 #45 的子包兼容声明和两个客户端 API 差异，增加初始化异常隔离、回滚与错误诊断；包含 #44 的 minimap CSS 修复。
- 精确 `0.2.0-rc.2` Web 宿主已验证两个客户端激活、工作台入口、DoG 面板和其他插件共存，无需版本豁免。
- Core 仍为 5.8.2 / contract 1。正式发布直接使用本版本完整 CI 验收通过的同一份产物，SHA-256、来源提交和原生平台结果以 Release 附件为准。
- Windows Electron 桌面端启动及恢复链路尚未实机复测；宿主恢复策略未修改，已被重置的 profile 需要从备份恢复。真实模型验证未运行。

## 0.2.10

[Release](https://github.com/LiPu-jpg/Openwrite/releases/tag/v0.2.10) 使用 [主分支 CI](https://github.com/LiPu-jpg/Openwrite/actions/runs/34836925547) 验收的同一份包，来源提交为 9108038699f64613f66a3fea21dfdb3841881d25，SHA-256 为 09f80826dd4ec72ba0f968feb978257f792033dab6f428dc6f09ab38e8b62f64。npm `dsh-openwrite@0.2.10` 已发布，`latest` 已更新；从公共 npm registry 重新下载后，SHA-256 与上述 Release 包一致。

- 修复 #36：初始化支持 author / language；已有作品可在「任务 → 导入与导出 → 编辑作品信息」补齐出版元数据，保存经过认证、Workspace、revision 与原子写入保护。
- 修复 #37：写作的五个调用点使用所选模型配置的输出预算，移除固定小预算覆盖；推理模型仍需配置足够额度，不自动增加付费重试。
- 修复 #38：会话头部隐藏 idle 保存状态，编辑器内显示「尚未载入正文」。
- Core 5.8.2 / contract 1，来源 native-core 833c66407a780283bdb7f901540322a9b549ee1d；依赖声明不变。
- 原生 Linux/macOS arm64/macOS x64/Windows Node 24、Linux Node 22.19/26、源码安装及精确 alpha 宿主全部通过。浏览器验收包含作者信息保存后重新读取，后端覆盖未认证请求和过期 revision。
- Core 54 项回归、前端 291 项组件测试通过。真实模型测试 not-run，不计入通过；预算替身测试覆盖三个配置额度下的五个调用点。

## 0.2.9

[Release](https://github.com/LiPu-jpg/Openwrite/releases/tag/v0.2.9) 与 npm dsh-openwrite@0.2.9 使用 [主分支 CI](https://github.com/LiPu-jpg/Openwrite/actions/runs/34532531326) 验收过的同一份包；来源提交为 8ecada040db2c3ddf699d7a5bc1ddd86336b88fe，SHA-256 为 2a885d03f931505432b78424922c63e7ac75c70a10ab57b7c7503d059af7b627。npm 下载后再次核对一致。

- 六组原生平台安装、启动、浏览器和卸载，以及 GitHub 源码安装、固定 alpha 依赖图兼容检查全部通过；详见 Release 的 release-acceptance.json。
- 287 项组件测试通过；编辑器随包资源改为固定同源脚本加载，并验证在不允许 unsafe-eval 的浏览器策略下正常初始化和渲染 Markdown。
- 日常安装使用 npm latest；验收、兼容和回退保留精确版本。运行中不自动升级。宿主基线仍为 dsh 0.1.2-rc.1，Core 5.8.1 / contract 1。
- 真实模型验证 not-run，模型调用 0 次。不将静态扫描警告全部消除作为本次结论。

## 0.2.8

[Release](https://github.com/LiPu-jpg/Openwrite/releases/tag/v0.2.8) 与 npm dsh-openwrite@0.2.8 的 SHA-256 均为 3a54f30fec03a5a64338f6cbc8216cafdc733cdf3622691fdbc8f029d78e4902。验收见 [CI](https://github.com/LiPu-jpg/Openwrite/actions/runs/34368570869)：Intel 首次超时，未修改代码重跑通过；历史失败保留。npm 分发另在 macOS arm64 / Node 24 的隔离环境完成 25 项安装、运行、浏览器及卸载检查。真实模型验证 not-run。

## 0.2.7 记录

下载与最终结果以 [Release 附件](https://github.com/LiPu-jpg/Openwrite/releases/tag/v0.2.7) 的 `release-acceptance.json` 为准。报告绑定唯一 `.tgz` 的 SHA-256。失败、未运行、取消和跳过不计为通过；发布直接提升 CI 产物。不覆盖 `v0.2.6` / `v0.2.5` 附件。

宿主基线：dsh **0.1.2-rc.1**。Core **5.8.1** / contract 1。

## 本版改动与验收

- 未解决批注出现在正文上方「作者选区批注」条，不必先打开右侧「修订」。
- 正文覆盖层提高不透明度并加彩色下划线。
- 回归：保存批注后出现 `creation.notes.locate: 查来源` 按钮。

平台矩阵仍以 GitHub `Release artifact validation` 为准。真实模型测量 `not-run`。本机已运行的 dsh 安装默认不自动替换。

## 0.2.6 记录

下载与最终结果以 [v0.2.6 Release 附件](https://github.com/LiPu-jpg/Openwrite/releases/tag/v0.2.6) 的 `release-acceptance.json` 为准。报告绑定唯一 `.tgz` 的 SHA-256。失败、未运行、取消和跳过不计为通过；发布直接提升 CI 产物。不覆盖 `v0.2.5` / `v0.2.4` 附件。

宿主基线：dsh **0.1.2-rc.1**。Core **5.8.1** / contract 1。

## 本版改动与验收

- 批注输入框的 `mousedown` 不再 `preventDefault`，可以获得焦点并输入。颜色按钮和提交仍保留选区。
- 回归：`lets the author focus and type in the annotation note field`。

平台矩阵仍以 GitHub `Release artifact validation` 为准。真实模型测量 `not-run`。本机已运行的 dsh 安装默认不自动替换。

## 0.2.5 记录

下载与最终结果以 [v0.2.5 Release 附件](https://github.com/LiPu-jpg/Openwrite/releases/tag/v0.2.5) 的 `release-acceptance.json` 为准。报告绑定唯一 `.tgz` 的 SHA-256。失败、未运行、取消和跳过不计为通过；发布直接提升 CI 产物。不覆盖 `v0.2.4` / `v0.2.3` 附件。

宿主基线：dsh **0.1.2-rc.1**。Core **5.8.1** / contract 1。

## 本版改动与验收

- 覆盖层 Range 跨 IR 文本节点拼接，粗体拆分的引文和 `//**…**` 标记能定位。
- 滚动 `.vditor-ir` 或窗口缩放后重新绘制覆盖层。
- 「定位」调用编辑器 `revealQuote`，选中并滚到原文。
- 回归：`manuscript-overlay-dom.test.ts` 拆节点引文/标记、第 n 处 reveal、scroll/resize 解绑；CreationView locate 调用 `revealQuote` 并设置选区。

平台矩阵仍以 GitHub `Release artifact validation` 为准。真实模型测量 `not-run`。本机已运行的 dsh 安装默认不自动替换。

## 0.2.4 记录

下载与最终结果以 [v0.2.4 Release 附件](https://github.com/LiPu-jpg/Openwrite/releases/tag/v0.2.4) 的 `release-acceptance.json` 为准。报告绑定唯一 `.tgz` 的 SHA-256。失败、未运行、取消和跳过不计为通过；发布直接提升 CI 产物。不覆盖 `v0.2.3` / `v0.2.2` 附件。

宿主基线：dsh **0.1.2-rc.1**。Core **5.8.1** / contract 1。

## 本版改动与验收

- 创作工作台 Vditor IR 正文可对选区添加作者批注：保存后绑定 chapter、revision 与精确范围；重复引文不静默取第一处。未保存草稿先保存再核对选区，否则拒绝。脱离原文或多处匹配显示「已脱离原文／需重新定位」，不把颜色或 HTML 写进 Markdown。
- 批注使用固定调色板；旧记录缺颜色时显示琥珀。状态变化 `//**人物[维度]：旧 -> 新**` 与指向关系 `//**A~>B:关系**` 使用另一组覆盖层颜色。插入标记从当前作品人物选择，同名需明确 id；打开表单不写盘、不调模型。有效内部标记不计入可读字数和默认导出。
- Core `ManuscriptAnnotationV1` 增加可选 `color`，钉住 `native-core` 的 5.8.1 wheel。v0.2.3 的迁移、子进程环境允许列表和受管理后端恢复行为未回退。

平台矩阵仍以 GitHub `Release artifact validation` 为准。真实模型测量 `not-run`。本机已运行的 dsh 安装默认不自动替换。

## 0.2.3 记录

下载与最终结果以 [v0.2.3 Release 附件](https://github.com/LiPu-jpg/Openwrite/releases/tag/v0.2.3) 的 `release-acceptance.json` 为准。报告绑定唯一 `.tgz` 的 SHA-256。失败、未运行、取消和跳过不计为通过；发布直接提升 CI 产物。不覆盖 `v0.2.2` / `v0.2.1` 附件。

宿主基线：dsh **0.1.2-rc.1**。

## 本版改动与验收

- 自动恢复的 `queueRestart` 失败不再变成未处理拒绝，因此不会把整个 dsh 带退出。
- 恢复启动失败计入同一退避上限并继续重试；取消或卸载发生在恢复等待中时，不抛未处理错误、不再启动后端。
- 回归：`recovery start failures retry up to the cap without an unhandled rejection`、`cancel and dispose during recovery wait do not reject unhandled or start a backend`。

平台矩阵仍以 GitHub `Release artifact validation` 为准。真实模型测量 `not-run`。

## 0.2.2 记录

下载与最终结果以 [v0.2.2 Release 附件](https://github.com/LiPu-jpg/Openwrite/releases/tag/v0.2.2) 的 `release-acceptance.json` 为准。报告绑定唯一 `.tgz` 的 SHA-256、插件提交、Core 提交、宿主版本和原生执行记录。失败、未运行、取消和跳过不计为通过；发布直接提升 CI 产物，不重新打包。不覆盖 `v0.2.1` 附件。

宿主基线：dsh **0.1.2-rc.1**（npm `latest`/`next` 同此版本；`alpha` 为 `0.1.5-alpha.1`，本版不追随）。Core 5.8.0 / contract 1。

## 本版改动与验收

- 旧安装迁移检查 bundle **和** `dependencies`；应用时走宿主 `dsh plugin remove`，先备份、失败恢复。不再只改 bundle 列表而把旧包留给后续 `plugin add` 重新登记（该路径会触发 `duplicate loader entry id: openwrite-bridge`）。作者所有预设按无包装标记识别，不会删除；历史会话不改绑。
- 受管理后端在 dsh 运行期间对已启动进程的异常退出做有上限退避自动恢复；取消、宿主退出、卸载不复活。恢复只重连服务，不重放写作/评审等付费请求，状态文案不得写成任务已恢复。
- 安装与 Python 子进程使用允许列表环境，不继承无关 API Key。工具策略测试覆盖只读、计划模式、缺失/伪造 Workspace、过期 revision、未认证请求。文档标明这不是操作系统沙箱。
- 成本比较方法见 [COST_MEASUREMENT.md](COST_MEASUREMENT.md)。离线 schema 字节继续由测试打印；真实 tokenizer/缓存/费用本版 `not-run`。

平台矩阵、浏览器检查和 GitHub 源码安装仍以本版 CI `Release artifact validation` 为准。真实模型调用本版未授权，记为 `not-run`。

## 0.2.1 记录

下载与最终结果以 [v0.2.1 Release 附件](https://github.com/LiPu-jpg/Openwrite/releases/tag/v0.2.1) 的 `release-acceptance.json` 为准。报告绑定唯一 `.tgz` 的 SHA-256、插件提交、Core 提交、宿主版本和原生执行记录。失败、未运行、取消和跳过不计为通过；发布直接提升 CI 产物，不重新打包。

宿主基线：dsh 0.1.2-rc.1；Core 5.8.0 / contract 1。Core 固定提交和 DoG v1.2.0 来源见 `release/runtime-manifest.json`。构建任务记录插件提交、依赖来源和许可证，最终 `.tgz.manifest.json` 绑定产物 SHA-256。

## 本版改动与验收

修复关系图侧栏中同一人物被多条关系重复列出的问题；正文同名或别名冲突改为候选选择，不再静默打开第一份资料。普通姓名与别名仍按资料身份合并。发布验收还发现并修复了启动入口固定选择旧版本预设的问题：浏览器入口现在从根发布版本生成预设 ID，并以实际安装的预设验证启动流程。前端 266 项组件测试覆盖这些行为及切换 Workspace/章节时清除候选。

以下既有核心功能沿用 0.2.0 的验收基线，最终 0.2.1 产物的重复安装、平台安装与浏览器检查以本版 Release 附件为准。

## 既有功能基线（0.2.0）

- macOS arm64 / Node 24.15：实际 `.tgz` 安装进隔离 DSH_HOME，重复安装、自动下载 Python、隔离依赖安装、认证后端握手、编辑器资源和标准卸载通过。没有相邻 Core 路径依赖，没有调用模型。
- 本机已有作品检查使用 `~/my_novel`：标准预设不出现小说工作台；OpenWrite 入口创建新创作会话，空会话显示工作台，已有正文编辑器成功加载。DoG 默认不浮动占位。作者另外明确要求新建独立文件夹实测；新建作品验证单独记录，不借用已有作品数据。
- Core 94 项相关回归通过；前端 260 项组件测试、DoG 42 项测试通过。后续新增测试以 CI 最终结果为准。
- 运行时测试覆盖中断下载、缓存校验、安装锁取消、旧活动记录保留和进程清理；真实 dsh ToolRuntime 验证 90 个小说工具只在创作预设出现，普通预设为 0。
- 原生工具声明测量：90 个工具共 63,614 UTF-8 字节；PTC 传输声明 944 字节，另有 60,232 字节 SDK。未测 tokenizer token 数，不据此承诺 PTC 缓存或费用收益。

## 原生平台与发布门禁

`Release artifact validation` 工作流只构建一次包，Node 24 的 Linux x64、Windows x64、macOS arm64/x64，以及 Linux Node 22.19 / 26 六个原生任务下载同一个产物。Windows 不使用 WSL。真实模型检查单列：0.2.1 发布验收不调用模型，真实正文生成和多模型测试未计为通过。0.2.0 曾完成 DeepSeek 官方的只读 novel_status 调用，历史记录见该版本 Release 附件，不作为本版真实模型验收结果。

安装任务覆盖标准与重复安装、其他插件共存、后端认证、隔离 Python、Core 契约、编辑器静态资源、原生依赖加载、动态端口、多实例、崩溃恢复、进程清理、失败升级保留活动环境、回退与卸载保留数据。浏览器实际完成首次引导、打开 OpenWrite、创建测试作品和切换工作台。GitHub 源码安装另起任务，从不带 `.git` 的源码压缩包自行构建。

构建门禁另外执行权限和计划模式、90 工具预设隔离、安装锁与下载取消、旧安装迁移备份、官方预设并发与自定义内容保护、前端组件和 DoG 回归。Core 回归使用模型替身验证生成、评审、取消、部分结果与费用；这些自动化检查的真实模型调用数为 0。

macOS arm64 依赖要求至少 macOS 14，Intel 至少 macOS 13；运行器之外的系统小版本未计为通过。Intel 使用官方 ONNX Runtime 1.23.2 wheel，其他平台使用 1.29.0。cryptography 50.0.1 的 Intel wheel 从同版本源码原生构建，来源、编译工具链、OpenSSL 静态链接检查和校验值见包内清单。

报告保留系统、架构、Node 版本、产物 SHA-256、实际检查和模型调用数。自动化均使用临时 DSH_HOME、配置及 ProjectRegistry。通过前不添加 `dsh-plugin` 发现标签。
