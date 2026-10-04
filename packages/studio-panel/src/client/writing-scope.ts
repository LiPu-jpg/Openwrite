import type { SessionListState } from '@deepseek-ai/dsh-api-session-controller/client'
import type { SessionId } from '@deepseek-ai/dsh-session'

/** Main-view retention, published on list rows from dsh 0.2 on. */
type RetainedRow = { retainedBy?: Readonly<Partial<Record<string, number>>> }
/** Older hosts publish the displayed session as a list-level `current` instead. */
type LegacyList = { current?: SessionId }

/**
 * Presentation follows the session the main view is displaying; the host tool
 * catalog never follows UI navigation.
 *
 * dsh 0.2 removed `SessionListState.current` — showing a session moved to
 * `UiWorkspace.openSession` — so the displayed session is read from the row's
 * own main-view retention, the same criterion `dsh-client-ui-agent-preset`
 * uses. Hosts that still publish `current` keep their previous behaviour.
 */
export function isWritingSession(state: SessionListState): boolean {
  const retained = state.ids.find(id => (((state.byId[id] as RetainedRow | undefined)?.retainedBy?.mainView) ?? 0) > 0)
  const displayed = retained ?? (state as SessionListState & LegacyList).current
  const preset = displayed === undefined ? null : state.byId[displayed]?.projectionValues?.agentPreset
  return typeof preset === 'string' && (preset === 'openwrite' || preset.startsWith('openwrite-'))
}

export function watchWritingScope(
  source: { getSnapshot(): SessionListState; subscribe(listener: () => void): () => void },
  mount: () => (() => void),
): () => void {
  let dispose: (() => void) | undefined
  const refresh = () => {
    const enabled = isWritingSession(source.getSnapshot())
    if (enabled && !dispose) dispose = mount()
    if (!enabled && dispose) { dispose(); dispose = undefined }
  }
  const unsubscribe = source.subscribe(refresh)
  try { refresh() } catch (error) { unsubscribe(); throw error }
  return () => { unsubscribe(); dispose?.() }
}
