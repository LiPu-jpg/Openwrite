# 第二十一轮：并发不变量测试扩展到 truth_manager / task_store / arc_audit

## 结论：1 个真实并发缺陷（已修），6 个并发测试（新增）

## U-1：章节提交路径的 truth 结算没有锁（真实缺陷）

`apply_runtime_delta` 是对共享 truth 文件的读-改-写。第十三轮只给 `settle_backfill` 加了 `ProjectWriteLock`，但**章节提交路径**（`MultiAgentDirector._apply_state_settlement` → `apply_runtime_delta_with_fallback`）没有：

两个并发章节提交都读、都应用、只有第二个 delta 存活。

**修法上的关键约束**：不能把锁加进 `apply_runtime_delta_with_fallback` 本身——`settle_backfill` 已经在锁内调用它，而 `ProjectWriteLock` 用 `O_EXCL`，不可重入，会死锁。所以锁加在 `director.py` 的调用点。

顺带确认了 `chapter_pipeline.execute_write_chapter` **已经有锁**（885 行 `operation="write:{chapter_id}"`，1194 行的调用在其内），不需要改。

## U-2：task_store 的 CAS（无缺陷，但测试设计错了三次）

CAS 本身是正确的，我的测试三次才写对：

1. **第一次**：让两个线程同时 transition，断言终态不被回退。失败——因为两个线程的 `expected_status` 都是 `"pending"`，先到者合法胜出。这不是 CAS 失效，是我的场景让"回退者"也持有合法令牌。
2. **第二次**：改成回退者用 `expected_status="running"`。通过，但**变异测试抓不到**——barrier 只同步起点，不保证执行顺序，去掉 CAS 后时序上仍可能绿。
3. **第三次**：用 `threading.Event` 让回退线程**等完成之后**再执行，模拟真实的"任务完成后才恢复"。同时断言拒绝必须是 `TaskStoreError`（即 CAS 拒的），而不是其他原因。这样去掉 CAS 必红。

## U-3：arc_audit 的 revision CAS（无缺陷，但暴露了测试的隔离问题）

并发测试通过，但变异测试**抓不到**去掉 CAS 的情况——因为项目锁仍然串行化三个写入，每个后续写入因 revision 不匹配被拒。双保险中单去掉一层，不变量仍成立。

这说明并发测试验证的是**组合效果**，无法单独证明某一层的必要性。补了一个单线程测试：第一个写入者推进 revision，第二个持原始 revision 的写入者必须被拒——这隔离出了 CAS 本身。两个变异现在都能被抓。

## 验证

| 变异 | 结果 |
|---|---|
| U-1a director 结算不加锁 | 1 failing ✓ |
| U-2a task_store 去掉 CAS | 1 failing ✓ |
| U-3a arc_audit 去掉 revision CAS | 1 failing ✓ |
| U-3b arc_audit 去掉项目锁 | 1 failing ✓ |

## 最终状态

| | |
|---|---|
| Core | **1652 passed / 32 skipped / 2 xfailed / 0 failed** |
| 新增 | `tests/test_concurrency_invariants.py` 从 2 个测试增至 6 个 |

改动：Core 80 项，未提交。源码无变异残留。

## 本轮的方法论收获

**并发测试比单线程测试更容易写错，而且错得不明显。**

U-2 我错了三次：前两次测试都"通过"了，但变异测试证明它们抓不到要防的缺陷。U-3 的并发测试甚至无法单独验证 CAS——因为锁的存在掩盖了它。

两个修正技术值得记住：
- **用 `threading.Event` 而不是 `Barrier` 控制顺序**：Barrier 只同步起点，要验证"A 完成后 B 的陈旧写入被拒"必须让 B 真的等 A 完成。
- **当多个防护层叠加时，并发测试只能验证组合效果**。要单独验证某一层，需要绕过其他层（如 U-3 的单线程测试）。

这也解释了为什么此前那些并发修复（settle_backfill 的锁、task_store 的 CAS、arc_audit 的双保险）都"有测试"却从未被验证过并发正确性——单线程测试对这三者都足够，但换不出任何关于并行的信息。
