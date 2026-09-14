import { render } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { HeaderProjectStatus } from '../../src/client/HeaderChrome.tsx'

const state = vi.hoisted(() => ({ projectTitle: '雾城', connection: 'connected', chapters: [], activeChapterPath: '', editorStatus: 'idle', activeTasks: 0 }))
vi.mock('../../src/client/WorkbenchStore.ts', () => ({ useWorkbench: () => state, workbenchStore: {} }))

describe('header editor status', () => {
  it('does not label a connected project unopened before mounting the editor', () => {
    state.editorStatus = 'idle'
    const { container } = render(<HeaderProjectStatus {...({ t: (key: string) => key } as any)} />)
    expect(container.textContent).toContain('雾城')
    expect(container.querySelector('[data-save]')).toBeNull()
    expect(container.querySelector('[data-state="connected"]')).not.toBeNull()
  })
  it('still shows unsaved manuscript changes', () => {
    state.editorStatus = 'dirty'
    const { container } = render(<HeaderProjectStatus {...({ t: (key: string) => key } as any)} />)
    expect(container.querySelector('[data-save="dirty"]')?.textContent).toBe('creation.status.dirty')
  })
})
