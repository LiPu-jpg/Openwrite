/** `studio-panel` namespace dictionaries (view tab labels + panel states). */

/** Dictionary namespace owned by this plugin. */
export const NS = 'studio-panel'

/** The studio-panel dictionary key set (the source of truth for both locales). */
export type StudioPanelKey =
  | 'view.studio'
  | 'view.outline'
  | 'view.assets'
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
  | 'assets.character'
  | 'assets.world'
  | 'assets.progression'
  | 'assets.other'
  | 'assets.stages'
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
  'assets.character': '角色',
  'assets.world': '世界',
  'assets.progression': '成长体系',
  'assets.other': '其他',
  'assets.stages': '阶段',
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
}

/** English dictionary. */
export const en: Record<StudioPanelKey, string> = {
  'view.studio': 'Manuscript',
  'view.outline': 'Outline',
  'view.assets': 'Assets',
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
  'assets.character': 'Characters',
  'assets.world': 'World',
  'assets.progression': 'Progression',
  'assets.other': 'Other',
  'assets.stages': 'stages',
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
}
