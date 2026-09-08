---
name: export-book
description: 导出。Use when the author asks 导出, 备份, 出书, EPUB, or types /export-book. Preflight first; never use the host /export session-log command for the manuscript.
---

# 导出

接到已有 `novel_*`。成稿导出与会话日志下载不是同一条命令。

1. `novel_export_preflight`：阅读顺序、结构缺陷、写作目标、评审新鲜度、正文接纳、阻断项与警告。
2. 向作者说明 `backup`（可带警告下载）与 `delivery`（门禁阻断则不可交付）。
3. 作者确认后 `novel_export`，原样传入同一 `format`、`purpose` 与 `preflight_revision`。

不要用宿主 `/export` 下载会话日志来代替成稿。完整项目档案走 `novel_project_archive_action`。
