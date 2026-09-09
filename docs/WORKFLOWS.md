# 创作流程与工作区

[返回首页](../README.md) · [安装指南](INSTALL.md)

## Workspace 模型

dsh Workspace 是唯一的工作区身份：agent 工具调用按会话的不可变 `cwd`、浏览器
面板按当前 session 绑定的 Workspace，都把请求路由到该 Workspace canonical root
对应的独立 OpenWrite 应用实例（任务、评审、搜索、DAG、benchmark、DoG 产物全部
按 root 隔离）。切换 dsh Workspace 即切换全部能力；OpenWrite 的 legacy 最近项目
列表只用于直接 CLI（`openwrite studio --project ...`）兼容，不能改变 dsh 当前
上下文。在 dsh 中新建作品的路径是：目录选择/创建 → `workspace.create` → 在该
绝对路径初始化 OpenWrite（同时创建该作品目录的独立 Git 仓库）→ 连接 Workspace。
也可以先按 [安装指南](INSTALL.md) 使用 `openwrite init --project` 初始化作品，
再把该目录加入 dsh Workspace。契约细节见 [Workspace 契约](WORKSPACE_CONTEXT_CONTRACT.md)。

## 工作方式

作者入口是斜杠命令（与口语同义），接到已有 `novel_*`，不另建进度/伏笔/设定/记忆存储：
`/progress` 看进度、`/write-next` 写下一章、`/review-chapter` 审这一章、`/revise-span` 改这段、
`/foreshadow` 查伏笔、`/canon` 查设定、`/learn` 写法记忆、`/export-book` 导出。
默认顺序：看进度 → 写下一章 → 审这一章 → 必要时改这段。宿主 `/export` 是会话日志，不是成稿。

1. 在 **OpenWrite 创作** 会话里先收敛灵感、人物、世界观与大纲（所有写入经 OpenWrite
   修订门控，重要改动先出 diff 再确认），再在同一会话中写正文。
   正文和正典使用 `novel_document_change_plan`；大纲、资产、创作重点、伏笔和写作目标
   使用 `novel_structured_change_plan`。两者都由服务端保存不可变预览、在确认时重验源
   revision，并返回只对已确认结果有效的安全撤销 token。
   正文区按 canonical reading order 切章和连续审读，计划未写章节保留在大纲中但不会被
   当作可读正文；搜索结果只有在 document ID 与完整 revision 都仍匹配时才开放改单行。
2. 写正文时执行 `novel_context_preview` 预检上下文包 →
   `novel_write_chapter` 写章 → `novel_review_chapter` 六域累加评审。
   每次评审同时生成 `data/novels/{id}/data/dog/reviews/{chapter}/dog-graph.json`；
   通过 `novel_task_create(type=chapter_review)` 启动的后台评审，也会在
   `novel_task_get` 读到完成态时生成同样的图；
   图的顶层是上下文完整性、六个质量域、硬门禁和确定性聚合，六域下可展开原 37 项，
   查询 criterion、证据、问题、覆盖率和继承状态。DoG 只查询已生成的 artifact，
   不重新调用模型评审。
   写章、评审和 `novel_revision_*` 操作还会维护
   `data/novels/{id}/data/dog/deliveries/{chapter}/dog-graph.json`：它把正文、
   `writing → review → revision → application → rereview → closure` 六阶段串成章节交付总图；
   正文 SHA 改变后旧评审立即 stale，修订应用后必须复评通过才算交付。
   DoG 的 `workspaceRoot` 需要指向 OpenWrite 项目根目录。
   资产不齐时 Agent 会回到规划阶段补齐，不需要切换会话。
   拆书导入则先执行 `conductor/smart_import.py`，对输出的
   `data/novels/{id}/data/dog/imports/{IMPORT_ID}/dog-graph.json` 做 DoG 验收；
   验收通过后继续在同一 Agent 中建立大纲、角色、世界观、进度和正典事件，最后重新评审。
3. 无人值守批量生产用 **conductor**（需 Studio 在跑）：
   `cd conductor && .venv/bin/python pipeline.py --chapters next --limit 3`——
   连续写章 → 六域评审 → 低质量分/低覆盖率/含 blocker 自动经修订闭环回炉；
   `--review-only` / `--rework` / `--agent-guidance` 见模块 docstring 与 DESIGN.md §6。
4. 在「资料 → 图谱」查看可缩放、筛选和展开的评审 DAG/交付 DAG；节点详情显示
   质量分、覆盖率、门禁、证据、模型、token 和耗时。
5. 在「任务 → 模型测试」选择「章节写作」或「大纲设计」，再选择多个生成模型和独立评审模型。
   章节可用 `next` 或指定可测试的计划章节；大纲可接续已有规划，或指定起始章与设计章数，
   页面会显示包含首尾章的范围。任务自动匹配 DAG 和评审范围，结果可展开节点状态及证据；
   完整规则见 [模型测试说明](BENCHMARK_TASKS.md)。每个候选使用独立作品沙箱；章节的
   「真实写作框架」进入 OpenWrite 公共写章、状态结算、正文提交、Chapter Run V2 与正式评审流程；「裸写诊断」
   只用于排查模型原始输出。测试固定同一上下文 hash，结果隔离写入
   `data/novels/{id}/data/benchmarks/`，不会改变全局路由或正式正文。结果页分别展示输入、
   输出、推理 token 和服务商实际报告的费用；明确 `$0` 与未知费用分开，`/ 1M tokens`
   仅表示本次调用的综合有效价。
6. 在「创作」正文编辑器中，选中一段后可添加**作者选区批注**（不写入正文）。先保存当前草稿，或由工作台保存后再核对选区；重复句子不会静默绑到第一处。批注有一组固定颜色，旧记录没有颜色时显示琥珀。列表在「修订」中，可定位或标为已解决；找不到或出现多处匹配时显示「已脱离原文／需重新定位」。颜色只画在编辑器覆盖层，不会把 `span`/`style` 写进 Markdown。导出和字数仍不含这些批注。
   同一编辑器可用**插入标记**写入两种内部语法：`//**人物[维度]：旧 -> 新**` 与 `//**A~>B:关系**`。人物来自当前作品，同名或别名必须选明确身份。打开表单不会创建资产、改关系、写盘或调用模型。有效标记不计入可读字数，也不会进入默认导出；无效或代码围栏中的文本保持原样。
7. 在「创作」中精修稿件并处理审稿/修订，在「资料」维护正典，在「任务 → 导入与导出」
   处理旧稿、项目迁移和成稿。作者旧稿先冻结源文件，再确认可编辑的分章预览；中断后从
   已完成阶段继续，发布前不会进入正式正文。导出先选择“完整备份”或“交付成品”：备份会
   显示接纳/评审警告但仍可下载，交付会把结构、元数据、正文事实和评审问题作为阻断项。
   完整作品档案列出纳入、排除、缺失文件和校验和；恢复前必须选择新路径，检查 ID/引用
   重写与冲突，旧任务只归档、不自动续跑。在「资料 → 大纲 → 原生场景结构」可先只读
   预览旧正文分场，再显式确认迁移；场景用稳定 ID 分别维护阅读顺序与故事时间、人物/地点/
   事件引用，并以 scene、源章和目标章 revision 保护元数据和跨章移动。过期结构可重新预览
   锚定，交付会阻断 stale/ambiguous，备份始终回退到完整正文。Studio 只作为头部溢出菜单
   中的高级维护出口。
