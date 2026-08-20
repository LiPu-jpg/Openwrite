# dsh agent 预设：Goethe 规划 / Dante 写作

本目录存放 dsh-novel 的两个 agent 预设，把 OpenWrite 的双 agent 小说创作系统
移植到 dsh 的 agent-preset 模式。

## 预设说明

- `goethe/`（Goethe 规划，order 10）：长期会话规划 Agent。负责收敛灵感与作者意图、
  维护人物/设定/大纲/伏笔资产，所有写入走"暂存 diff → 用户确认 → 应用"的门控流程；
  资产成熟后提示用户切换到 Dante。
- `dante/`（Dante 写作，order 20）：正文创作 Agent。基于已确认资产执行
  预检（`novel_context_preview`）→ 写章（`novel_write_chapter`）→ 37 维评审
  （`novel_review_chapter`）→ 状态结算；资产不齐时退回 Goethe 补齐。
  另挂载 `subagent_goethe` 委派工具（`dsh-tool-subagent`，spawn provider，
  persona 为只读规划顾问，toolFilter 仅放行只读 novel 工具），
  写作中可就大纲/人物/设定一致性问题向 Goethe 咨询。

两个预设都以 dsh shipped `standard` 预设的组合为基座（保留文件/Shell/检索/
todo/plan/compaction/委派能力），叠加：

- persona 行（`@deepseek-ai/dsh-persona`，移植自 OpenWrite 的
  `DEFAULT_GOETHE_SYSTEM_PROMPT` / `DEFAULT_DANTE_SYSTEM_PROMPT`，
  大纲写入契约、内联批注契约、角色文档契约已内联全文）；
- `openwrite-bridge` 桥接插件行（`@dsh-novel/openwrite-bridge`，注册 `novel_*` 工具）；
- `skill-filesystem` 的 `customSkillDirs` 指向预设自带的 `skills/` 目录
  （`!!js new URL('skills/', baseUrl)` 写法，预设被复制后仍能解析）。

## 安装与修改

预设由 `scripts/install.sh` 复制到 dsh 的用户预设根 `~/.dsh/.agent-presets/`。
dsh 预设是 **copy-only** 语义：安装后请在**本仓库**里修改，再重新运行
`scripts/install.sh` 安装；不要直接编辑 `~/.dsh/.agent-presets/` 下的副本。
会话已产生内容后不能切换预设，改动对新会话生效。

各预设 `skills/` 是仓库根 `skills/` 的子集副本（非符号链接），保证复制安装后自包含。
