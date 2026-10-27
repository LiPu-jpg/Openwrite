# #98–#100：连载写作与运行可靠性

dsh-openwrite 0.2.25 / Core 5.8.12 已在 [GitHub Release](https://github.com/LiPu-jpg/Openwrite/releases/tag/v0.2.25) 与 [npm](https://www.npmjs.com/package/dsh-openwrite/v/0.2.25) 发布。Core 代码已合并到同仓库 native-core 分支；安装包捆绑对应 wheel。完整数据契约见 Core `docs/SERIAL_WRITING.md`。

## 覆盖范围

| Issue | 实现 |
| --- | --- |
| #98.1 插件升级破坏 bundle | 新增停机离线旁路升级工具，复制整个 profile 后安装、校验、切换，保留旧目录和日志；支持修复不完整 OpenWrite bundle 与中断恢复。原生宿主安装器补丁单独保留在 fork PR，未随插件包发布，见下方限制。 |
| #98.2 外部验收失败 | `no_model=true` / `mode=fast` 承认正文版本，派生事实明确 stale，可稍后完整对账。 |
| #98.3 误连实例 | status/响应头标识 root、instance、port；Bridge 校验实际根，不一致返回 409。 |
| #98.4、#99.1 长章 | 按 beats 分段，携带 1,500 字尾文续写，拼接去重；不足时续写，预算耗尽保留草稿。 |
| #98.5 已定稿章横评 | 显式选择历史隔离改写，产物不写正式正文/事实账本；标注当前正典上下文限制。 |
| #98.6 自留存档 | `personal_archive` 档位将质量门禁降为警告并写 hash 回执，结构错误仍阻断。 |
| #98.7 心跳与超时 | 活动、worker 心跳、当前模型调用时长分别显示；流式总期限有界，超时保留部分输出。 |
| #98.8 读写互斥 | GET 与纯读诊断不被写任务统一阻断；修改仍持项目写锁。 |
| #98.9 章级体检 | 汉字/段落、句长和段长 P50/P90、对白占比、项目词典名词密度，写后自动保存。 |
| #99.2–#99.6 写作资产 | anchor 范本、共享术语表及例句、最低次数、review 开关、12 字窗口重合/重复、角色属性分组轮换和明确已用标记。 |
| #99.7 用量 | reasoning_tokens 从上游嵌套 usage 提升，真实 0 与未知分别保留。 |
| #100 章节组审计 | 章纲四字段、只读计数与缺失报告、声明伏笔连边、漂移预算与冻结、吸收/回收/冻结裁决、不可变基线和事务恢复。 |

工作台「操作 → 连载体检」提供资产编辑、范本导入、章节体检、章纲元数据、漂移记账与裁决。相关工具为 `novel_writing_assets`、`novel_manuscript_metrics`、`novel_outline_audit`、`novel_drift_entry`、`novel_arc_reconcile`；当前预设共 95 个领域工具。大纲吸收要求真实版本化更新；界面里的承诺计数是声明检查，不能当作已验证的故事推进。

## 离线升级和损坏修复

先完整退出 DeepSeek Harness / DSH Desktop 并停止 dsh、OpenWrite managed runtime。整个升级过程中保持停机。工具会在安装前及切换前检查进程；未知进程状态也拒绝修改。宿主原生命令不受此检查保护。

从解压的发行包运行（或已安装版本提供的 `openwrite-safe-upgrade`）：

```sh
node /path/to/package/scripts/safe-upgrade.mjs --profile desktop --package /absolute/path/dsh-openwrite-0.2.25.tgz
```

可用 `npm pack dsh-openwrite@0.2.25` 下载官方包，或从对应 GitHub Release 获取相同字节的附件。`DSH_HOME` 必须指向实际宿主的 home；默认 `~/.dsh`。Windows 另设 `DSH_BIN` 为已验收宿主运行时的绝对 `lib/bin.js` 路径，使用 Node 直接执行而非 `.cmd` shell。其余平台可通过 DSH_BIN 指定同一受信任 CLI。

候选 0.2.28 的工具可从解压目录读取所选已安装 profile 中的运行依赖；本地 tgz 会先保存到 `<DSH_HOME>/openwrite/packages/<sha256>.tgz`，再传给安装器，避免新依赖和锁文件指向临时下载。此改进尚未发布，旧包解压入口缺少依赖时应使用已安装包内的工具。pnpm 11 的 store/构建授权及既有失效锁文件仍属于宿主安装路径限制，失败时查看操作日志；不要把源码 tarball 与预编译发行包混用。详见 [#123 回复补修](ISSUE_123_FOLLOWUP.md)。

安装在旁路 profile 中进行；整个旧 profile（包括其他插件、锁文件及设置）在切换前保持可用。只有 OpenWrite 的必要文件和 manifest 校验成功才进入目录切换。切换为两次同盘 rename，**不是整个目录树的单次原子交换**；停机状态避免读取窗口，中断由持久事务记录恢复。锁覆盖本工具的并发操作，不能阻止未经协调的原生安装器或用户重新启动宿主。

记录保存在 `<DSH_HOME>/openwrite/upgrades/upgrade_*/`：`operation.json`、`pnpm.log`、成功切换后的 `previous-profile/`。stdout/stderr 实时落盘；安装 180 秒超时终止子进程。保留目录可能占用较多空间，确认升级稳定后再人工清理。

```sh
# 中断恢复，只恢复同一批准操作；若后来修改过 profile 则拒绝覆盖
node /path/to/package/scripts/safe-upgrade.mjs --recover upgrade_<实际操作ID>

# 损坏 bundle 修复：先检查，再明确应用。仅禁用不完整的 OpenWrite bundle。
node /path/to/package/scripts/safe-upgrade.mjs --profile desktop --repair
node /path/to/package/scripts/safe-upgrade.mjs --profile desktop --repair --apply
```

修复会备份 profile manifest，不删除正文、其他插件或设置；不会假装重装已经成功。完整 OpenWrite bundle 不会被该修复入口禁用。之后使用旁路升级重新安装。

## 验收与边界

自动化覆盖分段续写/去重、版本冲突、术语与 Unicode 位置、快验收及后续完整对账、持双重写锁时纯读、心跳不伪造进度、流式期限、漂移超预算及中断恢复、存档回执、升级失败时旧 profile 不变和非空日志。前端测试覆盖连载体检读取/资产保存/版本化追认；手工浏览器验收仅使用 `~/my_novel`。

这些测试不调用付费模型。真实模型达到 10,000 字的稳定率仍由模型决定；系统保证有限续写与草稿留存，不保证模型质量。具象名词密度依赖作者词典；承诺是否兑现未做语义判断。历史横评使用当前正典，不声称复原当时章前状态。伏笔声明边与 DAG 已确认状态分别报告，不自动篡改已收状态。

原生宿主修复保留在 [deepseek-harness fork PR #1](https://github.com/LiPu-jpg/deepseek-harness/pull/1)，代码提交 `906e10574b7cc2875348cc31c43aa779a5c8e652`：Desktop 记录外壳进程、原生 CLI 在停机后暂存并校验整个 profile、拒绝运行中替换、保留真实 stdout/stderr 和中断恢复记录。该补丁的 [Windows/Linux 原生专项 CI](https://github.com/LiPu-jpg/deepseek-harness/actions/runs/39901088607) 通过：Windows 185 passed / 3 skipped，Linux 187 passed / 1 skipped；macOS 187 passed / 1 skipped，构建、类型检查及 43 项文档检查通过。Windows 用例实际运行 profile 内的程序并检查存活与退出后的升级行为，未执行交互式 Electron 人工验收。

当前上游 master 已有损坏 bundle 的跳过加载及插件管理恢复能力，相关现有用例已重跑通过。上游仓库所有者已关闭 PR 提交入口，API 与网页均无法创建上游 PR；fork 补丁尚未合入上游或成为已发布宿主。它不包含在 OpenWrite 0.2.25 包内，因此 #98.1 仍需追踪宿主发布及 Windows Desktop 人工验收。现有宿主用户继续使用本工具的停机升级路径。

本地回归记录（2026-10-23，macOS arm64）：Core 全量 1,424 passed / 32 skipped；后续超时配置校验等定向回归 38 passed、规划转换回归 36 passed；前端 301 passed；managed runtime/策略 24 passed；离线升级 5 passed；跨端契约检查通过。Core wheel 已从独立解压目录验证版本、体检模块及 HTTP 路由。真实服务商调用与 Windows Electron 人工验收未执行。跨平台发布 CI 的 8 份原生安装/源码报告和 4 份精确宿主客户端报告均通过；发布状态与哈希见 [发布验收](RELEASE_ACCEPTANCE.md#025)。
