import { useCallback, useState } from 'react'
import { BookMarked, Boxes, FlaskConical, Network, Search } from 'lucide-react'
import type { ConvViewProps } from '@deepseek-ai/dsh-client-ui-conversation/client'
import type { InjectFace, PropsLocale } from '@deepseek-ai/dsh-client-ui-slots'
import type { StudioApiInjected } from './api.ts'
import { AssetsView } from './AssetsView.tsx'
import { DiscardDraftDialog } from './DiscardDraftDialog.tsx'
import { GraphView } from './GraphView.tsx'
import { OutlineView } from './OutlineView.tsx'
import { ResearchView } from './ResearchView.tsx'
import { SearchView } from './SearchView.tsx'
import { useWorkbench } from './WorkbenchStore.ts'
import { useBindStudioContext } from './workspace-context.ts'
import css from './Workbench.module.css'

type LibraryMode = 'assets' | 'outline' | 'graph' | 'research' | 'search'

export type LibraryViewProps = ConvViewProps & InjectFace<StudioApiInjected> & PropsLocale<'studio-panel'>

/** One native library shell over canon, outline, continuity, research and search. */
export function LibraryView(props: LibraryViewProps) {
  const [mode, setMode] = useState<LibraryMode>('assets')
  const [pendingMode, setPendingMode] = useState<{ mode: LibraryMode; contextEpoch: number } | null>(null)
  const workbench = useWorkbench()
  const [assetDraft, setAssetDraft] = useState({ contextEpoch: -1, dirty: false, busy: false, discard: () => {} })
  const onAssetDraftStateChange = useCallback((state: { dirty: boolean; busy: boolean; discard: () => void }) => {
    setAssetDraft({ contextEpoch: workbench.contextEpoch, ...state })
  }, [workbench.contextEpoch])
  const currentDraft = assetDraft.contextEpoch === workbench.contextEpoch && mode === 'assets' ? assetDraft : null
  useBindStudioContext({ sessionId: props.sessionId, useWorkspaces: props.useWorkspaces })
  const items = [
    { id: 'assets' as const, icon: Boxes, label: props.t('view.assets') },
    { id: 'outline' as const, icon: BookMarked, label: props.t('view.outline') },
    { id: 'graph' as const, icon: Network, label: props.t('view.graph') },
    { id: 'research' as const, icon: FlaskConical, label: props.t('view.research') },
    { id: 'search' as const, icon: Search, label: props.t('view.search') },
  ]
  return (
    <div className={css.workspaceRoot}>
      <nav className={css.workspaceNav} aria-label={props.t('view.library')}>
        {items.map(item => <button key={item.id} type="button" data-active={mode === item.id} aria-current={mode === item.id ? 'page' : undefined}
          disabled={currentDraft?.busy === true && mode !== item.id} onClick={() => {
            if (mode === item.id || currentDraft?.busy) return
            if (currentDraft?.dirty) {
              setPendingMode({ mode: item.id, contextEpoch: workbench.contextEpoch })
              return
            }
            currentDraft?.discard()
            setMode(item.id)
          }}>
          <item.icon size={16} /><span>{item.label}</span>
        </button>)}
      </nav>
      <section className={css.workspaceContent}>
        {mode === 'assets' && <AssetsView key={workbench.contextEpoch} {...props} refreshEpoch={workbench.epochs.assets} draftContext={workbench.context ?? undefined} onDraftStateChange={onAssetDraftStateChange} />}
        {mode === 'outline' && <OutlineView key={workbench.epochs.outline} {...props} />}
        {mode === 'graph' && <GraphView key={workbench.epochs.graph} {...props} />}
        {mode === 'research' && <ResearchView key={workbench.epochs.research} {...props} />}
        {mode === 'search' && <SearchView key={workbench.epochs.workspace} {...props} />}
      </section>
      {pendingMode !== null && pendingMode.contextEpoch === workbench.contextEpoch && <DiscardDraftDialog t={props.t}
        onKeep={() => { setPendingMode(null) }}
        onDiscard={() => {
          if (currentDraft?.busy) return
          currentDraft?.discard()
          setMode(pendingMode.mode)
          setPendingMode(null)
        }} />}
    </div>
  )
}
