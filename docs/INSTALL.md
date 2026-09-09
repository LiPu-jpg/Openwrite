# 安装、更新与卸载

安装已发布的版本；可下载产物、SHA-256 和实际平台结果以 [GitHub Release](https://github.com/LiPu-jpg/Openwrite/releases/tag/v0.2.4) 附件为准。验收方法见 [验收报告](RELEASE_ACCEPTANCE.md)。

## 标准安装

本次锁定 dsh `0.1.2-rc.1`，Node 24 为完整验收基线；Node 22.19 / 26 做兼容检查。安装不自动升级 dsh。先执行 `dsh --version` 核对宿主。

安装命令：

```sh
dsh plugin --profile web add -w https://github.com/LiPu-jpg/Openwrite/releases/download/v0.2.4/dsh-openwrite-0.2.4.tgz
dsh web
```

`-w` 是 pnpm profile workspace 的安装参数。只输入 `dsh` 会要求 `--profile`；启动浏览器使用 `dsh web`。浏览器地址由宿主输出，不固定为 3080。

点击侧栏 OpenWrite，等待环境准备完成。下载和安装进度来自同一个运行时状态，支持取消与重试。选择已有作品目录，或选择空目录后在创作工作台初始化。入口创建新创作会话，已有会话、作品和预设不被改写。点击「创作」进入编辑器；无需发送第一条消息。

Git 是可选的作品归档能力。未安装 Git 或 Git 初始化失败时，小说文件仍会保留，工作台显示自动 checkpoint 不可用；正常编辑和模型创作可以继续。

dsh 对话模型在宿主中配置。小说生成、评审与测试模型在「任务 → 模型」配置；安装健康检查不调用这些模型。

## 安装影响

本轮原生验收覆盖 macOS 15、Ubuntu 和 Windows GitHub 原生运行器。
依赖包要求 Apple Silicon Mac 至少 macOS 14，Intel Mac 至少 macOS 13；
其他系统小版本的覆盖范围以 Release 报告为准。

- 插件装在指定 profile。bridge、panel、DoG、技能、编辑器资源和 Core wheel 位于同一包。
- `$DSH_HOME/openwrite/` 保存下载缓存、Python 环境、管理记录、隔离配置与凭据；未指定 DSH_HOME 时使用 dsh 默认目录。
- 作品保存在作者选定目录。受管理 Core 仅监听回环地址，端口自动分配，实例认证只在宿主与 Core 之间传递。
- 只启动、停止本插件创建的进程。不修改系统 Python、全局 PATH 或 Shell 配置。
- 首次准备需要连接 GitHub 和 Python 包索引。版本及校验值见包内 `release/runtime-manifest.json`；依赖见 `requirements.lock`。

## 从旧本地安装迁移

旧开发安装会同时留下 `@dsh-novel/openwrite-bridge`、`@dsh-novel/studio-panel`、`@dsh-external/dsh-dog` 的 bundle 登记和 `dependencies`。只取消 bundle 而不走宿主 `dsh plugin remove` 时，随后的 `plugin add` 会按依赖重新登记，启动时报 `duplicate loader entry id: openwrite-bridge`。

执行顺序（dsh 必须已停止；需要本机 `dsh` 与 `pnpm`）：

1. 下载并解开新 Release `.tgz`。
2. 预览：检查 bundle **和** dependencies，不改文件。
3. 应用：先备份，再对仍在依赖中的旧包执行宿主 `dsh plugin --profile <name> remove -w <旧包名>`；失败则恢复备份。
4. 再执行下面的标准 `plugin add` 安装新包。
5. 启动 `dsh web`。不要修改用户 `node_modules` 源码来掩盖重复加载。

```sh
node package/scripts/maintenance.mjs migrate --profile web
node package/scripts/maintenance.mjs migrate --profile web --apply
dsh plugin --profile web add -w https://github.com/LiPu-jpg/Openwrite/releases/download/v0.2.4/dsh-openwrite-0.2.4.tgz
dsh web
```

备份写入 `$DSH_HOME/openwrite/migration-backups/`，包含 profile 的 `package.json` / lock、宿主 settings 和预设目录副本。不删除其他插件、用户配置、凭据、作品和历史会话。使用过旧 headless profile 的用户，再对 `--profile headless` 执行同样的预览与应用。

预设按来源区分：带 `.openwrite-managed.json` 的是包装管理的官方版本预设（目录名为 `openwrite-<版本>`）；没有该标记、或内容与包装校验不一致的，视为作者所有，迁移不会删除。本机若仍有旧名 `openwrite` 默认预设，会保留；已有会话继续使用当时绑定的预设，不会被改写。需要改官方预设时，先复制为 `openwrite-你的名称`。历史会话不会自动切换到新版本预设。

旧全局模型配置不会被受管理环境自动读取；作者可在新环境中重新配置，也可停机备份后迁移相应配置文件。不要把凭据复制进作品或 Git 仓库。不要手工改用户 `node_modules` 里的 JS 来消除重复 loader。

## 更新与回退

停止 dsh，对照新 Release 的精确宿主兼容版本，用新 `.tgz` 再执行 `plugin add`。环境安装使用临时目录，校验并成功启动后才替换活动记录；失败保留旧环境和配置。取消或失败后可从入口重试。

回退时，停止 dsh，重新安装上一份已验收 `.tgz`。官方预设采用版本 ID（如 `openwrite-0-2-1`），不会覆盖用户预设。请先把官方预设复制为 `openwrite-你的名称` 再修改；对被直接修改的同版本官方预设，插件保留文件并报告冲突。

## 卸载

停止 dsh 后执行：

```sh
dsh plugin --profile web remove -w dsh-openwrite
```

正常停止时卸载本插件服务、界面、连接与进程。作品、配置、凭据、会话和缓存默认保留。关闭全部 dsh 进程后，可单独删除 `$DSH_HOME/openwrite/cache/` 清理下载缓存；不要删除整个目录，其中也有配置与管理记录。异常强制退出留下的版本预设可保留排查，重装同版本并正常退出会清理未修改副本。

## 自定义预设和高级配置

自定义预设从官方版本复制，目录 ID 使用 `openwrite-` 前缀以启用创作界面。小说工具行是 `dsh-openwrite/tools`，DoG 工具行是 `dsh-openwrite/dog-tools`；不要再次注册全局 bridge 或 DoG 引擎。工具集合随会话预设保持稳定，不随界面切换。

小说工具支持 `presentation: native`（默认）、`ptc` 或 `both`。只读策略和计划模式独立约束副作用。模型服务商已接收的请求可能无法撤回：取消后停止新调度和重试，保存已完成结果与用量；费用未知时显示未知，不计为零。

bridge 的高级 `mode: external` / `baseUrl` 配置继续支持外部 Core，不接管外部进程。默认 `managed` 不需要配置端口。旧显式地址配置仍按外部模式解释。

## GitHub 源码安装

源码安装使用 dsh 官方 GitHub source 机制：`dsh plugin --profile web add -w github:LiPu-jpg/Openwrite#v0.2.4`。仓库 `prepare` 自行构建三个插件，Core wheel 随固定提交提供，不访问相邻工作区。源码安装需要 Git 和构建依赖；建议普通用户优先使用已验收 Release 包。

如果 pnpm 按本机策略阻止构建，按它显示的构建审批指引仅批准本包，再重试。安装脚本不放宽构建授权。源码安装也必须在发布验收中通过，不能用本机已编译目录代替。

## 诊断

界面「OpenWrite → 诊断与帮助」显示实时状态与可恢复错误。解包后执行 `node package/scripts/maintenance.mjs doctor --profile web` 检查标准包登记、**bundle 与 dependencies 中的旧包**、以及环境是否准备；不打印凭据或调用模型。若仍报告 leftover 旧包，先停止 dsh 再执行 `migrate --apply`。

受管理后端随 **dsh 进程** 运行：首次打开时准备，就绪后若进程异常退出会有限次自动恢复（带退避），启动失败也按同一上限继续重试。连续失败后显示脱敏的退出码/信号并提供手动重试；恢复失败不会把 dsh 一起退出。取消准备、退出 dsh 或卸载插件不会把后端拉起来，也不会留下未处理错误。恢复只重新连接写作服务，不会重放写作、评审或其他付费请求。本插件不是开机常驻服务。

小说工具的只读 / 计划模式 / Workspace 绑定是 **dsh 策略与桥接检查**，不是操作系统沙箱。受管理 Python 与安装子进程只继承启动、代理和证书所需环境变量，不把无关 API Key 传给子进程。

反馈请提供宿主版本、系统与架构、Release 版本、安装阶段及脱敏错误。来源、许可证和校验值见 Release 附件及包内 `release/`。不要提交 API Key、浏览器登录 URL 或作品全文。
