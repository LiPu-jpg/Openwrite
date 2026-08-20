# Changelog

## 未发布

- openwrite-bridge 从 14 扩到 **62 个 `novel_*` 工具**，OpenWrite Studio 动作面全覆盖
  （修订闭环、任务中心、后台连写、章节运行、滚动大纲、叙事预测、风格/参考库/规则、
  深度研究、模型配置、项目生命周期等）；刻意不桥接 `/api/chat` 与 `/api/agent/*`，
  agent 会话层唯一归属 dsh
- 移除 `novel_chat_goethe`：不再回调 OpenWrite 内部 agent，草案生成由 dsh agent 自身完成
- goethe/dante 预设 persona 更新完整工具面；删章改走 `novel_chapter_delete` 服务端三重确认
- `subagent_goethe` 只读面补 `novel_asset_read`、`novel_continuity`
- studio-panel：新增「大纲」「资产」「任务」原生视图 tab 与 `novel_review_chapter`
  评审报告卡；host 侧 `GET /studio-panel/api/*` 只读代理（透传状态码/错误体，
  写操作仍只走 agent 工具）
- 配套 OpenWrite 侧改动（在 OpenWrite 仓库，未提交）：嵌入检测改为
  参数/被嵌/sessionStorage 三重判定；修复 start() 覆盖 shell 主题的问题；
  `applyShellTheme` 实时联动 Vditor 编辑器主题；嵌入时隐藏 Studio 主题切换按钮；
  **修复嵌入模式从未生效的根因——Studio CSP `script-src 'self'` 拦截内联脚本，
  启动逻辑移到外部 `embed-boot.js`**；嵌入时不再自动弹新手引导
- studio-panel：iframe 带 `?embed=dsh&theme=` 参数，跟随 shell 深浅色主题实时联动
- 配套 OpenWrite 侧改动（在 OpenWrite 仓库，未提交）：`OPENWRITE_FRAME_ANCESTORS`
  可配置嵌入白名单、`embed-dsh.css` 皮肤（嵌入时隐藏 Studio 内置 agent 入口）、
  index.html 启动脚本
- 新增 `scripts/verify.sh` 一键集成验证

## 0.1.0

- 首个版本：`@dsh-novel/openwrite-bridge`（14 个 `novel_*` 工具）、
  `@dsh-novel/studio-panel`（「稿件」tab 内嵌完整 Studio）、
  goethe/dante 双 agent 预设（persona 移植自 OpenWrite）、13 个移植技能、
  `install.sh` / `dev.sh` 脚本
