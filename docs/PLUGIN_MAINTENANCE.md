# OpenWrite 标准插件维护

当前候选基线为 dsh 0.1.2-rc.1、Cordis 4.0.2、Node 24；实际 SDK 图记录在 `release/sdk-compatibility.json`。不要机械地把所有依赖改成同一版本，也不要追随 alpha。旧本地安装的历史记录见 [rc.7 维护记录](PLUGIN_MAINTENANCE_RC7.md)，不再作为用户安装指南。

## 构建与验证

```sh
npm ci --ignore-scripts
node scripts/prepare.mjs
npm run check:plugin
npm run test:managed
npm --prefix vendor/dsh-dog run typecheck
npm --prefix vendor/dsh-dog test
node scripts/release-provenance.mjs
npm pack --ignore-scripts
node scripts/release-check.mjs
node scripts/release-smoke.mjs
```

`prepare` 对 GitHub 源码压缩包同样有效，不依赖 `.git` 或相邻 Core。Release 包已编译，不需要安装时构建。客户端与宿主分别检查类型；浏览器产物不得携带 Node、第二份 React、Cordis 或宿主服务。

`check:plugin` 保留旧开发脚本回归，普通用户使用 [标准安装指南](INSTALL.md)。模型替身与真实模型验收分开记录。自动化使用隔离 DSH_HOME、配置和 ProjectRegistry；本机人工验收仅使用 `~/my_novel`。

## 发布产物

根包 `dsh-openwrite` 组合运行时、bridge、panel、DoG 和版本预设。Core 使用 `native-core` 固定 commit 的 wheel；用户无需切换分支。版本、来源和所有平台下载哈希记录在 runtime manifest。

Python 主依赖从该 wheel 的 METADATA 导出到 `release/core-requirements.in`，用固定 uv 重建：

```sh
uv pip compile release/core-requirements.in --universal --python-version 3.12 --generate-hashes --constraint release/python-constraints.in --override release/platform-overrides.in --output-file release/requirements.lock
```

重建后补入 `release/wheels/provenance.json` 中受控 Intel wheel 的哈希，并更新 runtime manifest 的 requirements SHA-256。Core 更新时同时刷新输入依赖和约束，检查平台 wheel 覆盖与库的原生加载。

Intel Mac cryptography wheel 由独立原生构建工作流从校验过的上游源码生成，保留静态 OpenSSL 的许可证、版本和链接检查。它是固定发布输入，不在每位用户机器上编译。升级该依赖须重新执行该工作流并审核产物。

`release/source.json` 记录 Git commit，或无 `.git` 的源码压缩包指纹，并列出 JavaScript 运行依赖来源。GitHub Actions 将同一 `.tgz` 交给原生 macOS、Linux、Windows 的 Node 24 安装与浏览器验收，另做 Node 22.19 和 26 兼容检查。发布必须推广通过验收的原文件及 SHA-256，不得重新打包后发布。

## 生命周期与权限

领域服务常驻宿主，模型工具由创作预设注册。新增工具及 action 必须分类实际副作用：未知和会持久化预览记录的操作按写入处理。只读策略、计划模式、Workspace 身份、revision 与作者确认分别检查。这些是宿主策略与桥接拒绝，不是操作系统沙箱。

受管理后端仅使用自己的进程、动态回环端口和实例凭据。外部模式不接管用户进程。资源、请求、SSE、计时器、watcher 和 DoG 脚本都必须在创建它们的 scope 卸载时释放。

官方预设按版本发布，多宿主使用租约保护。安装前检查同名未管理目录，禁止合并写入作者目录。迁移先备份，再通过宿主 `dsh plugin remove` 删除仍在 `dependencies` 或 bundle 列表中的三个旧包；失败恢复备份。作者修改过的预设按无包装标记或校验不一致识别，不会删除。卸载默认保留作品、配置、凭据和历史。

受管理后端状态区分为：首次未启动、准备中、就绪、异常退出、恢复中、已取消、已卸载。dsh 运行期间已启动后端异常退出会有上限的退避重启；取消、宿主退出和卸载不复活。外部 `mode: external` 不接管进程。恢复不得重放付费任务。子进程环境为允许列表，不是 `process.env` 整包复制。

## 成本与取消

取消测试后停止新任务及重试，保存已完成候选、评审和实际用量。服务商在途请求不能保证撤回，界面持续显示取消中，直到结果收回或失败。未知费用不计为零。

实测 90 个小说工具 native schema 为 63,614 UTF-8 字节。PTC 的传输 schema 为 944 字节，生成 SDK 为 60,232 字节，另有说明文本；未测 tokenizer 数量和真实请求缓存，因此不承诺节费比例。比较方法见 [成本测量](COST_MEASUREMENT.md)。PTC 要求宿主配置支持的 codeRuntime，可在工具行选择 presentation，或使用官方展示插件，避免同一 scope 重复声明。
