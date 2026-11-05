# 第十五轮：修正上一轮误判 + 审查未触碰的 Core 模块

## 1. 修正第十四轮的一个错误结论

第十四轮我把 `ContinuousReader` 外层 catch 的 `loaded` fallback 判为「不可观测的死代码」。**这个结论是错的**——探针的 fixture 给了 `has_next: false`，而 `while` 循环里有 `if (!packet.has_next) break`，所以第二个 packet 从未被请求，catch 自然不会触发。

用 `has_next: true` + `next_occurrence_id` 正确链接后，第二个 packet 的 identity 不匹配确实在 `loaded` 非空时抛错，分支可达，变异 `if (false)` 被测试抓住（`1 failed`）。已在 `docs/REVIEW_ROUNDS_13_14.md` 文首加修正说明。

**教训**：判定「代码不可达」之前，先确认自己的输入真的能走到那里。我用一个必然提前退出的 fixture 得出了结构性结论。

## 2. 86 个从未被触碰的 Core 模块

十四轮以来 `tools/` 下有 86 个模块从未被修改也从未在报告中审查。本轮从中筛出有破坏性或并发风险的，发现并修复 2 个真实缺陷。

### O-2a：benchmark_scheduler 一个任务抛异常会静默丢掉其余全部

`run_bounded` 的 dispatch 循环里 `completed(future.result(), ...)`。`future.result()` 会重新抛出工作线程的异常，而调用方（`model_benchmark.py` 两处）只通过 `completed` 回调收集结果、从不 try/except——异常必然穿透到 HTTP 层。

实测（4 个任务、并发 2、第 2 个抛错）：

```
CRASHED with: provider exploded
completed: [1, 3]        # 任务 4 从未执行
```

横评里一个 provider 失败就丢掉其余候选，且 `draining` 未调用、`completed` 未收到失败通知。已改为 `_settled()` 把异常转成 `{"status": "failed", "error": {...}}` 数据结构：

```
completed: [1, 3, 4, {'code': 'JOB_RAISED', ...}]
```

### O-2b：伏笔 DAG 的三重失效

`foreshadowing_manager.py` 是 86 个未触碰模块里最严重的一个：

1. `_save_dag` 用裸 `open(..., "w")` — 崩溃留下截断的 `dag.yaml`
2. 保存异常只 `print` 不抛 — 调用方以为保存成功
3. `_load_dag` 对解析失败也 `print` + 返回**空图** — 截断文件被静默替换成 `ForeshadowingGraph()`

这个组合比第十二轮修的 `hierarchy.yaml` 更严重：写入崩溃 → 文件截断 → 下次读取解析失败 → 返回空图 → **所有伏笔记录消失，且全程没有任何错误**。

修复：`atomic_write` 原子写 + 读失败抛 `ForeshadowingDagError`（保留原文件供手工修复）。

### O-2c：studio checkpoint 路径越界

`studio_application.py:1743` 用裸 `target.relative_to(self.project_root)`，同文件 2013 行用的是带 `try/except ValueError` 容错的 `_project_relative`。`target_path` 含 `..` 时前者抛未捕获异常，会让整个结构化变更失败。已与同文件其他地方一致。

## 验证

| 变异 | 结果 |
|---|---|
| O-2a 调度器不捕获任务异常 | 1 failing ✓ |
| O-2b checkpoint 路径越界 | 1 failing ✓ |
| O-2c DAG 读失败静默返空图 | 2 failing ✓ |
| O-2d DAG 裸写 | 1 failing ✓ |

新增测试 4 个（`test_benchmark_cancellation.py` 1 个、`test_runtime_diagnostics.py` 2 个、`test_studio_application.py` 相关 1 个）。

## 最终状态

- Core：**1637 passed / 32 skipped / 2 xfailed / 0 failed**
- studio-panel：**41 files / 358 passed / 0 failed**
- 源码无变异残留
- 改动：Core 55 文件 / 2781 insertions，未提交

## 这一轮的元教训

十四轮的总账现在要多加一条：**我自己的验证工具也会出错**。第十四轮的变异脚本数错了失败标记（`✖` vs `not ok`），这一轮的探针造错了 fixture（`has_next: false`）。两次都差一点得出错误的结构性结论——一次把有防线的修复判为无防线，一次把可达代码判为死代码。

共同点：**结论的证据来自我构造的输入，而不是来自真实路径**。变异验证的价值在于它强制证明"测试能失败"，但构造变异和构造测试用的是同一套假设，所以两者可以一起错。
