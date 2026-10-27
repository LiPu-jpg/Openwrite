# 正文编辑与审稿选区补修

候选 0.2.28 / Core 5.8.20，尚未发布。原先 22 项检查没有覆盖编辑器延迟回调、审稿选区上限与真实 Markdown 序列化；本轮三项均先复现，再修复并增加行为回归。

| 缺口 | 修复后行为 | 验证 |
| --- | --- | --- |
| 输入后立即保存或离开，最后一段未进入延迟回调 | 首次 DOM 输入立即启用保存；保存、离开和相关操作前同步收集最新正文。切章/切工作区时，只保存到原正文的恢复草稿；明确放弃后不复活旧稿。 | 9 项真实 CreationView/VditorBody 生命周期测试，含首次输入、未 blur 的保存、切工作区/章节、加载失败后重试保护、明确丢弃、未编辑对照。 |
| “按审稿改这段”扩大到选区外 | 按实际锚点优先选择问题；传递完整原文选区，服务端在生成前验证准确片段、版本和问题范围。问题证据可与选区部分重叠，生成范围始终限定为作者选区。 | 重复句和部分选区，经同步/后台真实 HTTP；重新生成/应用保留上限，选区外问题及不匹配拒绝且零调用。 |
| Vditor 自动补换行/调整空行后拒绝未编辑的正文 | 加载时记录原文与实际序列化结果，仅对这一对文本支持末尾换行、标题空行和连续换行的范围映射。其余字符、NBSP、后续作者改动、版本变化和不明确边界仍拒绝。 | 真实候选包 Vditor、独立 Studio 编辑器包装、Core 与原生面板映射模块共 9 组浏览器场景；额外 3 项独立 Studio 实际绑定代码测试。 |

正文不会为了通过映射而被静默规范化。批注提示、定位及选区请求使用同一份源范围映射。常规“按所选问题修订”入口不提供 selection 时仍保留原语义；选区入口不能仅凭 original_text 猜重复句位置。

`novel_revision_create_from_review` 新增可选 `selection: {start,end,original_text}`，start/end 是保存原文的 Unicode 码点下标，保留原始 CR/LF。传递当前 `expected_document_revision` 与 `expected_review_revision`。旧界面只带 original_text 而没有明确选区时返回 INVALID_SELECTION，请刷新界面重新选择。

本地 Core 1550 passed / 32 skipped，真实 HTTP 14 passed，界面 336 passed，managed 34 passed，完整插件检查通过。Core wheel 的 499 个运行时源文件逐字节一致，163 个应打包 Python 文件无遗漏。原生安装矩阵额外对同一候选 tarball 中的真实 Vditor/独立编辑器和两端映射器运行 9 组场景，结果写入每份原生报告的 editorSerialization 字段。

测试不调用付费模型，不写作者作品或真实 profile。最终跨平台回执见[发布验收](RELEASE_ACCEPTANCE.md)。#123 的宿主正式发布和 Android/Termux 真机验收仍保留，本次不发布。
