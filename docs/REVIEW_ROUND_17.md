# 第十七轮：按系统性缺陷模式验证剩余命中模块

## 方法

第十六轮识别出代码库的系统性模式（**裸写 + 读失败降级 + 调用方覆写**），本轮按这个模式精确扫描：找"读失败返默认值"与"同模块有写"配对的地方，而不是笼统地数 except。

精确扫描只找到 1 个新候选（`project_registry`），因为第十六轮已把五个实例修掉了。但本轮在**另一个维度**上发现了更严重的问题。

## 修掉的缺陷：fail-open 的门禁（比数据丢失更危险）

前六轮修的全是"数据丢失"类。本轮发现的是"**安全门禁在异常路径上放行**"类。

### Q-1a：goethe 的 handoff 捷径读不到状态就放行

`goethe.py:_should_use_handoff_shortcut`：

```python
try:
    state = BookStateStore(...).load_or_create()
except Exception:
    return True        # ← 放行捷径
```

捷径的作用是绕过 outline-scope 确认门。读不到状态时无法知道是否还有待确认项，此时返回 `True` = **放行绕过**。这与用户要求的 fail-closed 完全相反。

### 但第一版修复是无效的——因为异常根本没抛出

我先把 `return True` 改成 `return False`，测试却仍然失败。深入发现：`BookStateStore.load_or_create()` 对损坏文件**不抛错**——它 quarantine 原文件后返回一个全新状态：

```python
except Exception as exc:
    self._quarantine(exc)          # 原文件移走
    state = BookState(...)          # 全新状态
    return state                   # 不抛
```

所以真正的触发路径是：文件损坏 → quarantine → 新状态（`pending_confirmation` 为空）→ `not bool("")` = **True** → 捷径放行。我的 `return False` 在这条路径上永远不会执行。

**这是本轮最重要的发现**：一个看起来修好了的 fail-open，实际上修的是不可达的分支。

### Q-1c：同一个坑在 K3 守卫上还有一处

`goethe_actions.generate_character_draft` 的 K3 守卫（第十三/十四轮验证过）用的是 `load_or_create()`。状态文件损坏 → quarantine → 新状态 → 守卫不触发 → 角色生成放行 → 之后 `confirm_outline_scope()` 升格**旧大纲**，而作者以为新大纲已确认。

这正是 K3 注释里描述的那个 bug 的**另一条触发路径**——之前的修复只覆盖了"pending_confirmation 确实为 outline_scope"的情况，没覆盖"状态读不出来"的情况。

### 修法

给 `BookStateStore` 加 `load_strict()`：文件存在但解析失败时抛 `BookStateError`（quarantine 与否由调用方决定）。两处门禁改用它，损坏时 fail closed。

`discard_outline_edits` 保持宽松读——作者显式要求丢弃时不该被文件损坏挡住，且清除不是提权操作。

## 被证伪的候选

- **`project_registry.load_project_metadata`** 返 `{}`：两个消费者都是 `git_checkpoint`，后果是 `project_type` 视为 `unmarked` → 禁用自动 checkpoint。**安全侧 fail-closed，正确**。顺手把它的裸 `write_text` 改成原子写。
- **`goethe._load_onboarding_snapshot` / `_load_config`** 返 `{}`：消费方全部有空值保护，只影响引导信息，不影响正确性。
- **`write_guard.outline_node`** 返 `None`：docstring 明确说明两种 None 的语义由调用方区分，是有意设计。

## 验证

| 变异 | 结果 |
|---|---|
| Q-1a goethe 用宽松读 | 1 failing ✓ |
| Q-1b book_state 无严格读入口 | 1 failing ✓ |
| Q-1c goethe_actions 用宽松读 | 2 failing ✓ |
| Q-1d 严格读对空文档不抛错 | 1 failing ✓ |

新增 3 个测试。中途还有一个测试自身的问题：截断一半的状态文件（235 → 117 字节）恰好仍是合法 YAML，测试抓不到缺陷；改成真正不可解析的内容后才生效。

## 最终状态

| | |
|---|---|
| Core | **1643 passed / 32 skipped / 2 xfailed / 0 failed** |
| 插件 test:maintenance | **80 passed / 0 failed** |

改动：Core 74 项，未提交。

## 十七轮总账

| 轮次 | 缺陷类 |
|---|---|
| 12-16 | 数据丢失（裸写 + 降级 + 覆写），5 个模块 |
| 17 | **安全门禁 fail-open**，2 处 |

第十七轮的意义：前六轮我一直在找"数据会丢吗"，从来没有系统性地问过"**异常路径上门禁是放行还是拒绝**"。这次一问就找到两处，其中一处的第一版修复还是无效的（修了不可达分支）。

这个维度此前完全没被覆盖过，剩余的 except 分支都值得按"fail-open 还是 fail-closed"重新过一遍。
