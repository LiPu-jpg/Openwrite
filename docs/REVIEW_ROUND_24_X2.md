# 第二十四轮：无界增长与资源泄漏审计（X-2 部分）

## 结论：无产品缺陷，但统一了 3 处临时文件写入路径

## X-2：文件句柄与临时文件

### 已确认正确的部分

- **零裸 `open()`**：`tools/` 下所有文件写入都用 `with` 或 `atomic_write`
- **所有 `NamedTemporaryFile` 都用 `with`**：句柄不会泄漏
- **7 处 `delete=False` + `replace` 消费**：`replace` 会把临时文件移走，无需 unlink

### 发现的缺口：临时文件清理不统一

7 处 `delete=False` 的实现各自手写了 temp+replace，但**没有 finally 清理**。如果 `replace` 失败（权限、目标被占、跨设备），临时文件残留且永不清理。同目录 replace 几乎不失败，所以概率低——但会累积。

而 `file_ops.atomic_write`（已有 9 个模块在用）**有 finally 清理**。

### 修复

把三个最常用的纯文本写入路径统一到 `atomic_write`：
- `character_state_index._save_cache`
- `chapter_run_v2.save`
- `chapter_run_store.save`

顺带清理了因此不再使用的 `tempfile`/`os` import。

### 验证中的关键错误（我自己的）

变异测试第一次报 NOT CAUGHT，我追查了很久，最后的根因是**我的断言过滤条件写错了**：

```python
if path.is_file() and path.suffix == ".tmp"   # 错
```

`atomic_write` 的 `NamedTemporaryFile` 只传了 `prefix` 没传 `suffix`，所以临时文件是 `.character-state-index.json.io9w505u`——**后缀是随机串，不是 `.tmp`**。我的过滤器精确地漏掉了要找的东西。

这个错误特别值得记住：**我在找一个我不认识的模式的泄漏**，用的匹配条件来自我的假设而不是实际命名。

修正为"点开头的非 .json 文件"后，两个变异都被抓住。

## 与 X-1 的关系

X-1（版本历史无上限）和 X-2（临时文件清理）是同一类问题的两面：**资源的生命周期没有被统一管理**。X-1 是"只创建不销毁"，X-2 是"销毁路径只覆盖成功情况"。

`atomic_write` 之所以是对的，因为它把"创建临时文件 + 原子替换 + 失败清理"封装成一件事。剩余 4 处（`asset_package`、`chapter_memory`、`chapter_pipeline`、`cli`）仍是各自实现，是后续统一的候选。

## 最终状态

| | |
|---|---|
| Core | **1655 passed / 32 skipped / 2 xfailed / 0 failed** |
| 插件 test:maintenance | **81 passed / 0 failed** |
| 新增 | 1 个测试（`test_concurrency_invariants.py`） |

改动：Core 85 项，未提交。
