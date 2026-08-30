# Changelog

## 2026-08-23 - dsh 原生创作工作台

- OpenWrite 改为无界面领域后端；`NovelDomainService` 统一工具、同源 API 代理和轻量 revision 失效流。
- 顶层插件视图收敛为「创作 / 资料 / 任务」，默认工作流彻底移除 iframe 与重复导航。
- 新增原生 Vditor 正文编辑器：1.2 秒自动保存、version 乐观锁、409 草稿保护、显式覆盖。
- 新增共享 `NovelWorkbenchStore`、会话头作品状态、输入章节上下文、Turn 写操作汇总。
- 44 个常用工具归入八类原生卡片；大纲默认只展开当前章节路径。
- Vditor 主运行时随插件打包，辅助资源由 dsh 同源提供；增加原生路由、无 iframe 与多工作台 smoke 门禁。

## 未发布

- 评审体系升级为 review v2：原 37 项恰好映射到六个计分域和一个硬门禁，使用有正文
  证据才得分的累加机制；`quality_score`、`coverage`、`gate_status`、
  `delivery_status` 分离，issue 不再直接扣分，severity 与 `revision_priority` 独立。
- 评审 DoG 改为 47 节点分层图（上下文、六域、门禁、确定性聚合、37 个 legacy leaf），
  全部使用程序 verifier；交付图扩为
  `writing → review → revision → application → rereview → closure` 六阶段。
- 「图谱」新增 React Flow + ELK 的评审/交付 DAG，可选章节、筛选异常/blocker、折叠六域、
  展开 37 项并查看 score/coverage/evidence/issue/provenance；Studio 新增只读
  `GET /api/dog/graphs`，不会运行 verifier 或模型。
- 新增框架内模型测试台与第 63 个工具 `novel_model_benchmark`：通过 OpenWrite profile
  和 LiteLLM-compatible gateway 固定上下文 hash，隔离运行多写作模型 × 独立评审模型，
  artifact 写入 `data/novels/{id}/data/benchmarks/`，不修改全局路由或正式正文。
- 模型测试默认进入 OpenWrite 公共生产写章与评审管线；每个候选/重复轮次使用完整作品
  沙箱并保留 Chapter Run V2、记忆、工作流与提交证据。裸 `_creative_write` 路径仅作为
  显式 `creative` 诊断模式。
- 框架内候选失败现在也保留公共入口、Run V2 ID、阶段状态、失败阶段与安全错误码；未完成
  `commit` 的可靠性失败不会进入评审或获得质量分，旧 artifact 在 UI 中仍按执行模式显示
  正确入口。
- 模型测试统一归一 OpenRouter/OpenAI-compatible/LiteLLM 的 token 与实际费用，汇总输入、
  输出、推理用量和费用覆盖率；明确免费的 `$0` 与未知费用分开显示，并提供本次调用的综合
  有效价 `/ 1M tokens`，不冒充模型目录单价。
- 审稿卡和任务列表优先显示 v2 质量分、覆盖率、门禁/交付状态，并分别展示
  `critical/warning/info` 评审严重度与 `blocker/high/medium/low` 修订优先级。
- 新增 DAG/benchmark HTTP 生命周期测试、bridge tool/proxy smoke、Python/TypeScript
  parity/无环/stale 测试，以及优质/当前/故障三类合成 golden fixtures 与 v1/v2 双轨校准。

- dsh-dog 进一步融合：同步评审、conductor 与后台 `chapter_review` 任务统一物化
  分层评审查询图（保留 `1..37` legacy leaf）；修正维度参数为 OpenWrite 要求的
  `1..37` 整数数组并加入阈值校验。
- 新增章节交付总图：以正文 SHA、评审 `source_revision`、修订提案状态和复评结果
  串联 `writing → review → revision → application → rereview → closure`；应用修订后强制进入待复评，
  只有当前正文复评通过才标记 `readyForDelivery`。同步工具、后台任务和 conductor
  均会刷新交付快照，并新增 `dog-delivery-query` 技能。
- 修复智能导入的 DOCX/EPUB 二进制文件被提前文本解码、空任务项目无法解析
  `novel_id` 的问题；补齐导入格式依赖和 DoG 契约测试（含真实 dsh-dog 图校验）。

- 「审稿」tab 并入「写作」（原总览）三分段：总览 ⇄ 正文 ⇄ 审稿，Studio iframe
  三合一；tab 总数 10 → 9，标签更名「写作」
- 搜索 tab 点击即读：结果行可点击，内联预览经 GET /api/document 取全文，
  命中行 ±2 行带行号高亮，返回钮回列表——查到的资料不再需要跳去别处看
- 任务 tab 补管理闭环：行悬停 取消（pending/running/awaiting_confirmation，
  confirm 门）与 重试（failed 且 recoverable）按钮，走 host 代理新增的模式
  白名单 `tasks/{id}/cancel|retry`
- 任务 tab 评审结果可见化：完成的 chapter_review 行内嵌分数徽章（分档着色），
  点击展开问题清单（severity 着色 + 维度 + 摘要，≤10 条）——conductor 经 HTTP
  跑的评审与 agent 工具跑的同样可见
- 设计令牌归一：本轮新增样式全部映射回平台既有词汇，清除自造令牌
- conductor 新增 dsh 原生深度研究路线（`research.py`）：headless 会话用平台
  自带 web_search 联网调研并综合成报告，落库 OpenWrite 报告目录（研究 tab
  直接可见）——绕开博查 Key 依赖，零额外凭据；实测两份真实报告入库
- 研究 tab 补「发起研究」：问题输入 → type=research 托管任务（进度在任务 tab，
  可恢复错误如搜索凭据缺失原样透传）；host 白名单增补 `tasks` 写路径
  （修复研究提交被代理 405 拦截的遗漏）
- 「总览」「正文」两个 tab 合并为一个「总览」：原生工具箱条 + 分段切换
  （总览 ⇄ 正文），单一 Studio iframe 经 hash 片段导航切换（不整页重载，
  编辑器状态保留）；tab 总数 11 → 10
- 总览 tab 原生工具箱条：导出 md/txt/epub（经代理二进制安全下载）、同步项目、
  导入章节（文件选择 → 预览切章计划/冲突 → 确认/强制覆盖）——补齐 Studio
  「工具与设置」抽屉在 dsh 侧最后一个无 UI 缺口；代理改二进制安全透传并放宽超时至 60s，
  写白名单增补 sync / import/preview / import
- conductor 落地（`conductor/`）：无人值守写章流水线——写章/评审/修订回炉全部
  走 OpenWrite 后台任务系统（phase 轮询、预算超时显式取消、recoverable 原生
  retry），回炉经 revision_from_review → regenerate → apply 修订闭环（含客户端
  锚点预过滤）；可选 --agent-guidance 用 dsh SDK bundled 会话综合改写指导。
  同步端点 /api/write、/api/review 因孤儿化服务端任务被弃用于编排路径
- 新增 --review-only（对成稿章节只跑评审门）；实测 ch_001~004 全流程，
  ch_003 修订回炉 0 → 35 分
- 根目录 `skills/` 移除：技能唯一来源是 `presets/*/skills/`（内容相同，根副本无任何引用）
- `scripts/verify.sh` / `dev.sh` 导出 `NO_PROXY`：系统代理指向本机时
  （HTTP_PROXY=127.0.0.1:*），探活与验证请求不再被代理劫持而全部误报失败
- DESIGN.md / README 与实现对齐：补 studio-panel 组件章节；「组合与启动」改为
  profile bundle 安装路径（`overlays/` patch 层方案已废弃）；技能章节改为预设自带 skills/
- studio-panel：新增「研究」tab（深度研究报告库，主从布局 + 全文渲染 + 运行环境就绪态）
  与「搜索」tab（项目资料检索：350ms 防抖、canonical scope 下拉、命中词高亮、
  加载/空态/服务端 warning 提示）；「图谱」tab 补齐连续性面——伏笔校验错误块与 ⚠ 角标、
  事实账本（truth 三文档渲染）、章节工作流列表；新增 search-harness 逻辑级测试
  （真实 bundle 组件 + DOM shim 驱动防抖→fetch→渲染流）
- openwrite-bridge 从 14 扩到 **62 个 `novel_*` 工具**，OpenWrite Studio 动作面全覆盖
  （修订闭环、任务中心、后台连写、章节运行、滚动大纲、叙事预测、风格/参考库/规则、
  深度研究、模型配置、项目生命周期等）；刻意不桥接 `/api/chat` 与 `/api/agent/*`，
  agent 会话层唯一归属 dsh
- 移除 `novel_chat_goethe`：不再回调 OpenWrite 内部 agent，草案生成由 dsh agent 自身完成
- goethe/dante 预设 persona 更新完整工具面；删章改走 `novel_chapter_delete` 服务端三重确认
- `subagent_goethe` 只读面补 `novel_asset_read`、`novel_continuity`
- studio-panel：新增「大纲」「资产」「任务」「图谱」原生视图 tab 与 `novel_review_chapter`
  评审报告卡；host 侧 `GET /studio-panel/api/*` 只读代理（透传状态码/错误体，
  写操作仍只走 agent 工具）。「资产」tab 含资料库（参考作品）分组；「图谱」tab 为
  伏笔分层看板 + 人物关系环形图（类型过滤、密度自适应）
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
