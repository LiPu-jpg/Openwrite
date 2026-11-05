# 第二十四轮：无界增长审计

## 结论：1 个真实缺陷（已修），1 个已知限制（记录未修）

## X-1：manuscript 版本历史无上限（已修）

`ManuscriptVersionStore.checkpoint` 每次写一对文件（`ver_*.md` + `ver_*.json`），**从不删除**。虽然有 `AUTOSAVE_COALESCE_SECONDS` 节流（同一时间窗内合并），但节流只降低速率、不限总量。

规模：100 章 × 每章 20 次编辑 = 2000 对文件，每个 `.md` 是**整章正文的完整副本**。且 `list()` 每次请求都 glob + 解析全部版本文件。

这与 `arc_audit` baseline（第十五轮修，裁到 24）和 `review_store` history（裁到 20）是同一类问题——那两个修了，这个漏了。

### 修复

保留最近 `VERSION_HISTORY_KEEP = 20` 个，**外加所有作者显式标记（label 非空）的版本**——那些是刻意留的标记，不是 incidental 快照。

理由：
- 实时正文不在版本目录里，裁剪不可能影响作者正在读的内容
- 纯自动保存的历史对作者价值低（回退到"20 次编辑前"很少见），但磁盘成本高
- label 是作者意图的显式信号

### 验证

25 次自动保存 → 保留 20；标记版本在后续 25 次自动保存后仍保留；实时正文不受影响。

| 变异 | 结果 |
|---|---|
| X-1a 版本历史不裁剪 | 1 failing ✓ |
| X-1b 裁剪不保留标记版本 | 1 failing ✓ |

## 已知限制（记录，未修）：task_store.list() 是 O(n)

`list()` glob 并 load **所有** `task_tsk_*.yaml`，然后才切 `limit`。1000 个任务 = 1000 次 YAML 解析，即使只要 100 条。

未修原因：
- 任务文件是小的元数据（输入/结果被 `_externalize` 拆到单独文件），不像版本历史那样每个含整章正文
- 修复需要改 glob 策略（如按 created_at 前缀分区），风险高于当前收益
- 这是性能退化，不是正确性问题

## 审查过但未发现问题的部分

- `review_store`：已有 `REVIEW_HISTORY_KEEP = 20` 裁剪
- `arc_audit`：已有 `MAX_BASELINES = 12` 裁剪
- `novel_archive`：已有 `MAX_ARCHIVE_FILES = 20_000` / `MAX_ARCHIVE_BYTES = 1 GiB` 上限
- `session_state`：已有 8 MiB 转录轮转
- `research_service` 的 `episode_*` 目录：无清理，但是显式的作者操作（不是每次写作触发），且是作者可能要查的研究产物
- `task_store.index.yaml`：无 reader（`list()` 靠 glob），增长不影响读性能

## 最终状态

| | |
|---|---|
| Core | **1654 passed / 32 skipped / 2 xfailed / 0 failed** |
| 新增 | 2 个测试（`test_manuscript_editing.py`） |

改动：Core 82 项，未提交。

## 本轮的模式

又是"同一个缺陷类修了五个、漏了一个"：`arc_audit`、`review_store`、`session_state`、`novel_archive` 都有上限，`manuscript_editing` 没有。前四个都是在处理各自的具体症状时顺手加的，没有一个是"系统性审计无界增长"的结果。

这说明**逐点修复不会自然覆盖同类**——只有按维度（无界增长）主动扫描才能找出漏网的。这也是本轮做这个扫描的价值。
