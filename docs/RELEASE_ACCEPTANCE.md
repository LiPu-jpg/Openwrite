# 发布验收记录

## 0.2.28 候选（未发布）

本轮捆绑 Core **5.8.20**，固定源码 `9611c654e5d77bcb5968105a7adfa8e9b4f9624a`。修复正文延迟输入漏存、按审稿修订越过作者选区，以及真实 Vditor 换行规范化导致的选区拒绝，详见[补修范围](EDITOR_SAFETY_REPAIRS.md)。

本地 Core **1550 passed / 32 skipped**、真实 HTTP **14 passed**、界面 **336 passed**、managed **34 passed**、完整插件检查通过。新增真实候选包编辑器浏览器场景 **9 组通过**。wheel 的 499 个运行时文件与固定源码逐字节一致，163 个应打包 Python 文件无遗漏，SHA-256 为 `aa1f25f3c615497cd73c3c059fd2acc4e71ba2e936765d02331d1382df4b201a`。跨平台最终结果在验收后补齐。

候选仍未发布，公开版本为 **0.2.27**；#123 的宿主正式发布和 Android/Termux 真机条件继续保留。

### 前轮候选证据（Core 5.8.19，未发布）

本轮捆绑 Core **5.8.19**，固定源码 `d2b3cbe6009a1ab4f1064dca0115cb44ba080a3f`。修复 CRLF/emoji 选区坐标、独立 Studio 原始片段保留、中断升级无依赖恢复与损坏 tgz 缓存重试，详见 [补修记录](SELECTION_UPGRADE_REPAIRS.md)。

本地 Core 全量 **1542 passed / 32 skipped**，修订服务与真实 HTTP 23 passed，原生预设/升级/运行时 40 passed，managed 33 passed，界面 319 passed，插件完整检查通过。wheel 的 499 个运行时文件与固定源码逐字节一致，163 个应打包 Python 文件无遗漏，SHA-256 为 `9d5307201bea47be3675b2d968ab444503479ff71d2b7ad9b3922a998889ba3a`。本地测试不计作 Windows/Android 真机验收。

[Core PR #134](https://github.com/LiPu-jpg/Openwrite/pull/134) 与 [插件 PR #135](https://github.com/LiPu-jpg/Openwrite/pull/135) 已合并，最终 **22 项检查全部成功**：[三系统回归](https://github.com/LiPu-jpg/Openwrite/actions/runs/40446870919)、[完整安装/客户端验收](https://github.com/LiPu-jpg/Openwrite/actions/runs/40446870931)、[插件检查](https://github.com/LiPu-jpg/Openwrite/actions/runs/40446870954)。下载原始报告后再次核对：

| 验收 | Linux | macOS | Windows |
| --- | --- | --- | --- |
| 固定 Core 全量 | 1542 passed / 32 skipped | 1542 passed / 32 skipped | 1542 passed / 32 skipped |
| 真实 HTTP 路由与选区保护 | 10 passed | 10 passed | 10 passed |
| 真实 Electron 44.7.0 脚本 | 5 passed / 0 skipped | 5 passed / 0 skipped | 5 passed / 0 skipped |
| wheel 源码字节 / 应打包 Python 文件 | 499 / 163 一致 | 499 / 163 一致 | 499 / 163 一致 |

8 份安装/源码、5 份精确宿主客户端、6 份原生回归报告全部通过。六组原生安装测试对同一 tarball 中的预设、升级与运行时脚本运行 40 项回归。32 项 Core 跳过项沿用缺失样例/外部 checkout 限制，新增回归没有跳过；测试不调用真实模型。

候选 tarball SHA-256：`b73ed0a87da44f93f804ded3c5fffe6c83c29a9d6bf9c64fe9141eefc5a3a85b`。CI 提交 `7c91429693dd672bd1d426fa54a1bc075cad13b4` 与插件合并提交 `3c51627bf2a21a4e7c22fc3e77ab0e61f0db891f` 的源码 tree 均为 `879b9f30ed0c812d5b3aca34571a186f86670471`。Core 来源提交保留于 native-core 合并提交 `1ff7d699a456b90b7315eccfcf63c042cbf37d99`；候选包保留为验收证据，未发布。

#123 的宿主正式发布与 Android/Termux 真机两项继续保留，暂停发布。公开 npm/GitHub 版本仍为 **0.2.27**。

### 前轮候选证据（Core 5.8.18，未发布）

本轮根据 #123 新回复捆绑 Core **5.8.18**，固定源码 `43cb604a7583b7268f47e54ceb8a0c30b95e82b2`。本地全量 **1541 passed / 32 skipped**，真实 HTTP 2 passed；wheel 的 498 个打包源文件与固定源码逐字节一致，163 个应打包 Python 文件无遗漏，SHA-256 为 `09f9baef5fe0d502510c8542f20c6abaf6893f02e2d069d7f0d7cc50c7aeea93`。

写章/修订 thinking 模式的三个回归在旧冻结源码失败，新实现通过。原生预设/升级/运行时本地 34 passed。报告者已补齐旧会话与 B-13 的 Windows 验收；余下宿主正式发布和 Android/Termux 真机两项仍暂停新版本发布。具体修复、来源和边界见 [#123 回复补修](ISSUE_123_FOLLOWUP.md)。

[PR #131](https://github.com/LiPu-jpg/Openwrite/pull/131) / [#132](https://github.com/LiPu-jpg/Openwrite/pull/132) 已合并，最终 22 项检查全部成功：[三系统回归](https://github.com/LiPu-jpg/Openwrite/actions/runs/40437762040)、[完整安装/客户端验收](https://github.com/LiPu-jpg/Openwrite/actions/runs/40437761963)、[插件检查](https://github.com/LiPu-jpg/Openwrite/actions/runs/40437762138)。三系统 Core 各 1541 passed / 32 skipped、HTTP 各 2 passed、真实 Electron 各 5 passed。8 份安装/源码、5 份客户端和 6 份原生报告下载后复核通过。

本轮 tarball SHA-256 为 `4bcde6d6f535906a5a04490218a0d972e84329ff750af6803a4214fbf609024e`；CI 提交 `ecfb7c34c5b0a29d395136da775bb964c3c91d11` 与修复合并提交 `14dd3a5dbc7d1661adb9b684e0f137298bf2591f` 的源码 tree 同为 `67042838daf11f5c7fc27e0ffe158677a73c3196`。产物未发布；本轮未发起真实模型请求，不能把请求边界替身测试算作服务商实测。

### 前轮候选证据（Core 5.8.17，未发布）

按用户要求先修可修部分，保留未完成项并暂停发布。变更范围与限制见 [#121–#123 修复记录](ISSUES_121_123.md)。本节不是正式发布记录，npm/GitHub 公开版本仍为 0.2.27。

Core 5.8.17 来源 [PR #126](https://github.com/LiPu-jpg/Openwrite/pull/126)，固定提交 `c655dc2106b07cf08324728e0b5babf1fcc12afb`；冻结提交全量 **1531 passed / 32 skipped**。wheel 从该提交的干净归档构建，498 个打包源文件逐字节一致，并核对 163 个应打包 Python 文件未遗漏；wheel SHA-256 为 `93507c54ee5fe3d22d4e858e9e1d8efe0cd2917f554ff5a13872dbb1fed06fab`。

修复已通过 [Core PR #126](https://github.com/LiPu-jpg/Openwrite/pull/126) 和 [插件 PR #127](https://github.com/LiPu-jpg/Openwrite/pull/127) 合并。最终 **22 项检查全部成功**：[三系统回归](https://github.com/LiPu-jpg/Openwrite/actions/runs/40391934852)、[完整安装/客户端验收](https://github.com/LiPu-jpg/Openwrite/actions/runs/40391934711)、[插件检查](https://github.com/LiPu-jpg/Openwrite/actions/runs/40391935114)。原始 CI 报告下载后再次核对：

| 验收 | Linux | macOS | Windows |
| --- | --- | --- | --- |
| 固定 Core 全量 | 1531 passed / 32 skipped | 1531 passed / 32 skipped | 1531 passed / 32 skipped |
| 真实 HTTP dry-run / 归档历史 | 2 passed | 2 passed | 2 passed |
| 真实 Electron 44.7.0 脚本 | 5 passed / 0 skipped | 5 passed / 0 skipped | 5 passed / 0 skipped |
| wheel 源码字节 / 应打包 Python 文件 | 498 / 163 一致 | 498 / 163 一致 | 498 / 163 一致 |

32 项跳过均来自仓库缺失的旧标准样例、演示作品或外部 checkout，新增问题回归未跳过。自动化没有复现报告者的原 Windows Electron 历史会话，也不等于 Android/Termux 真机验收。

界面 310 项、本地 DoG 64 项和类型检查、managed 32 项及插件完整检查通过。8 份安装/源码、5 份精确宿主客户端和 6 份原生回归报告全部通过；原生报告覆盖持久预设、离线升级和受管理后端三组。安装包报告绑定同一 tarball SHA-256，源码安装固定插件提交。

候选 tarball SHA-256：`2d0f1b6c34c1a48386fc08798c8fb7a09c2e964ef6d2d6a558f62e7ed469c7bb`。CI 来源提交 `a8babe9b9b3909bbfedbf3e26df41d022624abbb` 与主分支修复合并提交 `bc6af78a562725a02a0fff6133eb0e3f5e603d6f` 的 tree 均为 `240a99caea04ba8436c1bfaec306969db0c216ea`。Core 来源提交已保留在 native-core 的合并历史中。

真实 OpenCode Go 单次流式取消验收确认保留部分正文、关闭 HTTP 响应，后续请求在调用提供方前拒绝，作品文件未变；它与不调用模型的 CI 分开记录。新增 [95 项工具参考](TOOLS.md) 和 [上下文槽位参考](CONTEXT_SLOTS.md) 已核对运行时注册、固定 Core 源码及候选包内字节，修复 #128。

**以上前轮候选包只作验收证据保存，没有发布。** 当时 #123 的四项待办均保留；后续回复补齐了其中两项，余下条件见本节开头。#121/#122 的报告条目已修复、验收并合并关闭；关闭报告不代表候选版本已发行。

## 0.2.27

捆绑 Core 5.8.16，来源 [PR #124](https://github.com/LiPu-jpg/Openwrite/pull/124)，源码提交 `27ec8b3bea0a3f8754f5701a7b21c23a9328d6b7`。wheel 从该提交的干净归档构建，496 个打包源文件与提交逐字节一致，SHA-256 为 `8be4dc5e3feb2d0faf91a1e0763f05ff338c237912edd8c066aaad118ec41ec4`。

本地 Core 全量 1478 passed / 32 skipped；HTTP 行中锚点的 LF/CRLF 预览、应用、撤销与不匹配保护通过。预设生命周期、停机升级与 managed runtime 组合 32 passed（含五项手动重试/取消回归），并加入六组原生安装矩阵。真实 OpenCode Go 流式安全评审 1 次成功，首次 max_tokens=24000、耗时 4.424 秒；此前工作台 Console 档案保存、连接测试及流式写作也成功。CI 本身不调用模型，真实模型记录与其独立，不能把 CI 的 modelCalls:0 解释成真实模型验收。

[GitHub Release v0.2.27](https://github.com/LiPu-jpg/Openwrite/releases/tag/v0.2.27) 与 [npm `dsh-openwrite@0.2.27`](https://www.npmjs.com/package/dsh-openwrite/v/0.2.27) 均已发布，官方 registry 的 `latest` 已更新到 0.2.27。GitHub 四份公开附件逐字节与 CI 原始文件一致；从官方 npm registry 无认证重新下载的 10,169,500 字节安装包也与 CI 包逐字节一致，SHA-256、npm 的 SHA-1 与 SHA-512 integrity 均已核对。发布通过本人双重验证后先返回 HTTP 202，等待服务端校验与公开同步完成，再以公开下载验证确认发布成功。

使用 [完整发布 CI](https://github.com/LiPu-jpg/Openwrite/actions/runs/40358781683) 原始 validated-release 产物；[插件检查](https://github.com/LiPu-jpg/Openwrite/actions/runs/40358781965) 同样通过，共 16 项检查全部成功。验收包含 8 份安装/源码报告、5 份精确宿主客户端报告，以及 6 份绑定安装包哈希的原生回归报告，每组 32 项回归通过。tarball SHA-256 为 `94e9df25289b7053f12978f8fc4bb75f3f8da894f02312e82a88ca19efa095f2`。CI 来源提交 `e08679c47258bb1584e2920cf0245f24718bb9db` 与主分支合并提交 `cbab43b4e427ae1507d26e96e47a9abdbeb6414b` 的源码 tree 均为 `5bde0e856c7643d603bfe202704c4051860c43a0`；发布直接使用 CI 包，没有重新打包。

合并后的[主分支发布 CI](https://github.com/LiPu-jpg/Openwrite/actions/runs/40360046529) 和[插件检查](https://github.com/LiPu-jpg/Openwrite/actions/runs/40360046553) 同样全部通过。

[未完成验收与上游依赖](CLOSED_ISSUE_FOLLOWUPS.md) 继续由 [#123](https://github.com/LiPu-jpg/Openwrite/issues/123) 跟踪；其后新增的 #121/#122 已由上方候选修复完成并关闭，尚未随新版本发行。

## CI 运行范围

仅修改 README.md 或 docs 下的 Markdown 文档时，跳过插件维护与跨平台发布验收。预设、技能、脚本、依赖、资源和工作流变更仍触发检查；混合文档与代码的提交也照常检查。开发分支通过 PR 检查，避免同一提交在分支 push 与 PR 上重复执行；主分支合并后保留验收，两个工作流均可手动触发。发布必须使用完整验收通过的产物，跳过检查不能作为发布通过的证据。

新建作品的验收请求最多等待 60 秒（原为 15 秒），保留成功耗时和失败诊断；不重试写请求，超时仍失败。此调整容纳慢速运行器，不代表初始化耗时问题已被修复。

## 0.2.26

[GitHub Release](https://github.com/LiPu-jpg/Openwrite/releases/tag/v0.2.26) 与 [npm `dsh-openwrite@0.2.26`](https://www.npmjs.com/package/dsh-openwrite/v/0.2.26) 均已发布，npm `latest` 已更新到 0.2.26。使用 [完整发布 CI](https://github.com/LiPu-jpg/Openwrite/actions/runs/40323278858) 的原始 `validated-release` 产物，没有重新打包；[离线契约](https://github.com/LiPu-jpg/Openwrite/actions/runs/40323278881) 也通过，共 16 项检查全部成功。发布 PR [#118](https://github.com/LiPu-jpg/Openwrite/pull/118) 已合并，合并后的 [主分支发布 CI](https://github.com/LiPu-jpg/Openwrite/actions/runs/40324223823) 和 [插件检查](https://github.com/LiPu-jpg/Openwrite/actions/runs/40324223804) 同样全部通过。

包 SHA-256：`d8cd9926a9b4d749f320028313046f0b14a55dbab68d7626d18f13d49740eccd`，大小 10,159,927 字节；GitHub 附件服务端 digest、公开地址无认证重新下载的完整包，以及官方 npm registry 无认证重新下载的完整包，均与 CI 包一致；npm 的 SHA-1 与 SHA-512 integrity 也已核对。来源提交为 CI 测试合并提交 `7522b6cb3b7f37ebaf267519c6051389413aa089`，源码 tree `9e2a2d746f44af554af9192458eb9d8318a6049d` 与主分支合并提交 `e8805b2bcc43bec74af0e9ae364137146c7edf96` 一致。Core 5.8.14 wheel SHA-256：`b96637d9cad364d280122bae9dd59e42be811cd43389ddb704ff4dc110f0acc0`。

8 份原生安装/源码报告和 5 份精确宿主客户端报告全部通过，覆盖 Linux、macOS arm64/x64、Windows、Node 22.19/24/26、GitHub 源码安装、alpha 兼容，以及 DSH `0.1.2-rc.1` / `0.1.5-alpha.1` / `0.2.0-rc.2` / `0.2.1-rc.2` / `0.2.1-rc.3` 的 Web 工作台、预设、DoG 与其他插件共存。发布包的各平台/alpha 安装及客户端报告均绑定同一 SHA-256；源码安装单独固定来源 Commit。

此前 Core 全量 1451 passed / 32 skipped，前端 307 passed；版本升级后的预设生命周期与离线升级回归 8 passed。真实付费模型调用、Android 原生和 Windows Electron 手工升级/恢复未执行，不能计为通过。修复范围与限制见 [升级恢复](ISSUES_105_113.md)、[连载报告](ISSUE_109_REPAIRS.md)、[OpenCode Go](OPENCODE_GO.md)。

## 0.2.25

[GitHub Release](https://github.com/LiPu-jpg/Openwrite/releases/tag/v0.2.25) 与 [npm `dsh-openwrite@0.2.25`](https://www.npmjs.com/package/dsh-openwrite/v/0.2.25) 均已发布，npm `latest` 已更新到 0.2.25。使用 [PR 完整发布 CI](https://github.com/LiPu-jpg/Openwrite/actions/runs/39893387812) 验收通过的原始产物，没有重新打包。该运行的来源提交为 `1c04d97c9571f09f9a49567c95b7c38c0507ddbc`，源码 tree `3db86dcdb88f69fd6d92f5881fee0db3c2f0bd8c` 与主分支合并提交 `f0785f2c331f2d090450b1e127e5750c64dc4487` 一致。包 SHA-256 为 `ca73ca424844ddee62f37c2725591bf44ff7701f25d1d12693fa270ee0c26049`；官方 registry 无认证下载的完整 10,141,143 字节与 CI 包一致，GitHub Release 的服务端附件 digest 也一致。

8 份原生安装/源码报告和 4 份精确宿主客户端报告均通过，覆盖 Linux、macOS arm64/x64、Windows、Node 22.19/24/26、源码安装、alpha 兼容及宿主 `0.1.2-rc.1` / `0.1.5-alpha.1` / `0.2.0-rc.2` / `0.2.1-rc.2`。合并后的 [主分支发布 CI](https://github.com/LiPu-jpg/Openwrite/actions/runs/39895883025) 同样通过。核心 [PR #101](https://github.com/LiPu-jpg/Openwrite/pull/101) 与插件 [PR #102](https://github.com/LiPu-jpg/Openwrite/pull/102) 已合并。Core wheel 5.8.12 的 SHA-256 为 `fefd03aebfb0ebf084fd40f4897af309a532111903a3813f01276daa1c36c345`。

Core 全量 1424 passed / 32 skipped；后续超时配置校验等定向回归 38 passed、规划转换回归 36 passed；前端 301 passed；managed runtime/策略 24 passed；离线升级 5 passed；跨端契约通过。手工浏览器检查只使用 `~/my_novel`。真实模型调用为 0，Windows Electron 人工验收尚未执行。#98.1 的原生宿主补丁见 [fork PR #1](https://github.com/LiPu-jpg/deepseek-harness/pull/1)，[专项 CI](https://github.com/LiPu-jpg/deepseek-harness/actions/runs/39901088607) 的 Windows 185 passed / 3 skipped、Linux 187 passed / 1 skipped。上游关闭 PR 提交入口，补丁尚未成为已发布宿主；详情见 [实现与限制](ISSUES_98_100.md)。

## 0.2.24

[GitHub Release](https://github.com/LiPu-jpg/Openwrite/releases/tag/v0.2.24) 与 [npm `dsh-openwrite@0.2.24`](https://www.npmjs.com/package/dsh-openwrite/v/0.2.24) 均已发布，npm `latest` 已更新到 0.2.24。直接使用[完整发布 CI](https://github.com/LiPu-jpg/Openwrite/actions/runs/39716542888) 验收通过的原始产物，未重新打包。来源提交 `d16623c6b0d2a84d45dffe23c24e641df790175f`，源码 tree `e0b2fd0647114e46e6fd188f4fb32b13fadc6b3d` 与主分支合并提交 `32166de6a3f66d8ebb2e3b5bd3912c1c1236f07b` 一致。npm 包 SHA-256 为 `a9fb766e8277b0f7dfecd9ea2284720512583e766e82515b70a529c967aa0170`；从官方 registry 无认证重新下载后，包字节、SHA-1、SHA-512 integrity 与 CI 产物和 registry 元数据均一致。

8 份原生安装/源码报告与 4 份客户端契约报告全部通过，覆盖 Linux、macOS arm64/x64、Windows、Node 22.19/24/26、源码安装、alpha 兼容与精确宿主 `0.1.2-rc.1` / `0.1.5-alpha.1` / `0.2.0-rc.2` / `0.2.1-rc.2`。GitHub 四份公开附件重新下载后均与 CI 原文件逐字节一致；合并后的[主分支完整 CI](https://github.com/LiPu-jpg/Openwrite/actions/runs/39717124199) 也已通过。源码安装命令的超时从两分钟调整为五分钟，保留原有成功条件，并补充退出状态、信号和错误码诊断。

修复 #88–#95，合并核心 [PR #96](https://github.com/LiPu-jpg/Openwrite/pull/96) 与插件 [PR #97](https://github.com/LiPu-jpg/Openwrite/pull/97)。捆绑 Core 5.8.11，wheel 来源提交 `596709e3f4bbe4eab7ce59513c9f36c4390ad367` 已包含在 `native-core` 分支，wheel SHA-256 为 `7937914eee6b99cd64fee2ead96a5e6d63e807acae0a610c1c4abf863e814188`。行为与草稿恢复步骤见[修复说明](ISSUES_88_95.md)。

核心全量 pytest：1409 passed、32 skipped；wheel 解包后隔离回归：11 passed。插件构建、doctor、生命周期、双 profile、预设、bridge/panel smoke、14 项 epoch、298 项组件、23 项受管理运行时检查及跨仓库 contracts 通过。真实服务商连续请求与 Windows Electron 实机验收未运行，不计入通过。

## 0.2.23

[GitHub Release](https://github.com/LiPu-jpg/Openwrite/releases/tag/v0.2.23) 与 npm `dsh-openwrite@0.2.23` 已发布，npm `latest` 已更新到 0.2.23。使用[主分支完整 CI](https://github.com/LiPu-jpg/Openwrite/actions/runs/39219394324) 验收的原始产物，来源提交 `341408b80075fe4cc429f30a3327bcbdf2e69903`，npm 包 SHA-256 为 `8eb13e3de31b2144f1d5a57094abff38951c0329058520c96331aed03c735470`。8 份安装/源码报告与 4 份宿主客户端报告（含精确 `0.2.1-rc.2`）全部通过；GitHub 四份附件逐一与 CI 原文件比对一致，官方 npm registry 无认证下载包的字节与 SHA-256 也一致。

修复 [#83](https://github.com/LiPu-jpg/Openwrite/issues/83)/[#84](https://github.com/LiPu-jpg/Openwrite/issues/84)/[#85](https://github.com/LiPu-jpg/Openwrite/issues/85)：根包与全部内嵌子包的 `peerDependencies`、`dsh.compatibility.dsh` 和 `dshReleases` 加入精确宿主 `0.2.1-rc.2`。宿主版本闸门读取的是 dsh peer 范围，因此只修改展示用的 `dsh.compatibility` 不能让旧包通过；本版四个包同步声明后，安装与激活均不需要版本豁免。发布矩阵新增 `0.2.1-rc.2` 客户端契约，并与 `0.1.2-rc.1`、`0.1.5-alpha.1`、`0.2.0-rc.2` 一起通过。

本机 macOS arm64 / Node v24.15 另使用官方 registry 的精确 `@deepseek-ai/dsh@0.2.1-rc.2` 完成安装级复验：tarball 经 pnpm 安装进隔离 profile，宿主启动不再出现 `incompatible with dsh` / `skipping profile bundle`；浏览器中两个客户端入口激活，OpenWrite 入口和作品启动器可用。真实模型调用为 0。Windows Electron 桌面端原生启动与恢复仍须对应平台实机验收，本版未计为通过。

## 0.2.22

[GitHub Release](https://github.com/LiPu-jpg/Openwrite/releases/tag/v0.2.22) 与 npm `dsh-openwrite@0.2.22` 已发布，npm `latest` 已更新到 0.2.22。使用[主分支完整 CI](https://github.com/LiPu-jpg/Openwrite/actions/runs/39084916927) 验收的原始产物，来源提交 `58209eabbaf0be1f54f562eab4bb5ca12a46bc57`，npm 包 SHA-256 为 `2f20f5e2326707d65119d549b08382dd2e83af481ac60e6ac6f1ee668b446683`。8 份安装报告与 3 份宿主客户端报告全部通过；GitHub 四份附件逐一与 CI 原文件比对一致，官方 npm registry 无认证下载包的字节与 SHA-256 也一致。修复 [#81](https://github.com/LiPu-jpg/Openwrite/issues/81)（bundle patch 覆写核心 connection 行与其他 bundle 冲突导致整机无法启动；DoG 调试通道改由插件自托管于 Web 载体）与 [#82](https://github.com/LiPu-jpg/Openwrite/issues/82)（受限网络下运行时下载必然超时、依赖索引不可换源）。两个 issue 的报告者均已随 issue 关闭获得修复说明。

## 0.2.21

[GitHub Release](https://github.com/LiPu-jpg/Openwrite/releases/tag/v0.2.21) 与 npm `dsh-openwrite@0.2.21` 已发布，npm `latest` 已更新到 0.2.21。使用[主分支完整 CI](https://github.com/LiPu-jpg/Openwrite/actions/runs/38444848871) 验收的原始产物，来源提交 `4e5f88aac8b14c2402c509b2282810cc85840129`，npm 包 SHA-256 为 `b53e3638308185b5890207bc01806641a966620915b99102f5cb35c462b1daee`。8 份安装报告与 3 份宿主客户端报告全部通过；GitHub 四份附件逐一与 CI 原文件比对一致，官方 npm registry 无认证下载包的字节与 SHA-256 也一致。

修复 [#79](https://github.com/LiPu-jpg/Openwrite/issues/79)，合并来源 [PR #80](https://github.com/LiPu-jpg/Openwrite/pull/80)。Windows Desktop 宿主目录接口失败后，插件使用桌面公开的系统目录选择通道；侧栏进入和工作台内所有目录选择共用入口。宿主取消不触发第二个对话框，桌面取消不创建作品/会话，手填路径跳过选择器，没有桌面能力时保留原始错误。Core 保持 5.8.10，wheel 与 requirements.lock 未变。

`npm run check:plugin` 全部通过（298 项组件测试）。新增回归直接对正式 0.2.20 客户端复现同一错误，修复后的客户端通过；从本版主分支 CI 包提取客户端执行相同回归也通过。正式发布构建在打包前执行该回归。回归覆盖宿主优先、两种取消、首次进入、共享入口、缺失/无效桌面能力、桌面对话框失败和手填路径。

本版原生 Windows 安装与浏览器检查运行在 Web profile；Windows Electron 系统文件夹对话框的实机复测未计为通过。目录通道的名称与返回契约已对照桌面上游源码，安装指南补充排查及手填路径方式。升级后需关闭并重新打开 DSH Desktop，重新加载客户端。真实模型调用为 0。

## 0.2.20

[GitHub Release](https://github.com/LiPu-jpg/Openwrite/releases/tag/v0.2.20) 与 npm `dsh-openwrite@0.2.20` 已发布，npm `latest` 已更新到 0.2.20。使用[主分支完整 CI](https://github.com/LiPu-jpg/Openwrite/actions/runs/38296670387) 验收的同一份原始产物，来源提交 `4d54f3c619f853a4243cd60e67ef6c8ba8d336af`，npm 包 SHA-256 为 `486c20fbd36909e32cc6cac1fd1e734872abec53da749c0860f8e5e1d4cf6cda`。六组原生平台/Node、源码安装与 alpha 兼容共 8 份运行报告、三代宿主客户端 3 份报告全部通过；GitHub 四份附件逐一与 CI 原文件比对一致，从官方 npm registry 无认证重新下载后，包字节及 SHA-256 也一致。

修复 [#76](https://github.com/LiPu-jpg/Openwrite/issues/76) 与 [#65](https://github.com/LiPu-jpg/Openwrite/issues/65)，合并来源为引擎 [PR #77](https://github.com/LiPu-jpg/Openwrite/pull/77) 和插件 [PR #78](https://github.com/LiPu-jpg/Openwrite/pull/78)。捆绑 Core 5.8.10，wheel 来源提交 `18a500015f5d5da00f2f4d5ccd2325b084fed24b` 已包含在合并后的 native-core 分支；wheel SHA-256 为 `f121410300c7e7c55d594d0b8d7f4da41f8a17f0dfb5dc3b195e447b618bfd4d`。

- 生成后提交失败保留正文与恢复句柄；恢复提交复用已有草稿。写章返回持久化 task_id，忙碌延后、取消请求与终态分离，传输错误可追踪。
- 统一字数目标，补齐验收恢复、批量与字段级编辑、精确文本/换行保护、完整审稿覆盖与硬检查、正文结构及推理污染检查、审稿历史。
- persona 和所有技能入口跟随作者语言；运行环境与任务状态提供英文，Studio 错误附带英文说明和错误码。
- Core 全套 pytest 1397 passed / 32 skipped，专项回归 21 passed。本地 macOS arm64 真实候选包安装、生命周期及浏览器验收通过；正式包以以上主分支 CI 报告为准。真实模型写作未实测，不计为通过。

恢复步骤与明确的范围见 [修复说明](ISSUE_76_REPAIRS.md)。跨章聚合与逾期伏笔硬阻断按 issue 允许的方案声明职责范围，本版未新增这些功能。

## 0.2.19

[GitHub Release](https://github.com/LiPu-jpg/Openwrite/releases/tag/v0.2.19) 已发布，直接使用[完整 CI](https://github.com/LiPu-jpg/Openwrite/actions/runs/38167325137) 验收的同一份包。来源提交 `e0c1ab7`，npm 包 SHA-256 为 `97f89586e4c43071ebca67abd5af1df1ae42b637cf6637d4fc26ca31c133d784`。六组原生平台/Node、源码安装与 alpha 兼容共 8 份运行报告、三代宿主客户端 3 份报告全部通过；Release 四份附件的校验值已与 CI `validated-release` 产物逐一核对。npm `dsh-openwrite@0.2.19` 已发布到官方 registry（registry.npmjs.org），`latest` 已更新到 0.2.19；从官方 registry 无认证重新下载后，SHA-256 与上述 CI 包一致。

修复 [#74](https://github.com/LiPu-jpg/Openwrite/issues/74) 与 [#75](https://github.com/LiPu-jpg/Openwrite/issues/75)，均为插件侧改动，Core 保持 5.8.9（native-core `d0a75e30047c28c99af909e1b85b07190abb1fb7`），wheel 与 requirements.lock 未变。

- #74：vendor/dsh-dog 运行时不再裸导入 `@deepseek-ai/dsh-home-paths` 与 `@deepseek-ai/dsh-tools` 两个 peer 宿主包（pnpm 隔离布局下从 vendor 目录不可解析 → openwrite-dog 条目导入失败 → openwriteDog 未注册 → 预设从列表消失）。`dshHomePath` 与 `defineTool` 由新增 `src/host-shims.ts` 自包含实现，行为对齐宿主；构建产物 `lib/index.js` 只导入 node 内置模块与 dependencies 内的 `@deepseek-ai/schemastery`，独立 `import()` 成功。新增 host-shims 单元测试 10 例，dsh-dog 共 60/60 通过。
- #75：bridge 的 90 个 `novel_*` 工具统一经本地 `defineTool`（复用宿主 `parameterSchemaSpecToJsonSchema`/`valueSchemaSpecToJsonSchema`/`validateJsonSchemaValue`/`ToolArgsError`），在 schema 校验前对 `type: 'json'` 参数（含 array 的 json items）做字符串 `JSON.parse` 归一化；报错带参数名与实际类型。8 项归一化冒烟用例通过；四个宿主符号已核对在 0.1.2-rc.1 / 0.1.5-alpha.1 / 0.2.0-rc.2 三个受支持宿主中均导出且签名一致。

## 0.2.18

[GitHub Release](https://github.com/LiPu-jpg/Openwrite/releases/tag/v0.2.18) 已发布，直接使用[完整 CI](https://github.com/LiPu-jpg/Openwrite/actions/runs/38059156641)验收的同一份包。来源提交 `6e84c2a`，npm 包 SHA-256 为 `edd510c6d4de58bfa09eb30f8a3b74e5a0e6cf7cf2425bc6fe3681b732c1a196`。六组原生平台/Node、源码安装、alpha 兼容及三代宿主客户端共 12 份报告全部通过；Release 四份附件的校验值已与 CI `validated-release` 产物逐一核对。合并来源 [PR #73](https://github.com/LiPu-jpg/Openwrite/pull/73)。npm `dsh-openwrite@0.2.18` 已发布到官方 registry（registry.npmjs.org），`latest` 已更新到 0.2.18；从官方 registry 无认证重新下载后，SHA-256 与上述 CI 包一致。main CI 首次运行 source-install 因 pnpm `--find-links` 目录瞬时不存在失败，重跑同一提交通过，判定为运行器 flake。

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

[GitHub Release](https://github.com/LiPu-jpg/Openwrite/releases/tag/v0.2.12) 已发布，直接使用[完整 CI](https://github.com/LiPu-jpg/Openwrite/actions/runs/37389772004)验收的同一份包。来源提交 a349ea964e43d75f9fc98d1f83364a237bc2ff51，SHA-256 为 2545031292d80689f80d4c0d8c99e007c18ff0c477d662e2813cf67bc876246c。六组原生平台/Node、源码安装、alpha 兼容及三代宿主客户端共 11 份报告全部通过；详见 Release 的 release-acceptance.json。npm `dsh-openwrite@0.2.12` 和 GitHub Release 均已发布，`latest` 已更新到 0.2.12；从公共 npm registry 无认证重新下载后，SHA-256 与上述 CI / Release 包一致。合并后的[主分支完整 CI](https://github.com/LiPu-jpg/Openwrite/actions/runs/37390503895)也已通过。

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
