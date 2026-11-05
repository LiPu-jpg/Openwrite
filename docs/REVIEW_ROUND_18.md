# 第十八轮：系统性审计门禁处 except 分支的放行方向

## 结论：两个维度均未发现新缺陷

本轮是第十七轮识别出的新维度（"异常路径上门禁是放行还是拒绝"）的系统化扫描。两个子任务都完成，**都没有发现缺陷**。这本身是有效信息。

## R-1：except 分支的放行方向（127 个候选 → 6 个门禁候选 → 全部排除）

第一轮粗扫（函数名含门禁词）只有 3 个命中，全是 `_is_stale`（锁陈旧判定）。放宽到所有 except 分支后得到 127 个候选，再用"函数体内含 confirm/expected_revision/pending_confirmation 等门禁词汇"过滤，降到 6 个：

| 位置 | 判定 |
|---|---|
| `project_lock._is_stale` | 读不到 mtime 判陈旧。注释明确"宁可误清理也不要让残留锁卡死写作"，且有 `initialization_grace_seconds` 宽限。**有意的可用性权衡**，且锁不是提权门禁。 |
| `project_search._is_stale` | 同上，索引锁。 |
| `manuscript_acceptance.inspect` | `continue` 跳过单个读不到的历史 operation，不影响当前门禁判定。 |
| `task_store._load_raw` | 返 `None`（非 `{}`）。三处消费全部正确：`load` 返 None、`update` 抛 `TaskStoreError`、`heartbeat` 是 `if task and ...`。 |
| `agent/writer.py:363` | 模型输出重试循环，解析失败试下一个候选。 |
| `llm/response.load_structured_mapping` | 候选遍历，最后抛 `ProviderResponseError`。 |

**关键排除依据**：`project_lock` 那两处如果按"fail-closed"修，会让一个残留锁永久卡死写作——那是用可用性换安全，而这里的锁保护的是并发写（数据竞争），不是权限。方向选择取决于风险类型，不能一律 fail-closed。

## R-2：确认类门禁的覆盖完整性（14 处 → 无缺陷）

逐个检查所有 `confirm` / `expected_revision` 门禁的**校验顺序与严格度**：

| 位置 | 校验 |
|---|---|
| `novel_archive.restore` | confirm → sha256 校验 → 重新 preview → 冲突检查。范本级。 |
| `manuscript_import.confirm_structure` | confirm → `expected_preview_revision` → `_assert_not_final` |
| `manuscript_import.discard` | confirm → ProjectWriteLock |
| `manuscript_editing.restore_version` | confirm → chapter/version ID 清洗 → 锁 |
| `arc_audit.change` | `confirm is not True`（严格，拒绝 `1`/`"true"`）→ `expected_revision` 用 `is not int` 类型校验 |
| `export_preflight.require_exportable` | revision 不匹配抛 `EXPORT_PREFLIGHT_CHANGED` → `can_export` 检查 |

`export_preflight.require_exportable` 的 `expected_revision` 默认 `""`（不校验）一度像是缺口，但唯一调用方 `novel_service.py:261` 确实传了 `preflight_revision`。默认值只是 API 灵活性。

## 顺带的改动

`project_registry.write_content_project_metadata` 的裸 `write_text` 改为 `atomic_write`（显式创建动作，低风险，但一致性更好）。

## 状态

| | |
|---|---|
| Core | **1643 passed / 32 skipped / 2 xfailed / 0 failed** |
| 确认门禁相关测试 | 66 passed |
| 改动 | Core 75 项，未提交 |

## 对目标的意义

这是第一个**没有发现缺陷**的轮次。前十七轮每轮都有收获，本轮两个系统化扫描都是零命中——说明这两个维度已经趋于干净，继续在同一维度扫描的边际收益在下降。

剩余未被这些维度覆盖的面：
- **`live_tests/`**（需真实模型）
- **三系统 CI / Windows / Android 实机**（无本地环境）
- **插件侧 TypeScript 的 except 方向**（本轮只扫了 Core 的 Python）
- **并发时序类缺陷**（本轮扫的是静态模式，竞态需要压力测试才能暴露）

其中"插件侧 except 方向"是与本轮同维度、尚未覆盖的部分，是下一轮最直接的候选。
