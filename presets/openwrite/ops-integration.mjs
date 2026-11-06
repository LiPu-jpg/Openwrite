// dsh-ops preset integration. The row that mounts this module is only added
// when dsh-ops is installed, its declared host range covers the running host,
// and it exposes `dsh-ops/integration`. The import is still defensive: a
// companion that changed its entry between detection and load must degrade to
// a no-op row rather than take the whole preset composition down.
export const name = '@dsh-novel/openwrite-ops'

export async function apply(ctx) {
  let integration
  try {
    ({ integration } = await import('dsh-ops/integration'))
  } catch {
    ctx.effect(() => () => {}, 'openwrite-ops: dsh-ops integration unavailable')
    return
  }
  // Bounded file tools plus progressive discovery for the OpenWrite preset.
  // Official file tools stay available (`replaceOfficial: false`), no shell is
  // published (`shell: false`), and the preset's own guidance is not replaced.
  const plugin = integration({
    preset: 'openwrite',
    files: true,
    discovery: true,
    presentation: 'native',
    replaceOfficial: false,
    shell: false,
  })
  return plugin.apply(ctx)
}
