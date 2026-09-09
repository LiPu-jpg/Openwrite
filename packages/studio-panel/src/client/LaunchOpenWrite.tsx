import { useEffect, useRef, useState } from 'react'
import { BookOpen, X } from 'lucide-react'
import css from './LaunchOpenWrite.module.css'

interface Status { phase: string; message?: string; error?: string; downloadedBytes?: number; totalBytes?: number }
export async function runtimeAction(action: string): Promise<Status> {
  const result = await fetch('/studio-panel/runtime', { method: 'POST', headers: { 'content-type': 'application/json', 'X-OpenWrite-Studio': '1' }, body: JSON.stringify({ action }) })
  if (!result.ok) throw new Error(`写作环境操作失败 (${result.status})`)
  return result.json() as Promise<Status>
}

export function LaunchOpenWrite({ wide, openWorkspace }: { wide: boolean; openWorkspace: (path?: string) => Promise<boolean> }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [open, setOpen] = useState(false)
  const [status, setStatus] = useState<Status>({ phase: 'idle' })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [path, setPath] = useState('')
  useEffect(() => {
    const launch = () => setOpen(true)
    window.addEventListener('openwrite:launch', launch)
    return () => window.removeEventListener('openwrite:launch', launch)
  }, [])
  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      try {
        const response = await fetch('/studio-panel/runtime', { signal: controller.signal })
        if (!response.ok) throw new Error(`状态读取失败 (${response.status})`)
        const next = await response.json() as Status
        setStatus(next)
      } catch (cause) { if (!controller.signal.aborted) setError(String(cause)) }
      if (!controller.signal.aborted) timer = setTimeout(() => void poll(), 1000)
    }
    dialog.current?.showModal()
    void runtimeAction('prepare').catch(cause => setError(String(cause)))
    void poll()
    return () => { controller.abort(); clearTimeout(timer); dialog.current?.close() }
  }, [open])
  const choose = async () => {
    setBusy(true); setError('')
    try { if (await openWorkspace(path)) setOpen(false) }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)) }
    finally { setBusy(false) }
  }
  const preparing = !['idle', 'ready', 'error', 'cancelled', 'stopped', 'uninstalled'].includes(status.phase)
  const title = status.phase === 'ready' ? '写作环境已就绪' : status.phase === 'recovering' ? '正在恢复写作环境' : status.phase === 'uninstalled' ? '插件已卸载' : '准备写作环境'
  return <>
    <button className={css.entry} type="button" title="OpenWrite" aria-label="打开 OpenWrite" onClick={() => setOpen(true)}><BookOpen size={18} />{wide && <span>OpenWrite</span>}</button>
    {open && <dialog ref={dialog} className={css.dialog} onCancel={() => setOpen(false)}>
      <header><div><small>长篇小说工作台</small><h2>开始创作</h2></div><button type="button" aria-label="关闭" onClick={() => setOpen(false)}><X size={20} /></button></header>
      <section aria-live="polite"><strong>{title}</strong><p>{status.message ?? '正在连接…'}</p>
        {preparing && <progress value={status.totalBytes ? status.downloadedBytes : undefined} max={status.totalBytes} aria-label="环境准备进度" />}
        {preparing && <button type="button" onClick={() => void runtimeAction('cancel').catch(cause => setError(String(cause)))}>取消准备</button>}
        {['error', 'cancelled', 'stopped'].includes(status.phase) && <button type="button" onClick={() => { setError(''); void runtimeAction('retry').catch(cause => setError(String(cause))) }}>重试</button>}
      </section>
      <section><strong>选择作品目录</strong><p>可以打开已有作品，也可以选择空文件夹创建小说。每次进入都会建立独立的创作会话，已有会话保持原样。</p>
        <label className={css.path}>作品目录<input aria-label="作品目录" placeholder="填写作品的完整路径，或留空选择文件夹" value={path} onChange={event => setPath(event.target.value)} /></label>
        <button className={css.primary} type="button" disabled={status.phase !== 'ready' || busy} onClick={() => void choose()}>{busy ? '正在打开…' : path.trim() ? '进入作品' : '选择目录并进入'}</button>
      </section>
      {error && <p role="alert">{error}</p>}
      <details><summary>诊断与帮助</summary><p>环境状态：{status.phase}</p>{status.error && <pre>{status.error}</pre>}<p>模型可在「任务 → 模型」中配置。关闭本窗口不会中断环境准备。</p></details>
    </dialog>}
  </>
}
