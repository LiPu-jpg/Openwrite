# 第二十五轮：插件侧资源生命周期

## 结论：1 个真实缺陷（已修）

## Y-2：失败升级留下整个 profile 副本

`upgradeProfile` 的 staging 目录是**完整 profile 副本，含 node_modules**（数百 MB）。它的 finally 只关 log 和释放锁，**从不删除 staging**。

全仓库只有一处 `openwrite-stage-`（创建处），没有任何清理处——`recoverUpgrade` 也不清理。所以每次失败升级都永久留下一个 staging 目录，重试一次再多一个，无上限。

对比：同文件其他资源都有 finally 保护——文件句柄（第 90 行）、pending 文件（第 94 行）、定时器/ drain（第 163 行）、恢复租约（第 208/283/307 行）。**只有 staging 漏了**，而它是最大的那个。

### 修复

```js
} finally {
  try { await log?.close() } finally {
    try { await rm(staging, { recursive: true, force: true }) } catch { /* best effort */ }
    await release()
  }
}
```

成功路径上 staging 已被 `rename` 到 target，所以这个 `rm` 是 no-op；失败路径上 reclaimed。

## 已确认正确的部分

- `managed-runtime.download`：`.partial` 文件有 finally 清理，且启动时清理历史残留（issue #82 的修复）
- `install.sh`：`set -euo pipefail` 保证 `mv` 失败即中止（rsync 不执行）；marker 写入已原子化（V-2）
- `safe-upgrade` 的锁：`mkdir` 原子创建 + dev/ino/birthtime 身份校验 + 心跳续租 + 陈旧回收
- Core 侧 `atomic_write`：finally 清理（第二十四轮统一了 5 处）

## 验证

| 变异 | 结果 |
|---|---|
| Y-2a 失败升级不清理 staging | 3 failing ✓ |

| | |
|---|---|
| 插件 test:maintenance | **81 passed / 0 failed**（原 80） |
| docs:check / doctor | 全绿 |
| studio-panel | **41 files / 358 passed / 0 failed** |

改动：插件 212 项，未提交。

## 本轮的模式

又是"同一个缺陷类修了 N 个、漏 1 个"：`safe-upgrade.mjs` 内部有 5 处 finally 覆盖了句柄/临时文件/定时器/租约，**唯独漏了最大的那个资源**（staging 目录）。

这与第二十四轮（5 个模块有上限，1 个没有）、第十六轮（5 个模块原子写，1 个没有）是同一模式：**逐个处理具体症状时不漏大项，因为大项往往不在当时视野里**。只有按维度（资源生命周期）主动枚举才能找出来。
