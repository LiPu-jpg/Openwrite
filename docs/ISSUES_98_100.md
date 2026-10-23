# #98–#100：连载写作与运行可靠性

本分支为 dsh-openwrite 0.2.25 / Core 5.8.12 候选，尚未发布。Core 代码位于同仓库 native-core 分支；安装包将捆绑对应 wheel。完整数据契约见 Core `docs/SERIAL_WRITING.md`。

## 覆盖范围

| Issue | 实现 |
| --- | --- |
| #98.1 插件升级破坏 bundle | 新增停机离线旁路升级工具，复制整个 profile 后安装、校验、切换，保留旧目录和日志；支持修复不完整 OpenWrite bundle 与中断恢复。原生 dsh 安装器和宿主启动降级未修改，见下方限制。 |
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

从解压的候选/发行包运行（或已安装版本提供的 `openwrite-safe-upgrade`）：

```sh
node /path/to/package/scripts/safe-upgrade.mjs --profile desktop --package /absolute/path/dsh-openwrite-0.2.25.tgz
```

候选版本未上架前不要使用 `dsh-openwrite@0.2.25` 下载命令。`DSH_HOME` 必须指向实际宿主的 home；默认 `~/.dsh`。Windows 另设 `DSH_BIN` 为已验收宿主运行时的绝对 `lib/bin.js` 路径，使用 Node 直接执行而非 `.cmd` shell。其余平台可通过 DSH_BIN 指定同一受信任 CLI。

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

Windows Desktop 的文件句柄冲突与恢复需 Windows 实机补验；本次在 macOS 完成实现和本地回归。原生 `dsh plugin add/update` 与「损坏 bundle 自动跳过并提供修复入口」属于 deepseek-harness 宿主代码，未在这个仓库修复，因此 #98 不应标为全部解决。现有宿主用户必须使用本工具的停机路径，或等宿主更新后再走原生更新。

本地回归记录（2026-10-23，macOS arm64）：Core 全量 1,424 passed / 32 skipped；后续超时配置校验等定向回归 38 passed、规划转换回归 36 passed；前端 301 passed；managed runtime/策略 24 passed；离线升级 5 passed；跨端契约检查通过。Core wheel 已从独立解压目录验证版本、体检模块及 HTTP 路由。真实服务商调用、Windows 实机和发布操作均未执行。
