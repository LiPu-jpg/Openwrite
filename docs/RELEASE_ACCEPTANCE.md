# 0.2.6 发布验收记录

下载与最终结果以 [Release 附件](https://github.com/LiPu-jpg/Openwrite/releases/tag/v0.2.6) 的 `release-acceptance.json` 为准。报告绑定唯一 `.tgz` 的 SHA-256。失败、未运行、取消和跳过不计为通过；发布直接提升 CI 产物。不覆盖 `v0.2.5` / `v0.2.4` 附件。

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
