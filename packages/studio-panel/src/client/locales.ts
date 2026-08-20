/** `studio-panel` namespace dictionaries (view tab label + panel states). */

/** Dictionary namespace owned by this plugin. */
export const NS = 'studio-panel'

/** The studio-panel dictionary key set (the source of truth for both locales). */
export type StudioPanelKey =
  | 'view.studio'
  | 'resolving'
  | 'loading'
  | 'unreachable'
  | 'retry'
  | 'openExternal'

declare module '@deepseek-ai/dsh-client-ui-slots' {
  interface LocaleNamespaceMap {
    /** The 稿件 view tab label and panel state strings. */
    'studio-panel': StudioPanelKey
  }
}

/** Simplified Chinese dictionary (the key-set source of truth). */
export const zh: Record<StudioPanelKey, string> = {
  'view.studio': '稿件',
  resolving: '正在读取 Studio 配置…',
  loading: '正在连接 OpenWrite Studio…',
  unreachable: '无法连接 OpenWrite Studio。请确认 Studio 已启动（默认 http://127.0.0.1:4567）。',
  retry: '重试',
  openExternal: '在新标签页打开',
}

/** English dictionary. */
export const en: Record<StudioPanelKey, string> = {
  'view.studio': 'Manuscript',
  resolving: 'Reading Studio configuration…',
  loading: 'Connecting to OpenWrite Studio…',
  unreachable: 'OpenWrite Studio is unreachable. Make sure Studio is running (default http://127.0.0.1:4567).',
  retry: 'Retry',
  openExternal: 'Open in new tab',
}
