/**
 * Out-of-tree mirror of the DSH shared client-bundle preset
 * (DSH packages/client/tsdown.client.ts). Kept self-contained because an
 * out-of-tree package cannot import the in-repo preset: the browser half is
 * emitted as the same closure-factory artifact (window.__ModuleLoader__.load
 * handoff, externals resolved through the loader module table, CSS Modules
 * compiled by lightningcss and auto-injected as <style data-plugin> tags).
 */
import { readFile } from 'node:fs/promises'
import { basename, dirname, resolve as resolvePath } from 'node:path'
import type { UserConfig } from 'tsdown'
import { transform } from 'lightningcss'

/** Plugin id (package name), stamped into the module-loader handoff and style tags. */
const ID = '@dsh-novel/studio-panel'

/**
 * Browser platform modules the shell seeds into the frozen module table —
 * mirror of DSH packages/client/web/src/platform.ts (PLATFORM_MODULES) plus
 * the documented runtime store exemption from tsdown.client.ts. Only these
 * specifiers may stay external in the client bundle.
 */
const CLIENT_EXTERNALS: readonly string[] = [
  'react', 'react/jsx-runtime', 'react-dom', 'react-dom/client', '@deepseek-ai/cordis',
  '@deepseek-ai/dsh-client-ui-slots',
  '@deepseek-ai/dsh-client-web-react',
  '@deepseek-ai/dsh-client-ui-primitives',
  '@deepseek-ai/dsh-client-ui-attachment',
  '@deepseek-ai/dsh-client-schema-form',
  '@deepseek-ai/dsh-client-runtime/client', // documented store-engine exemption
]

/** Browser-safe wire/type layers a bundle may inline (mirror of INLINE_SAFE). */
const INLINE_SAFE = /^@deepseek-ai\/dsh-(host-apiproxy|session|llm|tools|brand)(\/|$)/
/** Vendored framework libraries rescoped into @deepseek-ai (no shared runtime identity). */
const VENDORED_LIBRARY = /^@deepseek-ai\/(cosmokit|schemastery)(\/|$)/
/** Generated descriptor/codec contributions with no shared runtime identity. */
const GENERATED_REMOTE = /^@deepseek-ai\/dsh-[a-z0-9]+(?:-[a-z0-9]+)*\/remote$/

/**
 * Virtual-id wrapper keeping module CSS away from tsdown's own css pipeline
 * (the suffix matters: tsdown's guard matches ids ending in `.css`).
 */
const CSS_VIRTUAL_PREFIX = '\0dsh-css:'
const CSS_VIRTUAL_SUFFIX = '.mjs'
const VDITOR_RUNTIME_SPECIFIER = 'dsh-vditor-runtime'
const VDITOR_RUNTIME_VIRTUAL_ID = '\0dsh-vditor-runtime.mjs'
const VDITOR_RUNTIME_FILE = resolvePath('vendor/vditor/dist/index.min.js')
const VDITOR_ICONS_FILE = resolvePath('vendor/vditor/dist/js/icons/ant.js')

/** Node half: the host-side cordis plugin (Config schema + config route). */
const lib: UserConfig = {
  name: ID,
  entry: ['src/index.ts'],
  outDir: 'lib',
  format: ['esm'],
  platform: 'node',
  target: 'es2022',
  fixedExtension: false,
  dts: false,
  clean: false,
}

/** Browser half: the /plugins/<id>/client.js bundle. */
const client: UserConfig = {
  name: `${ID}/client`,
  entry: { client: 'src/client/index.ts' },
  // Single lib/ artifact dir shared with the node half; clean must stay off.
  outDir: 'lib',
  format: 'cjs',
  platform: 'browser',
  dts: false,
  sourcemap: true,
  clean: false,
  external: [...CLIENT_EXTERNALS],
  // tsdown auto-externalizes package dependencies; anything NOT in the loader
  // module table must inline instead — a require() the table cannot answer is
  // a guaranteed runtime throw.
  noExternal: (id: string) => (CLIENT_EXTERNALS.includes(id) ? undefined : true),
  plugins: [{
    name: 'dsh-vditor-runtime-inline',
    resolveId(source: string) {
      return source === VDITOR_RUNTIME_SPECIFIER ? VDITOR_RUNTIME_VIRTUAL_ID : null
    },
    async load(id: string) {
      if (id !== VDITOR_RUNTIME_VIRTUAL_ID) return null
      this.addWatchFile(VDITOR_RUNTIME_FILE)
      this.addWatchFile(VDITOR_ICONS_FILE)
      const [source, icons] = await Promise.all([
        readFile(VDITOR_RUNTIME_FILE, 'utf8'),
        readFile(VDITOR_ICONS_FILE, 'utf8'),
      ])
      return [
        'const vditorModule = { exports: {} };',
        '(function (exports, module, define) {',
        source,
        '}).call(globalThis, vditorModule.exports, vditorModule, undefined);',
        'const Vditor = vditorModule.exports;',
        'export function installVditorIcons() {',
        '  if (document.getElementById("vditor-icon-undo") !== null) return;',
        icons,
        '}',
        'export default Vditor;',
      ].join('\n')
    },
  }, {
    // Bundle purity gate (build-time mirror of the module-edge rules):
    // platform seed entries stay external, inline-safe wire layers inline,
    // every other @deepseek-ai value import is a build error.
    name: 'dsh-client-bundle-purity',
    resolveId(source: string) {
      if (!source.startsWith('@deepseek-ai/')) return null
      if (CLIENT_EXTERNALS.includes(source)) return null
      if (VENDORED_LIBRARY.test(source)) return null
      if (INLINE_SAFE.test(source) || GENERATED_REMOTE.test(source)) return null
      throw new Error(
        `client bundle purity: "${source}" is not a platform module (CLIENT_EXTERNALS), an inline-safe wire layer, or a generated /remote contribution — `
        + 'cross-plugin value imports are forbidden; collaborate through cordis services (type-only imports are erased and never reach this gate)',
      )
    },
  }, {
    name: 'dsh-css-modules-inline',
    resolveId(source: string, importer: string | undefined) {
      if (!source.endsWith('.module.css')) return null
      const abs = importer !== undefined ? resolvePath(dirname(importer), source) : source
      return CSS_VIRTUAL_PREFIX + abs + CSS_VIRTUAL_SUFFIX
    },
    async load(virtualId: string) {
      if (!virtualId.startsWith(CSS_VIRTUAL_PREFIX)) return null
      const fileId = virtualId.slice(CSS_VIRTUAL_PREFIX.length, -CSS_VIRTUAL_SUFFIX.length)
      // The virtual id otherwise hides the physical stylesheet from Rolldown's watch graph.
      this.addWatchFile(fileId)
      const source = await readFile(fileId)
      const { code, exports: cssExports } = transform({
        filename: fileId,
        code: source,
        cssModules: { pattern: '[hash]_[local]' },
        minify: true,
      })
      const classMap: Record<string, string> = {}
      for (const [local, exp] of Object.entries(cssExports ?? {})) classMap[local] = exp.name
      // One <style data-plugin> per module file; idempotent under re-evaluation.
      return [
        `const css = ${JSON.stringify(code.toString())};`,
        `const tagId = ${JSON.stringify(`${ID}/${basename(fileId)}`)};`,
        'if (typeof document !== \'undefined\' && document.querySelector(\'style[data-plugin-css=\' + JSON.stringify(tagId) + \']\') === null) {',
        '  const tag = document.createElement(\'style\');',
        `  tag.dataset.plugin = ${JSON.stringify(ID)};`,
        '  tag.dataset.pluginCss = tagId;',
        '  tag.textContent = css;',
        '  document.head.appendChild(tag);',
        '}',
        `export default ${JSON.stringify(classMap)};`,
      ].join('\n')
    },
  }],
  outputOptions: {
    entryFileNames: 'client.js',
    banner: `window.__ModuleLoader__.load({ id: ${JSON.stringify(ID)}, factory: (require) => {`,
    footer: 'return module.exports; } });',
    intro: 'var module = { exports: {} }; var exports = module.exports;',
  },
}

export default [lib, client]
