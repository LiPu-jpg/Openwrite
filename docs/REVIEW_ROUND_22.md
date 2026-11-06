# 第二十二轮：插件侧并发与安装/升级路径审查

## 结论：2 个真实缺陷（已修）

## V-1：companion 升级后缓存不失效

`companions.mjs` 的缓存 fingerprint 只包含 profile 的 `package.json` mtime，**不含 companion 自身的 manifest**。而 companion 的 `package.json`（`peerDependencies['@deepseek-ai/dsh']`）正是判定宿主兼容性的依据。

后果：升级 companion（放宽或收紧 peer range）后，缓存仍返回旧判定——正是 #150/#151/#142 那一类问题的复发路径，只是触发条件从"版本比较错"变成"缓存不失效"。

修复：把每个候选 companion 的 manifest mtime 纳入 fingerprint。

**测试因此在断言错误行为**：原测试 `a cache hit serves the stored answer instead of recomputing` 删掉 companion 包后断言仍返回 `cached: true, usable: true`——即"包没了还说可用"。已改为正确语义（删除后必须失效、重新计算为不可用），并补了第三次调用验证纯重复仍命中缓存。

## V-2：损坏的 ownership marker 被永久误判

`install.sh` 用裸 `cat >` 写 `.openwrite-managed.json`，崩溃会留下截断文件。`maintenance.mjs` 的 `inspectPresets` 对解析失败 `.catch(() => null)` → 判为 `author-owned` → **升级被永久拒绝，且没有任何诊断说明原因**。

fail-closed 方向是对的（不会误覆盖作者数据），但不可恢复、不可诊断。

双管齐下：
- **消除根因**：marker 改为 `mktemp` + `mv` 原子写入，带 `trap` 清理临时文件
- **可诊断**：`inspectPresets` 区分 `marker-corrupt` 与 `author-owned`，并返回 marker 内容

## V-2b 的测试三次才抓住

内容断言无法区分原子写和非原子写（成功时字节相同）。前两次尝试：
1. 断言 marker 内容完整 → 两种写法都通过
2. 断言 `version` 非空 → 发现 fixture 的 package.json 没 version 字段（不是产品缺陷）

最终用**结构性断言**：install.sh 必须匹配 `marker_tmp=$(mktemp ...)` + `mv "$marker_tmp" "$target/.openwrite-managed.json"`，且不得匹配 `cat > "$target/.openwrite-managed.json"`。

## 审查过但未发现问题的部分

- **`safe-upgrade.mjs` 的 `acquireRecoveryLock`**：`mkdir` 原子创建 + `dev/ino/birthtime` 身份校验 + 每秒心跳续租 + 30 秒陈旧回收。实现相当严谨，未发现问题。
- **`install.sh` 的 move-aside + rsync**：`set -euo pipefail` 保证 `mv` 失败即中止（rsync 不会执行），`mktemp -d` 避免同秒冲突，NUL 分隔处理任意文件名。安全。
- **companion 缓存的并发写**：`writeFile` 非原子，但读侧有容错，损坏只导致缓存失效（重新计算），不会产生错误结果。低风险。

## 验证

| 变异 | 结果 |
|---|---|
| V-1a fingerprint 不含 companion manifest | 3 failing ✓ |
| V-2a 损坏 marker 当作 author-owned | 3 failing ✓ |
| V-2b install.sh marker 裸写 | 3 failing ✓ |

## 最终状态

| | |
|---|---|
| 插件 test:maintenance | **81 passed / 0 failed**（原 80） |
| studio-panel | **41 files / 358 passed / 0 failed** |
| docs:check / doctor | 全绿 |
| lifecycle | 10 passed |

改动：插件 211 项，未提交。

## 二十二轮总账

| 维度 | 轮次 | 结果 |
|---|---|---|
| 变异验证 | 13–14 | 15 个修复无防线 |
| 数据丢失 | 12–16 | 5 个模块 |
| 门禁 fail-open | 17 | 2 处 |
| except 方向 | 18–19 | 7 个错误码缺失 |
| 并发（Core） | 20–21 | 1 个无锁缺陷 |
| 并发（插件）+ 安装路径 | 22 | 2 个缺陷 |
