export const name = '@dsh-novel/openwrite-dog-tools'
export const inject = ['tools', 'openwriteDog']
export function apply(ctx) {
  for (const tool of ctx.openwriteDog.tools) ctx.effect(() => ctx.tools.register(tool))
  ctx.effect(() => ctx.tools.guard(execution => {
    if (!execution.name.startsWith('dog_') || ['dog_status', 'dog_wait', 'dog_validate'].includes(execution.name)) return
    if (!execution.agent) return 'DOG_AGENT_SESSION_REQUIRED: DoG execution requires an Agent session; run this tool inside a writing Agent session.'
    if (execution.agent.ctx.get('planMode')?.get(execution.agent)?.active) return 'DOG_PLAN_MODE: DoG execution is disabled in plan mode; leave plan mode before running it.'
    const policy = ctx.get('sandboxPolicy')
    if (!policy) return 'DOG_SANDBOX_POLICY_UNAVAILABLE: The host sandbox policy service is unavailable; check the host configuration.'
    if (policy.resolve({ session: execution.agent.session }).mode === 'read-only') return 'DOG_READ_ONLY: DoG execution requires a writable session; the current sandbox is read-only.'
  }))
}
