import type { SessionListState } from '@deepseek-ai/dsh-api-session-controller/client'
import { describe, expect, it } from 'vitest'
import type { DogDebugSnapshot } from '../src/debug.ts'
import type { DogRun, GoalAgentSessionRef } from '../src/model.ts'
import {
  agentParentSessionIds,
  goalAgentRefs,
  goalAgentTelemetry,
  settledGoalCount,
  summarizeRunAgents,
} from '../src/client/agentTelemetry.ts'

const BOUND_AT = '2026-08-19T00:00:00.000Z'

function agent(sessionId: string, role: GoalAgentSessionRef['role'], parentSessionId?: string): GoalAgentSessionRef {
  return { sessionId, role, boundAt: BOUND_AT, ...(parentSessionId === undefined ? {} : { parentSessionId }) }
}

function run(): DogRun {
  return {
    runId: 'run-agents',
    graphId: 'agent-demo',
    graphDigest: 'digest',
    state: 'running',
    invocation: { callId: 'call', agentSessionId: 'owner', invokedAt: BOUND_AT },
    gmDigests: {},
    goals: {
      root: { state: 'success', agentSessions: [agent('owner', 'orchestrator')] },
      leaf: {
        state: 'running',
        agentSessions: [
          agent('child-a', 'verifier', 'owner'),
          agent('child-a', 'reviewer', 'owner'),
          agent('missing-child', 'verifier', 'owner'),
        ],
      },
    },
    createdAt: BOUND_AT,
    updatedAt: BOUND_AT,
  }
}

function sessions(): SessionListState {
  return {
    ids: ['owner', 'child-a'],
    byId: {
      owner: {
        id: 'owner',
        displayTitle: 'Lead Agent',
        running: false,
        blank: false,
        updatedAt: 12_000,
      },
      'child-a': {
        id: 'child-a',
        displayTitle: 'Layout Agent',
        running: true,
        blank: false,
        updatedAt: 12_000,
        projectionValues: {
          tokenUsage: {
            uncachedInputTokens: 100,
            outputTokens: 20,
            cacheReadTokens: 30,
            cacheWriteTokens: 40,
          },
          subagentTiming: {
            settledMs: 3_000,
            active: { since: 10_000, through: 12_000 },
          },
        },
      },
    },
    current: undefined,
    phase: 'ready',
    subagentsByParent: {},
    jobsBySession: {},
    currentAddress: undefined,
  } as unknown as SessionListState
}

describe('Agent telemetry projection', () => {
  it('deduplicates persisted bindings and reports live token and duration data', () => {
    const current = run()
    const state = sessions()
    expect(goalAgentRefs(current, 'leaf').map(ref => [ref.sessionId, ref.role])).toEqual([
      ['child-a', 'verifier'],
      ['missing-child', 'verifier'],
    ])

    const live = goalAgentTelemetry(goalAgentRefs(current, 'leaf')[0]!, state, 20_000)
    expect(live).toMatchObject({
      label: 'Layout Agent',
      available: true,
      running: true,
      needsInput: false,
      tokens: 190,
      durationMs: 13_000,
    })

    const missing = goalAgentTelemetry(goalAgentRefs(current, 'leaf')[1]!, state, 20_000)
    expect(missing).toMatchObject({
      label: 'Verifier Agent',
      available: false,
      running: false,
    })

    expect(summarizeRunAgents(current, state, 20_000)).toEqual({
      linked: 3,
      visible: 2,
      running: 1,
      tokens: 190,
      partialTokens: true,
    })
    expect(settledGoalCount(current)).toBe(1)
  })

  it('identifies parent catalogs needed to resolve subagent sessions', () => {
    const snapshot = { graphs: [{ runs: [run(), run()] }] } as unknown as DogDebugSnapshot
    expect(agentParentSessionIds(snapshot)).toEqual(['owner'])
  })
})
