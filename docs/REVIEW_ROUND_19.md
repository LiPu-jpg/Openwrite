# 第十九轮：插件 TypeScript 层的门禁方向与错误路径审计

## 结论：1 个真实缺陷（S-2），S-1 干净

## S-1：插件 TS 层 catch 方向（全部排除）

第一版扫描（只匹配 `return true` 等狭窄模式）零命中。放宽到"所有不抛错的 catch"后得到一批候选，逐个排查：

| 位置 | 判定 |
|---|---|
| `AssetsView.tsx:446` | `workspacePromise.catch(() => null)` 是**有意的部分失败容忍**（注释说明 reference/核心文档的失败不能拖垮资产区），且 `workspace?.references ?? []` 有空值保护。 |
| `CreationView.tsx:867` | 草稿写入链的 `.catch(() => undefined)`——让前一个失败不阻塞后一个写入，且 `.then(onOk, onFail)` 的 onFail 设置了错误提示。 |
| `SerialWritingView.tsx:89` | 第十四轮修的 409 分支，有测试覆盖。内层 `.catch(() => {})` 是重拉失败时保留已有提示。 |
| `companions.tsx:162` | `existingProfile().catch(() => undefined) !== undefined`——读取失败时当作"配置已存在"→ 弹确认框而非直接写入。**这是 fail-closed 的正确方向**。 |
| 其余约 10 处 | `if (cancelled) return` / `if (!active) return` 的清理代码，不是门禁。 |

## S-2：错误码到 HTTP 状态的映射（发现 7 个缺失）

写了一个交叉校验：把 `NovelServiceError` 能抛的所有 `code` 与 `_translate_service_error` 的映射表比对。

**第一版校验报 230 个未映射，几乎全是误报**——它比对了 `tools/` 下所有 `code=`，但 `_translate_service_error` 只接收 `NovelServiceError`，其他错误类型走任务路径（`task_runner` 用 `getattr(exc, "code", "TASK_FAILED")` 原样保留错误码，不需要 HTTP 映射）。

修正后只比对 `novel_service.py` 里的 15 个 code，得到真实的 7 个缺失：

| code | 语义 | 落 502 的后果 |
|---|---|---|
| `INVALID_EXPORT_OUTPUT` | 导出目标是符号链接/非普通文件 | **安全检查被当作临时故障重试** |
| `EXPORT_OUTPUT_CHANGED` | 目标在检查期间变化 | 409 语义丢失 |
| `EXPORT_OUTPUT_RECOVERY_REQUIRED` | 需人工恢复 | 同上 |
| `RUN_NOT_RESUMABLE` | 无可恢复草稿 | 同上 |
| `RUN_TARGET_MISMATCH` | 恢复目标长度不符 | 同上 |
| `CHAPTER_ALREADY_EXISTS` | 章节已存在 | 同上 |
| `EXPORT_AUDIT_FAILED` | 回执写盘失败（导出已完成） | 500（本就该是 500） |

最值得注意的是 `INVALID_EXPORT_OUTPUT`：它是对符号链接的**安全拒绝**，502 会让客户端和作者都以为是可以重试的上游故障。

### 固化为守卫

新增 3 个测试：一个自动比对（未来新增 code 漏映射会红）、两个具体断言（symlink → 400、章节已存在 → 409）。

## 验证

| 变异 | 结果 |
|---|---|
| S-2a 去掉 `INVALID_EXPORT_OUTPUT` 映射 | 2 failing ✓ |
| S-2b 去掉 `CHAPTER_ALREADY_EXISTS` 映射 | 2 failing ✓ |

## 最终状态

| | |
|---|---|
| Core | **1646 passed / 32 skipped / 2 xfailed / 0 failed** |
| 插件 test:maintenance | **80 passed / 0 failed** |
| studio-panel | **41 files / 358 passed / 0 failed** |

改动：Core 76 项，未提交。

## 方法论教训

本轮第一次尝试的校验脚本给出 230 个"未映射"，我差一点就要去补 230 条映射。真正的问题是**校验的范围错了**：它假设所有错误码都走同一个翻译层，而实际上同步路径和任务路径是两套机制。

这跟第十七轮是同一类错误——**结论来自我构造的假设，不是来自真实的调用路径**。修正方法是追调用链（`benchmark.run` 在 `_task_model_benchmark` 里，异常被 `task_runner` 统一捕获并保留 code），而不是看静态的 `code=` 出现次数。
