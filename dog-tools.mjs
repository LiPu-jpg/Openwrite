export const name = '@dsh-novel/openwrite-dog-tools'
export const inject = ['tools', 'openwriteDog']
export function apply(ctx) {
  for (const tool of ctx.openwriteDog.tools) ctx.effect(() => ctx.tools.register(tool))
  ctx.effect(() => ctx.tools.guard(execution => {
    if (!execution.name.startsWith('dog_') || ['dog_status', 'dog_wait', 'dog_validate'].includes(execution.name)) return
    if (!execution.agent) return 'DoG requires an Agent session'
    if (execution.agent.ctx.get('planMode')?.get(execution.agent).active) return 'DoG execution is disabled in plan mode'
    if (!ctx.get('sandboxPolicy') || ctx.get('sandboxPolicy').resolve({ session: execution.agent.session }).mode === 'read-only') return 'DoG execution is disabled in read-only mode'
  }))
}
