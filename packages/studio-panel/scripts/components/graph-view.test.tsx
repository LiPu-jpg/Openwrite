/**
 * Graph/DAG epoch-driven refetch (component layer, offline).
 *
 * GraphView mounts the review/delivery DAG views with `key={epochs.tasks}`:
 * a tasks mutation bumps the epoch, remounts ReviewDagView, and the remount
 * refetches `/dog/graphs`. These tests pin that loop with:
 *   - the WorkbenchStore module mocked to a controllable epoch snapshot;
 *   - `@xyflow/react` and `elkjs` mocked (canvas rendering/layout are
 *     browser-QA territory; the fetch/remount contract is what matters here);
 *   - `fetchStudioApi` counted per path.
 */
import { useState } from 'react'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { GraphView } from '../../src/client/GraphView.tsx'

/** Mutable epoch state shared with the WorkbenchStore mock. */
const harness = vi.hoisted(() => ({ tasksEpoch: 0 }))

vi.mock('../../src/client/WorkbenchStore.ts', () => ({
  useWorkbench: () => ({
    context: null,
    contextEpoch: 0,
    workspaceError: null,
    epochs: {
      workspace: 0, manuscript: 0, outline: 0, assets: 0,
      tasks: harness.tasksEpoch, benchmark: 0, models: 0,
      dag: 0, graph: 0, research: 0, revisions: 0,
    },
  }),
}))

vi.mock('@deepseek-ai/dsh-client-ui-primitives', () => ({
  MarkdownText: ({ text }: { text: string }) => <div>{text}</div>,
}))

vi.mock('@xyflow/react', () => ({
  ReactFlow: ({ nodes, children }: { nodes?: { id: string; data?: { label?: unknown } }[]; children?: unknown }) => (
    <div data-testid="react-flow">
      {(nodes ?? []).map(node => <div key={node.id} data-node-id={node.id}>{node.data?.label as never}</div>)}
      {children as never}
    </div>
  ),
  Background: () => null,
  BackgroundVariant: { Dots: 'dots' },
  Controls: () => null,
  MarkerType: { ArrowClosed: 'arrowclosed' },
  useNodesState: (initial: unknown) => useState(initial),
  useEdgesState: (initial: unknown) => useState(initial),
}))

vi.mock('elkjs/lib/elk.bundled.js', () => ({
  default: class ElkStub {
    async layout(graph: { children?: { id: string }[] }) {
      return { children: (graph.children ?? []).map((child, index) => ({ id: child.id, x: index * 240, y: 0 })) }
    }
  },
}))

const t = (key: string): string => key

const CONTINUITY = {
  truth: { current_state: '', ledger: '', relationships: '' },
  foreshadowing: { nodes: [], total: 0 },
  foreshadowing_validation: { valid: true, errors: [] },
  relationship_graph: { nodes: [], edges: [], truncated: false },
  workflows: [],
}

const DOG_SURFACE = {
  chapter_id: 'ch_001',
  chapters: ['ch_001'],
  review_framework: {
    id: 'openwrite.standard-chapter-review', version: '1.0.0',
    revision: `sha256:${'a'.repeat(64)}`,
    invariants: { domain_count: 6, legacy_check_count: 37, criterion_count: 20 },
  },
  review: {
    graph: {
      root: 'root',
      nodes: { root: { title: '交付决策' }, context: { title: '上下文完整性' } },
      contains: [{ parent: 'root', child: 'context' }],
      dependsOn: [{ source: 'root', target: 'context' }],
    },
    manifest: { qualityScore: 80, coverage: 0.9, gateStatus: 'pass', deliveryStatus: 'advisory_pass' },
    records: { context: { status: 'pass' } },
  },
  delivery: null,
}

function makeApi() {
  const dogCalls: string[] = []
  const fetchStudioApi = vi.fn(async (path: string) => {
    if (path === '/continuity') return CONTINUITY
    if (path.startsWith('/dog/graphs')) {
      dogCalls.push(path)
      return DOG_SURFACE
    }
    throw new Error(`unexpected GET ${path}`)
  })
  return { fetchStudioApi, dogCalls }
}

function renderView(api: ReturnType<typeof makeApi>) {
  const props = {
    fetchStudioApi: api.fetchStudioApi,
    postStudioApi: vi.fn(async () => ({})),
    t,
  }
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return render(<GraphView {...(props as any)} />)
}

describe('GraphView DAG epoch refresh', () => {
  beforeEach(() => {
    harness.tasksEpoch = 0
  })

  it('refetches /dog/graphs when the tasks epoch bumps', async () => {
    const api = makeApi()
    const view = renderView(api)

    // Continuity loads on mount, then switch to the review DAG segment.
    await screen.findByText(/graph\.reviewDag/)
    fireEvent.click(screen.getByText(/graph\.reviewDag/))

    // DAG surface loads and renders the mocked canvas nodes. (ReviewDagView
    // fetches twice on mount: once with chapter='', then again after it
    // adopts the server-returned chapter — both land before settle.)
    await screen.findByText('交付决策')
    expect(screen.getByText(/graph\.reviewFramework v1\.0\.0/).textContent).toContain(
      '6 graph.reviewDomains · 37 graph.reviewChecks · 20 graph.reviewCriteria',
    )
    expect(api.dogCalls.length).toBeGreaterThanOrEqual(1)
    expect(api.dogCalls[0]).toBe('/dog/graphs')
    const settled = api.dogCalls.length

    // A tasks mutation bumps epochs.tasks → key remount → refetch.
    harness.tasksEpoch = 1
    view.rerender(
      <GraphView
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        {...({ fetchStudioApi: api.fetchStudioApi, postStudioApi: vi.fn(async () => ({})), t } as any)}
      />,
    )
    await waitFor(() => expect(api.dogCalls.length).toBeGreaterThan(settled))

    // Without an epoch change there is no further refetch.
    const refetched = api.dogCalls.length
    await screen.findByText('交付决策')
    expect(api.dogCalls.length).toBe(refetched)
  })

  it('fetches /continuity exactly once on mount', async () => {
    const api = makeApi()
    renderView(api)
    await waitFor(() => expect(api.fetchStudioApi).toHaveBeenCalledWith('/continuity'))
    await screen.findByText(/graph\.reviewDag/)
    const continuityCalls = api.fetchStudioApi.mock.calls.filter(([path]) => path === '/continuity')
    expect(continuityCalls.length).toBe(1)
  })
})


describe('GraphView related people', () => {
  it('deduplicates neighbors by ID while retaining distinct same-name people and all edges', async () => {
    const api = makeApi()
    const edges = [
      { id: 'friend', source: 'a', target: 'b', label: '朋友' },
      { id: 'partner', source: 'a', target: 'b', label: '搭档' },
      { id: 'reverse', source: 'b', target: 'a', label: '信任' },
      { id: 'same-name', source: 'a', target: 'c', label: '认识' },
      { id: 'self', source: 'a', target: 'a', label: '自省' },
    ]
    api.fetchStudioApi.mockImplementation(async () => ({ ...CONTINUITY, relationship_graph: {
      nodes: [
        { id: 'a', label: '沈烬', kind: 'character' },
        { id: 'b', label: '顾衡', kind: 'character', description: '医师' },
        { id: 'c', label: '顾衡', kind: 'character', description: '守卫' },
      ], edges, truncated: false,
    } }))
    const view = renderView(api)
    fireEvent.click(await screen.findByRole('button', { name: /graph.relationships/ }))
    await waitFor(() => expect(view.container.querySelector('[data-node-id="a"]')).not.toBeNull())
    fireEvent.click(view.container.querySelector('[data-node-id="a"]')!)
    const detail = screen.getByRole('complementary')
    expect(within(detail).getAllByRole('button', { name: '顾衡' })).toHaveLength(2)
    expect(within(detail).queryByRole('button', { name: '沈烬' })).toBeNull()
    expect(view.container.querySelectorAll('[data-edge-id]')).toHaveLength(5)
    fireEvent.click(within(detail).getAllByRole('button', { name: '顾衡' })[1]!)
    expect(await screen.findByText('守卫')).not.toBeNull()
    expect(within(screen.getByRole('complementary')).getAllByRole('button', { name: '沈烬' })).toHaveLength(1)
  })
})
