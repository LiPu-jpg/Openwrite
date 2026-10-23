# 连载写作与章组审计（Core 5.8.12）

本版本新增确定性体检和作者裁决，不调用模型给整组章节打分。已有作品无需补齐所有新字段才能读取；缺失项会出现在审计中。

## 章纲契约

章标题下可写：

```markdown
> 预估字数: 10000
> 字数预算: 10000
> 章节承诺: 未取得钥匙 -> 已取得钥匙
> 回收伏笔: hook_001, hook_003
> 章节功能: 推进, 代价
```

字段对应 `promise`、`payoff_of`、`word_budget`、`function`。预算与已有章级目标共用来源：同时给出时必须一致；写入预算也更新预估字数，正文目标通过原有 writing_targets 解析链读取。功能仅支持推进/揭示/关系/代价。空回收列表表示本章未声明回收，不等于元数据缺失。

`GET /api/outline/audit?group_id=sec_001`（也可用篇 ID `arc_001` 或 start/end 章 ID）返回字段缺失、计划/实际字数及偏差、功能分布与连续段、伏笔声明边与已确认回收、漂移账本。`declared_state_change` 仅验证 A -> B 形式；`promise_verified_in_prose=null` 明确表示没有验证正文是否实现承诺。伏笔连接是大纲声明的派生投影，`known` 表示 ID 是否存在；不会偷偷把伏笔 DAG 状态改成已收。正文缺失或多副本时不伪造实际字数。

## 共享写作资产

项目的作品根目录 `data/novels/<id>/` 下：

- `src/writing/assets.yaml`：术语、禁用项、最低出现次数、用法示例、重合阈值、具象名词词典、角色描写分组。
- `anchor/*.md`：范本池。逐章轮换一份最多 1,200 字的句法参照；提示禁止抄句。检测覆盖最多 100 个有效范本（每个不超过 1 MB）。
- `data/writing_usage/<ch>.yaml`：作者明确标记的本章已用组；不会把模型收到素材误记为实际采用。

```yaml
terms:
  - term: 灵钥
    min_occurrences: 1
    example: 他把灵钥藏回衣领。
  - term: 万能钥匙
    forbidden: true
    replacement: 灵钥
review_terms: true
overlap_threshold: 0.05
concrete_nouns: [钥匙, 衣领]
character_groups:
  林舟:
    - id: gesture
      text: 思考时捻一下衣角
```

Writer 和 Reviewer 共用词表；最低次数按整章衡量，禁止项输出行号和字符位置。Reviewer 的术语检查可用 `review_terms=false` 关闭。描写组每章轮换最多三组；身份、关系和当前状态仍保留。角色卡中的分组原文须与配置文本一致，才能从原描述中精确移除。

GET `/api/writing-assets` 返回资产及 revision。POST 同一路径保存 `{assets, expected_revision}`；`action=save_anchor` 使用 `{name,content,expected_revision}`；`action=mark_usage` 使用 `{chapter_id,groups:{角色:[组ID]}}`。保存采用原子替换和版本检查，冲突时刷新后重试。

## 分段生成和体检

目标不少于 6,000 字时默认分段，每段约 2,500 字，按 beats 分配，携带前段尾部 1,500 字。短章首次输出不足也接续已有草稿。拼接去掉重复标题、至少 12 字的边界重合和较长重复段落；不删除重复短对话。最多计划段数加三次续写，仍不足则保留草稿和长度警告；调用异常携带已有分段正文供恢复。调用预算沿用模型档案，usage 汇总所有段，`reasoning_tokens` 保留上游真实 0，未知不补 0。

`GET /api/manuscript/ch_001/metrics` 返回汉字、写作单位、段落、句长/段长均值与 P50/P90、闭合引号对白占比、术语问题、重合证据和已用组。具象名词是项目词典的非重叠命中/千字；未配置时为 null，不冒充语言学标注器。重合采用去标点的 12 字窗口，与范本及最近三章比较；位置为原文 Unicode 字符索引，附可显示的片段。写章后自动保存 `data/writing_diagnostics/<ch>.json`，Reviewer 可引用相同诊断。GET 实时重算以反映外部改写，不产生写操作。

## 漂移记账与裁决

POST `/api/arc-reconcile`：

1. `action=drift_entry`：`group_id=sec_001`、`chapter_id`、`kind=growth|escape|dilution|snowball`、`impact=local|section|arc`、`note`、`rewrite`、`expected_revision`。
2. `action=arc_reconcile`：`group_id`、`entry_ids`、`decision=absorb|recover|freeze`、`confirm=true`、`expected_revision`。

每节未解决的改写级漂移预算为两条。第三条记账后冻结该节，拒绝继续叠加和生成正文。记账/回改前冻结大纲和已有正文的不可变基线，位于 `data/arc_audit/baselines/`。

吸收必须提供当前 `outline_revision` 和真实的 `outline_updates:[{node_id,metadata}]`，每个吸收章均有更新；仅改账本状态不算追认。支持现有章级元数据修改，正文保持原文。`resume=true` 且未解决漂移已回到预算内才解冻。回收必须给出 `plan`、较后的 `target_chapter_id`，记录为 recovery_planned，仍计入未解决预算；Writer 在目标章收到该计划，不宣称已经回收。冻结保留基线并停止写入，供重规划。

大纲/账本跨文件提交先写 `transaction.json`。中断时读取会明确拒绝伪装完整状态；作者用 `action=recover_transaction, confirm=true` 恢复同一批准事务。若文件已被后续修改则保留日志，要求人工对账，不覆盖新改动。

## 验收、任务、横评与导出

- POST `/api/manuscript/accept` 外部验收支持 `no_model=true`；已有操作可用 `/api/manuscript/reconcile` 的 `mode=fast`。只承认当前正文 revision，派生域保留 stale、`facts_pending=true`。之后仍可完整 reconcile；不能把快验收当作事实已更新。
- `/api/status` 返回 instance_id/project_path/port，响应头也提供实例与 URI 编码根目录。请求根不一致返回 409 和允许根目录；客户端也校验连接根。
- 任务有 last_activity_at、last_heartbeat_at、model_call_elapsed_ms；心跳每五秒仅证明 worker 活着，不增加完成数、不伪造模型活动。流式调用同时受 idle timeout 和有限总期限约束；`OW_LLM_TOTAL_TIMEOUT` 可覆盖总期限（默认 max(300, 4×客户端 timeout)，单位秒）。超时为 PROVIDER_TIMEOUT，保留已有输出。
- 只读查询不因写任务持锁而整体拒绝；写操作继续互斥。
- 已写章节横评须显式 `allow_historical=true`，标签为 current_canon_rewrite。其上下文可能含当前正典，不是可验证的章前基线。产物放在隔离运行目录，不写正式正文/事实账本。
- 导出 `purpose=personal_archive` 将质量门禁降为警告，结构性错误仍拦截；回执位于 `data/exports/archive_*.json`，保留预检结果、状态和输出 hash。不能据此声称达到交付标准。导出已完成但回执收尾失败时明确返回 export_completed=true。
