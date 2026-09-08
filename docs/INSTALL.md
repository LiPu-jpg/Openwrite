# 安装 dsh-Openwrite

[返回首页](../README.md) · [使用流程](WORKFLOWS.md)

本文既是手动安装指南，也是首页安装提示词交给 Agent 的执行说明。

## 安装前

安装脚本面向 **macOS / Linux**；Windows 请在 **WSL2** 中执行。原生 PowerShell 尚无对应安装脚本。

| 依赖 | 要求与用途 |
|---|---|
| Git | 获取插件、OpenWrite Core 与 DoG |
| Node.js + npm | Node ≥ 22.19.0；使用仓库锁定的 dsh CLI |
| pnpm | 安装 dsh profile；当前验证版本为 9.15.9 |
| rsync | 同步 OpenWrite 创作预设 |
| uv | 创建 Python 3.12 环境并安装 OpenWrite Core |

已有 dsh 也需要这些依赖。项目兼容基线是 **dsh 0.1.0-rc.7 / Cordis 4.0.1**，不要把全局新版 dsh 当作已验证的替代版本。可先用 `node --version`、`npm --version`、`pnpm --version`、`git --version`、`rsync --version`、`uv --version` 检查现有环境；缺失项按当前操作系统安装。

Node 安装见 [Node.js](https://nodejs.org/en/download)，uv 安装见 [uv 文档](https://docs.astral.sh/uv/getting-started/installation/)。如未安装 pnpm，可在 Node 就绪后运行 `npm install --global pnpm@9.15.9`。

首次下载依赖需要网络和磁盘空间。安装、建空作品和 `doctor` 不需要模型密钥，也不会调用写作模型。首次使用本地向量检索可能另行下载模型。

## 1. 获取两份源码

同一仓库的两个分支承担不同职责，分别放入相邻目录：

```text
~/novel-tools/
├── dsh-Openwrite/   # main：dsh 插件、预设、原生工作台
└── OpenWrite/      # native-core：Python 小说领域后端

~/my_novel/         # 作品目录，与工具源码分开
```

全新安装可复制执行：

```sh
mkdir -p "$HOME/novel-tools"
cd "$HOME/novel-tools"
git clone --branch main --single-branch https://github.com/LiPu-jpg/Openwrite.git dsh-Openwrite
git clone --branch native-core --single-branch https://github.com/LiPu-jpg/Openwrite.git OpenWrite
cd dsh-Openwrite
```

如果目录已存在，先检查其远端、分支和未提交改动，复用正确的工作树。升级方式见下文，不要删除目录重新克隆。

## 2. 安装插件和后端

在 `dsh-Openwrite` 目录执行：

```sh
bash scripts/install.sh
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -e ../OpenWrite
npm run doctor -- --profiles
```

已有 `.venv/bin/openwrite` 时复用环境，跳过 `uv venv`，只在后端依赖更新时重新执行 `uv pip install`。也可让首次运行的 `scripts/dev.sh` 自动创建后端环境。

安装器会构建两个插件、同步 `OpenWrite 创作` 预设并登记到 dsh profile，默认同时安装固定版本的 DoG 图谱插件。预设位于 `$DSH_HOME/.agent-presets/openwrite/`，`DSH_HOME` 默认是 `~/.dsh`。本项目的预设副本会被源码同步；原 Goethe / Dante 预设移至 `.agent-presets-legacy/` 保留备份。

安装不会自动重启已经运行的 dsh。若由当前 dsh Agent 执行安装，先完成安装和检查，再由用户退出旧进程；不要让 Agent 杀掉承载当前安装会话的进程。

## 3. 创建或选择作品

**已有 OpenWrite 作品**：使用包含 `novel_config.yaml` 的作品根目录，跳过初始化。

**新作品**：下面命令只在 `~/my_novel` 尚不存在时初始化空作品，书名之后可以修改：

```sh
if [ ! -e "$HOME/my_novel" ]; then
  .venv/bin/openwrite init my_novel --title "我的小说" --project "$HOME/my_novel"
else
  echo "目录已存在：已有 OpenWrite 作品可直接使用；其他目录请先换一个新路径。"
fi
```

不要把插件仓库或 Core 仓库选作作品。只有普通 TXT / Markdown 旧稿时，先建新作品，启动后通过「任务 → 导入与导出」导入；不要把旧稿目录直接当作已初始化项目。

## 4. 启动并打开工作台

```sh
bash scripts/dev.sh --project "$HOME/my_novel"
```

使用自己的作品时，替换 `--project` 后的路径。保持这个终端运行，打开 [http://127.0.0.1:3080](http://127.0.0.1:3080)。退出时按 Ctrl-C，启动器会清理自己启动的 dsh 和 Studio 进程。

在 dsh 中添加该作品目录为 Workspace，并在这个 Workspace **新建会话，选择「OpenWrite 创作」预设**。已有会话不会自动换预设。会话启动后可见「创作 / 资料 / 任务」三个页签。

`--project` 设置后端的默认项目；日常操作仍按当前 dsh 会话的 Workspace 路由。只改启动参数、却继续使用旧会话，并不会切换那条会话的作品。

## 5. 配置模型并开始写作

- **对话 Agent**：使用 dsh 自己的模型设置与凭据，选择用于对话、规划和工具调用的模型。
- **小说生成、评审及模型测试**：在「任务 → 模型」配置 OpenWrite 的模型档案与用途路由。

这两处是不同的配置入口；dsh 能聊天不代表小说后端已经有可用模型。密钥在本机设置界面填写，不粘贴到公开 Issue 或安装提示词中。

新书可以先发送：“先帮我梳理题材、人物和大纲，整理好后给我确认。”准备完成后再使用 `/write-next`、`/review-chapter` 等创作入口，见 [完整使用流程](WORKFLOWS.md)。

## 如何判断安装成功

1. `npm run doctor -- --profiles` 通过，确认插件登记及打包文件完整。
2. 启动日志显示 Studio 健康检查通过、dsh web 启动；浏览器能打开 3080。
3. 正确作品 Workspace 的新会话可选「OpenWrite 创作」，并显示三个工作台页签。

这些是安装验收；实际生成还取决于模型配置和作品就绪状态。可用 `npm run check:plugin` 做完整离线插件回归，跨仓库契约检查使用 `npm run check`。不需要通过付费写章或模型横评来证明安装完成。

## 常见问题

| 现象 | 处理 |
|---|---|
| 克隆后没有 `scripts/install.sh` | 插件使用 `main`，Core 使用 `native-core`，核对是否进错目录或分支。 |
| 找不到 OpenWrite 源码 | 默认路径是插件相邻的 `../OpenWrite`；首次启动时可设置 `OPENWRITE_DIR=/绝对路径/OpenWrite`。 |
| 4567 或 3080 已被占用 | 检查已运行的服务，退出旧实例后再启动；不要同时用启动器和另一套 daemon 占同一端口。 |
| 已安装但看不到预设或页签 | 安装、检查、启动使用相同的 `DSH_HOME`；重启后新建会话选择预设。 |
| 切换了启动路径，内容仍是旧作品 | 在 dsh 切换 Workspace 并打开属于该 Workspace 的会话。 |
| 提示缺少接纳基线或事实待更新 | 这是作品准备问题。按作品导入/接纳流程处理现有正文，不要重装插件或绕过检查。 |

## 更新和自定义安装

退出运行中的服务后，在两个**没有未提交改动**的仓库分别执行 `git pull --ff-only`，再回到插件仓库运行 `bash scripts/install.sh`。Core 依赖变化时重新执行 `uv pip install --python .venv/bin/python -e ../OpenWrite`，检查通过后重新启动。预设源码有改动时，需要重新安装并新建会话才会生效。

| 设置 | 用途 |
|---|---|
| `DSH_HOME` | dsh 用户配置目录；安装、doctor 和启动必须使用相同值。 |
| `OPENWRITE_DIR` | 首次创建后端环境时使用的 Core 源码路径。已有 editable 安装换路径时需重新 `uv pip install -e`。 |
| `OPENWRITE_PROJECT` / `--project` | 后端默认作品路径；日常操作以会话 Workspace 为准。 |
| `DSH_DOG_DIR` | 使用已有 DoG 工作树。 |
| `DSH_DOG_AUTO_INSTALL=0` | 显式跳过自动安装 DoG；默认安装完整图谱能力。 |

安装细节、版本升级和回退见 [维护手册](PLUGIN_MAINTENANCE.md)。
