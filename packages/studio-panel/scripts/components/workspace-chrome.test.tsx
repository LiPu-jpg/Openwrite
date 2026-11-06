import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { WORKSPACE_CHROME_CSS, installWorkspaceChromeStyles } from '../../src/client/workspace-chrome.ts'

/**
 * The workbench's bottom edge and the host's composer.
 *
 * The host parks its composer in a seat element inside the conversation
 * scroller and reserves the seat's band out of the content area, so a view
 * that stops at the content area's bottom leaves a bare strip of page
 * background under the composer — a flat white slab, not a composer floating
 * over the workbench. Switching the seat to an absolute overlay
 * (`data-conversation-composer-overlay`) hands the view the full height, but
 * the centered composer card then covers the workbench's own content.
 *
 * The workbench is a full-screen surface, not a chat transcript, so it takes
 * the whole content area: the seat is hidden while one of our views is
 * mounted, and our views fill the area the host hands them.
 *
 * Vitest stubs CSS modules to empty objects, so the styling is pinned in the
 * source instead of the DOM.
 */
const read = (path: string): string => readFileSync(resolve(process.cwd(), path), 'utf-8')

/** One CSS rule body, from the selector up to its closing brace. */
const ruleOf = (css: string, selector: string): string => {
  const start = css.indexOf(`${selector} {`)
  expect(start, `missing rule ${selector}`).toBeGreaterThan(-1)
  return css.slice(start, css.indexOf('}', start))
}

/**
 * The rule without its comments.
 *
 * A rule's own comment often names the value it replaced — that prose must
 * not be read as the live declaration, or the assertion checks the wrong
 * thing (a rule that still uses `100dvh` passes because its comment
 * mentions the offset it dropped).
 */
const declarationsOf = (css: string, selector: string): string =>
  ruleOf(css, selector).replace(/\/\*[\s\S]*?\*\//g, '')

/** The bottom inset of a `padding: a b c` shorthand, in pixels. */
const bottomInsetOf = (rule: string): number => {
  const shorthand = /padding:\s*([^;]+);/.exec(rule)
  expect(shorthand, `no padding shorthand in ${rule}`).not.toBeNull()
  const parts = (shorthand as RegExpExecArray)[1].trim().split(/\s+/)
  const last = parts[parts.length - 1]
  return Number.parseFloat(last)
}

describe('workbench chrome', () => {
  it('marks every OpenWrite view so the host seat can be scoped to them', () => {
    // Match the JSX attribute, not the bare name: the explanatory comments
    // above it name the attribute too, and a substring check would match the
    // prose and pass even after the attribute was deleted.
    for (const view of ['src/client/LibraryView.tsx', 'src/client/OperationsView.tsx', 'src/client/CreationView.tsx']) {
      const source = read(view)
      expect(source, view).toContain('data-openwrite-workspace=""')
      expect(source, view).toContain('data-conversation-composer-overlay=""')
    }
  })

  it('hides the host composer seat only while a workbench view is mounted', () => {
    expect(WORKSPACE_CHROME_CSS).toContain('[data-conversation-scroll]:has([data-openwrite-workspace]) > [data-composer-seat]')
    expect(WORKSPACE_CHROME_CSS).toContain('display: none')
  })

  it('installs the chrome stylesheet once per document', () => {
    document.getElementById('openwrite-workspace-chrome')?.remove()
    installWorkspaceChromeStyles()
    installWorkspaceChromeStyles()
    const styles = document.querySelectorAll('#openwrite-workspace-chrome')
    expect(styles.length).toBe(1)
    expect(styles[0]?.textContent).toBe(WORKSPACE_CHROME_CSS)
  })

  it('wires the chrome installation into the client activation', () => {
    expect(read('src/client/index.ts')).toContain('installWorkspaceChromeStyles()')
  })

  it('lets both workbench roots follow the host content area', () => {
    const css = read('src/client/Workbench.module.css')
    const workspace = declarationsOf(css, '.workspaceRoot')
    expect(workspace).toContain('height: 100%')
    expect(workspace).not.toContain('100dvh')
    const creation = declarationsOf(css, '.creationRoot')
    expect(creation).toContain('height: 100%')
    expect(creation).not.toContain('100dvh')
  })

  it('drops the clearance bands that only existed for the floating composer', () => {
    const views = read('src/client/views.module.css')
    expect(views).not.toContain('.assetsSidebar')
    expect(read('src/client/AssetsView.tsx')).not.toContain('css.assetsSidebar')
    // A cleared band would leave the list ending in blank space now that
    // nothing floats over it.
    expect(bottomInsetOf(declarationsOf(views, '.body'))).toBeLessThanOrEqual(40)
    expect(bottomInsetOf(declarationsOf(views, '.mainPane'))).toBeLessThanOrEqual(40)
    expect(bottomInsetOf(declarationsOf(read('src/client/Workbench.module.css'), '.transferPanel'))).toBeLessThanOrEqual(40)
  })
})
