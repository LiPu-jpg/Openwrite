/** Load only the editor resources shipped and served by this plugin. */
const resources = {
  Lute: '/studio-panel/vendor/vditor/dist/js/lute/lute.min.js',
  VditorI18n: '/studio-panel/vendor/vditor/dist/js/i18n/zh_CN.js',
} as const

type GlobalName = keyof typeof resources
const pending = new Map<GlobalName, Promise<void>>()

export function loadPackagedEditorGlobal(name: GlobalName): Promise<void> {
  const win = window as unknown as Record<string, unknown>
  if (win[name] !== undefined) return Promise.resolve()
  const current = pending.get(name)
  if (current) return current
  const promise = new Promise<void>((resolve, reject) => {
    const script = document.createElement('script')
    script.src = resources[name]
    script.async = true
    script.dataset.openwriteGlobal = name
    const finish = (error?: Error) => {
      window.clearTimeout(timer)
      script.onload = null
      script.onerror = null
      if (error) { script.remove(); reject(error) }
      else resolve()
    }
    const timer = window.setTimeout(() => finish(new Error(`studio-panel: ${name} load timed out`)), 20_000)
    script.onload = () => finish(win[name] === undefined ? new Error(`studio-panel: ${name} did not initialize`) : undefined)
    script.onerror = () => finish(new Error(`studio-panel: failed to load ${name}`))
    document.head.appendChild(script)
  })
  pending.set(name, promise)
  // Both outcomes clear the shared request, so a failed load can be retried.
  void promise.then(() => pending.delete(name), () => pending.delete(name))
  return promise
}
