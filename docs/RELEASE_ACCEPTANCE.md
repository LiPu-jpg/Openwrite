# 0.2.0 发布验收记录

下载与最终结果以 [Release 附件](https://github.com/LiPu-jpg/Openwrite/releases/tag/v0.2.0) 的 `release-acceptance.json` 为准。报告绑定唯一 `.tgz` 的 SHA-256、插件提交、Core 提交、宿主版本和原生执行记录。失败、未运行、取消和跳过不计为通过；发布直接提升 CI 产物，不重新打包。

宿主基线：dsh 0.1.2-rc.1；Core 5.8.0 / contract 1。Core 固定提交和 DoG v1.2.0 来源见 `release/runtime-manifest.json`。构建任务记录插件提交、依赖来源和许可证，最终 `.tgz.manifest.json` 绑定产物 SHA-256。

## 当前已执行

- macOS arm64 / Node 24.15：实际 `.tgz` 安装进隔离 DSH_HOME，重复安装、自动下载 Python、隔离依赖安装、认证后端握手、编辑器资源和标准卸载通过。没有相邻 Core 路径依赖，没有调用模型。
- 本机已有作品检查使用 `~/my_novel`：标准预设不出现小说工作台；OpenWrite 入口创建新创作会话，空会话显示工作台，已有正文编辑器成功加载。DoG 默认不浮动占位。作者另外明确要求新建独立文件夹实测；新建作品验证单独记录，不借用已有作品数据。
- Core 94 项相关回归通过；前端 260 项组件测试、DoG 42 项测试通过。后续新增测试以 CI 最终结果为准。
- 运行时测试覆盖中断下载、缓存校验、安装锁取消、旧活动记录保留和进程清理；真实 dsh ToolRuntime 验证 90 个小说工具只在创作预设出现，普通预设为 0。
- 原生工具声明测量：90 个工具共 63,614 UTF-8 字节；PTC 传输声明 944 字节，另有 60,232 字节 SDK。未测 tokenizer token 数，不据此承诺 PTC 缓存或费用收益。

## 原生平台与发布门禁

`Release artifact validation` 工作流只构建一次包，Node 24 的 Linux x64、Windows x64、macOS arm64/x64，以及 Linux Node 22.19 / 26 六个原生任务下载同一个产物。Windows 不使用 WSL。真实模型检查单列，本轮尚未执行，不计为通过。

安装任务覆盖标准与重复安装、其他插件共存、后端认证、隔离 Python、Core 契约、编辑器静态资源、原生依赖加载、动态端口、多实例、崩溃恢复、进程清理、失败升级保留活动环境、回退与卸载保留数据。浏览器实际完成首次引导、打开 OpenWrite、创建测试作品和切换工作台。GitHub 源码安装另起任务，从不带 `.git` 的源码压缩包自行构建。

构建门禁另外执行权限和计划模式、90 工具预设隔离、安装锁与下载取消、旧安装迁移备份、官方预设并发与自定义内容保护、前端组件和 DoG 回归。Core 回归使用模型替身验证生成、评审、取消、部分结果与费用；真实模型调用数为 0。

macOS arm64 依赖要求至少 macOS 14，Intel 至少 macOS 13；运行器之外的系统小版本未计为通过。Intel 使用官方 ONNX Runtime 1.23.2 wheel，其他平台使用 1.29.0。cryptography 50.0.1 的 Intel wheel 从同版本源码原生构建，来源、编译工具链、OpenSSL 静态链接检查和校验值见包内清单。

报告保留系统、架构、Node 版本、产物 SHA-256、实际检查和模型调用数。自动化均使用临时 DSH_HOME、配置及 ProjectRegistry。通过前不添加 `dsh-plugin` 发现标签。
