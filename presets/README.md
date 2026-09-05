# dsh agent 预设：OpenWrite 创作

本目录存放 dsh-Openwrite 的 OpenWrite 创作 agent 预设，把原先的 Goethe 规划与 Dante
写作职责合并到一个长期会话中。

## 预设说明

- `openwrite/`（OpenWrite 创作，order 10）：统一的长期会话 Agent。按项目阶段在
  规划、资产维护、正文写作、评审与修订之间切换；所有写入仍走预览/确认门控。

统一预设以 dsh shipped `standard` 预设的组合为基座（保留文件/Shell/检索/
todo/plan/compaction/委派能力），叠加：

- persona 行（`@deepseek-ai/dsh-persona`，移植自 OpenWrite 的
  `DEFAULT_GOETHE_SYSTEM_PROMPT` / `DEFAULT_DANTE_SYSTEM_PROMPT`，
  大纲写入契约、内联批注契约、角色文档契约已内联全文）；
- host profile 统一挂载的 `openwrite-bridge`（`@dsh-novel/openwrite-bridge`，注册
  `novel_*` 工具）；它不再重复写入每个 preset，否则会触发 `novelDomain` 服务冲突；
- `skill-filesystem` 的 `customSkillDirs` 指向预设自带的 `skills/` 目录
  （`!!js new URL('skills/', baseUrl)` 写法，预设被复制后仍能解析）。

## 安装与修改

预设由 `scripts/install.sh` 复制到 dsh 的用户预设根 `~/.dsh/.agent-presets/`。
dsh 预设是 **copy-only** 语义：安装后请在**本仓库**里修改，再重新运行
`scripts/install.sh` 安装；不要直接编辑 `~/.dsh/.agent-presets/` 下的副本。
会话已产生内容后不能切换预设，改动对新会话生效。

`openwrite/skills/` 是原 Goethe/Dante 技能的并集副本（非符号链接），保证复制安装后自包含。
