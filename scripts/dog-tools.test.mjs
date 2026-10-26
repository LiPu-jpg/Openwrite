import { test } from 'node:test'
import assert from 'node:assert/strict'
import { apply } from '../dog-tools.mjs'

function guard(policy) {
  let check
  apply({openwriteDog: {tools: []}, effect: fn => fn(), tools: {guard: fn => {check = fn}}, get: () => policy})
  return check
}
const agent = active => ({session: {}, ctx: {get: () => ({get: () => active === undefined ? undefined : {active}})}})

test('DoG mutation errors identify the exact unmet condition without blocking read tools', () => {
  const writable = guard({resolve: () => ({mode: 'workspace-write'})})
  assert.match(writable({name: 'dog_run'}), /DOG_AGENT_SESSION_REQUIRED/)
  assert.match(writable({name: 'dog_run', agent: agent(true)}), /DOG_PLAN_MODE/)
  assert.match(guard(undefined)({name: 'dog_run', agent: agent(false)}), /DOG_SANDBOX_POLICY_UNAVAILABLE/)
  assert.match(guard({resolve: () => ({mode: 'read-only'})})({name: 'dog_run', agent: agent(false)}), /DOG_READ_ONLY/)
  assert.equal(writable({name: 'dog_run', agent: agent(undefined)}), undefined)
  for (const name of ['dog_status', 'dog_wait', 'dog_validate', 'novel_status']) assert.equal(guard(undefined)({name}), undefined)
})
