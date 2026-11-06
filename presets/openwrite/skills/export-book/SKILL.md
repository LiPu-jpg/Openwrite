---
name: export-book
description: 导出。Use when the author asks 导出, 备份, 出书, EPUB, or types /export-book. Preflight first; never use the host /export session-log command for the manuscript.
---

Language: follow the author's current conversation language for responses and help; preserve the manuscript language. Translate these instructions when presenting them.

# 导出

接到已有 `novel_*`。成稿导出与会话日志下载不是同一条命令。

1. `novel_export(action="preflight"`：阅读顺序、结构缺陷、写作目标、评审新鲜度、正文接纳、阻断项与警告。
2. 向作者说明三种 `purpose`：`personal_archive`（作者自留，可带警告下载，**不代表通过交付门禁**）、`backup`、`delivery`（门禁阻断则不可交付）。
3. 作者确认后 `novel_export`，原样传入同一 `format`、`purpose` 与 `preflight_revision`。

不要用宿主 `/export` 下载会话日志来代替成稿。完整项目档案走 `novel_project(action="archive", archive_op="preflight"` → `archive_op="create"`（需带 `expected_preflight_revision`）→ 需要时 `archive_op="restore_preview"` / `archive_op="restore"`。
