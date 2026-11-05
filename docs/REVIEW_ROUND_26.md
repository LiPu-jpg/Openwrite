# 第二十六轮：畸形/恶意输入的健壮性审计

## 结论：4 个真实缺陷（已修），全部由新增的攻击面向测试暴露

本轮覆盖从未碰过的维度：**外部输入解析与文件系统边界**。

## Z-1：解析器的栈溢出（3 处）

`json.loads` / `yaml.safe_load` 在深层嵌套文档上抛 `RecursionError`，而它**不是** `JSONDecodeError` / `YAMLError` 的子类，所以逃逸了所有"损坏则降级"的处理器。

实测：**400 KB** 的嵌套 JSON 就能溢出（`"[" * 200000`），远小于 `MAX_DOCUMENT_BYTES`（2 MB）。

| 位置 | 修复前 | 修复后 |
|---|---|---|
| `studio_http._body_json` | 逃逸到 `do_POST` 的 `except Exception` → 500 + traceback | `INVALID_JSON_DEPTH` 400 |
| `session_state` / `goethe_session_state` | 每次会话启动都因同一损坏文件失败（重建也被同一错误挡住） | 重建并继续 |
| `book_state._merge_with_disk` | 每次 `save()` 抛异常，损坏文件永不更换 | 降级为写入者的状态 |

## Z-2：文件系统边界（2 处，其中 1 个是死代码）

### 符号链接写入检查是死代码

`_resolve_document` 原有 `if write and candidate.is_symlink(): raise` ——但 `candidate` 来自 `(root / path).resolve()`，**`resolve()` 已经跟随了符号链接**，所以 `candidate` 永远是真实路径，`is_symlink()` 恒为 False。

实测证明：`src/evil.md` → 符号链接到 `src/real.md`，PUT 返回 **200**，`real.md` 内容被改成 "clobbered"。

修复：把检查移到 `resolve()` **之前**。原有的死后检查保留（无害，且覆盖未来不经 resolve 的路径）。

### 超长路径组件导致 500

`ch_` + 500 个 `9` 的路径：`_resolve_document` 通过（`resolve()` 不碰文件系统），但后续 `is_symlink()`/`stat()`/写盘抛 `OSError [Errno 63] File name too long` → 逃逸成 **500**。

修复：在最开头（任何文件系统调用之前）拒绝 >255 字符的路径组件。

### 审计过但已安全的部分

路径/ID 边界整体是范本级——这是多轮修复的累积：

- HTTP URL 路由：`fullmatch` + 严格字符类（`ch_\d+`、`tsk_[A-Za-z0-9_-]+`、`ver_[A-Za-z0-9_-]{8,80}`）
- `TaskStore._task_id`、`RevisionStore._proposal_id`、`ChapterMemory.path_for`、`ManuscriptEditing._chapter_id/_version_id`、`ChapterRunStore.path_for` 全部 `fullmatch`
- HTTP body：按路由分级大小上限 + 413 + JSON 类型校验
- 文档路径：白名单根（`src/`、`data/manuscript/`）+ `.md` 后缀

## 验证

| 变异 | 结果 |
|---|---|
| Z-1a HTTP 不捕获 RecursionError | 2 failing ✓ |
| Z-1b session 不重建 | 1 failing ✓ |
| Z-1c book_state merge 不降级 | 1 failing ✓ |
| Z-2a 文档边界不再拒绝穿越 | 7 failing ✓ |
| Z-2b 允许写入符号链接 | 1 failing ✓ |
| Z-2c 不拒绝超长路径组件 | 2 failing ✓ |

新增 17 个测试（13 个遍历形状 × 2 方法 + 符号链接 + 深嵌套 ×2 + book_state）。

| | |
|---|---|
| Core | **1673 passed / 32 skipped / 2 xfailed / 0 failed** |

改动：Core 91 项，未提交。

## 本轮的方法论收获

**Z-2b 的变异第一次没被抓住，而这正是发现死代码的路径。**

我第一版变异改的是 `if write and candidate.is_symlink():` → `if False:`，测试仍绿。当时我以为是测试不够，追下去才发现：**那个检查本身就是死代码**，改掉它当然没有影响。真正的守卫是我新加的 resolve 前检查。

这印证了第二十五轮的教训：**变异测试抓不到，可能不是因为测试弱，而是因为被变异的目标本来就是死的**。这个信号值得追查，而不是放宽测试。

另一个收获：Z-2c（超长路径）不是扫描器找到的，是 Z-2 的测试在跑遍历形状时**意外撞出来**的——我加的 `ch_` + 500×`9` 用例本来只是"超长 ID"，预期 400，实际 500。攻击面向测试的价值在于它会走到你没预料的地方。
