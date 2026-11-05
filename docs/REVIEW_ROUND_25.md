# 第二十五轮：统一临时文件写入路径

## 结论：3 个真实漏洞（已修），1 个守卫测试（准确性问题已收敛）

## 背景

第二十四轮发现 7 处 `delete=False` + `replace` 的实现里，只有 `file_ops.atomic_write` 有 finally 清理。本轮把其余的统一。

## 修掉的 3 个真实漏洞

| 位置 | 问题 |
|---|---|
| `book_state.save` | `delete=False` + `replace`，无清理。这正是第二十一轮测过并发的那个函数——并发 merge 有测试，临时文件清理没有 |
| `session_state.save` / `goethe_session_state.save` | 同上 |
| `manuscript_editing._atomic_text` | 同上 |
| `model_profiles._write_json` | 同上，且**这里写的是凭据**——失败时残留的临时文件可能是全局可读的（默认 `NamedTemporaryFile` 权限），比别的更严重 |

另外 `chapter_memory._atomic_write`、`chapter_pipeline._atomic_write`、`cli._atomic_write_bytes` 也补上了 finally（后两个是 bytes 路径，不能直接用 str 版的 `atomic_write`）。

## 守卫测试的准确性问题（我花了最多时间的地方）

我写了一个 AST 守卫"所有 `delete=False` 的 writer 必须有清理"，它报了 **12 个 offender**。逐个核实发现：

- 2 个是真漏洞（上面修的）
- 其余是**守卫的误报**：`ast.get_source_segment` 对含嵌套 `def` 的函数返回不完整，导致外层函数看不到内层的 unlink
- `tool_runtime._application_executor`（71–615 行）含嵌套的 `execute`，那些分散的 unlink 在内层

我试了四种修法（限定非嵌套函数、行号切片、缩小判据），都有残余误报。**守卫本身无法在不误报的前提下覆盖这个模式**——因为"清理"可以合法地散落在多条早退路径上，静态判断"有没有清理"和"清理是否覆盖所有路径"是不同难度的问题。

### 最终决定

把守卫**收窄**到唯一无争议的核心：`file_ops.atomic_write` 自己不能泄漏。这个断言稳定、有价值（它是最多模块委派的写路径），变异测试能抓住。

"所有手写 temp+replace 都有清理"记录为已知待办——它需要人工审查，不是可靠的自动化门禁。

## 一个测试断言了实现细节

全量跑时发现 `test_save_uses_atomic_temp_file_and_replace` 失败：它断言 `Path.replace` 被调用，而我改用 `atomic_write` 后走的是 `os.replace`（经 `replace_file`）。

这个测试的本意是"save 不直接写最终文件"——这个断言仍然有效且已保留。把对 `Path.replace` 的具体断言放宽，因为实现细节变了但核心不变量没变。

## 验证

| 变异 | 结果 |
|---|---|
| Y-1a `atomic_write` 无 finally 清理 | 2 failing ✓ |
| Y-1b `book_state.save` 回到裸写 | 8 failing ✓ |

| | |
|---|---|
| Core | **1656 passed / 32 skipped / 2 xfailed / 0 failed** |
| 插件 test:maintenance | **81 passed / 0 failed** |

改动：Core 89 项，未提交。

## 本轮的方法论教训

**我花在守卫测试上的时间比修漏洞还多，而最后把它收窄了。** 这本身是个信号：当一个自动化检查需要反复调整判据才能不误报时，说明它想验的性质（"所有路径都清理"）超出了静态分析的能力，应该退回人工审查，而不是继续调判据。

值得对照的是：Y-1a 那个简单断言（"共享 writer 不泄漏"）一次就写对了，且变异测试直接抓住。**窄而准的断言比宽而反复调整的断言更有价值。**
