import type { SessionListState } from '@deepseek-ai/dsh-api-session-controller/client'

/** Presentation follows the current session; the host tool catalog never follows UI navigation. */
export function isWritingSession(state: SessionListState): boolean {
  const preset = state.current ? state.byId[state.current]?.projectionValues?.agentPreset : null
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
  refresh()
  return () => { unsubscribe(); dispose?.() }
}
