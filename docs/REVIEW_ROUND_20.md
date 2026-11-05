# 第二十轮：并发时序类缺陷的实证审查

## 结论：未发现新缺陷，但建立了此前缺失的验证能力

本轮覆盖了唯一还没被任何轮次碰过的维度——**并发**。静态扫描（第十九轮及以前）只能证明"锁存在"，不能证明"锁有效"。

## T-1：ProjectWriteLock 持有范围审计（3 个候选，全部排除）

扫描每个 `with ProjectWriteLock(...)` 块，找出"读在锁外、写在锁内"的：

| 位置 | 判定 |
|---|---|
| `chapter_pipeline.execute_review_chapter` | `workflow` 在锁外读，但锁保证只有一个执行者能到达写。锁外读的值在锁内变旧不是问题，因为该状态只被本函数修改。 |
| `chapter_pipeline.execute_multi_agent_chapter` | 同上。 |
| `reference_library.apply_adoption` | 锁包住 `_atomic_write_text`，注释说明了用途（防两个 adopt 并发写同一 preview）。`synthesize_style_document` 在锁外读刚写的文件——有窗口，但 adopt 是作者手动操作且 preview_id 唯一。**低风险，非数据损坏**。 |

## T-2：真实线程并发测试（新建 `tests/test_concurrency_invariants.py`）

用 `threading.Barrier` 让两个线程真正同时进入临界区，而不是 mock。

### 过程中我的三次错误预期

1. **第一次**：断言两个线程写的不同 `current_chapter` 都该保留。失败。但 `current_chapter` 是**单值字段**，必然有一个胜者——这是字段语义，不是并发 bug。
2. **第二次**：改用 `last_agent_action`，同样失败。它也是单值的，且在 `_own_state_fields` 里（语义就是"这个 agent 刚才做了什么"）。
3. **第三次**：想用 `recent_files`，但 `BookState` 没有这个字段——它的字段全是单值的。

最终锁定真正的不变量：**一个线程从未设置、另一个线程设置了的字段，不能被整对象覆盖清空**。用 `last_handoff_from`（B 传空串，必须继承 A 的值而不是清掉它）。

### 这三次纠正的价值

前两次失败让我确认了 `book_state` 的并发语义边界：它的所有字段都是单值的，所以"丢失更新"在这个结构上只能表现为"某个字段被清空"，不可能表现为"某条记录消失"（那是多值结构的问题）。

第三次让我发现 `BookState` 根本没有多值字段——这解释了为什么 K5(a) 的 merge 只需要处理单值继承。

## 验证

| 变异 | 结果 |
|---|---|
| T-2a book_state 回到整对象写 | 1 failing ✓ |

并发测试确实能抓住 K5(a) 的 revert——这补上了第十三轮只做单线程测试的缺口。

## 最终状态

| | |
|---|---|
| Core | **1648 passed / 32 skipped / 2 xfailed / 0 failed** |
| 新增 | `tests/test_concurrency_invariants.py`（2 个真实线程测试） |

## 对目标的意义

本轮是**零缺陷**轮次，但建立了新能力：真实线程并发测试。此前所有关于并发的修复（K5(a) 的 merge、settle_backfill 的锁、review_chapter 的锁、`_start` 的 RMW 锁）都只有单线程测试覆盖——也就是说那些修复的**并发正确性从未被验证过**，只验证了功能正确性。

现在这个缺口补上了一部分（`book_state`）。`truth_manager`、`task_store`、`arc_audit` 的并发不变量仍缺同类测试，是下一轮最直接的候选。
