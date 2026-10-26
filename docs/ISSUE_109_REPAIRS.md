# Core 5.8.14：连载报告逐项处理

对应 #109（B-01–B-17、S-01–S-15），并包含 #114 的 OpenCode Go 请求头适配。
这是源码修复；插件是否发布，以 npm 和 GitHub Release 为准。

| 条目 | 处理与边界 |
| --- | --- |
| B-01 / S-01 | style 默认份额 12%，可用 `context_style_share` 配置；在总体预算内优先保留最多 4000 字符的作者风格，最多占可压缩预算一半。各文件按实际长度分配。移除第二层 600/700 字符限额，仍保留整体提示词上限；返回 `style_profile_truncated`，不隐藏截断。 |
| B-02 / S-10 | 补救续写按剩余字数重新计算分段数量，段目标涵盖全部剩余字数时才要求章末钩子；节拍按已完成字数推进。支持关闭分段补救。 |
| B-03 / S-11 | 长段落相似度去重，默认 0.96，可设 0.9–1.0；短对话与数字不同的段落保留。不声称能够识别任意语义复述。 |
| B-04 / S-02 | 网络中断、输出截断至多重试两次，退避 1/2 秒；每次重试前检查取消。不重试认证/格式等错误；已知用量合并，缺失费用保持未知。 |
| B-05 / S-03 | coverage 小于 1 时 quality_score 与旧 score 均为 null，状态仍为 partial / inconclusive；CLI 与章节摘要显示未评分。未改变已完成维度的评审标准。 |
| B-06 / S-15 | `PROJECT_BUSY` 返回可恢复状态、建议 30 秒重试与重新读取 revision 的提示。不假称能预测长任务结束时间，也不放宽并发写锁。 |
| B-07 / S-04 | 大纲审计把无法解析的 payoff_of 列为 `UNKNOWN_PAYOFF_REFERENCE` 错误，保留原始引用与章节。 |
| B-08 / S-05 | 大纲树 `parse_report` 返回逐项元数据的 node_id、行、原键值、是否识别、识别数量和忽略明细。识别字段数与章节完整性必检项数是不同指标，不再靠固定数字推断。 |
| B-09 / S-12 | world/terminology.md 与 world/timeline.md 加入 writer 输入；完整预览附文档投影清单，原 manifest 继续提供来源、预算与排除项。 |
| B-10 / S-06 | related 同时支持目标到说明的映射及标准数组；默认按目标合并，raw_text 更新也保留关系，`related_mode: replace` 显式替换/清空。修正 TOML 根字段落入最后一个关系表的问题。 |
| B-11 / S-07 | 范围编辑提供 `end_inclusive: false` 保留结束锚点（例如下一节标题）；默认 true 保持原接口兼容。 |
| B-12 / S-14 | retry、apply、undo 消费的凭据保留校验后的墓碑，可 reject 清理；消费凭据不能再次写入。相同内容 retry 不会误删新预览。 |
| B-13 | 逐字锚点在源码中没有行首语义；新增行中 `> ` 的范围定位及 old_text 实际写入回归，均通过。未复现为独立缺陷，不引入模糊替换来掩盖不匹配。 |
| B-14 / S-08 | resume / acknowledge / abandon 同时接受 operation_id 或可解析到现有操作的 chapter_id，缺少目标时给统一参数提示。external 创建操作仍需 chapter_id；baseline 是整书建基线。保留已有接口与错误码。 |
| B-15 / S-09 | 未完成接纳返回 completed:false、status:partial、blocking 与下一步 resume 参数；no_model 只接纳正文，明确不解除事实门禁。 |
| B-16 | 事实未更新的门禁错误明确说明尚未调用模型，提供 external / resume、operation_id 与受影响章节，保留稳定错误码。 |
| B-17 | `GET /api/context?chapter=ch_001&include_agent_payload=true` 提供完整 canonical writer payload、初始提示词及文档投影清单，不调用模型。后续生成 guidance、分段、重试和传输预算会改变具体请求，预览不冒充历史服务商逐次请求日志。 |
| S-13 | 写章结果 `context_summary` 返回已报告用量、压缩级别、style 实际字符数、客户端模型调用次数与二次截断标记；未报告值为 null。 |

配置示例（`novel_config.yaml`）：

```yaml
context_style_share: 0.12
writing_options:
  segmented_write: false
  segment_similarity_threshold: 0.96
```

`segmented_write: false` 同时关闭长章自动分段与首次不足的续写补救，长度修复仍按既有有界流程处理。
相似度去重属于保守文本比较，无法替代人工判断故事是否从头复述。

验证包括新增回归、既有预算/受保护约束、完整审稿与不完整审稿、资产、编辑凭据、接纳门禁、
模型请求路由及全量 pytest。自动测试使用隔离目录和 ProjectRegistry，不使用作者模型凭据。
