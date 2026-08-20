/** `studio-panel` namespace dictionaries (view tab labels + panel states). */

/** Dictionary namespace owned by this plugin. */
export const NS = 'studio-panel'

/** The studio-panel dictionary key set (the source of truth for both locales). */
export type StudioPanelKey =
  | 'view.studio'
  | 'view.outline'
  | 'view.assets'
  | 'view.tasks'
  | 'view.graph'
  | 'resolving'
  | 'loading'
  | 'unreachable'
  | 'retry'
  | 'refresh'
  | 'openExternal'
  | 'outline.empty'
  | 'outline.drafted'
  | 'outline.planned'
  | 'outline.draftedCount'
  | 'assets.empty'
  | 'assets.other'
  | 'assets.stages'
  | 'assets.aliases'
  | 'assets.segment.characters'
  | 'assets.segment.world'
  | 'assets.segment.progression'
  | 'assets.segment.references'
  | 'assets.segment.core'
  | 'assets.segment.empty'
  | 'assets.references.empty'
  | 'assets.core.empty'
  | 'assets.detail.loading'
  | 'assets.detail.relations'
  | 'assets.relation.confirmed'
  | 'assets.relation.registered'
  | 'assets.relation.incoming'
  | 'assets.searchPlaceholder'
  | 'assets.edit.open'
  | 'assets.edit.name'
  | 'assets.edit.summary'
  | 'assets.edit.tags'
  | 'assets.edit.listHint'
  | 'assets.edit.save'
  | 'assets.edit.saving'
  | 'assets.edit.cancel'
  | 'assets.edit.conflict'
  | 'assets.edit.conflictRefresh'
  | 'assets.edit.addRelation'
  | 'assets.edit.removeRelation'
  | 'assets.edit.relationTarget'
  | 'assets.edit.relationNote'
  | 'assets.edit.derivedRelations'
  | 'assets.create.open'
  | 'assets.create.submit'
  | 'assets.create.idHint'
  | 'assets.create.tier'
  | 'assets.create.type'
  | 'assets.create.progressionKind'
  | 'assets.create.stages'
  | 'assets.create.stageId'
  | 'assets.create.stageName'
  | 'assets.create.addStage'
  | 'tasks.empty'
  | 'tasks.filter.all'
  | 'tasks.attempt'
  | 'tasks.status.pending'
  | 'tasks.status.running'
  | 'tasks.status.awaiting_confirmation'
  | 'tasks.status.completed'
  | 'tasks.status.failed'
  | 'tasks.status.cancelled'
  | 'tasks.status.interrupted'
  | 'tasks.phase.queued'
  | 'tasks.phase.reading'
  | 'tasks.phase.preparing'
  | 'tasks.phase.model'
  | 'tasks.phase.validating'
  | 'tasks.phase.committing'
  | 'tasks.phase.complete'
  | 'tasks.type.chapter_write'
  | 'tasks.type.chapter_review'
  | 'tasks.type.continuous_write'
  | 'tasks.type.revision'
  | 'tasks.type.source_operation'
  | 'tasks.type.reference_operation'
  | 'tasks.type.manuscript_import'
  | 'tasks.type.research'
  | 'graph.foreshadowing'
  | 'graph.relationships'
  | 'graph.weight'
  | 'graph.target'
  | 'graph.truncated'
  | 'graph.validation.errors'
  | 'graph.empty.foreshadowing'
  | 'graph.empty.relationships'
  | 'graph.kind.character'
  | 'graph.kind.faction'
  | 'graph.kind.place'
  | 'graph.kind.concept'
  | 'graph.kind.other'
  | 'assets.references'
  | 'reference.intent.reference'
  | 'reference.intent.continuation'
  | 'reference.intent.canon'
  | 'reference.intent.migration'
  | 'reference.structure.awaiting_confirmation'
  | 'reference.structure.confirmed'
  | 'reference.analysis.complete'
  | 'reference.analysis.pending'
  | 'reference.chars'
  | 'review.running'
  | 'review.passed'
  | 'review.failed'
  | 'review.score'
  | 'review.issues'
  | 'review.suggestion'
  | 'review.quote'
  | 'review.dimension'
  | 'review.severity.blocker'
  | 'review.severity.high'
  | 'review.severity.medium'
  | 'review.severity.low'
  | 'review.rawTitle'

declare module '@deepseek-ai/dsh-client-ui-slots' {
  interface LocaleNamespaceMap {
    /** The 稿件/大纲/资产 view tab labels and panel state strings. */
    'studio-panel': StudioPanelKey
  }
}

/** Simplified Chinese dictionary (the key-set source of truth). */
export const zh: Record<StudioPanelKey, string> = {
  'view.studio': '稿件',
  'view.outline': '大纲',
  'view.assets': '资产',
  'view.tasks': '任务',
  'view.graph': '图谱',
  resolving: '正在读取 Studio 配置…',
  loading: '正在连接 OpenWrite Studio…',
  unreachable: '无法连接 OpenWrite Studio。请确认 Studio 已启动（默认 http://127.0.0.1:4567）。',
  retry: '重试',
  refresh: '刷新',
  openExternal: '在新标签页打开',
  'outline.empty': '大纲为空。在 Studio 中创建 src/outline.md 后刷新。',
  'outline.drafted': '已成稿',
  'outline.planned': '待写',
  'outline.draftedCount': '已成稿章节',
  'assets.empty': '暂无资产。让 agent 用 novel_asset_* 工具创建后刷新。',
  'assets.other': '其他',
  'assets.stages': '阶段',
  'assets.aliases': '别名',
  'assets.segment.characters': '角色',
  'assets.segment.world': '设定',
  'assets.segment.progression': '进阶体系',
  'assets.segment.references': '参考作品',
  'assets.segment.core': '作品核心',
  'assets.segment.empty': '该分类暂无条目。',
  'assets.references.empty': '暂无参考作品。让 agent 用 novel_reference_* 工具导入后刷新。',
  'assets.core.empty': '作品核心为空。让 agent 先完成创作承诺与故事基础。',
  'assets.detail.loading': '加载详情…',
  'assets.detail.relations': '关系',
  'assets.relation.confirmed': '确认',
  'assets.relation.registered': '注记',
  'assets.relation.incoming': '被关联',
  'assets.searchPlaceholder': '搜索名称 / ID / 类型 / 别名 / 标签 / 摘要…',
  'assets.edit.open': '编辑',
  'assets.edit.name': '名称',
  'assets.edit.summary': '摘要',
  'assets.edit.tags': '标签',
  'assets.edit.listHint': '用逗号或顿号分隔',
  'assets.edit.save': '保存',
  'assets.edit.saving': '保存中…',
  'assets.edit.cancel': '取消',
  'assets.edit.conflict': '资产已在其他位置修改，请重新载入后再改。',
  'assets.edit.conflictRefresh': '刷新重试',
  'assets.edit.addRelation': '添加关系',
  'assets.edit.removeRelation': '移除',
  'assets.edit.relationTarget': '目标资产 ID',
  'assets.edit.relationNote': '关系说明',
  'assets.edit.derivedRelations': '派生关系（只读；请在对方资产上编辑）',
  'assets.create.open': '新建',
  'assets.create.submit': '创建',
  'assets.create.idHint': '字母或数字开头，可含 _ . -',
  'assets.create.tier': '位阶',
  'assets.create.type': '类型',
  'assets.create.progressionKind': '体系类型',
  'assets.create.stages': '阶段',
  'assets.create.stageId': '阶段 ID',
  'assets.create.stageName': '阶段名称',
  'assets.create.addStage': '添加阶段',
  'review.running': '评审进行中…',
  'review.passed': '通过',
  'review.failed': '未通过',
  'review.score': '得分',
  'review.issues': '问题',
  'review.suggestion': '修改建议',
  'review.quote': '原文引用',
  'review.dimension': '维度',
  'review.severity.blocker': '阻塞',
  'review.severity.high': '高',
  'review.severity.medium': '中',
  'review.severity.low': '低',
  'review.rawTitle': '原始输出',
  'tasks.empty': '暂无任务。agent 启动写章/评审等后台任务后会出现在这里。',
  'tasks.filter.all': '全部',
  'tasks.attempt': '尝试',
  'tasks.status.pending': '排队',
  'tasks.status.running': '运行中',
  'tasks.status.awaiting_confirmation': '待确认',
  'tasks.status.completed': '已完成',
  'tasks.status.failed': '失败',
  'tasks.status.cancelled': '已取消',
  'tasks.status.interrupted': '已中断',
  'tasks.phase.queued': '排队中',
  'tasks.phase.reading': '读取',
  'tasks.phase.preparing': '准备',
  'tasks.phase.model': '生成',
  'tasks.phase.validating': '校验',
  'tasks.phase.committing': '提交',
  'tasks.phase.complete': '完成',
  'tasks.type.chapter_write': '写章',
  'tasks.type.chapter_review': '评审',
  'tasks.type.continuous_write': '连写',
  'tasks.type.revision': '修订',
  'tasks.type.source_operation': '风格源',
  'tasks.type.reference_operation': '参考库',
  'tasks.type.manuscript_import': '导入',
  'tasks.type.research': '研究',
  'graph.foreshadowing': '伏笔',
  'graph.relationships': '关系图',
  'graph.weight': '权重',
  'graph.target': '回收',
  'graph.truncated': '结果已被服务端截断',
  'graph.validation.errors': '伏笔 DAG 校验错误',
  'graph.empty.foreshadowing': '暂无待回收伏笔。让 agent 用 novel_foreshadowing_* 埋设后刷新。',
  'graph.empty.relationships': '暂无关系数据。建立资产关系后刷新（或调整上方类型过滤）。',
  'graph.kind.character': '角色',
  'graph.kind.faction': '势力',
  'graph.kind.place': '地点',
  'graph.kind.concept': '概念',
  'graph.kind.other': '其他',
  'assets.references': '参考作品',
  'reference.intent.reference': '参考',
  'reference.intent.continuation': '续写',
  'reference.intent.canon': '正典',
  'reference.intent.migration': '迁移',
  'reference.structure.awaiting_confirmation': '结构待确认',
  'reference.structure.confirmed': '结构已确认',
  'reference.analysis.complete': '分析完成',
  'reference.analysis.pending': '分析未完成',
  'reference.chars': '字符',
}

/** English dictionary. */
export const en: Record<StudioPanelKey, string> = {
  'view.studio': 'Manuscript',
  'view.outline': 'Outline',
  'view.assets': 'Assets',
  'view.tasks': 'Tasks',
  'view.graph': 'Graph',
  resolving: 'Reading Studio configuration…',
  loading: 'Connecting to OpenWrite Studio…',
  unreachable: 'OpenWrite Studio is unreachable. Make sure Studio is running (default http://127.0.0.1:4567).',
  retry: 'Retry',
  refresh: 'Refresh',
  openExternal: 'Open in new tab',
  'outline.empty': 'The outline is empty. Create src/outline.md in Studio, then refresh.',
  'outline.drafted': 'Drafted',
  'outline.planned': 'Planned',
  'outline.draftedCount': 'Drafted chapters',
  'assets.empty': 'No assets yet. Ask the agent to create some with the novel_asset_* tools, then refresh.',
  'assets.other': 'Other',
  'assets.stages': 'stages',
  'assets.aliases': 'Aliases',
  'assets.segment.characters': 'Characters',
  'assets.segment.world': 'World',
  'assets.segment.progression': 'Progression',
  'assets.segment.references': 'References',
  'assets.segment.core': 'Story Core',
  'assets.segment.empty': 'Nothing in this section yet.',
  'assets.references.empty': 'No reference works yet. Ask the agent to import some with the novel_reference_* tools, then refresh.',
  'assets.core.empty': 'The story core is empty. Ask the agent to draft the author intent and story foundation first.',
  'assets.detail.loading': 'Loading details…',
  'assets.detail.relations': 'Relations',
  'assets.relation.confirmed': 'Confirmed',
  'assets.relation.registered': 'Annotation',
  'assets.relation.incoming': 'Incoming',
  'assets.searchPlaceholder': 'Search name / id / type / aliases / tags / summary…',
  'assets.edit.open': 'Edit',
  'assets.edit.name': 'Name',
  'assets.edit.summary': 'Summary',
  'assets.edit.tags': 'Tags',
  'assets.edit.listHint': 'Separate with commas',
  'assets.edit.save': 'Save',
  'assets.edit.saving': 'Saving…',
  'assets.edit.cancel': 'Cancel',
  'assets.edit.conflict': 'This asset changed elsewhere. Reload it before editing again.',
  'assets.edit.conflictRefresh': 'Reload & retry',
  'assets.edit.addRelation': 'Add relation',
  'assets.edit.removeRelation': 'Remove',
  'assets.edit.relationTarget': 'Target asset id',
  'assets.edit.relationNote': 'Relation note',
  'assets.edit.derivedRelations': 'Derived relations (read-only; edit them on the owning asset)',
  'assets.create.open': 'New',
  'assets.create.submit': 'Create',
  'assets.create.idHint': 'Starts with a letter or digit; may contain _ . -',
  'assets.create.tier': 'Tier',
  'assets.create.type': 'Type',
  'assets.create.progressionKind': 'System kind',
  'assets.create.stages': 'Stages',
  'assets.create.stageId': 'Stage id',
  'assets.create.stageName': 'Stage name',
  'assets.create.addStage': 'Add stage',
  'review.running': 'Reviewing…',
  'review.passed': 'Passed',
  'review.failed': 'Needs revision',
  'review.score': 'Score',
  'review.issues': 'Issues',
  'review.suggestion': 'Suggestion',
  'review.quote': 'Quote',
  'review.dimension': 'Dimension',
  'review.severity.blocker': 'Blocker',
  'review.severity.high': 'High',
  'review.severity.medium': 'Medium',
  'review.severity.low': 'Low',
  'review.rawTitle': 'Raw output',
  'tasks.empty': 'No tasks yet. Background jobs the agent starts (chapter writing, review, …) will show up here.',
  'tasks.filter.all': 'All',
  'tasks.attempt': 'Attempt',
  'tasks.status.pending': 'Queued',
  'tasks.status.running': 'Running',
  'tasks.status.awaiting_confirmation': 'Awaiting confirmation',
  'tasks.status.completed': 'Completed',
  'tasks.status.failed': 'Failed',
  'tasks.status.cancelled': 'Cancelled',
  'tasks.status.interrupted': 'Interrupted',
  'tasks.phase.queued': 'Queued',
  'tasks.phase.reading': 'Reading',
  'tasks.phase.preparing': 'Preparing',
  'tasks.phase.model': 'Generating',
  'tasks.phase.validating': 'Validating',
  'tasks.phase.committing': 'Committing',
  'tasks.phase.complete': 'Done',
  'tasks.type.chapter_write': 'Write',
  'tasks.type.chapter_review': 'Review',
  'tasks.type.continuous_write': 'Continuous write',
  'tasks.type.revision': 'Revision',
  'tasks.type.source_operation': 'Style source',
  'tasks.type.reference_operation': 'Reference',
  'tasks.type.manuscript_import': 'Import',
  'tasks.type.research': 'Research',
  'graph.foreshadowing': 'Foreshadowing',
  'graph.relationships': 'Relationships',
  'graph.weight': 'Weight',
  'graph.target': 'Target',
  'graph.truncated': 'Results truncated server-side',
  'graph.validation.errors': 'Foreshadowing DAG validation errors',
  'graph.empty.foreshadowing': 'No pending foreshadowing. Ask the agent to plant some with novel_foreshadowing_*, then refresh.',
  'graph.empty.relationships': 'No relationship data. Create asset relations and refresh (or adjust the kind filters above).',
  'graph.kind.character': 'Characters',
  'graph.kind.faction': 'Factions',
  'graph.kind.place': 'Places',
  'graph.kind.concept': 'Concepts',
  'graph.kind.other': 'Other',
  'assets.references': 'References',
  'reference.intent.reference': 'Reference',
  'reference.intent.continuation': 'Continuation',
  'reference.intent.canon': 'Canon',
  'reference.intent.migration': 'Migration',
  'reference.structure.awaiting_confirmation': 'Structure pending',
  'reference.structure.confirmed': 'Structure confirmed',
  'reference.analysis.complete': 'Analyzed',
  'reference.analysis.pending': 'Analysis incomplete',
  'reference.chars': 'chars',
}
