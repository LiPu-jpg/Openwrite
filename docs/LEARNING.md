# OpenWrite / dsh-novel 学习与完善进度

日期：2026-09-06。本文件是 S1–S6 之后的学习文档：对照七个外部项目，记录计划做的、正在做的、做完的。
实施状态以本文件与 [GOAL.md](../GOAL.md) 为准；对话历史不能覆盖仓库证据。

## 范围

- OpenWrite 是领域后端；dsh-novel 是 DeepSeek Harness 插件与原生工作台。不另建 RAG / lorebook / 第二套正文存储。
- **示例书不在目标内**（non-goal）。不要为演示做内置样书、市场一键安装包、KDP/封面/有声书。
- S1–S6 已验收，见 [GOAL.md](../GOAL.md) 与 [IMPROVEMENT_PLAN.md](IMPROVEMENT_PLAN.md)。本轮不重做保存队列、草稿恢复、接纳 SHA、导入归档、场景双序。

## 对照项目（固定 URL）

| 项目 | URL |
|---|---|
| Casting-Workflow | https://github.com/dama-cyber/Casting-Workflow |
| ainovel-cli | https://github.com/voocel/ainovel-cli |
| Scriverse | https://github.com/musnows/Scriverse |
| OpenFic | https://github.com/syrizelink/OpenFic |
| CharacterArc | https://github.com/uu201/character-arc |
| MuMuAINovel | https://github.com/xiamuceer-j/MuMuAINovel |
| InkOS | https://github.com/Narcooo/inkos |

源码对照细节见 [TARGETED_NOVEL_PROJECT_REVIEW.md](TARGETED_NOVEL_PROJECT_REVIEW.md)。

## 计划做的

未在本轮验收范围内、仍值得后续做的项。完成一项就移到「做完的」。

| 项 | 学自 | 说明 |
|---|---|---|
| 示例书 | — | **明确排除。** 不要做。 |

## 正在做的

写作冲刺统计本轮已完成。计划做的只剩示例书（排除）。不开始示例书。

## 做完的

### 基线（S1–S6，2026-09-05）

全部 **done**。证据在 [GOAL.md](../GOAL.md)。

| 阶段 | 状态 | 对应外部启发（已吸收，不再重做） |
|---|---|---|
| S1.1 正文保存状态机 | done | Scriverse 请求快照 / 排队 |
| S1.2 本地草稿恢复 | done | CharacterArc 草稿恢复 |
| S1.3 统一上下文计量 | done | InkOS 预算与估算口径 |
| S2 历史、修订、上下文检查、横评/研究页 | done | OpenFic 变更审阅；Scriverse before/after |
| S3 正文接纳与事实一致性 | done | ainovel-cli accepted SHA 与派生物失效 |
| S4 可恢复导入与完整迁移 | done | ainovel-cli 导入状态机；CharacterArc 项目档案 |
| S5 原生作者工作台 | done | 连续审读、搜索回跳、跨卷排序、工作简报 |
| S6 场景与双序结构 | done | 阅读顺序与故事时间分开 |

### 本轮（2026-09-06）

| 项 | 状态 | 证据 |
|---|---|---|
| 学习文档（三桶 + 七 URL + S1–S6 done + 示例书排除） | done | [LEARNING.md](LEARNING.md)；示例书写在范围里为 non-goal |
| write / review / workflow 技能对齐 `novel_*` | done | `presets/openwrite/skills/{novel-creator,novel-reviewer,workflow-manager}`；`npm run test:preset` 拒绝旧 Python 命令名并要求 `novel_outline_read` / `novel_write_chapter` / `novel_review_chapter` |
| 本章 due / overdue / to-plant 伏笔行动清单 | done | work-brief 的 `must_resolve`/`overdue`/`to_plant` 映射到创作检查器可打开的行动；组件测试 146 passed，含三项行动与展开详情 |
| 编辑器选区润色（扩写/缩写/去 AI 味/按审稿改这段） | done | 选区动作走 `/revisions/selection`（expand/compress/naturalize）与 `/revisions/from-review`；hunk 应用走 `/revisions/{id}/apply` + `selected_hunk_ids`，不 PUT 正文；源 revision 不一致时拒绝覆盖 |
| 正文提及高亮与资料卡 | done | 创作页用现有 `/assets` 的人物/地点名与别名做最长匹配；点击在创作视图打开只读资料卡；切章/切 Workspace 清卡；不进资料库、不 POST 资产更新 |
| 斜杠命令 / 7 个作者入口 | done | `presets/openwrite/skills/{progress,write-next,review-chapter,revise-span,foreshadow,canon,export-book}` 接到 `novel_*`；persona 默认工作流为看进度 → 写下一章 → 审这一章 → 改这段；其余技能 `user-invocable: false`；`npm run test:preset` 断言入口存在并拒绝旧 Python 命令名 |
| 项目级 `/learn` 写法记忆 | done | `presets/openwrite/skills/learn`：风格/成功钩子/作者偏好走 `novel_source_action` 与 `novel_structured_change_plan`，随 Workspace 资产走；无 cwd 时现有工具返回 `WORKSPACE_CONTEXT_MISSING`；`npm run test:preset` 24 skills / 8 author entries |
| 网文可选审稿维（钩子/黄金三章/追读力） | done | `form: web_novel` 时六域上附加 `max=0` 的钩子/黄金三章/追读力；37 项与质量分不变；黄金三章仅第 1–3 章；非网文项目不附加 |
| 每 50 章规划窗口 | done | `novel_rolling_plan_action` 默认/上限 50 章；`accepted_window` 只含已接纳正文，`planned_window` 只含未接纳大纲计划；create 不改正文/事实 |
| 写作冲刺统计 | done | 创作动态页从工作简报字数目标 + 已知 `writing_units_delta` 推导新增/删减/净增；修订净增只来自 `revision_applied`；无 delta 的事件不猜来源；不另建冲刺账本 |
