# 第二十三轮：缓存/标记失效条件的系统性审计

## 结论：未发现新缺陷（V-1/V-2 已在第二十二轮修复）

本轮按第二十二轮识别出的模式（**缓存/标记与事实不同步**）做了两个系统化审计，都是零命中。

## W-1：派生缓存的失效键（Core 侧全部完备）

自动扫描噪音太大（正则匹配到 `us` 之类的碎片），改为按已知缓存逐个查：

| 缓存 | 失效键 | 判定 |
|---|---|---|
| `writing_assets` | `sha256(内容)` | 内容哈希，比 mtime 更可靠 |
| `context_manifest` | `sha256(rendered)` | 内容哈希 |
| `character_state_index` | `path + size + mtime_ns` 三元组 | 路径集变化也会改变 manifest（列表长度不同） |
| `chapter_memory` / `review_store` | `source_revision` 对比 | 三态 current/stale/corrupt |
| `companions.mjs` | **已在 V-1 修复** | 现含 companion manifest mtime |

`character_state_index._load_cache` 对损坏返回 `{}` → `cached` 为假 → 重新计算。**fail-open 到"重新算"，是安全方向**。

其余 `st_mtime` 用法（`arc_audit`、`narrative_forecast`、`research_service`、`review_store`）都是"取最新的 N 个"排序，不是缓存判定。

## W-2：二值/三态判定的第三态

V-2 已修（`marker-corrupt`）。其余：

| 判定 | 第三态行为 | 判定 |
|---|---|---|
| `preset-definition.legacyPresetIds` | version 不可解析 → `[]` | fail-open 到"无兼容别名"，但此时整个插件都该失败，不会静默 |
| `chapter_memory` acceptance head 检查 | `except Exception: pass` 保持原 freshness | **有意的权衡**：降到 `unknown` 会让所有摘要都不进 prompt（可用性骤降），而保持 current 的风险只是"摘要略旧" |
| `manuscript_editing.revision_matches` | 允许 16 位短哈希前缀 | 空串不匹配（`fullmatch` 拒绝），16^16 碰撞可忽略 |

## 方法论：本轮为什么零命中

不是因为没有问题了，而是：

1. **W-1 的自动扫描失败了**——正则噪音让我无法相信它的输出，只好回到手工逐个查。这意味着"系统性"只覆盖了我已知列表里的缓存，可能漏掉我没列出的。
2. **W-2 的判定大多是三态或 fail-open 到重新计算**——这是第二十二轮修复 + 前几轮修复的结果，模式已经被清理过一遍。

## 状态

Core 缓存/新鲜度相关测试 **102 passed**，插件 81 passed，改动未提交（第二十二轮的 211 项 + 本轮无新改动）。

## 剩余未覆盖面

- **W-1 的自动扫描能力缺失**：我没有可靠的方法枚举"所有派生缓存"。本轮靠手工列表，可能遗漏。一个可靠的扫描需要先定义"缓存"的语义（有失效键的持久化数据），这本身是个待建能力。
- `live_tests/`、三系统 CI、真实设备（始终未覆盖）。
- **性能/资源维度**：从未审查过（内存增长、文件句柄泄漏、无界增长）。
