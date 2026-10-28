# #146：审稿证据回填与状态批注隔离

面向 0.2.29 候选 / Core 5.8.22，尚未发布。
报告：[OpenWrite Core 5.8.20 B-28 / B-29](https://github.com/LiPu-jpg/Openwrite/issues/146)。

## B-28：同条判据已有引用却被判未定论

审稿模型有时把有效的原文引用放进 criterion 自己的 `issues[].evidence`，
却漏填 `criterion.evidence`。旧实现只检查后者，正分会被清零并将该项判为 `inconclusive`。

修复先在送审正文中验证引用。若 criterion 没有有效的直接证据，则从**同一 criterion** 的有效问题
回填引用；保留模型给出的 `evaluated` 状态和分值上限，并在返回值标记
`evidence_source: "criterion_issues"`。直接证据若误填为一个字符串，按一整条引用处理，
避免逐字符迭代后把碰巧存在的单字当成原文证据。

同时将 criterion 内的问题纳入完整问题列表，包含有原文依据的 `critical`。
缺少 `dimension` 时沿用所属 criterion 的第一个 legacy check 标签；显式越出该 criterion 的标签、
无效严重度和无法在正文中定位的引用不参与回填。

真正缺少引用、模型明确给出 `inconclusive`、硬门禁未定论或严重问题，仍不能通过交付。
没有放宽正典门禁、评分完整性要求或最小覆盖率策略。修复的目标是使已有证据进入正确字段，
让正常的完整评审能获得正确状态；真实未完成的检查仍须补齐。

报告中提到的部分审稿，当前实现已有 `scope_status: partial`、`scope_quality_score`、
`scope_passed` 与 `unreviewed_dimensions`；整章 `delivery_status` 保持 `inconclusive`，
`quality_score` 为 null。新增回归再次覆盖仅请求 coherence 的情况，避免误报整章通过。

## B-29：机器批注进入送审正文

审稿入口在术语检查、规则检查、AI 痕迹分析、模型评审和正文统计前调用
`strip_character_state_annotations`。各域、硬门禁及旧分批审稿入口也执行同一处理，
确保上下文检查器等直接调用路径一致。

清理范围沿用现有阅读/导出契约：有效的角色状态和关系注册从读者正文移除；
正常代码示例与不符合批注契约的作者文本保留。原稿和状态批注文件都不会被重写。
已有审稿记录保持原样，需要用新版本重新审稿才能得到修复后的结果。

## 回归方法

`tests/test_issue146_review_evidence.py` 覆盖：

- 三项 criterion 漏填直接证据、同条问题有原文时，恢复到完整 80 分并允许交付。
- 缺失/伪造引用、显式未定论、硬门禁未定论、嵌套严重问题继续阻断。
- 不借用相邻判据的引用、不接受无效证据类型或越界标签。
- 仅审 coherence 明确保持部分审稿。
- 所有七次正常评审请求，以及直接域/门禁/旧版分批请求，都不包含机器批注。
- 真实 `execute_review_chapter` 管线将正确结果存入 ReviewStore，原稿保持不变。

相同测试在修复前的冻结源码上为 **8 failed / 5 passed**，修复后全部通过。
所有模型响应均由测试夹具提供，没有调用真实或付费模型，也不读写作者作品和真实项目登记。

本地完整 Core 回归：1564 passed / 32 existing skipped；定向组合回归 52 passed。
Core wheel 从冻结 Git 提交归档构建，打包后逐文件核对运行时源码。
