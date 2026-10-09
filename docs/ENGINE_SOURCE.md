# 引擎源码唯一真身（native-core）

## 规则

1. `native-core` 分支是 OpenWrite 引擎（Python Core：`craft/`、`contracts/`、`models/`、`tools/`、`integrations/`）的**唯一源码真身**。`main` 不携带引擎源码，只通过 `release/openwrite-*.whl` 制品依赖引擎。
2. 引擎的任何修改必须先作为提交落在 `native-core` 并推送到远端，然后才能从该提交构建 wheel 进入 `release/`。**禁止从带未提交改动的工作树构建 wheel；禁止"只改 wheel、不回补源码"。**
3. `release/runtime-manifest.json` 的 `sources.core.commit` 必须满足：指向 `native-core` 分支上的提交、已推送远端、且该提交的工作树与 wheel 内容完全一致（用 `git status` 确认干净，`git diff <commit> 工作树` 为空）。
4. 当前两条消费线都以 `native-core` 为真身，形态不同：
   - **dsh 插件线（本分支）**：制品依赖，`openwrite-bridge` 的 managed runtime 拉起 `release/` 里的 wheel。
   - **JiuwenSwarm 迁移线（`jiuwenswarm-swarm` 分支）**：源码级依赖，`openwrite-mcp` 通过 `OPENWRITE_CORE` 直接挂载 native-core 工作树，引擎升级即时生效、无需 repack。

## 构建 / 升级 wheel 流程

1. 切到 native-core 的干净工作树：`git worktree add .wt-native-core native-core`。
2. 应用引擎改动、提交、推送；**先在 native-core 上跑通引擎测试**（至少 `tests/test_managed_runtime.py`、`tests/test_embedding_runtime.py`、`tests/test_model_connection_test.py`）。
3. 构建 wheel（纯 Python 包）：`python -m pip wheel --no-deps -w dist .`，更新 `release/openwrite-<ver>-py3-none-any.whl`。
4. 同步更新 `release/runtime-manifest.json`：`core_version`、`wheel.sha256`、`sources.core.commit`（= 本次构建的 native-core 提交）。
5. 若依赖变化，从 wheel METADATA 重导 `release/core-requirements.in` 并用固定 uv 重建 `release/requirements.lock`。
6. 提交 PR 走完整验收（见 [PLUGIN_MAINTENANCE](PLUGIN_MAINTENANCE.md) / [RELEASE_ACCEPTANCE](RELEASE_ACCEPTANCE.md)）。

## 事故记录：5.8.5 源码漂移（2026-10-09 修复）

**现象**：`release/openwrite-5.8.5-py3-none-any.whl` 内含 embedding 依赖预载、探测硬超时、有界收尾、httpx 构造期错误分类等源码改动（修复 #60/#61），但 `native-core` 分支上没有任何对应提交——wheel 是从带未提交改动的工作树打的，`runtime-manifest.json` 记录的 `sources.core.commit = 3a5da97` 无法复现 wheel 内容。

**后果**：

1. 引擎源码线停留在 5.8.4，与制品线漂移；依赖源码的 JiuwenSwarm 迁移线（`OPENWRITE_CORE`）吃不到 #60/#61 修复。
2. wheel 中 `_local_client_construction_error` 直接引用 `httpx.InvalidProxy`，而 `requirements.lock` 锁定的 `httpx==0.28.1` 并无该符号——`AttributeError` 会击穿整条连接错误分类路径。

**处理**（均已推送到 `native-core`）：

| 提交 | 内容 |
|---|---|
| `e34ccdd` | 从 wheel 反解 5.8.4→5.8.5 源码差异并回流（4 文件） |
| `7a08855` | `httpx.InvalidProxy` 逐个 `getattr` 容错，兼容 0.28.1 及更早版本 |
| `d8e741c` | managed-runtime 健康检查断言改用 `tools.version.__version__`，不再硬编码 5.8.1 |

回归：引擎三件套 33/33，蜂群桩件 18/18，MCP 写路径 6/6 全绿。

**教训**：wheel 是源码的投影，不是源码的替代品。manifest 里的 commit 必须能被 `git checkout <commit>` 后重新打出同一个 wheel。

## 当前状态

- `native-core` HEAD：`d8e741c`（Core 5.8.5 + httpx 容错 + 测试修复）。
- `release/` 中的 wheel 仍为修复前版本；下次 repack 必须基于 `native-core` 上 ≥ `d8e741c` 的提交，并同步更新 manifest。
