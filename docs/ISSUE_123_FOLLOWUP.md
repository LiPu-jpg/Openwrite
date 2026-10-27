# #123 回复补修与验收（候选 0.2.28 / Core 5.8.18，未发布）

依据报告者的[升级、会话与模型调用记录](https://github.com/LiPu-jpg/Openwrite/issues/123#issuecomment-6422870871)及 [B-13 Windows 实测](https://github.com/LiPu-jpg/Openwrite/issues/123#issuecomment-6423904648)更新结论。回复是有版本、入口和结果的外部验收证据；不把其中推测当成已证实根因。

## 两项原待办已有实机证据

- #105：报告者确认 Windows Desktop 按手工替换路径升级到 0.2.26 后，旧会话正常打开；旧 0.2.24 预设目录缺失时兼容注册仍可解析。此证据不代表宿主原生安装器安全。0.2.27 已补齐 0.2.26/27 的永久别名，当前候选覆盖至 0.2.28；发布回归要求每个版本身份进入永久列表，新会话使用稳定 ID `openwrite`。
- #109 B-13：报告者在 Windows 11、DSH Desktop、插件 0.2.27 / Core 5.8.16 上确认行中/行首 `>`、混合行尾预览均可匹配，读取指纹与原始文件字节一致。NBSP 与普通空格不等属于精确匹配的预期拒绝。保留精确字节匹配，不自动归一化再写文件；候选增加混合行尾的 HTTP 预览、应用、撤销回归。

## 本轮代码补修

| 问题 | 最终行为 | 验证 |
| --- | --- | --- |
| `thinking_modes.chapter_write` 漏传 | Writer 的草稿、分段、重试、事实提取和结算都默认传 `chapter_write`；显式 operation 仍优先。usage 的阶段名独立保留。 | 直接检查实际提供方请求参数：enabled / disabled / omit；草稿、观察、结算及重试均覆盖，不只检查配置对象。 |
| 同类修订漏传 | 正文修订模型请求传 `revision`。Dante 的章节生成仍经 Writer；Goethe/通用 ReAct 的规划及工具选择没有冒用写章开关。 | 真实 LLMClient 调用到提供方边界的替身检查；旧冻结源码三个用例失败，新实现通过。 |
| 修订选择的原文不匹配 | `OLD_TEXT_NOT_FOUND` / HTTP 400，带当前范围、原始字节版本、唯一精确候选与空白差异提示。真正的 apply 版本漂移仍为 `DOCUMENT_CONFLICT` / 409。 | LF 请求与 CRLF/混合文件不符时零模型调用、磁盘不变；既有 apply 冲突回归保留。 |
| `similarity:1` 但匹配失败 | 增加 `similarity_basis=whitespace_collapsed`、`mismatch_kind`；该相似度不承诺字节相等。范围锚点失败也给各缺失锚点的诊断，不自动重定位/应用。 | NBSP 与换行提示保留准确原文；不确定时不伪造唯一候选。 |
| 预览 `changed:true` 误读 | 保留兼容字段 `changed`，增加 `would_change`；`applied:false` 明确还没有写入。锚点不匹配返回 400，版本冲突仍返回 409。 | 公共 HTTP 测试逐字节核对预览无写入、确认后写入、撤销恢复。 |
| 已有正文时错误过于泛化 | 直接写章预检返回 `CHAPTER_ALREADY_EXISTS`、章节 ID 和打开正文/创建修订的恢复提示。 | 预检拒绝且不调用模型；不再依赖泛化的 `STUDIO_ERROR` 推断原因。 |
| 健康检查版本不一致 | 当前源码已使用同一版本来源；新增 health / workspace / pyproject 元数据一致性检查。 | 不把旧 5.8.14 环境的字符串误报当成新候选仍存在的缺陷。 |
| 解压包运行升级工具找不到依赖 | 延迟解析依赖，先查工具自身，再查明确选择的 profile；不加载已安装插件、不修改凭据。 | 解压目录没有 node_modules，依赖只存在于目标 profile 时仍完成受控暂存/切换。 |
| 升级后引用被删除的 tgz | 先按 SHA-256 将本地 tgz 固定到 `<DSH_HOME>/openwrite/packages/`，再交安装器写依赖与锁文件。 | 原下载目录在安装过程中删除后，稳定缓存和提交后的 file: 引用仍可读。 |

## 升级路径与边界

在宿主原生保护正式发布前，继续使用[停机旁路工具](ISSUES_98_100.md#离线升级和损坏修复)，先完全退出 Desktop（含托盘）及 dsh/managed runtime，并备份 profile。使用正式预编译 tgz，不把 GitHub 源码包当成相同的离线安装包；源码包可能需要构建授权。

这轮修复了解压工具的依赖入口，并避免新安装记录引用易删除的 tgz；**不承诺修复宿主的 pnpm 11 store、构建授权或既有损坏锁文件**。遇到安装器失败，活动 profile 保持原样，保留操作日志与旧完整目录；不要反复改 profile 的依赖、store 配置和锁文件拼凑安装成功。

#124/#125 的首次评审输出预算与 B-20 的运行历史留存是两件事；后者已由 #126/#127 补修。0.2.27 已正式发布；这里的 Core 5.8.18 和插件 0.2.28 仍为候选，未经新一轮全部验收不发布。

## 继续保留的两项

- #98.1：原生宿主升级保护补丁进入正式宿主，插件旁路工具不替代该条件。
- #111：Android/Termux 真机及受信任外部 Studio 连接验收。

#123 保持打开跟踪以上两项。代码、原始环境确认、CI 产物与正式发布分别记录。

## 最终验收与合并

[Core PR #131](https://github.com/LiPu-jpg/Openwrite/pull/131) 和 [插件 PR #132](https://github.com/LiPu-jpg/Openwrite/pull/132) 已合并。最终 **22 项 CI 全部成功**：[三系统回归](https://github.com/LiPu-jpg/Openwrite/actions/runs/40437762040)、[安装/客户端验收](https://github.com/LiPu-jpg/Openwrite/actions/runs/40437761963)、[插件检查](https://github.com/LiPu-jpg/Openwrite/actions/runs/40437762138)。

| 项目 | Linux | macOS | Windows |
| --- | --- | --- | --- |
| 固定 Core 全量 | 1541 passed / 32 skipped | 1541 passed / 32 skipped | 1541 passed / 32 skipped |
| 真实 HTTP dry-run / 归档历史 | 2 passed | 2 passed | 2 passed |
| 真实 Electron 44.7.0 脚本 | 5 passed | 5 passed | 5 passed |
| wheel 源码 / 应打包 Python 文件 | 498 / 163 一致 | 498 / 163 一致 | 498 / 163 一致 |

32 项跳过均为缺失旧样例/checkout 的既有跳过，新增回归未跳过。另有混合行尾的公开 HTTP 预览/应用/撤销测试包含在 Core 全量中。本地插件完整检查、310 项组件、34 项原生预设/升级/运行时组合通过。最终 8 份安装/源码、5 份客户端、6 份原生报告已下载复核，安装包报告绑定同一 tarball，源码安装固定插件提交。

Core 固定提交 `43cb604a7583b7268f47e54ceb8a0c30b95e82b2`，wheel SHA-256 `09f9baef5fe0d502510c8542f20c6abaf6893f02e2d069d7f0d7cc50c7aeea93`。候选 tarball SHA-256 `4bcde6d6f535906a5a04490218a0d972e84329ff750af6803a4214fbf609024e`；CI 来源提交 `ecfb7c34c5b0a29d395136da775bb964c3c91d11` 与主分支修复合并提交 `14dd3a5dbc7d1661adb9b684e0f137298bf2591f` 的 tree 同为 `67042838daf11f5c7fc27e0ffe158677a73c3196`。

本轮没有发起真实付费模型请求，thinking 参数通过实际 LLMClient 到提供方请求边界的替身验证；不把它描述为真实服务商计费或输出质量验收。候选产物只保存为验收证据，**未发布 npm 或 GitHub Release，公开版本仍为 0.2.27**。
