# 小说工具参考

本候选共 95 个 novel_* 工具。由 tools.ts 的注册定义生成；说明与参数保留实际 schema 原文，避免手册与接口漂移。用浏览器或编辑器搜索工具名即可定位。

## 先选入口

- 看当前作品：`novel_status`；查文件：`novel_doc_read`；看本章输入：`novel_context_preview`。上下文来源与预算见 [上下文槽位](CONTEXT_SLOTS.md)。
- 修改大纲/设定/创作罗盘：先用 `novel_structured_change_plan` 预览并核对；只有作者已明确授权的精确变更才使用兼容的直接写入工具，如 `novel_focus`。
- 正文确认：`novel_manuscript_acceptance {}` 只读查 operation_id，核对影响后用 `novel_manuscript_acceptance_reconcile {"action":"acknowledge","operation_id":"实际返回值","confirm":true}` 确认；这不会补跑结算或审稿。
- 结算缺失：核对目标章节后使用 `novel_settle_backfill {"chapter_ids":["ch_001"],"only_missing":true}`，再查返回任务；会调用模型并写入记忆/运行态资料，不重写正文。不要把 canon 未定论一律解释为缺结算。
- 模型与嵌入：Chat 与 Embedding 档案独立；配置不等于连接成功。`novel_model_test` / `novel_model_embedding_test` 会实际请求提供方，可能计费。
- 写章返回 task_id 后用 `novel_task_get` 查询；取消用 `novel_task_cancel`。超时/网络错误后先查任务与运行，避免重复提交。

## 参数和错误

必填项是 schema 的静态必填；action 描述里的条件必填也要满足。JSON 参数传对象或数组，不要传 Markdown 代码块。章节 ID 使用 ch_数字。文档写入先读当前 version，大纲变更使用当前 revision；冲突时重读并重新预览。

参数错误会在请求前或服务端拒绝并说明原因；服务端错误提供 code/message/status/details/request_id。这里只读/会操作按执行路径保守分类：POST 也可能是预览或查询，GET 后的导出/审稿辅助操作也可能落盘；请同时看 action 和下面的完整说明。

## 工具索引

| 工具 | 影响 | 必填参数 |
| --- | --- | --- |
| [novel_arc_reconcile](#novel_arc_reconcile) | 会提交操作或保存文件；具体取决于 action/参数 | `data` |
| [novel_asset_create](#novel_asset_create) | 会提交操作或保存文件；具体取决于 action/参数 | `kind`, `id` |
| [novel_asset_read](#novel_asset_read) | 只读查询（可更新检索缓存） | `kind`, `id` |
| [novel_asset_update](#novel_asset_update) | 会提交操作或保存文件；具体取决于 action/参数 | `kind`, `id`, `revision` |
| [novel_assets_list](#novel_assets_list) | 只读查询（可更新检索缓存） | 无 |
| [novel_assets_package_export](#novel_assets_package_export) | 会提交操作或保存文件；具体取决于 action/参数 | 无 |
| [novel_assets_package_import](#novel_assets_package_import) | 会提交操作或保存文件；具体取决于 action/参数 | `upload_id` |
| [novel_assets_package_preview](#novel_assets_package_preview) | 会提交操作或保存文件；具体取决于 action/参数 | `package_base64` |
| [novel_chapter_delete](#novel_chapter_delete) | 会提交操作或保存文件；具体取决于 action/参数 | `path`, `confirm`, `version` |
| [novel_chapter_delete_batch](#novel_chapter_delete_batch) | 会提交操作或保存文件；具体取决于 action/参数 | `keep_through`, `confirm`, `version` |
| [novel_chapter_run_action](#novel_chapter_run_action) | 会提交操作或保存文件；具体取决于 action/参数 | `action` |
| [novel_chapter_scenes](#novel_chapter_scenes) | 只读查询（可更新检索缓存） | `chapter_id` |
| [novel_chapter_work](#novel_chapter_work) | 只读查询（可更新检索缓存） | `chapter_id` |
| [novel_context_preview](#novel_context_preview) | 只读查询（可更新检索缓存） | 无 |
| [novel_continuity](#novel_continuity) | 只读查询（可更新检索缓存） | 无 |
| [novel_diagnostics](#novel_diagnostics) | 会提交操作或保存文件；具体取决于 action/参数 | 无 |
| [novel_doc_create](#novel_doc_create) | 会提交操作或保存文件；具体取决于 action/参数 | `kind`, `name` |
| [novel_doc_read](#novel_doc_read) | 只读查询（可更新检索缓存） | `path` |
| [novel_doc_write](#novel_doc_write) | 会提交操作或保存文件；具体取决于 action/参数 | `path`, `content` |
| [novel_document_change_plan](#novel_document_change_plan) | 会提交操作或保存文件；具体取决于 action/参数 | `action` |
| [novel_drift_entry](#novel_drift_entry) | 会提交操作或保存文件；具体取决于 action/参数 | `group_id`, `chapter_id`, `kind`, `impact`, `note`, `expected_revision` |
| [novel_embedding_profile_delete](#novel_embedding_profile_delete) | 会提交操作或保存文件；具体取决于 action/参数 | `profile_id` |
| [novel_embedding_profile_save](#novel_embedding_profile_save) | 会提交操作或保存文件；具体取决于 action/参数 | `profile` |
| [novel_embedding_profile_select](#novel_embedding_profile_select) | 会提交操作或保存文件；具体取决于 action/参数 | `profile_id` |
| [novel_embedding_profiles](#novel_embedding_profiles) | 只读查询（可更新检索缓存） | 无 |
| [novel_export](#novel_export) | 会提交操作或保存文件；具体取决于 action/参数 | 无 |
| [novel_export_preflight](#novel_export_preflight) | 只读查询（可更新检索缓存） | 无 |
| [novel_focus](#novel_focus) | 会提交操作或保存文件；具体取决于 action/参数 | `goal` |
| [novel_foreshadowing](#novel_foreshadowing) | 会提交操作或保存文件；具体取决于 action/参数 | `action`, `node_id` |
| [novel_import](#novel_import) | 会提交操作或保存文件；具体取决于 action/参数 | `content` |
| [novel_import_preview](#novel_import_preview) | 会提交操作或保存文件；具体取决于 action/参数 | `content` |
| [novel_manuscript_acceptance](#novel_manuscript_acceptance) | 只读查询（可更新检索缓存） | 无 |
| [novel_manuscript_acceptance_reconcile](#novel_manuscript_acceptance_reconcile) | 会提交操作或保存文件；具体取决于 action/参数 | `action` |
| [novel_manuscript_edit_action](#novel_manuscript_edit_action) | 会提交操作或保存文件；具体取决于 action/参数 | `action` |
| [novel_manuscript_import_action](#novel_manuscript_import_action) | 会提交操作或保存文件；具体取决于 action/参数 | `action` |
| [novel_manuscript_metrics](#novel_manuscript_metrics) | 只读查询（可更新检索缓存） | `chapter_id` |
| [novel_model_benchmark](#novel_model_benchmark) | 会提交操作或保存文件；具体取决于 action/参数 | `action` |
| [novel_model_configure](#novel_model_configure) | 会提交操作或保存文件；具体取决于 action/参数 | `model` |
| [novel_model_embedding_test](#novel_model_embedding_test) | 会提交操作或保存文件；具体取决于 action/参数 | 无 |
| [novel_model_profile_delete](#novel_model_profile_delete) | 会提交操作或保存文件；具体取决于 action/参数 | `profile_id` |
| [novel_model_profile_save](#novel_model_profile_save) | 会提交操作或保存文件；具体取决于 action/参数 | `profile` |
| [novel_model_profiles](#novel_model_profiles) | 只读查询（可更新检索缓存） | 无 |
| [novel_model_routes_save](#novel_model_routes_save) | 会提交操作或保存文件；具体取决于 action/参数 | `routes` |
| [novel_model_test](#novel_model_test) | 会提交操作或保存文件；具体取决于 action/参数 | 无 |
| [novel_multi_write](#novel_multi_write) | 会提交操作或保存文件；具体取决于 action/参数 | 无 |
| [novel_narrative_forecast_action](#novel_narrative_forecast_action) | 会提交操作或保存文件；具体取决于 action/参数 | `action` |
| [novel_outline_audit](#novel_outline_audit) | 只读查询（可更新检索缓存） | 无 |
| [novel_outline_edit](#novel_outline_edit) | 会提交操作或保存文件；具体取决于 action/参数 | `operation`, `revision` |
| [novel_outline_read](#novel_outline_read) | 只读查询（可更新检索缓存） | 无 |
| [novel_project_archive_action](#novel_project_archive_action) | 会提交操作或保存文件；具体取决于 action/参数 | `action` |
| [novel_project_archive_download](#novel_project_archive_download) | 会提交操作或保存文件；具体取决于 action/参数 | `archive_id` |
| [novel_project_delete](#novel_project_delete) | 会提交操作或保存文件；具体取决于 action/参数 | `project_path`, `confirm` |
| [novel_project_init](#novel_project_init) | 会提交操作或保存文件；具体取决于 action/参数 | `novel_id`, `title` |
| [novel_project_open](#novel_project_open) | 会提交操作或保存文件；具体取决于 action/参数 | `project_path` |
| [novel_reading_order](#novel_reading_order) | 只读查询（可更新检索缓存） | 无 |
| [novel_reading_order_move](#novel_reading_order_move) | 会提交操作或保存文件；具体取决于 action/参数 | `document_id`, `target_volume_id`, `target_index`, `expected_revision` |
| [novel_reading_packet](#novel_reading_packet) | 只读查询（可更新检索缓存） | `document_id` |
| [novel_reference_library_action](#novel_reference_library_action) | 会提交操作或保存文件；具体取决于 action/参数 | `action` |
| [novel_research_report](#novel_research_report) | 只读查询（可更新检索缓存） | `report_id` |
| [novel_research_settings_save](#novel_research_settings_save) | 会提交操作或保存文件；具体取决于 action/参数 | `settings` |
| [novel_research_status](#novel_research_status) | 只读查询（可更新检索缓存） | 无 |
| [novel_review_chapter](#novel_review_chapter) | 会提交操作或保存文件；具体取决于 action/参数 | 无 |
| [novel_review_framework](#novel_review_framework) | 只读查询（可更新检索缓存） | 无 |
| [novel_revision_apply](#novel_revision_apply) | 会提交操作或保存文件；具体取决于 action/参数 | `proposal_id` |
| [novel_revision_create_from_review](#novel_revision_create_from_review) | 会提交操作或保存文件；具体取决于 action/参数 | `chapter_id`, `issue_ids` |
| [novel_revision_create_selection](#novel_revision_create_selection) | 会提交操作或保存文件；具体取决于 action/参数 | `chapter_id`, `start`, `end` |
| [novel_revision_get](#novel_revision_get) | 只读查询（可更新检索缓存） | `proposal_id` |
| [novel_revision_regenerate](#novel_revision_regenerate) | 会提交操作或保存文件；具体取决于 action/参数 | `proposal_id` |
| [novel_revision_reject](#novel_revision_reject) | 会提交操作或保存文件；具体取决于 action/参数 | `proposal_id` |
| [novel_revisions_list](#novel_revisions_list) | 只读查询（可更新检索缓存） | 无 |
| [novel_rolling_plan_action](#novel_rolling_plan_action) | 会提交操作或保存文件；具体取决于 action/参数 | `action` |
| [novel_rule_action](#novel_rule_action) | 会提交操作或保存文件；具体取决于 action/参数 | `action` |
| [novel_runtime_skill_action](#novel_runtime_skill_action) | 会提交操作或保存文件；具体取决于 action/参数 | `action` |
| [novel_scene_migration_apply](#novel_scene_migration_apply) | 会提交操作或保存文件；具体取决于 action/参数 | `expected_preview_revision`, `confirm` |
| [novel_scene_migration_preview](#novel_scene_migration_preview) | 只读查询（可更新检索缓存） | 无 |
| [novel_scene_migration_rollback](#novel_scene_migration_rollback) | 会提交操作或保存文件；具体取决于 action/参数 | `migration_id`, `expected_revision` |
| [novel_scene_move](#novel_scene_move) | 会提交操作或保存文件；具体取决于 action/参数 | `scene_id`, `target_chapter_id`, `target_index`, `expected_revision`, `expected_source_revision`, `expected_target_revision` |
| [novel_scene_structure](#novel_scene_structure) | 只读查询（可更新检索缓存） | 无 |
| [novel_scene_update](#novel_scene_update) | 会提交操作或保存文件；具体取决于 action/参数 | `scene_id`, `expected_revision` |
| [novel_search](#novel_search) | 只读查询（可更新检索缓存） | `q` |
| [novel_settle_backfill](#novel_settle_backfill) | 会提交操作或保存文件；具体取决于 action/参数 | 无 |
| [novel_source_action](#novel_source_action) | 会提交操作或保存文件；具体取决于 action/参数 | `action` |
| [novel_status](#novel_status) | 只读查询（可更新检索缓存） | 无 |
| [novel_structured_change_plan](#novel_structured_change_plan) | 会提交操作或保存文件；具体取决于 action/参数 | `action` |
| [novel_sync](#novel_sync) | 会提交操作或保存文件；具体取决于 action/参数 | 无 |
| [novel_task_cancel](#novel_task_cancel) | 会提交操作或保存文件；具体取决于 action/参数 | `task_id` |
| [novel_task_confirm](#novel_task_confirm) | 会提交操作或保存文件；具体取决于 action/参数 | `task_id` |
| [novel_task_create](#novel_task_create) | 会提交操作或保存文件；具体取决于 action/参数 | `type`, `input` |
| [novel_task_get](#novel_task_get) | 会提交操作或保存文件；具体取决于 action/参数 | `task_id` |
| [novel_task_retry](#novel_task_retry) | 会提交操作或保存文件；具体取决于 action/参数 | `task_id` |
| [novel_tasks_list](#novel_tasks_list) | 只读查询（可更新检索缓存） | 无 |
| [novel_trace_list](#novel_trace_list) | 只读查询（可更新检索缓存） | 无 |
| [novel_write_chapter](#novel_write_chapter) | 会提交操作或保存文件；具体取决于 action/参数 | 无 |
| [novel_writing_assets](#novel_writing_assets) | 会提交操作或保存文件；具体取决于 action/参数 | `action` |
| [novel_writing_targets](#novel_writing_targets) | 会提交操作或保存文件；具体取决于 action/参数 | 无 |

## novel_arc_reconcile

Resolve selected drift entries by absorbing authored outline metadata, scheduling recovery in a later chapter, or freezing. Absorption requires concrete outline_updates and outline_revision; baseline is saved before edits. resume=true explicitly resumes a replanned group within budget. Does not rewrite manuscript.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| data | json | 是 | Object: group_id, expected_revision, entry_ids[], decision absorb/recover/freeze, confirm:true. absorb: outline_revision, outline_updates[{node_id,metadata}], resume?. recover: plan, target_chapter_id. |

## novel_asset_create

Create a structured asset. character/world assets take front-matter fields via `data` plus an optional `body_markdown`; progression assets take their YAML mapping via `data`. Fails with a conflict if the id exists — use novel_asset_update instead.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| kind | string | 是 | ["character","world","progression"]；Asset kind. |
| id | string | 是 | Asset id (letters, digits, "_", "-", "."). |
| data | json | 否 | Object of asset fields (e.g. name, summary, aliases). |
| body_markdown | string | 否 | Markdown body (character/world assets). |

## novel_asset_read

Read one structured asset by kind and id, including its relation view.

影响：只读查询（可更新检索缓存）。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| kind | string | 是 | ["character","world","progression"]；Asset kind. |
| id | string | 是 | Asset id. |

## novel_asset_update

Immediate compatibility write for an asset change the author has already authorized exactly; otherwise use novel_structured_change_plan. Update a structured asset (character / world / progression). Revision-gated: pass the `revision` fingerprint from novel_assets_list; the server rejects the update with a conflict if the asset changed. Pass field changes via `data` (merged into the asset front matter), `body_markdown` to replace the markdown body, or `raw_text` to replace the whole document.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| kind | string | 是 | ["character","world","progression"]；Asset kind. |
| id | string | 是 | Asset id. |
| revision | string | 是 | The asset revision fingerprint from a fresh novel_assets_list call. |
| data | json | 否 | Object of asset fields to merge (e.g. name, summary, aliases). |
| body_markdown | string | 否 | Replacement markdown body (character/world assets). |
| raw_text | string | 否 | Full replacement document text, validated by the server. |
| related_mode | string | 否 | ["merge","replace"]；Preserve and merge existing related entries by default; replace explicitly clears or replaces relations. |

## novel_assets_list

List structured assets (characters, world entities, progression systems) of the current novel project.

影响：只读查询（可更新检索缓存）。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| kind | string | 否 | ["character","world","progression"]；Restrict to one asset kind; omit to list all kinds. |

## novel_assets_package_export

Export assets as an .owasset.zip package and save it locally. Omit selections to export all assets.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| selections | array[string] | 否 | Asset selectors in "kind:id" form, e.g. ["character:hero", "world:capital"]. |

## novel_assets_package_import

Import a previously staged asset package (see novel_assets_package_preview). Resolves per-asset conflicts via `resolutions`; set allow_missing_dependencies to skip missing dependency checks.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| upload_id | string | 是 | The upload_id returned by novel_assets_package_preview. |
| package_sha256 | string | 否 | Optional expected package digest guard. |
| resolutions | json | 否 | Object mapping conflicting asset keys to resolutions. |
| allow_missing_dependencies | boolean | 否 | Allow import despite missing asset dependencies (default false). |

## novel_assets_package_preview

Stage an .owasset.zip asset package (base64) and preview its contents and conflicts without importing. Returns an upload_id to pass to novel_assets_package_import.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| package_base64 | string | 是 | Base64-encoded .owasset.zip package (max 25 MB decoded). |

## novel_chapter_delete

Delete the LATEST manuscript chapter. The server enforces three safeguards: the path must be a chapter under data/manuscript, confirm must exactly equal the chapter id (e.g. "ch_0007"), and version must equal the document version fingerprint from a fresh novel_doc_read. Only the newest chapter can be deleted, and never while a background task is active.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| path | string | 是 | Chapter path, e.g. "data/manuscript/ch_0007.md". |
| confirm | string | 是 | Must exactly equal the chapter id, e.g. "ch_0007". |
| version | string | 是 | The document version fingerprint from novel_doc_read. |

## novel_chapter_delete_batch

Delete the contiguous latest manuscript tail in one server request, retaining the specified chapter. The server still performs the single-chapter backup/projection cleanup for every chapter and refuses active tasks, missing chapters, non-tail ranges, or stale latest-version fingerprints. confirm must exactly equal "DELETE_AFTER:<keep_through>" (for example "DELETE_AFTER:ch_0030").

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| keep_through | string | 是 | Last chapter to retain, e.g. "ch_0030". |
| confirm | string | 是 | Must exactly equal DELETE_AFTER:<keep_through>. |
| version | string | 是 | The latest chapter version fingerprint from a fresh novel_doc_read. |

## novel_chapter_run_action

Manage Chapter Run V2 records (the server's per-chapter write/review run ledger). Actions: "list" (chapter_id?/statuses?/limit?), "get" (run_id), "record_intervention" (run_id + revision + request, optional scope/risk/affected_items/rewrite_required), "update_intervention" (run_id + revision + intervention_id + state, optional facts_revision/impact/proposal/confirm — state transitions may require confirm: true), "cancel" (run_id + revision, optional reason). All mutating actions are revision-gated: pass the run's current revision from a list/get call.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| include_archived | boolean | 否 | For list: include historical runs moved to chapter_deletions when a chapter was deleted. Archived runs are read-only and include archive_directory. |
| action | string | 是 | ["list","get","record_intervention","update_intervention","cancel","archive"]；The chapter-run operation. |
| run_id | string | 否 | Run id (required for get/record_intervention/update_intervention/cancel). |
| revision | string | 否 | Current run revision (required for mutating actions). |
| chapter_id | string | 否 | Chapter filter for list. |
| statuses | array[string] | 否 | Status filter for list. |
| since | string | 否 | ISO timestamp filter for recent runs. |
| limit | integer | 否 | List limit (default 20). |
| scope | string | 否 | Intervention scope (default "chapter"). |
| risk | string | 否 | Intervention risk level (default "medium"). |
| request | string | 否 | Intervention request text. |
| affected_items | json | 否 | Array of affected item ids. |
| rewrite_required | boolean | 否 | Whether the intervention forces a rewrite. |
| intervention_id | string | 否 | Intervention id (update_intervention). |
| state | string | 否 | Target intervention state (update_intervention). |
| facts_revision | string | 否 | Facts revision for the transition (update_intervention). |
| impact | json | 否 | Impact array for the transition (update_intervention). |
| proposal | string | 否 | Proposal text for the transition (update_intervention). |
| confirm | boolean | 否 | Confirm a gated state transition (default false). |
| reason | string | 否 | Cancel reason (cancel). |

## novel_chapter_scenes

Read the revision-labelled scene slice for one chapter.

影响：只读查询（可更新检索缓存）。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| chapter_id | string | 是 | Chapter id (ch_<digits>). |

## novel_chapter_work

Read one chapter work brief: manuscript/acceptance/review revisions, writing target, recent edits, tasks, and categorized foreshadowing obligations.

影响：只读查询（可更新检索缓存）。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| chapter_id | string | 是 | Chapter id (ch_<digits>). |
| document_id | string | 否 | Stable document id used to bind recent activity. |
| recent_limit | integer | 否 | Maximum recent edit records (default 20). |

## novel_context_preview

Preview the context packet OpenWrite would assemble for writing a chapter (relevant outline, assets, foreshadowing, and prior-chapter memory). Set include_agent_payload to inspect canonical writer inputs and document inclusion without calling a model.

影响：只读查询（可更新检索缓存）。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| chapter | string | 否 | Chapter id (e.g. "ch_0007"); omit or pass "next" for the next chapter to write. |
| include_agent_payload | boolean | 否 | Include the full writer payload, rendered initial messages and document inventory. Later segment/retry messages depend on the write request. |

## novel_continuity

Get the continuity report: unresolved foreshadowing, character state drift, and timeline consistency of the current project.

影响：只读查询（可更新检索缓存）。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| 无 | — | — | — |

## novel_diagnostics

Run runtime diagnostics over the project (read-only): stuck runs, stale locks, and other operational issues.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| stuck_minutes | integer | 否 | Minutes after which a run counts as stuck (default 30). |

## novel_doc_create

Create a new project document by kind and name (e.g. a setting or character note), then returns the created document.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| kind | string | 是 | Document kind (e.g. "setting", "character"). |
| name | string | 是 | Document name. |
| description | string | 否 | Short description of the document. |

## novel_doc_read

Read a project document (path relative to the novel data root, e.g. "src/outline.md" or "data/manuscript/ch_0007.md"). Returns content plus a `version` fingerprint needed by novel_doc_write.

影响：只读查询（可更新检索缓存）。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| path | string | 是 | Document path relative to the novel data root. |

## novel_doc_write

Write a project document (path relative to the novel data root). Uses a version-based optimistic lock: pass the `version` returned by novel_doc_read; the server rejects with a conflict if the document changed. Omit version to create a new document; set force to bypass the lock.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| path | string | 是 | Document path relative to the novel data root. |
| content | string | 是 | Full new document content (max 2 MB). |
| version | string | 否 | The version fingerprint from novel_doc_read (optimistic lock). |
| force | boolean | 否 | Bypass the version check (default false). |

## novel_document_change_plan

Stage and review revision-gated changes to an existing novel document. Use action "preview" with path and edits to receive an immutable preview_token and real before/after summary. Use "apply" only after author acceptance, passing that token and confirm: true; "reject" discards it, "retry" rebuilds it against the current source, and "undo" safely applies an undo_preview_token returned by a prior apply. Each edit uses old_text/new_text or unique start_text/end_text/new_text anchors. Preview returns applied:false; changed/would_change describe only the proposed difference. OLD_TEXT_NOT_FOUND is an anchor mismatch (400), while revision conflicts are 409; use the exact suggested bytes and reread the source before retrying. The server rechecks the source revision and writes exactly the stored preview.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| action | string | 是 | ["preview","apply","reject","retry","undo"]；Plan lifecycle action. |
| confirm | boolean | 否 | Required true for apply and undo after author acceptance. |
| path | string | 否 | Existing document path for preview, relative to the novel root. |
| edits | json | 否 | Preview edits: [{old_text,new_text}] or [{start_text,end_text,new_text,end_inclusive}]. Range end defaults to inclusive for compatibility; end_inclusive:false preserves the end anchor (e.g. the next heading). |
| preview_token | string | 否 | Immutable preview or undo token for apply/reject/retry/undo. |

## novel_drift_entry

Record author-observed chapter drift. Saves an immutable outline/manuscript baseline first. More than two unresolved rewrite drifts in a section freezes generation until explicit reconciliation and replanning.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| group_id | string | 是 | Section ID sec_*. |
| chapter_id | string | 是 | Chapter in this section. |
| kind | string | 是 | ["growth","escape","dilution","snowball"]；Drift kind. |
| impact | string | 是 | ["local","section","arc"]；Impact scope. |
| rewrite | boolean | 否 | Counts toward rewrite budget; default true. |
| note | string | 是 | Observed drift and supporting evidence. |
| expected_revision | integer | 是 | ledger.revision from outline audit. |

## novel_embedding_profile_delete

Delete an independent Embedding profile; the active profile automatically moves to another one.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| profile_id | string | 是 |  |

## novel_embedding_profile_save

Create or update an independent Embedding profile; it is never attached to a Chat profile.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| profile | json | 是 | Embedding profile: id, label, provider, model, base_url, dimension, max_tokens. |
| api_key | string | 否 | Embedding API key. |
| remember_api_key | boolean | 否 | Persist the key (default true). |

## novel_embedding_profile_select

Select the active independent Embedding profile used by search.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| profile_id | string | 是 |  |

## novel_embedding_profiles

List independent Embedding profiles and the active selection. Embedding is configured separately from Chat profiles.

影响：只读查询（可更新检索缓存）。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| 无 | — | — | — |

## novel_export

Export the manuscript as a file download and save it locally. Inspect novel_export_preflight first and pass its preflight_revision unchanged to bind the download to that inspected manuscript state. Returns the saved file path.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| format | string | 否 | ["md","txt","epub"]；Export format (default "md"). |
| purpose | string | 否 | ["backup","delivery","personal_archive"]；Export purpose (default "delivery"). |
| preflight_revision | string | 否 | Revision returned by novel_export_preflight for the same format and purpose. |

## novel_export_preflight

Inspect the current manuscript export order, structural defects, writing targets, metadata, review freshness, manuscript acceptance, blockers, and warnings. Pass the returned preflight_revision unchanged to novel_export so the downloaded file is bound to the manuscript state that was inspected.

影响：只读查询（可更新检索缓存）。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| format | string | 否 | ["md","txt","epub"]；Export format (default "md"). |
| purpose | string | 否 | ["backup","delivery","personal_archive"]；Export purpose (default "delivery"). personal_archive preserves author copies with gate findings recorded as warnings. |

## novel_focus

Immediate compatibility write for a focus change the author has already authorized exactly; otherwise use novel_structured_change_plan. Set the writing focus compass for the project.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| goal | string | 是 | The current writing goal. |
| must_keep | array[string] | 否 | Constraints that must be kept. |
| must_avoid | array[string] | 否 | Things that must be avoided. |
| notes | array[string] | 否 | Free-form focus notes. |

## novel_foreshadowing

Immediate compatibility write for a foreshadowing change the author has already authorized exactly; otherwise use novel_structured_change_plan. Manage the foreshadowing DAG. action "create": node_id + content, optional weight (1-10, default 5), layer (default "支线"), target_chapter. action "update": node_id + status (e.g. planted/paid-off).

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| action | string | 是 | ["create","update"]；Create a new foreshadowing node or update an existing one. |
| node_id | string | 是 | Foreshadowing node id. |
| content | string | 否 | Node content (create). |
| weight | integer | 否 | Narrative weight 1-10 (create, default 5). |
| layer | string | 否 | Story layer, e.g. "主线" or "支线" (create, default "支线"). |
| target_chapter | string | 否 | Chapter id the foreshadowing should pay off at (create). |
| status | string | 否 | New node status (update). |

## novel_import

Import a TXT/Markdown manuscript as chapters (split on headings). Preview first with novel_import_preview; the server rejects conflicting chapter ids unless force is set.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| content | string | 是 | The manuscript text to import. |
| filename | string | 否 | Source filename; suffix must be .txt/.md/.markdown (default "import.md"). |
| arc_id | string | 否 | Arc id like "arc_001" (default: the project's current arc). |
| start_number | integer | 否 | First chapter number (default: continue numbering). |
| force | boolean | 否 | Overwrite conflicting existing chapters (default false). |

## novel_import_preview

Preview a TXT/Markdown manuscript import without writing anything: detected chapters, numbering, and conflicts with existing chapters. Run this before novel_import.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| content | string | 是 | The manuscript text to import. |
| filename | string | 否 | Source filename; suffix must be .txt/.md/.markdown (default "import.md"). |
| arc_id | string | 否 | Arc id like "arc_001" (default: the project's current arc). |
| start_number | integer | 否 | First chapter number (default: after the last existing chapter). |
| force | boolean | 否 | Report the import as allowed despite conflicts (default false). |

## novel_manuscript_acceptance

Inspect the canonical manuscript acceptance ledger: current and accepted content revisions, drift, recoverable operations, derived-result impacts, and chapters that require author review.

影响：只读查询（可更新检索缓存）。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| 无 | — | — | — |

## novel_manuscript_acceptance_reconcile

Reconcile the canonical manuscript acceptance ledger. Actions: "baseline" (accept current text as the initial baseline), "external" (accept a detected external edit), "resume" (continue a durable incomplete operation), "abandon" (release a stale operation without deleting prose), and "acknowledge" (record that the author reviewed the completed acceptance and impacts). Each action is mapped to the corresponding OpenWrite acceptance endpoint. Baseline, external, and acknowledge are confirmation-gated by the server.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| action | string | 是 | ["baseline","external","resume","acknowledge","abandon"]；The reconciliation action. |
| mode | string | 否 | ["full","fast"]；resume: fast accepts frozen manuscript without calling a model; derived facts remain stale and can be reconciled later. |
| no_model | boolean | 否 | external: accept manuscript bytes without extracting facts; does not clear the facts guard. |
| chapter_id | string | 否 | Optional chapter id (ch_<digits>); omit for the project-level operation. |
| operation_id | string | 否 | Durable operation id to resume or acknowledge. |
| domains | array[string] | 否 | Affected domains to acknowledge or retry; acknowledge defaults to outline and foreshadowing. |
| confirm | boolean | 否 | Explicit confirmation for a gated baseline, external acceptance, or acknowledgement. |

## novel_manuscript_edit_action

Chapter snapshots, annotations and saved drafts. Actions: "drafts" (list recoverable uncommitted prose), "restore_draft" (run_id_v2 + revision + confirm: true; copy the exact saved bytes without generation, then reconcile facts). Other actions: "versions" (chapter_id), "version" (chapter_id + version_id — returns the snapshot content), "checkpoint" (chapter_id, optional label — save a snapshot), "compare" (chapter_id + version_id — preview current-to-snapshot differences without writing), "restore" (chapter_id + version_id + revision — REVERTS the chapter to a snapshot; revision-gated and confirmation-gated: the server demands confirm: true), "annotations" (chapter_id), "annotate" (chapter_id + revision + quote + note, optional start_hint/end_hint and color amber|rose|sky|lime|violet), "resolve_annotation" (chapter_id + annotation_id).

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| action | string | 是 | ["drafts","restore_draft","versions","version","compare","checkpoint","restore","annotations","annotate","resolve_annotation"]；The manuscript-editing operation. |
| chapter_id | string | 否 | Chapter id (ch_<digits>), required except for drafts/restore_draft. |
| run_id_v2 | string | 否 | Saved run id from drafts (restore_draft). |
| version_id | string | 否 | Snapshot id (version/restore). |
| label | string | 否 | Snapshot label (checkpoint). |
| revision | string | 否 | Current chapter revision (restore/annotate). |
| confirm | boolean | 否 | Confirm a restore (required by the server). |
| quote | string | 否 | Annotated passage (annotate). |
| note | string | 否 | Annotation note (annotate). |
| start_hint | integer | 否 | Approximate start offset (annotate). |
| end_hint | integer | 否 | Approximate end offset (annotate). |
| color | string | 否 | ["amber","rose","sky","lime","violet"]；Display color for a selection note (annotate). |
| annotation_id | string | 否 | Annotation id (resolve_annotation). |

## novel_manuscript_import_action

Operate the durable, resumable import workspace for the author's own TXT/Markdown manuscript. Use list/get to inspect saved operations, prepare to snapshot and split a manuscript, structure to revise the chapter boundaries against the current preview revision, confirm for explicit structure approval, run to start or resume the persistent import task, and discard only before publication. This is manuscript migration, not reference-library analysis.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| action | string | 是 | ["list","get","prepare","structure","confirm","run","discard"]；Import workspace action. |
| import_id | string | 否 | Persistent import operation id. |
| limit | integer | 否 | Maximum operations for list (default 50). |
| filename | string | 否 | Source filename ending in .txt, .md, or .markdown. |
| content | string | 否 | The author's own manuscript text for prepare. |
| arc_id | string | 否 | Target arc id, e.g. arc_001. |
| start_number | integer | 否 | Optional first chapter number. |
| expected_preview_revision | string | 否 | Current preview revision required by structure/confirm. |
| chapters | array[json] | 否 | Edited chapter objects: chapter_id, title, content. |
| confirm | boolean | 否 | Must be true for confirm or discard. |

## novel_manuscript_metrics

Read deterministic chapter metrics, terminology findings, overlap against anchors and the previous three chapters, duplicate paragraphs and selected character groups. Overlap spans use Unicode codepoint offsets. No model call.

影响：只读查询（可更新检索缓存）。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| chapter_id | string | 是 | Canonical chapter ID. |

## novel_model_benchmark

Run or inspect isolated chapter or outline model benchmarks through OpenWrite profiles and LiteLLM. Use options first to read chapter choices, task limits, supported execution modes and the authoritative pipeline DAG/review domains without invoking a model. The run action creates a background task and never changes model routes, canonical manuscript or canonical outline files.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| action | string | 是 | ["list","get","options","run"]；Benchmark operation; options previews task choices and pipeline DAGs without starting a run. |
| run_id | string | 否 | Benchmark run id for get. |
| task_type | string | 否 | ["chapter","outline"]；Run target: chapter (default) or outline. Outline supports framework mode only. |
| chapter_id | string | 否 | Chapter task target: next (default) or an available canonical chapter_id from options, e.g. ch_003. Unavailable targets are rejected without fallback; inspect availability/reason first. |
| allow_historical | boolean | 否 | Explicit isolated rewrite of an already written chapter using current canon. This is not a reconstructed pre-chapter baseline. Source manuscript and ledgers remain unchanged. |
| outline_start_chapter | integer | 否 | Outline task first chapter number, inclusive, 1-100000. Omit to continue after the last outline chapter. |
| outline_chapter_count | integer | 否 | Outline task range length including its starting chapter, 1-20 (default 3). |
| writer_profile_ids | array[string] | 否 | Writing profiles to compare (run). |
| reviewer_profile_ids | array[string] | 否 | Independent blind-review profiles (run). |
| execution_mode | string | 否 | ["framework","creative"]；Execution path: full framework (default); creative diagnostic is available only for chapter tasks. Read task pipelines with options. |
| repeats | integer | 否 | Repeats per writing profile, 1-5. |
| target_words | integer | 否 | Chapter candidate target length, 200-50000; use outline_chapter_count for outline range. |
| concurrency | integer | 否 | Concurrent model jobs, 1-4. |
| limit | integer | 否 | List limit, default 20. |

## novel_model_configure

Apply and persist the server's active model connection (OpenWrite's own LLM for writing/review — independent of the dsh model). max_tokens must stay below context_tokens.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| provider | string | 否 | ["openai","anthropic","custom"]；Provider (default "openai"). |
| model | string | 是 | Model name (max 120 characters). |
| api_key | string | 否 | API key; omit to reuse the server environment key. |
| base_url | string | 否 | Base URL (required for provider "custom"). |
| api_format | string | 否 | ["chat","responses"]；API format (default "chat"). |
| context_tokens | integer | 否 | Context budget (min 12000). |
| max_tokens | integer | 否 | Max output tokens (min 256, must be < context_tokens). |
| remember_api_key | boolean | 否 | Persist the API key on the server (default true). |

## novel_model_embedding_test

Probe an independent Embedding profile without changing Chat profiles.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| id | string | 否 | Stored profile id to probe. |
| candidate | json | 否 | Embedding candidate settings object (merged into the request). |
| api_key | string | 否 | Embedding API key override. |

## novel_model_profile_delete

Delete a stored model profile. Routes pointing at it fall back to fallback_id.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| profile_id | string | 是 | Profile id to delete. |
| fallback_id | string | 否 | Profile id to reroute to (default: the server default profile). |

## novel_model_profile_save

Save (create or update) a named model profile on the server, with an optional API key.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| profile | json | 是 | Profile object, e.g. {"id": "fast", "label": "...", "provider": "openai", "model": "...", "base_url": "...", "max_output_tokens": 24000}. |
| api_key | string | 否 | Chat API key to store with the profile. |
| remember_api_key | boolean | 否 | Persist the API key on the server (default true). |

## novel_model_profiles

List the server's model profiles and per-task routing (which provider/model OpenWrite uses for writing, review, etc.).

影响：只读查询（可更新检索缓存）。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| 无 | — | — | — |

## novel_model_routes_save

Save per-task model routing: map operation names (e.g. "chapter_write", "review", "research") to profile ids.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| routes | json | 是 | Object mapping operation names to profile ids. |

## novel_model_test

Test a model connection without changing active settings. Pass id to test a stored profile, or a full candidate (provider/model/base_url/api_key...).

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| id | string | 否 | Stored profile id to test. |
| provider | string | 否 | ["openai","anthropic","custom"]；Provider (default "openai"). |
| model | string | 否 | Model name (required when id is omitted). |
| base_url | string | 否 | Base URL (required for provider "custom"). |
| api_format | string | 否 | ["chat","responses"]；API format (default "chat"). |
| api_key | string | 否 | API key; omit to reuse the server environment key. |
| context_tokens | integer | 否 | Context budget. |
| max_tokens | integer | 否 | Max output tokens. |

## novel_multi_write

Queue a BACKGROUND continuous-writing run: writes up to max_chapters chapters following the outline, reviewing each; stops early on review blockers, continuity errors, low scores, or budget limits. Returns immediately with a task id — poll with novel_task_get and resume paused runs with novel_task_confirm.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| max_chapters | integer | 否 | Chapters to write, 1-10 (default 1). |
| minimum_review_score | integer | 否 | Stop when a chapter scores below this, 0-100 (default 82). |
| max_tokens | integer | 否 | Token budget, 0 = unlimited (default 0). |
| max_failures | integer | 否 | Stop after this many consecutive failures, 1-10 (default 2). |
| max_cost_usd | number | 否 | Cost budget in USD, 0 = unlimited (default 0). |
| guidance | string | 否 | Writing guidance applied to every chapter. |
| target_words | integer | 否 | Target words per chapter (falls back to the outline recommendation). |
| temperature | number | 否 | Sampling temperature (default 0.7). |
| stop_on_blocker | boolean | 否 | Stop when a review reports a blocker issue (default true). |
| stop_on_continuity_error | boolean | 否 | Stop on high-severity continuity issues (default true). |
| require_confirmation_after_each_chapter | boolean | 否 | Pause for novel_task_confirm after each chapter (default false). |

## novel_narrative_forecast_action

Manage narrative forecasts (branching "what-if" plot projections). Actions: "list" (limit?), "create" (divergence + anchor_chapter_id?, branch_count default 3, horizon default 5), "get" (forecast_id), "stage" (forecast_id + branches + revision), "select" (forecast_id + branch_id + revision — commits one branch; revision-gated).

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| action | string | 是 | ["list","create","get","stage","select"]；The forecast operation. |
| limit | integer | 否 | List limit (default 20). |
| divergence | string | 否 | The divergence point description (create). |
| anchor_chapter_id | string | 否 | Chapter to anchor the forecast at (create). |
| branch_count | integer | 否 | Number of branches (create, default 3). |
| horizon | integer | 否 | Forecast horizon in chapters (create, default 5). |
| forecast_id | string | 否 | Forecast id (get/stage/select). |
| branches | json | 否 | Branch array to stage (stage). |
| branch_id | string | 否 | Branch id to commit (select). |
| revision | string | 否 | Forecast revision (stage/select, revision-gated). |

## novel_outline_audit

Read countable chapter-group facts: budgets/actual words, declared promises and function streaks, declared/confirmed payoffs, overdue hooks and drift ledger. Never generates a score or claims prose fulfilled a promise. No model call.

影响：只读查询（可更新检索缓存）。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| group_id | string | 否 | Optional sec_* or arc_* group. |
| start | string | 否 | Optional first chapter ID. |
| end | string | 否 | Optional last chapter ID. |

## novel_outline_edit

Immediate compatibility write for an outline change the author has already authorized exactly; otherwise use novel_structured_change_plan. Apply ONE atomic structural edit to the outline tree. Edits are revision-gated: read the current `revision` via novel_outline_read first and pass it back; the server rejects the edit with a conflict if the outline changed in between. Operations: "rename" (node_id + title), "update_summary" (node_id + summary), "add_child" (node_id = parent, + title/summary/kind), "add_after" (node_id = sibling, + title/summary/kind), "delete" (node_id, cascade=false keeps children), "promote" (remove a container), and "get_meta"/"set_meta" (chapter metadata, optionally updates[] for a batch).

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| operation | string | 是 | ["rename","update_summary","add_child","add_after","delete","promote","get_meta","set_meta"]；The structural operation to apply. |
| cascade | boolean | 否 | For delete, false removes only the container and keeps children and chapter IDs. |
| metadata | json | 否 | Field object for set_meta; use target_words, beats, hooks or characters. |
| chapter_id | string | 否 | Chapter ID alias for node_id in get_meta/set_meta. |
| updates | json | 否 | Batch of 1-50 {chapter_id, metadata} objects for set_meta, or {chapter_id} for get_meta; one revision guards the whole batch. |
| revision | string | 是 | The outline revision fingerprint from a fresh novel_outline_read call. |
| node_id | string | 否 | Target node id (parent for add_child, sibling for add_after); not needed for add_child at root. |
| title | string | 否 | Node title (rename / add_child / add_after). |
| summary | string | 否 | Node summary (update_summary / add_child / add_after). |
| kind | string | 否 | Node kind, e.g. "volume" or "chapter" (add_child / add_after). |

## novel_outline_read

Read the live outline tree. The response carries a `revision` fingerprint required by novel_outline_edit and a chapter `recommendation`.

影响：只读查询（可更新检索缓存）。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| chapter | string | 否 | Optional chapter id to get a writing recommendation for. |

## novel_project_archive_action

Inspect, create, and restore complete .owarchive project archives. Use preflight before create; use restore_preview before restore to inspect path/reference rewrites, conflicts, warnings, checksum, and the archived-without-auto-resume task policy. Restore requires the preview archive_sha256 and explicit confirmation.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| action | string | 是 | ["preflight","list","get","create","restore_preview","restore"]；Archive lifecycle action. |
| archive_id | string | 否 | Archive id shaped owa_<24 lowercase hex>. |
| expected_preflight_revision | string | 否 | Current archive preflight revision for create. |
| target_root | string | 否 | Absolute new or empty project directory for restore. |
| target_novel_id | string | 否 | Optional restored novel id. |
| reference_policy | string | 否 | ["preserve_relative","rewrite_novel_id"]；Reference handling during restore. |
| archive_sha256 | string | 否 | Checksum returned by restore_preview. |
| confirm | boolean | 否 | Must be true for restore. |

## novel_project_archive_download

Download one complete .owarchive project archive and save it in this workspace's local export directory.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| archive_id | string | 是 | Archive id shaped owa_<24 lowercase hex>. |

## novel_project_delete

PERMANENTLY delete a project directory and all its contents from the server machine (recursive delete, not recoverable). The server requires confirm to exactly equal the project's novel_id as a safeguard.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| project_path | string | 是 | Project directory to delete. |
| confirm | string | 是 | Must exactly equal the project's novel_id (from its novel_config.yaml). |

## novel_project_init

Create a new OpenWrite novel project on the server machine and make it the active project. Works without a currently open project. novel_id must be 2-64 chars of letters/digits/"-"/"_".

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| novel_id | string | 是 | Project id, e.g. "my_novel" (2-64 chars: letters, digits, "-", "_"). |
| title | string | 是 | Book title (max 120 characters). |
| author | string | 否 | Author credit for delivery export (max 120 characters). |
| language | string | 否 | Book language tag, e.g. zh-CN or en (default zh-CN). |
| project_path | string | 否 | Target directory on the server; omit to use the server default location. |
| template | string | 否 | ["default","demo_short"]；Project template (default "default"). |

## novel_project_open

Switch the Studio server to another existing project directory (must contain novel_config.yaml). Works without a currently open project; afterwards every other novel_* tool targets the newly opened project. The server rejects the switch while a background task is active.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| project_path | string | 是 | Absolute project directory path on the server machine. |

## novel_reading_order

Read the canonical manuscript order with stable document/occurrence ids, volume membership, previous/next links, revision, and explicit duplicate or missing-file issues.

影响：只读查询（可更新检索缓存）。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| 无 | — | — | — |

## novel_reading_order_move

Move one manuscript document within or across volumes. Requires the fresh reading-order revision and rejects ambiguous, missing, or concurrently changed order.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| document_id | string | 是 | Stable document_id or unambiguous occurrence_id. |
| target_volume_id | string | 是 | Target volume_id from novel_reading_order. |
| target_index | integer | 是 | Zero-based position inside the target volume. |
| expected_revision | string | 是 | Fresh reading-order revision used for CAS. |

## novel_reading_packet

Read a bounded continuous-reading window around one stable manuscript document or occurrence id.

影响：只读查询（可更新检索缓存）。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| document_id | string | 是 | Stable document_id or occurrence_id from novel_reading_order. |
| before | integer | 否 | Number of preceding chapters (0-20, default 1). |
| after | integer | 否 | Number of following chapters (0-20, default 1). |

## novel_reference_library_action

Reference-library pipeline (decomposing reference works into structured evidence). Actions: "list", "prepare" (source_id + content, optional title/relative_name/intent/focus array/input_budget_tokens), "confirm_structure" (source_id, units? array), "analyze" (source_id, LONG-RUNNING), "status" (source_id), "retry" (source_id + chunk_id?), "synthesize" (source_ids array), "profile" (profile_id), "adoption_preview" (profile_id + selections array, optional rejected_item_ids), "adopt" (preview_id, confirm: true to commit).

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| action | string | 是 | ["list","prepare","confirm_structure","analyze","status","retry","synthesize","profile","adoption_preview","adopt"]；The reference-library operation. |
| source_id | string | 否 | Reference source id. |
| content | string | 否 | Reference text (prepare). |
| title | string | 否 | Reference title (prepare). |
| relative_name | string | 否 | Display filename (prepare, default "source.txt"). |
| intent | string | 否 | Analysis intent (prepare, default "reference"). |
| focus | json | 否 | Array of focus names (prepare). |
| input_budget_tokens | integer | 否 | Token budget per chunk (prepare, default 12000). |
| units | json | 否 | Confirmed structure units (confirm_structure). |
| chunk_id | string | 否 | Chunk to retry (retry). |
| source_ids | array[string] | 否 | References to synthesize (synthesize). |
| profile_id | string | 否 | Analysis profile id (profile/adoption_preview). |
| selections | json | 否 | Array of adoption selections (adoption_preview). |
| rejected_item_ids | array[string] | 否 | Items to reject (adoption_preview). |
| preview_id | string | 否 | Adoption preview id (adopt). |
| confirm | boolean | 否 | Confirm a gated adoption (default false). |

## novel_research_report

Read one deep-research report by id (ids come from novel_research_status).

影响：只读查询（可更新检索缓存）。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| report_id | string | 是 | Report id. |

## novel_research_settings_save

Save deep-research API settings (search/LLM providers, API keys, defaults). Pass the whole settings object; returns the refreshed research surface.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| settings | json | 是 | Settings object, e.g. {"search": "bocha", "llm": "deepseek", ...}. |

## novel_research_status

Get the deep-research surface: settings status, report list, and the configured model route. Run a research job via novel_task_create with type "research".

影响：只读查询（可更新检索缓存）。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| 无 | — | — | — |

## novel_review_chapter

Run OpenWrite's multi-dimensional review on a drafted manuscript chapter (LONG-RUNNING). Pass either the manuscript path (e.g. "data/manuscript/ch_0007.md") or a chapter_id like "ch_0007".

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| action | string | 否 | ["review","versions","compare"]；Default review; versions lists saved reviews, compare compares a historical revision with the current review. |
| revision | string | 否 | Historical review revision for compare. |
| path | string | 否 | Manuscript path relative to the novel data root. Takes precedence over chapter_id. |
| chapter_id | string | 否 | Chapter id (ch_<digits>), resolved client-side to data/manuscript/<id>.md. |
| strict | boolean | 否 | Enable strict review mode (default false). |
| dimensions | array[integer] | 否 | Optional list of review dimension numbers (1-37) to restrict to. |
| depth | string | 否 | ["quick","full"]；Default full. Quick reviews coherence/canon/prose and safety only; scope_status=partial cannot approve full-chapter delivery. Do not combine quick with dimensions. |
| domains | array[string] | 否 | Review domain ids: coherence, character, plot, pacing, prose, canon. Use this or dimensions. Omitted domains remain explicitly unreviewed. |
| dog_threshold | integer | 否 | DoG aggregate score threshold (default 70); this does not change OpenWrite review. |

## novel_review_framework

Inspect the canonical reusable chapter-review DAG blueprint: its version, revision, six quality domains, 37 checks, hard gates, dependencies, invariants, and extension points.

影响：只读查询（可更新检索缓存）。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| 无 | — | — | — |

## novel_revision_apply

Apply a staged revision proposal to the manuscript. Optionally override the generated text or apply only selected diff hunks. Fails with a conflict if the document changed since the proposal was created.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| proposal_id | string | 是 | Revision proposal id (rev_*). |
| replacement_text | string | 否 | Replacement text overriding the proposal. |
| selected_hunk_ids | array[string] | 否 | Apply only these diff hunk ids. |

## novel_revision_create_from_review

Create a revision proposal that addresses selected issues from a chapter review (LONG-RUNNING, model-generated). Issue ids come from novel_review_chapter's issue_details. Pass selection to constrain rewriting to an exact manuscript range; overlapping issue evidence never expands that range. The proposal is only staged — apply it with novel_revision_apply.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| chapter_id | string | 是 | Chapter id (ch_<digits>). |
| issue_ids | array[string] | 是 | Review issue ids to fix. |
| selection | object | 否 | Optional exact saved-text range in Unicode code points; preserve raw CR/LF characters. |
| instruction | string | 否 | Additional revision instruction. |
| target_units | integer | 否 | Target length in writing units (0 = keep similar). |
| expected_review_revision | string | 否 | Exact review file revision from the chapter work brief. |
| expected_document_revision | string | 否 | Exact manuscript revision from the chapter work brief. |

## novel_revision_create_selection

Create a revision proposal for a text selection in a chapter (LONG-RUNNING, model-generated). start/end are Unicode code-point offsets in the exact saved text, including original CR/LF characters; pass the selected text as original_text and the current expected_document_revision. The proposal is only staged — apply it with novel_revision_apply.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| chapter_id | string | 是 | Chapter id (ch_<digits>). |
| start | integer | 是 | Selection start offset. |
| end | integer | 是 | Selection end offset. |
| original_text | string | 否 | The selected original text. |
| expected_document_revision | string | 否 | Current exact manuscript revision; reject before generation if the source changed. |
| instruction | string | 否 | Revision instruction (max 4000 characters). |
| action | string | 否 | ["rewrite","expand","compress","pace","dialogue","naturalize","custom"]；Revision mode (default "rewrite"). |
| target_units | integer | 否 | Target length in writing units (0 = keep similar). |
| full_chapter | boolean | 否 | Treat the whole chapter as the selection (default false). |

## novel_revision_get

Get one revision proposal with its diff hunks by proposal id (rev_*).

影响：只读查询（可更新检索缓存）。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| proposal_id | string | 是 | Revision proposal id (rev_*). |

## novel_revision_regenerate

Regenerate the text of a staged revision proposal (LONG-RUNNING, model-generated).

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| proposal_id | string | 是 | Revision proposal id (rev_*). |

## novel_revision_reject

Reject and discard a staged revision proposal. This permanently drops the generated text — it cannot be recovered except by regenerating.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| proposal_id | string | 是 | Revision proposal id (rev_*). |

## novel_revisions_list

List revision proposals, optionally filtered by chapter and/or status.

影响：只读查询（可更新检索缓存）。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| chapter | string | 否 | Chapter id filter (e.g. "ch_0007"). |
| status | string | 否 | Status filter (e.g. "proposed", "applied", "rejected"). |

## novel_rolling_plan_action

Manage rolling plan candidates (mid-range plot planning windows). Actions: "list" (limit?), "create" (current_arc?, window_size? default 50, max 50). current_window/accepted_window is accepted manuscript facts only; next_window/planned_window is outline plan, not facts. "get" (candidate_id), "stage" (candidate_id + proposal + revision — stages a plan proposal against the candidate; revision-gated), "delete" (candidate_id + revision), "apply" (candidate_id + revision — appends staged draft chapters that do not collide with the canonical outline into src/outline.md; never writes accepted facts).

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| action | string | 是 | ["list","create","get","stage","delete","apply"]；The rolling-plan operation. |
| limit | integer | 否 | List limit (default 20). |
| current_arc | string | 否 | Current arc id (create). |
| window_size | integer | 否 | Planning window size in chapters (create, default 50, max 50). |
| candidate_id | string | 否 | Candidate id (get/stage/delete/apply). |
| proposal | string | 否 | Plan proposal text (stage). |
| revision | string | 否 | Candidate revision (stage/delete/apply, revision-gated). |

## novel_rule_action

Compiled writing rules. Actions: "status" (active rule set), "preview" (compile a candidate preview), "apply" (preview_id — confirmation-gated: the server answers CONFIRMATION_REQUIRED until called again with confirm: true).

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| action | string | 是 | ["status","preview","apply"]；The rule operation. |
| preview_id | string | 否 | Preview id to apply (apply). |
| confirm | boolean | 否 | Confirm applying the preview (apply). |

## novel_runtime_skill_action

Inspect OpenWrite runtime skills. Actions: "list" (all discovered skills), "diagnose" (skill loading problems), "resolve" (which skills apply for an agent and task — optional agent one of dante/goethe/writer/reviewer/studio, skills, task, intent, document_type). Read-only.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| action | string | 是 | ["list","diagnose","resolve"]；The runtime-skill operation. |
| agent | string | 否 | Agent baseline for resolve: "dante", "goethe", "writer", "reviewer", or "studio" (default). |
| skills | array[string] | 否 | Explicit skill ids to resolve. |
| task | string | 否 | Task description for resolve. |
| intent | string | 否 | Intent hint for resolve. |
| document_type | string | 否 | Document type hint for resolve. |

## novel_scene_migration_apply

Apply one freshly read scene migration preview. Requires the exact preview revision and explicit confirmation.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| expected_preview_revision | string | 是 | Exact preview_revision from novel_scene_migration_preview. |
| confirm | boolean | 是 | Must be true after the author approves the preview. |

## novel_scene_migration_preview

Build a read-only, exact-revision preview that segments existing chapters into stable scenes. This does not write a sidecar.

影响：只读查询（可更新检索缓存）。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| 无 | — | — | — |

## novel_scene_migration_rollback

Restore the byte-exact scene sidecar that preceded a migration, guarded by the current scene-structure revision.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| migration_id | string | 是 | Migration id returned by novel_scene_migration_apply. |
| expected_revision | string | 是 | Fresh scene-structure revision used for CAS. |

## novel_scene_move

Move one complete scene within or across chapters with scene/source/target revision guards. Cross-chapter moves start the existing manuscript acceptance flow.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| scene_id | string | 是 | Stable scene id from novel_scene_structure. |
| target_chapter_id | string | 是 | Target chapter id (ch_<digits>). |
| target_index | integer | 是 | Zero-based scene position inside the target chapter. |
| expected_revision | string | 是 | Fresh scene-structure revision. |
| expected_source_revision | string | 是 | Fresh source chapter revision. |
| expected_target_revision | string | 是 | Fresh target chapter revision. |

## novel_scene_structure

Read the canonical scene structure with stable scene ids, reading/story-time order, chapter revisions, references, freshness, and explicit issues.

影响：只读查询（可更新检索缓存）。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| 无 | — | — | — |

## novel_scene_update

CAS-update scene title, story time, and character/location/event references without changing manuscript prose.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| scene_id | string | 是 | Stable scene id from novel_scene_structure. |
| expected_revision | string | 是 | Fresh scene-structure revision used for CAS. |
| title | string | 否 | Optional scene title. |
| story_time_sort_key | string | 否 | Optional lexical story-time sort key. |
| story_time_label | string | 否 | Optional author-facing story-time label. |
| characters | array[string] | 否 | Character references; replaces the current list when supplied. |
| locations | array[string] | 否 | Location references; replaces the current list when supplied. |
| events | array[string] | 否 | Event references; replaces the current list when supplied. |

## novel_search

Search the novel project (semantic + exact match) across chapters, outline, and assets.

影响：只读查询（可更新检索缓存）。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| q | string | 是 | The search query. |
| scope | string | 否 | Search scope, e.g. "all" (default), "chapters", "outline", "assets". |
| limit | integer | 否 | Maximum number of results (server default 20). |

## novel_settle_backfill

Settlement backfill for existing/imported chapters: replay the writer pipeline observer+settler over the actual chapter prose (never rewriting it) and commit chapter memory, runtime-truth notes and a character-state index refresh. Run once after importing an old manuscript so later chapters, reviews and canon/continuity checks have real facts from earlier chapters (without it, review canon stays inconclusive and context lacks previous-chapter recaps). Returns a background task (tsk_*); poll with novel_task_get.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| chapter_ids | array[string] | 否 | Optional chapter ids to backfill, e.g. ["ch_001","ch_002"]; omit to backfill every chapter missing memory. |
| only_missing | boolean | 否 | Skip chapters that already have memory (default true). |

## novel_source_action

Style/setting source pipeline (learning from reference texts). Actions: "extract" (source_id + content, focus "style"|"setting"), "analyze_v2" (source_id + content, focus as array, optional relative_name/input_budget_tokens), "status_v2" (source_id), "retry_v2" (source_id + chunk_id?), "synthesize_v2" (source_ids array), "profile_v2" (profile_id), "promotion_preview_v2" (profile_id + target), "promote_v2" (preview_id, confirm: true to commit), "review" (source_id), "promote" (source_id, target? default "all"), "synthesize" (source_id). Model-backed actions are LONG-RUNNING.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| action | string | 是 | ["extract","analyze_v2","status_v2","retry_v2","synthesize_v2","profile_v2","promotion_preview_v2","promote_v2","review","promote","synthesize"]；The source operation. |
| source_id | string | 否 | Source pack id. |
| content | string | 否 | Source text (extract/analyze_v2). |
| focus | json | 否 | "style"/"setting" string for extract; array of focus names for analyze_v2. |
| relative_name | string | 否 | Display filename (analyze_v2, default "source.txt"). |
| input_budget_tokens | integer | 否 | Token budget per analysis chunk (default 12000). |
| chunk_id | string | 否 | Chunk to retry (retry_v2). |
| source_ids | array[string] | 否 | Sources to synthesize (synthesize_v2). |
| profile_id | string | 否 | Analysis profile id (profile_v2/promotion_preview_v2). |
| target | string | 否 | Promotion target (promotion_preview_v2/promote, default "all"). |
| preview_id | string | 否 | Promotion preview id (promote_v2). |
| confirm | boolean | 否 | Confirm a gated promotion (default false). |

## novel_status

Get a snapshot of the current OpenWrite novel project: title, chapters, word counts, writing targets, and focus compass.

影响：只读查询（可更新检索缓存）。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| 无 | — | — | — |

## novel_structured_change_plan

Stage one structured OpenWrite domain change without writing it. Supported change_kind values are "outline", "asset", "focus", "foreshadowing", and "writing_targets"; `change` uses the corresponding direct tool payload. Use action "preview" to receive an immutable token and entity-level before/after summary. Only after author acceptance pass that token unchanged to "apply". "reject" consumes it, "retry" rebuilds the same semantic change against current source, and "undo" accepts only the revision-bound undo token returned by apply. The server writes the exact validated preview and rejects source conflicts.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| action | string | 是 | ["preview","apply","reject","retry","undo"]；Plan lifecycle action. |
| change_kind | string | 否 | ["outline","asset","focus","foreshadowing","writing_targets"]；Structured domain for a preview. |
| change | json | 否 | One direct-tool-shaped change object, required for preview. |
| preview_token | string | 否 | Immutable preview or undo token for apply/reject/retry/undo. |

## novel_sync

Synchronize derived caches that are direct src derivatives: outline hierarchy (data/hierarchy.yaml) and character cards (data/characters/cards/*.yaml). It does NOT rebuild chapter memory / runtime truth / character state: those are produced by the chapter-write settlement, so imported or pre-existing chapters need a one-time novel_settle_backfill. The sync response also reports memory_missing / memory_missing_count.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| 无 | — | — | — |

## novel_task_cancel

Request cancellation of a queued or running task. Check cancelled and cancellation_status for the actual outcome; poll novel_task_get while cancellation is requested.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| wait_seconds | number | 否 | Wait up to 30 seconds for actual cancellation; running model calls may finish later. |
| task_id | string | 是 | Task id (tsk_*). |

## novel_task_confirm

Confirm a background task that is awaiting confirmation (e.g. a continuous_write run paused between chapters), letting it resume.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| task_id | string | 是 | Task id (tsk_*). |

## novel_task_create

Queue a background AI task and return immediately; poll with novel_task_get. Task types and their `input` keys: chapter_write {chapter_id?, guidance?, target_words?, temperature?, outline_revision?}; chapter_review {chapter_id | path, strict?, dimensions?}; revision_selection / revision_from_review (same inputs as the novel_revision_create_* tools); source_operation / reference_operation (same inputs as novel_source_action / novel_reference_library_action); manuscript_import (same input as novel_import); research {prompt, search?, language?, quality?, llm?}; manuscript_reconcile (durable acceptance analysis; usually started through novel_manuscript_acceptance_reconcile); settle_backfill {chapter_ids?, only_missing?} — prefer the novel_settle_backfill convenience tool; continuous_write — prefer the novel_multi_write convenience tool.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| type | string | 是 | ["chapter_write","chapter_review","revision_selection","revision_from_review","source_operation","reference_operation","manuscript_import","manuscript_reconcile","continuous_write","research","settle_backfill"]；Task type. |
| input | json | 是 | Task input object; shape depends on the task type (see description). |

## novel_task_get

Get one background task with its event log by task id (tsk_*). Completed chapter write/review/revision tasks refresh the chapter-delivery DoG graph; chapter reviews also materialize the 37-dimension graph.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| task_id | string | 是 | Task id (tsk_*). |

## novel_task_retry

Retry a failed or cancelled background task.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| task_id | string | 是 | Task id (tsk_*). |

## novel_tasks_list

List background tasks (queued/running/finished AI jobs) with per-status counts.

影响：只读查询（可更新检索缓存）。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| since | string | 否 | ISO timestamp filter for requests whose response was lost. |
| limit | integer | 否 | Maximum number of tasks (server default 100). |

## novel_trace_list

Inspect recent redacted Prompt→context→model→tool→domain traces. Raw prompts, context, model output, credentials, chain-of-thought, and mutation values are never stored.

影响：只读查询（可更新检索缓存）。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| limit | number | 否 | Maximum records to return (1-100, default 20). |

## novel_write_chapter

Queue a chapter write and immediately return a durable task_id. Poll novel_task_get for progress/result. Omit chapter_id to write the outline-recommended next chapter; a given chapter_id must match the current recommendation. Preview context first with novel_context_preview and consult novel_outline_read for the recommendation. Cancel with novel_task_cancel. Generated partial prose is retained; resume_from_draft continues it in a new run when the source/context revisions still match.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| dry_run | boolean | 否 | Only assemble the current writer input and per-document sizes; no model call and no writing task. Guidance and target_words are included in this preview. |
| run_id_v2 | string | 否 | Resume this completed draft without generating it again. |
| resume_from_draft | boolean | 否 | Resume the latest uncommitted draft for this chapter. |
| target_words | integer | 否 | Target word count, 200-50000. When omitted use the outline target, then default 3000. |
| guidance | string | 否 | Writing guidance for this chapter (plot beats, tone, POV notes). |
| chapter_id | string | 否 | Chapter id to write; must equal the current outline recommendation. Omit for the next chapter. |
| temperature | number | 否 | Sampling temperature (default 0.7). |
| outline_revision | string | 否 | Optional outline revision guard from novel_outline_read; the server rejects the write if the outline changed. |

## novel_writing_assets

Read or save shared project terminology, review_terms toggle, concrete noun lexicon, overlap_threshold and character_groups. Anchors are Markdown files in the novel anchor/ directory. Save requires the revision returned by get. Character groups are optional descriptive material; retain identity and canonical state in character cards.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| action | string | 是 | ["get","save","save_anchor","mark_usage"]；Asset operation. |
| assets | json | 否 | Object: terms [{term, forbidden?, replacement?, min_occurrences?, example?}], character_groups {name: [{id,text}]}, review_terms?, concrete_nouns?, overlap_threshold?. |
| expected_revision | string | 否 | Revision from get; empty for a new asset table. |
| name | string | 否 | save_anchor: simple .md filename. |
| content | string | 否 | save_anchor: Markdown reference prose. |
| chapter_id | string | 否 | mark_usage: chapter whose optional character details were used. |
| groups | json | 否 | mark_usage: character name to group IDs used in this chapter. |

## novel_writing_targets

Immediate compatibility write for targets the author has already authorized exactly; otherwise use novel_structured_change_plan. Update the project writing targets. Ranges: book_words 10000-5000000, chapter_words 200-50000, outline_volume_words 100-5000, outline_act_words 80-3000, outline_section_words 50-2000, outline_chapter_words 30-1000. Omitted fields keep their current values.

影响：会提交操作或保存文件；具体取决于 action/参数。

| 参数 | 类型 | 必填 | 允许值 / 说明 |
| --- | --- | --- | --- |
| book_words | integer | 否 | Whole-book target word count. |
| chapter_words | integer | 否 | Default words per chapter. |
| outline_volume_words | integer | 否 | Outline summary words per volume. |
| outline_act_words | integer | 否 | Outline summary words per act. |
| outline_section_words | integer | 否 | Outline summary words per section. |
| outline_chapter_words | integer | 否 | Outline summary words per chapter. |
