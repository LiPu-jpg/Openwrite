# 第十三、十四轮：对既有修复做变异验证

## 第十四轮：插件 TypeScript 层与前四轮遗留修复

第十四轮：变异验证插件 TypeScript 层与前四轮遗留修复。

**结果：21 个修复做了变异验证，3 个没有防线（已补测试）。4 个门禁脚本全部验证过能失败。**

> **第十五轮修正**：本报告原先把 N-B7（`ContinuousReader` 外层 catch 的 `loaded` fallback）判为「不可观测的死代码」。那个结论是错的——探针的 fixture 给了 `has_next: false`，`while` 循环在第一个 packet 后就 `break`，第二个 packet 从未被请求，所以 catch 自然不会触发。
> 用 `has_next: true` + `next_occurrence_id` 正确链接后，第二个 packet 的 identity 不匹配确实在 `loaded` 非空时抛错，catch 可达，变异也被测试抓住（`1 failed`）。
> 教训：判定「代码不可达」之前，先确认自己的输入真的能走到那里。

### N-A（openwrite-bridge，5 个变异）

全部有防线，但过程中发现 **N-A2 完全没有覆盖**：没有任何测试断言"超时产生 `REQUEST_TIMEOUT`"与"连接拒绝产生 `NETWORK_ERROR`"的区别。变异把抛出处的 code 改成 `NETWORK_ERROR` 后测试全绿——而这个区别是调用方决定"重试还是放弃"的唯一依据。已补 2 个测试（真实慢服务器 + 拒绝连接）。

另外 `novel_reading_order` 的 CAS 守卫（`expected_revision` 必须存在且非空）在 `followup-tools.test.mjs` 里零覆盖——两个守卫都补了测试。

### N-B（studio-panel，8 个变异）

**N-B5 暴露了本轮最大的缺口：`OutlineView.tsx` 完全没有测试文件。** 它承载了草稿保留、409 处理、18 处本地化一整批修复。新建 `outline-view.test.tsx`（2 个测试）。

补测试：`continuous-reader`（部分失败保留已读文档）、`serial-writing`（409 重拉 audit）。

**N-B7 曾被我误判为死代码（见文首修正）。** `ContinuousReader` 外层 catch 里的 `if (loaded.length > 0) { setDocuments(...) }`：canonical 模式下循环先 push 每个 packet 的文档，再校验下一个，所以中途失败时 `loaded` 非空，该分支可达。已补 canonical 测试（第一个 packet 必须 `has_next: true` 并给出 `next_occurrence_id`，否则循环提前退出），变异 `if (false)` 被抓住。

### N-C（门禁脚本，4 个注入缺陷）

每个门禁注入一个它声称能防的缺陷，要求非零退出：

| 门禁 | 注入缺陷 | 结果 |
|---|---|---|
| check-tool-references | tools.ts 引用 `novel_task_get` | 退出 1 ✓ |
| check-tool-references | 技能引用 `novel_task_get` | 退出 1 ✓ |
| check-editor-coordinates | 重命名 `mapEditorRange` | 退出 1 ✓ |
| gen-tools-md --check | 改动工具描述 | 退出 1 ✓ |

companion 侧 3 个变异（npm 预发布锚定规则、ops 宿主范围校验、legacyPresetIds 去重）全部被抓住。

### 过程中的两个我自己的错误（已修正）

1. **变异脚本数错失败标记**：node:test 默认 spec reporter 用 `✖` 而非 TAP `not ok`，导致上一轮把多个有防线的修复误判为未覆盖。本轮改为同时匹配两种，并对 vitest 输出解析失败时回退到退出码——避免 reporter 变更把每个变异都变成"未抓住"。
2. **变异锚点选错文件/行**：`check-editor-coordinates` 检查的是 `selection-coordinates.ts` 而不是我改的 `OutlineView.tsx`；`client.ts` 的第一次 `NETWORK_ERROR` 出现在注释里。两者一度被误报为"门禁失效/无防线"。

### 最终状态

| | |
|---|---|
| Core | **1634 passed / 32 skipped / 2 xfailed / 0 failed** |
| 插件 test:maintenance | **80 passed / 0 failed** |
| studio-panel | **41 files / 357 passed / 0 failed** |
| docs:check / doctor / test:preset | 全绿 |

### 三轮变异验证的总账

第十三轮 + 第十四轮共验证 **36 个修复**，其中 **15 个原本没有防线**（含 N-B7，见文首修正），另发现 **1 个真实新缺陷**（character_state_index 的 acceptance 过滤失败时丢弃全部手稿批注，已在第十三轮修复）。

新增测试 24 个（Core 17 + 插件 7）。

**方法论上的结论**：修完缺陷不等于完成。这一系列轮次证明，"测试通过"这个信号在只写实现不写变异验证时是大幅打折的——14/36 的修复 revert 后测试全绿。变异验证必须作为修复的一部分，而不是可选的后续检查。


---

## 第十三轮：Core 侧修复

**方法**：逐个把已应用的修复改回缺陷形态，跑对应测试，看是否变红。结论：**12 个修复原本没有防线，其中 1 个还连带暴露了一个真实的新缺陷。**

### 本轮新发现的真实缺陷（C-M22 加深）

`character_state_index._source_paths()` 的 acceptance 过滤失败时，外层 `except Exception` 只记录警告后继续，但 `accepted` 保持为空——于是候选集只剩 `src/*.md`，**manuscript 里所有已验收章节被完全排除**。实测：acceptance store 抛错 → `paths: []` → 索引从空集回答。注释声称"exactly as `refresh` already does for its per-file failures"，但 `refresh` 不过滤，语义并不等价。

已修为失败时退回**整个 manuscript 集合**：宁可多报一条过期批注（可恢复），不可静默丢掉全部。

### 原本没有防线的修复（现已全部补齐）

| 修复 | 轮次 |
|---|---|
| K5(a) book_state 并发写合并 | 七 |
| K5(b) Dante 上下文快照刷新 | 七 |
| K5(c) session 转录轮转 | 七 |
| I-H1 记忆文件 stem 过滤 | 九 |
| J1 craft 正则匹配 / severity 映射 | 十 |
| J2 manifest.toml 原子写 | 十 |
| L1 outline_sync 原子写 | 十二 |
| C-M14 settle_backfill 全程写锁 | 五/六 |
| C-M15 baseline 裁剪 + evicted 标记 | 六 |
| C-M20 asset_package 悬空依赖 | 六 |
| C-M22 acceptance 过滤失败 fallback | 六 |
| G-H1 记忆 corrupt 可区分 | 八 |
| G-H2 anchors 不截断 | 八 |
| I-H3 install.sh 备份作者改过的随包文件 | 九 |
| I-H4a safe-upgrade `--profile` 无值报错 | 九 |

### 测试自身的两个缺陷

1. **I-H3 的假覆盖**：原测试的"作者编辑被保留"断言，实际被"作者独有文件触发整目录 move-aside"顺带满足——去掉 `cmp -s` 分支后测试仍绿。已新增隔离场景（只有随包文件被改、无作者独有文件）。
2. **子进程 stderr 收集竞态**：`on('data')` + `once('exit')` 会在 stderr 到达前断言，导致断言实际不生效。改用 `close` 事件后统一收集。

### 方法论错误（已修正）

node:test 默认 spec reporter，失败显示为 `✖` 而非 TAP `not ok`。前几轮的变异脚本一直在数 `not ok`，**把多个已有防线的修复误判为未覆盖**。已改为同时匹配两种输出。

### 本轮新增测试（17 个）

Core：`test_agent_session.py`（转录轮转）、`test_agent_book_state.py`（并发合并 ×2）、`test_dante_shell.py`（上下文刷新）、`test_issues_88_95.py`（stray 记忆文件 / corrupt 记忆 / settle 写锁）、`test_craft_rubric.py`（新文件，4 个）、`test_prompt_contract_repairs.py`（manifest 原子写）、`test_cli_sync.py`（outline 原子写）、`test_character_state_index.py`（acceptance fallback）、`test_asset_package.py`（悬空依赖）、`test_serial_writing.py`（baseline 裁剪）、`test_issue_109_regressions.py`（anchors 不截断）。

插件：`scripts/safe-upgrade.test.mjs`（2 个 CLI 子进程测试）、`scripts/lifecycle.test.mjs`（作者改随包文件的隔离场景）。

### 最终状态

- Core：**1634 passed / 32 skipped / 2 xfailed / 0 failed**
- 插件 `test:maintenance`：**80 passed / 0 failed**
- 全部 15 个变异均被测试抓住（1 failing 起）
