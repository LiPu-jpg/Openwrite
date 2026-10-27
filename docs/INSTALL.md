# 安装、更新与卸载

安装已发布的版本；可下载产物、SHA-256 和实际平台结果以 [GitHub Release](https://github.com/LiPu-jpg/Openwrite/releases/latest) 附件为准。验收方法见 [验收报告](RELEASE_ACCEPTANCE.md)。

## Windows Desktop 目录选择

若留空作品目录并点击“选择目录并进入”时出现 `directoryPicker.pick needs the native capability; the composed picker serves "browse"`，这是桌面宿主组合的目录选择能力与其接口要求不一致。OpenWrite 0.2.21 在宿主接口失败后调用桌面公开的 `__DSH_DESKTOP_PICK_DIRECTORY__`，覆盖侧栏进入、作品绑定、新建与恢复目录选择。取消目录对话框不会创建作品或会话；手填绝对路径仍可直接进入。

没有桌面选择通道的宿主会保留原始错误。此时可在同一个输入框填写作品的完整绝对路径，例如 `A:\AI\我的小说`，点击“进入作品”。升级插件后需要关闭并重新打开 DSH Desktop，使客户端重新加载。

## 标准安装

本次锁定 dsh `0.1.2-rc.1`，Node 24 为完整验收基线；Node 22.19 / 26 做兼容检查。安装不自动升级 dsh。先执行 `dsh --version` 核对宿主。

安装命令：

```sh
dsh plugin --profile web add -w dsh-openwrite@latest
dsh web
```

`@latest` 只在执行命令时解析 npm 最新发布版本；安装后不会后台自动升级。

需要固定版本时，例如 npm 的 `dsh-openwrite@0.2.8` 与 GitHub Release 的 v0.2.8 `.tgz` 为同一份已验收产物，包含预编译插件、编辑器资源与 Core wheel。也可直接安装 Release：

```sh
dsh plugin --profile web add -w https://github.com/LiPu-jpg/Openwrite/releases/download/v0.2.8/dsh-openwrite-0.2.8.tgz
```

`-w` 是 pnpm profile workspace 的安装参数。只输入 `dsh` 会要求 `--profile`；启动浏览器使用 `dsh web`。浏览器地址由宿主输出，不固定为 3080。

点击侧栏 OpenWrite，等待环境准备完成。下载和安装进度来自同一个运行时状态，支持取消与重试。选择已有作品目录，或选择空目录后在创作工作台初始化。入口创建新创作会话，已有会话、作品和预设不被改写。点击「创作」进入编辑器；无需发送第一条消息。

Git 是可选的作品归档能力。未安装 Git 或 Git 初始化失败时，小说文件仍会保留，工作台显示自动 checkpoint 不可用；正常编辑和模型创作可以继续。

dsh 对话模型在宿主中配置。小说生成、评审与测试模型在「任务 → 模型」配置；安装健康检查不调用这些模型。

托管模式的模型档案、路由和凭据读取 `$DSH_HOME/openwrite/state/config/`，不读取独立 Core 的 `~/.config/openwrite/`。优先使用上述界面配置；需要迁移时先停机、备份该目录，再核对「模型 → 路由」指向的档案 ID。新建自定义名称的档案后请核对路由，不能只改文件名。不要将配置或凭据提交进作品仓库。

0.2.12 的连接测试与生成请求使用同一个已配置的输出 token 上限，推理模型可在该额度内完成思考并返回正文。连接测试会发起真实模型请求；安装与自动验收使用替身，不产生模型费用。

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
dsh plugin --profile web add -w dsh-openwrite@latest
dsh web
```

备份写入 `$DSH_HOME/openwrite/migration-backups/`，包含 profile 的 `package.json` / lock、宿主 settings 和预设目录副本。不删除其他插件、用户配置、凭据、作品和历史会话。使用过旧 headless profile 的用户，再对 `--profile headless` 执行同样的预览与应用。

预设按来源区分：带 `.openwrite-managed.json` 的是包装管理的官方版本预设（目录名为 `openwrite-<版本>`）；没有该标记、或内容与包装校验不一致的，视为作者所有，迁移不会删除。本机若仍有旧名 `openwrite` 默认预设，会保留；已有会话继续使用当时绑定的预设，不会被改写。需要改官方预设时，先复制为 `openwrite-你的名称`。历史会话不会自动切换到新版本预设。

旧全局模型配置不会被受管理环境自动读取；作者可在新环境中重新配置，也可停机备份后迁移相应配置文件。不要把凭据复制进作品或 Git 仓库。不要手工改用户 `node_modules` 里的 JS 来消除重复 loader。

## 更新与回退

停止 dsh，对照新 Release 的精确宿主兼容版本，再执行：

```sh
dsh plugin --profile web add -w dsh-openwrite@latest
dsh web
```

`@latest` 不升级 dsh，也不改变已安装版本直到再次执行命令。环境安装使用临时目录，校验并成功启动后才替换活动记录；失败保留旧环境和配置。取消或失败后可从入口重试。

回退时，停止 dsh，使用精确版本（例如 `dsh plugin --profile web add -w dsh-openwrite@0.2.8`）或重新安装上一份已验收 `.tgz`，再启动。官方预设采用版本 ID（如 `openwrite-0-2-1`），不会覆盖用户预设。请先把官方预设复制为 `openwrite-你的名称` 再修改；对被直接修改的同版本官方预设，插件保留文件并报告冲突。

## 卸载

停止 dsh 后执行：

```sh
dsh plugin --profile web remove -w dsh-openwrite
```

正常停止时卸载本插件服务、界面、连接与进程。作品、配置、凭据、会话和缓存默认保留。关闭全部 dsh 进程后，可单独删除 `$DSH_HOME/openwrite/cache/` 清理下载缓存；不要删除整个目录，其中也有配置与管理记录。开发版从 #105 修复起保留版本预设目录，供旧宿主恢复历史会话。

## 自定义预设和高级配置

自定义预设从官方版本复制，目录 ID 使用 `openwrite-` 前缀以启用创作界面。小说工具行是 `dsh-openwrite/tools`，DoG 工具行是 `dsh-openwrite/dog-tools`；不要再次注册全局 bridge 或 DoG 引擎。工具集合随会话预设保持稳定，不随界面切换。

小说工具支持 `presentation: native`（默认）、`ptc` 或 `both`。只读策略和计划模式独立约束副作用。模型服务商已接收的请求可能无法撤回：取消后停止新调度和重试，保存已完成结果与用量；费用未知时显示未知，不计为零。

bridge 的高级 `mode: external` / `baseUrl` 配置继续支持外部 Core，不接管外部进程。默认 `managed` 不需要配置端口。旧显式地址配置仍按外部模式解释。

### Bring your own Python

以下配置从 **0.2.29 候选版**提供，尚未发布；0.2.28 及更早版本请使用下节的 external 模式。

已有 Python **3.10 或更高版本**及所需依赖时，可以在当前 profile 的 `cordis.patch.yml`
修改已有 `openwrite-bridge` 行的配置：

```yaml
config:
  mode: managed
  pythonPath: /absolute/path/to/python3
  # 依赖已安装在这个解释器的 site-packages 时，无须此项。
  # Android 手工准备的 pyroot 可显式列出；路径必须是绝对目录。
  pythonModulePaths:
    - /absolute/path/to/pyroot
```

也可以在启动 dsh 的进程环境中设置 `OPENWRITE_PYTHON`，值为解释器的绝对路径，不能附带命令参数；
显式 `pythonPath` 优先。桌面应用须从继承该变量的环境启动，也可直接使用上面的 profile 配置。
`pythonModulePaths` 只在选定自备解释器后生效；external 模式继续由作者管理服务端。

此路径不下载 uv 或 python-build-standalone，不执行 pip，也不安装或升级作者的依赖。
插件校验随包 Core wheel 后，将其解包到自己的环境目录，使用所选解释器启动这一份 Core，
无需作者另外安装相同版本的 `openwrite`。解释器和显式依赖目录加入环境标识，不会误用托管 Python 的缓存。
运行时保留 `-I` 隔离和 UTF-8，使用 `-B` 禁止写入依赖目录的字节码；不继承 `PYTHONPATH`，
需要额外依赖目录时使用 `pythonModulePaths`。Core 路径排在显式依赖目录之前。
共享构建需要的 `LD_LIBRARY_PATH` / `DYLD_LIBRARY_PATH` / `DYLD_FALLBACK_LIBRARY_PATH`
在此模式下从宿主传入；应选择可以用 `-I` 正常启动的解释器，不依赖 `PYTHONHOME` 或隐式用户 site。

依赖须与随包 Core 的 wheel `METADATA` 相容，包括 pydantic 及与 Python/系统 ABI 对应的
pydantic-core、PyYAML、httpx、Markdown-it-py 和需要使用的模型客户端等。
桌面 Python 3.12 可在作者自己创建的 venv 中，使用随包的 `release/requirements.lock`
与 `release/wheels/` 准备依赖；该锁文件的桌面二进制轮子不能直接套用到 Android Python 3.14。
Android 的原生依赖由宿主或作者编译、提供，插件不会尝试安装 glibc 轮子来替代 bionic 产物。

每次启动都会在所选解释器中检查 Python 版本、Core 导入和 API 版本；失败给出缺失依赖等诊断，
不回退到运行时下载，不替换旧活动记录。健康检查成功后才标记就绪。进程鉴权、随机端口、
取消、有限自动重启和卸载清理沿用托管模式；重启不重放写作或其他付费请求。
通过启动检查只说明 Studio 启动链可用，各模型及原生依赖功能仍需分别验证。

### External Studio

Android / Termux（bionic）和未列入 runtime manifest 的 ARM Linux 无托管 Python/ONNX 产物。
开发版对此返回 `RUNTIME_PLATFORM_UNSUPPORTED`（503），并提示配置外部 Studio；不再归类为网络故障。
这项修复不包含 Android 原生运行时。无需 Studio 的文件工具仍可使用。

在受支持的电脑上运行 Studio，通过私有网络或 SSH 隧道连接，在 dsh 当前 profile 的
`cordis.patch.yml` 中修改已有 `openwrite-bridge` 行的配置（不要另加同 ID 的行）：

```yaml
config:
  mode: external
  baseUrl: http://127.0.0.1:4567
  # authToken: <外部 Studio 实例凭据；仅在服务端启用认证时填写>
```

上面的回环地址可指向 SSH 本地转发端口；需要实例凭据时通过私有配置中的 `authToken`
提供，勿贴入 issue。作品目录必须在 Studio 所在机器上存在，Workspace 路径也须与服务端
一致，插件不会同步手机与电脑的文件。重启 dsh 后生效；外部进程由作者管理。

#### iPhone / iPad

iOS 可用浏览器访问电脑托管的 DSH Web 工作台或独立 Studio；电脑保持运行，并提供受信任且有访问控制的网络入口。
手机上的 `127.0.0.1` 只访问手机自身，不能沿用电脑的回环地址。本项目没有 iOS 本地 Python 后端。
候选 0.2.29 的开发范围、自动回归与待做的真机项目见 [手机验收说明](MOBILE_READINESS.md)。

#### Android / Termux

可以连接受信任的电脑，也可以在手机已有 Python 的环境中自行启动 Studio。
两者均使用上面的 external 配置，不要求插件下载 Android Python。
Termux 使用其自身的 Python 包；DSH Mobile 的 Python 扩展应使用该宿主提供的实际解释器路径。
不同发行方的路径、Python ABI 和依赖产物不能互换。

[#140](https://github.com/LiPu-jpg/Openwrite/issues/140) 的报告者提供了 Android/aarch64/bionic、
宿主 Python 3.14.8、pydantic 2.14.1 + 自编译 pydantic-core 2.50.1 的记录：
插件 0.2.26 所含 Studio 启动成功，`GET /` 返回 200。
这是一份第三方启动验证，不代表 0.2.28 或候选 0.2.29 已通过手机端完整工具验收。

可按以下目录约定准备；命令在解压 Release 后的工作目录执行：

1. 从 `package/release/runtime-manifest.json` 找到 `wheel.file`，用 Python 标准库解压到 `app/`。
   例如，0.2.28 的 Core 是 `python3 -m zipfile -e package/release/openwrite-5.8.20-py3-none-any.whl app`。
2. 在选定 Python 的 site-packages 或独立 `pyroot/` 中准备相容依赖。
   pydantic-core 需要与解释器及 Android ABI 匹配；报告者使用 Rust/clang 本地构建。
   其他原生依赖也可能需要对应构建，不能将 Linux/glibc 轮子直接改名使用。
3. 如果使用独立 `pyroot/`，在手机 shell 中以前台进程启动：

   ```sh
   PYTHONPATH="$PWD/pyroot:$PWD/app" python3 -m tools.cli studio --port 4567
   ```

4. 确认 `http://127.0.0.1:4567/` 可以打开，再将当前 profile 的已有 bridge 行设为
   `mode: external`、`baseUrl: http://127.0.0.1:4567`。此地址仅适用于 Studio 和 dsh
   在同一设备的情况；跨设备使用受信任的私网或 SSH 隧道。
5. 重启 dsh 后，继续验证 OpenWrite 面板、Workspace 路径绑定、实际文件工具和服务端鉴权。
   `GET /` 返回 200 不能代替这些检查。候选 0.2.29 也可改用上节的自备 Python 模式，
   把该 `pyroot` 绝对目录放入 `pythonModulePaths`，由插件负责启动和停止。

没有 fastembed/ONNX 等可选语义依赖时，部分检索会降级，不能据此承诺所有模型、
Embedding 或语义检索功能可用。平台 manifest 仍只列官方托管产物，不宣称提供 Android 原生构建。

## GitHub 源码安装

源码安装使用 dsh 官方 GitHub source 机制：`dsh plugin --profile web add -w github:LiPu-jpg/Openwrite#v0.2.8`。仓库 `prepare` 自行构建三个插件，Core wheel 随固定提交提供，不访问相邻工作区。源码安装需要 Git 和构建依赖；建议普通用户优先使用已验收 Release 包。

如果 pnpm 按本机策略阻止构建，按它显示的构建审批指引仅批准本包，再重试。安装脚本不放宽构建授权。源码安装也必须在发布验收中通过，不能用本机已编译目录代替。

## 诊断

界面「OpenWrite → 诊断与帮助」显示实时状态与可恢复错误。解包后执行 `node package/scripts/maintenance.mjs doctor --profile web` 检查标准包登记、**bundle 与 dependencies 中的旧包**、以及环境是否准备；不打印凭据或调用模型。若仍报告 leftover 旧包，先停止 dsh 再执行 `migrate --apply`。

受管理后端随 **dsh 进程** 运行：首次打开时准备，就绪后若进程异常退出会有限次自动恢复（带退避），启动失败也按同一上限继续重试。连续失败后显示脱敏的退出码/信号并提供手动重试；恢复失败不会把 dsh 一起退出。取消准备、退出 dsh 或卸载插件不会把后端拉起来，也不会留下未处理错误。恢复只重新连接写作服务，不会重放写作、评审或其他付费请求。本插件不是开机常驻服务。

小说工具的只读 / 计划模式 / Workspace 绑定是 **dsh 策略与桥接检查**，不是操作系统沙箱。受管理 Python 与安装子进程只继承启动、代理和证书所需环境变量，不把无关 API Key 传给子进程。

反馈请提供宿主版本、系统与架构、Release 版本、安装阶段及脱敏错误。来源、许可证和校验值见 Release 附件及包内 `release/`。不要提交 API Key、浏览器登录 URL 或作品全文。

### Stale package selection

如果宿主是 `0.2.1-rc.3`，错误却显示 `dsh-openwrite@0.2.25` 不兼容，先确认实际选择的包版本。
0.2.25 未声明该宿主；0.2.26 起根包和全部内嵌子包已声明精确支持，0.2.28 继续包含对应验收。
不要给旧包添加版本豁免来掩盖取包问题。

```sh
npm view dsh-openwrite@latest version peerDependencies --registry=https://registry.npmjs.org
```

对照当前 profile 的 `package.json`、`pnpm-lock.yaml` 和已安装包的 `package.json`。
不带版本的 `add dsh-openwrite` 可能沿用已有精确依赖；显式 `@latest` 或精确版本才清楚表达升级意图。
商城显示的目录版本也不能替代 npm 实际解析结果。仅凭 #142 的报错不能确定用户侧是哪份锁或缓存。

完全退出 dsh/Desktop（含托盘）、备份 profile 后，优先使用已验收 Release 包的停机升级工具：

```sh
node package/scripts/safe-upgrade.mjs --profile desktop --package dsh-openwrite@0.2.28
```

该例固定到已发布的 0.2.28；更新版本须先确认其验收结果。源码安装、tarball 和自定义 registry
按各自来源排查，不直接清空整个 pnpm store 或删除 profile。停机升级工具失败会保留旧环境与日志。
0.2.29 候选的 `maintenance.mjs doctor --profile desktop` 会另外显示请求 spec、实际已装版本及诊断工具版本，
其停机升级工具也会把裸包名规范成 `dsh-openwrite@latest`；指定精确版本和本地 tarball 不受影响。

## dsh 0.2 客户端兼容排查

`dsh-openwrite@0.2.10` 的旧工作台按 0.1 接口构建，不能通过版本豁免获得 0.2.0-rc.2 的客户端兼容性。根包豁免不覆盖内嵌子包：`@dsh-novel/studio-panel@<ver>`、`@dsh-external/dsh-dog@<ver>` 各自经过宿主版本检查。优先升级到包含 #45 修复的包；修复后的精确 `0.2.0-rc.2` 声明覆盖根包和所有子包，不需要手工编辑 `compatibility.json`。

`dsh-openwrite@0.2.23` 起，根包和全部内嵌子包的声明同时覆盖精确宿主 `0.2.1-rc.2`，安装和激活不需要版本豁免。宿主判断的是 `package.json` 的 `peerDependencies`（`@deepseek-ai/dsh-*`），不是 `dsh.compatibility` 字段；因此只改 `dsh.compatibility` 字符串并不能让 0.2.22 在 0.2.1-rc.2 上加载。若安装日志出现 `plugin does not support the DSH version in use`，请直接升级到 `0.2.23` 或更高的已验收版本，不要手工改版本号或给旧子包授权。本版已在 `0.2.1-rc.2` 完成 Web 启动、OpenWrite 入口、工作台三页签、DoG 面板与其他插件共存的验证；`0.1.2-rc.1`、`0.2.0-rc.2` 回归通过，Windows Electron 桌面端仍未实机复测。

本修复同时处理 `conversation.chat.turnTail` 从 chain 到 list 的变化，以及 `uiSession.pendingInteractions` 到 `uiSession.sessionStatus` 的变化。客户端初始化或延迟槽位注册失败时，插件回滚对应注册并在浏览器控制台输出 `[OpenWrite/Studio]` / `[OpenWrite/DoG]` 和原始异常，避免让这类插件初始化异常升级为宿主 web boot 失败。此修复不更改桌面端自身的 profile 恢复策略。

如果旧版本已经触发桌面端恢复，关闭桌面端后备份整个 profile，找到恢复前的 `cordis.patch.yml.bak-*`，恢复 patch 和原 `package.json` 中的 `dsh.profile.bundles`。这两项需一起核对，才能重新加载其他插件。保留已安装依赖和作品目录，不要用空 profile 替换完整配置。

开发者可在锁定依赖和构建完成后运行真实客户端启动检查：

```sh
npm run test:client-boot
node scripts/client-boot-smoke.mjs --host-cli=/absolute/path/to/dsh-0.2.1-rc.2/node_modules/@deepseek-ai/dsh/lib/bin.js
node scripts/client-boot-smoke.mjs --host-cli=/absolute/path/to/dsh-0.2.0-rc.2/node_modules/@deepseek-ai/dsh/lib/bin.js
node scripts/client-boot-smoke.mjs dsh-openwrite-<version>.tgz --host-cli=/absolute/path/to/dsh-0.2.1-rc.2/node_modules/@deepseek-ai/dsh/lib/bin.js
```

脚本需要 Playwright Chromium，创建临时 Web profile，检查无豁免版本闸门、两个客户端加载、真实预设选择、会话导航、三个工作台页签出现和创作视图激活、DoG 面板及其他插件共存，后端就绪与未初始化响应由测试夹具提供，不准备 Python 环境、不调用模型；实际安装与后端动作由独立发布验收覆盖。它验证 Web 客户端兼容性；Windows Electron 的原生启动和恢复流程仍须在对应平台完成发布验收。

## 0.2.12 的预设与审读修复

0.2.11 仅补齐了客户端启动与版本声明，仍存在 #50–#52 的预设注册和导航断点。0.2.12 在新宿主中注册同一份版本化预设，并保留旧宿主的目录副本；不要通过内联手工补丁或版本豁免替代升级。升级不重绑已有会话的预设，新的作品入口使用对应版本的预设。

连续审读在后台工作区轮询和任务失效时保持正文与滚动位置，仅在章节身份/顺序/修订变化或手动刷新时重载。重载期间保留上次正文，失败时显示错误。切换作品会清空旧作品的阅读状态。

## 作品信息与推理模型预算

在「任务 → 导入与导出 → 编辑作品信息」填写或修改书名、作者署名和语言。旧作品也可补齐作者，无需手工编辑配置文件。保存冲突时保留输入；请取消编辑并重新载入最新信息后再修改。未填写作者仍不能进行交付导出。`novel_project_init` 也支持可选 `author` 与 `language`。

写章、事实提取和状态结算（包括重试）统一使用「任务 → 模型」中所选模型的输出 token 预算，不再在非创作阶段偷偷降到 4096/8192。推理模型的隐藏推理通常也占用输出额度：若仍出现截断，请在服务商允许的范围内提高所选模型的输出预算（例如 32768 或 49152），同时核对上下文窗口。正文目标字数与 token 预算是两回事；较高上限不等于一定消耗该数量，也不能保证所有模型都支持它。此次验证使用模型替身，未进行真实模型计费测试。
