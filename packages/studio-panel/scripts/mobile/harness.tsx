import React, { useState } from 'react'
import { createRoot } from 'react-dom/client'
import { VditorBody } from '../../src/client/VditorBody.tsx'
import { downloadBlob } from '../../src/client/browser-download.ts'
import css from '../../src/client/Workbench.module.css'

window.mobileHoldInput = false
window.mobilePendingInput = []
window.mobileTest = { changes: [], selection: null, api: null }

function MobileEditor() {
  const [left, setLeft] = useState(false)
  const [right, setRight] = useState(false)
  return <main className={css.creationRoot} data-testid="workbench" data-chapter-rail-visible="false" data-inspector-visible="false">
    <nav className={css.mobileBar}>
      <button onClick={() => setLeft(!left)}>章节目录</button><span className={css.mobileTitle}>手机上的长篇作品标题与较长章节名称</span>
      <button onClick={() => setRight(!right)}>参考资料</button>
    </nav>
    <aside className={css.chapterRail} data-mobile-open={left} data-testid="chapters">
      <input aria-label="搜索章节" placeholder="搜索章节" />
      <button onClick={() => setLeft(false)}>关闭目录</button>
    </aside>
    <section className={css.editorPane}>
      <header className={css.editorHeader}><strong>正文</strong><button data-preserve-manuscript-selection="" data-testid="selection-action">改选区</button></header>
      <div className={css.manuscriptEditor}>
        <VditorBody initial={'原始正文。\n'} flushOnLeave disabled={false} onReady={() => { window.mobileTest.ready = true }} onFailed={cause => { window.mobileTest.failed = String(cause) }}
          onChange={value => { window.mobileTest.changes.push(value) }}
          onSelectionChange={value => { window.mobileTest.selection = value }}
          onEditorApi={api => { window.mobileTest.api = api }} />
      </div>
      <button onClick={() => downloadBlob(new Blob(['手机导出正文'], { type: 'text/plain;charset=utf-8' }), '手机正文.md')}>下载测试正文</button>
    </section>
    <aside className={css.inspector} data-mobile-open={right} data-testid="inspector">
      <textarea aria-label="参考指令" />
      <button onClick={() => setRight(false)}>关闭参考</button>
    </aside>
  </main>
}

createRoot(document.querySelector('#root')).render(<MobileEditor />)
