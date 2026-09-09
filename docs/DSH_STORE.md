# DSH STORE 接入

OpenWrite 是一个完整的小说创作插件套件。商城安装目标是仓库根包 `dsh-openwrite`，不是其中的开发子包。

## 唯一安装目标

在商城申请中填写：

- GitHub repository：`https://github.com/LiPu-jpg/Openwrite`
- Plugin path (optional)：`.`（显式填写，不能留空让扫描器猜测）
- manifestPath：`package.json`
- Bundle Patch：`cordis.patch.yml`

根包统一加载 `openwrite-bundle`、`openwrite-bridge`、`studio-panel`、`openwrite-dog`。这些既有 ID 保持稳定。`packages/openwrite-bridge`、`packages/studio-panel` 是内部开发包，不应和根包一起登记到同一个 Profile，也不需要删除它们或拆成独立商城条目。

源码安装必须固定到完整 Commit；`prepare` 会自包含构建三个内部插件，包含 Core wheel、编辑器静态资源、预设和许可证，不依赖相邻源码。构建授权仍遵循用户的 pnpm 设置。普通用户继续优先使用已验收的 GitHub Release `.tgz`，见 README。

## 兼容声明与证据

根 `package.json` 的 `dsh.compatibility.dshReleases` 是精确版本声明；没有实际验证的版本保持 `unknown`。Node.js 下限是 22.19.0，完整基础平台矩阵使用 Node 24，Node 22.19/26 作兼容检查；系统与架构限制见安装指南。

本机 macOS arm64 / Node 24.15 使用 0.2.7 运行代码对 alpha.1 完成了隔离安装、启动、后端初始化、恢复、回退与卸载验证；新版元数据及正式产物另由下述 CI 门禁验证。

默认宿主仍是 `0.1.2-rc.1`。商城当前滚动窗口还包含 alpha，所以额外验证 `0.1.5-alpha.1`，并保留 `0.1.3-alpha.1`、`0.1.3-alpha.2` 为未知。这不自动升级用户宿主，也不承诺整个 alpha 范围都兼容。

2026-09-09，从官方 npm Registry 直接安装 `@deepseek-ai/dsh@0.1.5-alpha.1` 时，上游范围依赖选中了正在发布的 alpha.2，其中 `@deepseek-ai/dsh-tool-pwsh-persistent@^0.1.5-alpha.2` 当时缺失，安装失败（ETARGET）。兼容测试使用 npm 的 `--before=2026-09-09T00:00:00Z` 解析 alpha.1 发布时的依赖，并保留解析锁。没有修改官方包源码或用 replacements/overrides 冒充官方组件。此证据仅适用于报告中的宿主依赖图，不代表后续浮动依赖安装也通过。

可重复执行的隔离验证：

```sh
npm install --prefix .tmp-dsh-alpha @deepseek-ai/dsh@0.1.5-alpha.1 --before=2026-09-09T00:00:00Z --registry=https://registry.npmjs.org
node scripts/release-smoke.mjs dsh-openwrite-<version>.tgz --host-cli=.tmp-dsh-alpha/node_modules/@deepseek-ai/dsh/lib/bin.js
```

不要把 `<version>` 原样复制；使用待验收的真实包路径。脚本创建临时 DSH_HOME、配置和作品注册表，不读取真实凭据、不调用模型。它验证安装、重复安装、其他插件共存、宿主服务版本、后端准备与认证、中文目录初始化、恢复、失败升级与回退、卸载保留数据；最终报告绑定包 SHA-256 和宿主版本。CI 另执行实际浏览器启动、空会话入口与作品创建，不用页面 HTTP 200 代替这些验证。

`Release artifact validation` 增加独立 alpha.1 Linux/Node 24 任务并保留宿主依赖锁。稳定版原生六平台和源码安装门禁仍保留；最终聚合要求 alpha 与稳定版测试同一个产物。未运行的系统/模型测试不能计为通过。以实际工作流报告为准，兼容声明不是安全审计证明。

## 权限与安装影响

- `prepare`：仅源码安装构建插件，声明在 manifest 中；预编译包已有运行资源。
- 文件：读写已绑定作品目录；托管环境、缓存和管理记录位于 `$DSH_HOME/openwrite/`，版本化预设位于 `$DSH_HOME/.agent-presets/`。
- 网络：环境准备从清单中固定来源下载并校验 uv/Python；依赖按锁文件安装。用户发起模型任务时访问其配置的服务。
- 子进程：启动插件管理的 uv/Python 和回环后端，退出/卸载仅清理自己的进程。
- 凭据：模型服务配置由宿主管理；准备环境的子进程使用允许列表环境，不继承无关 API Key。工具策略不是操作系统沙箱。
- 卸载保留作品、凭据和历史；缓存清理是单独操作。旧开发安装按安装指南先备份并迁移，不能同时挂载新旧包。

这些实际能力包括文件写入、网络、子进程和源码构建。不能为了低风险自动收录而隐藏它们、删除核心能力或伪造无权限声明；商城可能需要进一步审核或只提供外部安装入口。目录静态预检、可安装状态、运行验收是不同结果。

## 复检

对应 [作者修复请求 #682](https://github.com/AI-Scarlett/DSH-Store/issues/682)。新版固定 Commit 合入默认分支后，用明确的根目录提交预检，并核对商城最新结果。只在其公开结果明确通过后称为“已收录”；提交成功不能冒充审核成功。
