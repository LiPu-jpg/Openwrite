---
name: learn
description: 写法记忆。Use when the author asks 记住写法, 成功钩子, 作者偏好, or types /learn. Store style, hooks, and preferences as Workspace-scoped OpenWrite assets; do not create a second memory store.
---

# 写法记忆

接到已有 `novel_*`。风格、成功钩子和作者偏好是当前 Workspace 作品资产，不是会话本地文件，也不是第二套 RAG / lorebook。

## 读取

1. `novel_status` 确认当前作品。
2. 风格与提取源：`novel_source_action`（`status_v2` / `profile_v2`）。
3. 已登记钩子：`novel_assets_list`，必要时 `novel_asset_read`。

没有 Workspace（session cwd 缺失）时这些工具返回 `WORKSPACE_CONTEXT_MISSING`，不要改写全局或别的项目。

## 写入（预览/确认）

- 作者偏好、必须保留/避免：`novel_structured_change_plan(change_kind="focus")`。
- 成功钩子与可复用写法：`novel_source_action` extract/review，晋升用 `promote_v2` 且作者确认后 `confirm: true`；登记为资产时用 `novel_structured_change_plan(change_kind="asset")`。
- 普通讨论不得写入。

细则见 style-system。不要另建记忆文件。
