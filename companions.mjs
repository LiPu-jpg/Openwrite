// Companion-plugin detection. OpenWrite ships its own DoG engine and works
// without any companion; when a companion plugin is installed in the same
// profile AND its declared host range covers the running host, the companion's
// newest implementation is used instead of ours. Every unknown answer is
// fail-closed: detection problems keep our own implementation.
import { readFile, readdir, stat, mkdir, writeFile, realpath } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
import { dirname, join, resolve } from 'node:path'

/** Bundle names that identify each companion, with and without scope. */
const companionNames = {
  dog: ['@dsh-external/dsh-dog'],
  ops: ['dsh-ops'],
  freeModel: ['dsh-our-free-model', '@ebony-vinyl/dsh-our-free-model'],
}

/**
 * The host constraint a companion actually declares.
 *
 * Most plugins declare `peerDependencies["@deepseek-ai/dsh"]`, and the host reads
 * exactly that. Some (dsh-dog 1.4.x) declare only `@deepseek-ai/dsh-*`
 * sub-packages instead; the host needs every one of them, so their ranges are the
 * real constraint. Treating a missing `@deepseek-ai/dsh` peer as "no constraint"
 * would report such a plugin usable on hosts where the host itself refuses it.
 */
function hostConstraint(manifest) {
  const peers = manifest?.peerDependencies ?? {}
  const direct = peers['@deepseek-ai/dsh']
  if (typeof direct === 'string' && direct !== '') return { range: direct, source: '@deepseek-ai/dsh' }
  const subpackage = Object.entries(peers)
    .filter(([name]) => name.startsWith('@deepseek-ai/dsh-'))
    .map(([, range]) => String(range))
  if (subpackage.length > 0) return { range: subpackage.join(' '), source: '@deepseek-ai/dsh-*' }
  return { range: null, source: null }
}

/**
 * The public entry each companion must expose for OpenWrite to use it. A
 * companion that is installed but does not expose its entry (an older release,
 * or one that moved the API) is treated as absent: mounting a row whose import
 * fails would take the whole preset composition down with it.
 */
const companionEntries = { ops: 'dsh-ops/integration' }

/**
 * The exact dsh-ops integration OpenWrite mounts. Detection builds it too, so an
 * upstream release that stops accepting these options is reported instead of
 * breaking the preset composition at load time.
 */
/** The exact options OpenWrite passes to the dsh-ops integration factory. */
export const OPENWRITE_OPS_OPTIONS = Object.freeze({
  preset: 'openwrite',
  files: true,
  discovery: true,
  presentation: 'native',
  replaceOfficial: false,
  shell: false,
})

const opsIntegration = factory => factory({ ...OPENWRITE_OPS_OPTIONS })

/** The small, serializable summary of a resolved dsh-ops plan. */
export function summarizeOpsPlan(plan) {
  return {
    files: plan.files === true,
    discovery: plan.discovery === true,
    presentation: String(plan.presentation ?? ''),
    shell: plan.shell === true,
    replaceOfficial: plan.replaceOfficial === true,
    residentTools: plan.residentTools === true,
    residentNames: Array.isArray(plan.residentNames) ? plan.residentNames.length : 0,
  }
}

const readJson = async path => JSON.parse(await readFile(path, 'utf8'))

/** Compare two parsed versions, prerelease identifiers included. */
function compareVersions(a, b) {
  for (const key of ['major', 'minor', 'patch']) {
    if (a[key] !== b[key]) return a[key] < b[key] ? -1 : 1
  }
  const [x, y] = [a.pre, b.pre]
  if (x.length === 0 && y.length === 0) return 0
  if (x.length === 0) return 1
  if (y.length === 0) return -1
  for (let index = 0; index < Math.max(x.length, y.length); index += 1) {
    if (index >= x.length) return -1
    if (index >= y.length) return 1
    const left = x[index], right = y[index]
    if (left === right) continue
    const numeric = /^\d+$/.test(left) && /^\d+$/.test(right)
    if (numeric) return Number(left) < Number(right) ? -1 : 1
    return left < right ? -1 : 1
  }
  return 0
}

/** Parse `1.2.3-rc.4` into comparable parts; returns null when unparseable. */
function parseVersion(value) {
  const match = /^(\d+)(?:\.(\d+|[xX*]))?(?:\.(\d+|[xX*]))?(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?$/.exec((value ?? '').trim())
  if (!match) return null
  const wildcard = part => part === undefined || /[xX*]/.test(part)
  // `1.x.3` is not a version spelling npm accepts.
  if (wildcard(match[2]) && match[3] !== undefined && !wildcard(match[3])) return null
  if (wildcard(match[2]) && match[4] !== undefined) return null
  return { major: +match[1], minor: +(wildcard(match[2]) ? 0 : match[2]), patch: +(wildcard(match[3]) ? 0 : match[3]),
    pre: match[4] ? match[4].split('.') : [], partial: 3 - [match[2], match[3]].filter(wildcard).length }
}

/** One comparator: an optional operator plus its version spelling. */
function parseComparator(comparator) {
  const match = /^(>=|<=|>|<|=|\^|~)?\s*(.+)$/.exec(comparator.trim())
  if (!match) return null
  const version = parseVersion(match[2].trim().replace(/^[vV]/, ''))
  if (!version) return null
  return { op: match[1] ?? '=', version }
}

/** The exclusive end of a spelled version prefix (`0.3` -> 0.4.0-0, `1` -> 2.0.0-0). */
function upperBoundOf(spelling) {
  const version = parseVersion(spelling.replace(/^[vV]/, ''))
  if (!version) return null
  if (version.partial === 3) return { ...version, pre: ['0'] }
  return version.partial === 1
    ? { major: version.major + 1, minor: 0, patch: 0, pre: ['0'] }
    : { major: version.major, minor: version.minor + 1, patch: 0, pre: ['0'] }
}

/** Expand one comparator (`1.2.3`, `^1.2.3`, `~1.2.3`, `>=1.2.3`, `*`) into bounds. */
function expandComparator(comparator) {
  const trimmed = comparator.trim()
  // `x`, `*`, `x.x.x` and most operators applied to them accept any version;
  // the strict `>x` / `<x` accept none.
  const wildcard = /^((?:>=|<=|>|<|=|\^|~)?)\s*[xX*](?:\.[xX*]){0,2}$/.exec(trimmed)
  if (trimmed === '' || wildcard) {
    const strict = wildcard !== null && (wildcard[1] === '>' || wildcard[1] === '<')
    return strict ? [] : [{ op: '>=', version: { major: 0, minor: 0, patch: 0, pre: [] } }]
  }
  const parsed = parseComparator(trimmed)
  if (!parsed) return null
  const { op, version } = parsed
  const upper = (major, minor, patch) => ({ op: '<', version: { major, minor, patch, pre: ['0'] } })
  if (op !== '^' && op !== '~') {
    // npm X-range semantics for a partial spelling, taken from semver's own Range
    // expansion (verified comparator by comparator):
    //   `0.2`   -> >=0.2.0 <0.3.0-0      `<=0.2` -> <0.3.0-0
    //   `<0.3`  -> <0.3.0-0              `<=0.3` -> <0.4.0-0
    //   `>0.2`  -> >=0.3.0               `>=0.3` -> >=0.3.0
    //   `>0.3`  -> >=0.4.0               `<1`    -> <1.0.0-0
    //   `<=0`   -> <1.0.0-0              `>0`    -> >=1.0.0
    // `<` bounds at the spelled prefix; `<=`, `>` and `>=` bound one component
    // further. Zero-filling the bound instead would make `>0.2` accept 0.2.5
    // (fail open) and `<=0.2` reject it (fail closed).
    if (version.partial < 3) {
      const start = { major: version.major, minor: version.minor, patch: version.patch, pre: [] }
      const end = version.partial === 1
        ? { major: version.major + 1, minor: 0, patch: 0, pre: ['0'] }
        : { major: version.major, minor: version.minor + 1, patch: 0, pre: ['0'] }
      const here = { major: version.major, minor: version.minor, patch: 0, pre: ['0'] }
      if (op === '=') return [{ op: '>=', version: start }, { op: '<', version: end }]
      if (op === '>') return [{ op: '>=', version: { ...end, pre: [] } }]
      if (op === '<') return [{ op: '<', version: here }]
      if (op === '<=') return [{ op: '<', version: end }]
      // `>=0.3` starts AT the spelled prefix; `>0.3` starts one component later.
      return [{ op: '>=', version: op === '>=' ? start : end }]
    }
    return [{ op, version }]
  }
  const floor = { op: '>=', version }
  // npm X-ranges inside a caret/tilde: `^0` and `~0` both stop at 1.0.0.
  if (version.partial === 1) return [floor, upper(version.major + 1, 0, 0)]
  if (op === '~') return [floor, upper(version.major, version.minor + 1, 0)]
  if (op === '^' && version.partial === 2 && version.major === 0) return [floor, upper(0, version.minor + 1, 0)]
  if (version.major > 0) return [floor, upper(version.major + 1, 0, 0)]
  if (version.minor > 0) return [floor, upper(0, version.minor + 1, 0)]
  return [floor, upper(0, 0, version.patch + 1)]
}

/** Split one `||` alternative into comparators, keeping `>= 1.2.3` together. */
function expandAlternative(alternative) {
  const trimmed = alternative.trim()
  if (trimmed === '') return [{ op: '>=', version: { major: 0, minor: 0, patch: 0, pre: [] } }]
  const comparators = []
  const verbatim = []
  let cursor = 0
  for (const match of trimmed.matchAll(/(>=|<=|>|<|=|\^|~)?\s*(v?[0-9xX*][^\s]*)/g)) {
    verbatim.push({ op: match[1] ?? '=', version: match[2].replace(/^[vV]/, '') })
    // Anything but whitespace between two comparators is a spelling we refuse,
    // except the lone `-` of a hyphen range (`1.2.3 - 2.3.4`).
    const gap = trimmed.slice(cursor, match.index)
    if (gap.trim() !== '' && gap.trim() !== '-') return null
    const expanded = expandComparator(`${match[1] ?? ''} ${match[2]}`)
    if (expanded === null) return null
    comparators.push(...expanded)
    cursor = match.index + match[0].length
  }
  // (hyphen operands are re-emitted verbatim below)
  if (trimmed.slice(cursor).trim() !== '') return null
  // A hyphen range (`1.2.3 - 2.3.4`, `0.2 - 0.3`) is two partial-or-full
  // versions with a lone `-` between them; npm expands it to `>=lo <=hi` with
  // both bounds verbatim, so the X-range rule must not rewrite them. The
  // tokenizer drops the `-`, so detect it from the original text.
  if (verbatim.length === 2 && verbatim.every(item => item.op === '=')
    && /(^|\s)-(\s|$)/.test(trimmed)) {
    // npm's hyphen range is the X-range of the lower bound plus the prefix end of
    // the upper one: `0.2 - 0.3` is `>=0.2.0 <0.4.0-0`, `1 - 2` is
    // `>=1.0.0 <3.0.0-0`. Both operands keep their own partial expansion.
    const lower = parseVersion(verbatim[0].version.replace(/^[vV]/, ''))
    const upper = parseVersion(verbatim[1].version.replace(/^[vV]/, ''))
    // The lower operand is always inclusive; the upper one keeps its own value
    // when it is a full version and bumps to its prefix end when it is partial.
    return [{ op: '>=', version: lower }, upper.partial === 3
      ? { op: '<=', version: upper }
      : { op: '<', version: upperBoundOf(verbatim[1].version) }]
  }
  return comparators
}

/**
 * Whether one version satisfies one range. Implements the subset the dsh host
 * uses: `||` alternatives, `=`/`>`/`>=`/`<`/`<=`/`^`/`~`, X-ranges.
 *
 * The host decides with `semver.satisfies(version, range, { includePrerelease: true })`
 * (dsh-app-boot `unmetRequirements` → `satisfies`). That flag relaxes npm's rule
 * that a prerelease only matches a comparator carrying the same
 * major/minor/patch, so `0.2.1-rc.5` DOES satisfy `>=0.2.0-rc.2 <0.2.2-0`.
 *
 * Implementing the stricter rule here made this detection more conservative than
 * the host: dsh-ops and dsh-our-free-model were reported "installed but the host
 * does not allow it" on 0.2.1-rc.* while the host loaded both. Detection must
 * match the host, not npm's install-time resolution.
 */
export function satisfiesRange(version, range) {
  const parsed = parseVersion(version)
  // Only a complete version is testable; partial spellings belong to ranges.
  if (!parsed || parsed.partial !== 3 || typeof range !== 'string') return false
  for (const alternative of range.split('||')) {
    const comparators = expandAlternative(alternative)
    if (comparators === null || comparators.length === 0) continue
    if (comparators.every(({ op, version: bound }) => {
      const order = compareVersions(parsed, bound)
      return op === '=' ? order === 0
        : op === '>' ? order > 0
          : op === '>=' ? order >= 0
            : op === '<' ? order < 0
              : order <= 0
    })) return true
  }
  return false
}

/**
 * Walk up from one path to the `@deepseek-ai/dsh` package directory that owns
 * it, or null when the path belongs to no host package.
 *
 * That directory is the host's own resolution context: the cordis loader
 * imports a bare specifier from inside its own package tree, so a specifier
 * the host cannot resolve from there is a specifier the host cannot resolve
 * at all.
 */
export async function hostPackageRoot(path) {
  // Resolve symlinks first. The running host is usually started through the
  // `dsh` shim in the npm global bin directory, which is a symlink into
  // lib/node_modules/@deepseek-ai/dsh/lib/bin.js. `path.resolve` does not follow
  // symlinks, so walking up from the shim never reaches the package and the
  // version silently falls through to whatever this checkout happens to depend
  // on - reported a source checkout's 0.1.2-rc.1 devDependency while the real
  // host was 0.2.1-rc.5.
  let directory = dirname(await realpath(path).catch(() => resolve(path)))
  while (true) {
    const manifest = await readJson(join(directory, 'package.json')).catch(() => null)
    if (manifest?.name === '@deepseek-ai/dsh') return directory
    const parent = dirname(directory)
    if (parent === directory) return null
    directory = parent
  }
}

/**
 * The host package directory held by an ancestor's `node_modules`.
 *
 * `hostPackageRoot` answers "which package owns this file?". This answers
 * "which host does this directory install?": the Electron desktop application
 * keeps the host inside its own bundle and starts from an entry that no
 * package owns, so the only trace of the host is a `node_modules` directory
 * above the entry that holds it. Without this the desktop profile answers
 * nothing about the host that is running it.
 */
export async function hostPackageRootInAncestors(path) {
  let directory = dirname(await realpath(path).catch(() => resolve(path)))
  while (true) {
    const candidate = join(directory, 'node_modules', '@deepseek-ai', 'dsh')
    const manifest = await readJson(join(candidate, 'package.json')).catch(() => null)
    if (manifest?.name === '@deepseek-ai/dsh') return candidate
    const parent = dirname(directory)
    if (parent === directory) return null
    directory = parent
  }
}

/** Walk up from one path to the version of the host package that owns it. */
async function hostVersionAbove(path) {
  const root = await hostPackageRoot(path)
  if (root === null) return null
  const manifest = await readJson(join(root, 'package.json')).catch(() => null)
  return typeof manifest?.version === 'string' ? manifest.version : null
}

/**
 * The running host version. A host installed into a profile is read from that
 * profile; otherwise the host sub-packages this plugin already resolves are
 * read, because the harness publishes them in lockstep with `@deepseek-ai/dsh`.
 * `OPENWRITE_HOST_VERSION` overrides every source for diagnostics and tests.
 * Unknown when nothing resolves, which keeps every companion decision
 * fail-closed.
 */
export async function resolveHostVersion(home) {
  const override = process.env.OPENWRITE_HOST_VERSION
  if (typeof override === 'string' && parseVersion(override)) return override
  for (const profile of await readdir(join(home, 'profiles')).catch(() => [])) {
    const installed = join(home, 'profiles', profile, 'node_modules', '@deepseek-ai', 'dsh')
    const version = await hostVersionAbove(join(installed, 'lib', 'index.js'))
      ?? (await readJson(join(installed, 'package.json')).catch(() => null))?.version
    if (typeof version === 'string' && parseVersion(version)) return version
  }
  // The entry this process was started from is the host that is actually
  // running; it outranks whatever this checkout happens to depend on.
  const entry = process.argv?.[1]
  if (typeof entry === 'string') {
    const version = await hostVersionAbove(entry)
    if (version) return version
  }
  // Last resort: the host packages resolvable from here. In a source checkout
  // that is this repo's own pinned devDependency, never the running host, so it
  // can answer wrongly in both directions — prefer it over nothing only.
  for (const name of ['@deepseek-ai/dsh', '@deepseek-ai/dsh-home-paths', '@deepseek-ai/dsh-settings', '@deepseek-ai/dsh-tools']) {
    const version = await readJson(createRequire(import.meta.url).resolve(`${name}/package.json`)).then(manifest => manifest?.version).catch(() => null)
    if (typeof version === 'string' && parseVersion(version)) return version
  }
  return null
}

/** Every profile bundle list plus a fingerprint of the manifests behind them. */
async function readProfiles(home) {
  const profiles = []
  let fingerprint = ''
  for (const name of await readdir(join(home, 'profiles')).catch(() => [])) {
    const manifest = join(home, 'profiles', name, 'package.json')
    let parsed, modified
    try {
      parsed = await readJson(manifest)
      modified = (await stat(manifest)).mtimeMs
    } catch { continue }
    const bundles = parsed?.dsh?.profile?.bundles
    if (!Array.isArray(bundles)) continue
    profiles.push({ name, directory: join(home, 'profiles', name), bundles })
    fingerprint += `${name}:${Math.round(modified)};`
    // The companion's own manifest decides whether the running host is inside its
    // declared range, so an upgrade that widens (or narrows) that range must
    // invalidate the cache. Keying only on the profile manifest kept serving the
    // previous verdict after a companion upgrade - the exact #150/#151/#142 class
    // of bug, reachable again the moment the range changes.
    for (const candidates of Object.values(companionNames)) {
      for (const companion of candidates) {
        const companionManifest = join(profiles[profiles.length - 1].directory, 'node_modules', ...companion.split('/'), 'package.json')
        try {
          fingerprint += `${companion}:${Math.round((await stat(companionManifest)).mtimeMs)};`
        } catch { /* companion not installed in this profile */ }
      }
    }
  }
  return { profiles, fingerprint }
}

/** Locate one installed companion package inside a profile. */
async function installedPackage(profile, names) {
  for (const name of names) {
    if (!profile.bundles.some(bundle => String(bundle).toLowerCase() === name.toLowerCase())) continue
    const manifest = join(profile.directory, 'node_modules', ...name.split('/'), 'package.json')
    const parsed = await readJson(manifest).catch(() => null)
    if (parsed) {
      const constraint = hostConstraint(parsed)
      return { name, directory: join(profile.directory, 'node_modules', ...name.split('/')),
        version: parsed.version, range: constraint.range, rangeSource: constraint.source }
    }
  }
  return null
}

/**
 * Load a companion's entry and build the integration OpenWrite would mount, so an
 * entry that no longer accepts our options is caught here instead of taking the
 * preset composition down with it. Returns null when usable, or why it is not.
 */
async function validateEntry(directory, entry, build) {
  if (!resolvesEntry(directory, entry)) return `installed package does not expose ${entry}`
  try {
    const resolved = createRequire(join(directory, 'package.json')).resolve(entry)
    const module = await import(pathToFileURL(resolved).href)
    const factory = module.integration ?? module.default
    if (typeof factory !== 'function') return `${entry} no longer exports an integration factory`
    // The mounted row immediately calls `.apply` on the result, so a factory
    // that returns nothing must be refused here rather than at activation.
    const built = build(factory)
    if (built === null || typeof built !== 'object' || typeof built.apply !== 'function') {
      return `${entry} returned no plugin object`
    }
    return null
  } catch (error) {
    return `${entry} rejected the OpenWrite integration: ${error instanceof Error ? error.message : String(error)}`
  }
}

/** Whether one package directory exposes the entry OpenWrite would import. */
function resolvesEntry(directory, entry) {
  try {
    createRequire(join(directory, 'package.json')).resolve(entry)
    return true
  } catch { return false }
}

/**
 * Whether a companion's own bundle patch is self-consistent.
 *
 * The host imports each `insert` row by its `name`, resolved as a package from
 * the profile. A scoped package that ships a patch naming the bare package
 * (`@ebony-vinyl/dsh-our-free-model` declaring `name: dsh-our-free-model`)
 * therefore never activates: the host reports
 * "Cannot find package 'dsh-our-free-model'". Detecting that here turns a
 * panel that shows "available" and then fails to read the gateway into an
 * accurate "installed but the host cannot load it".
 */
async function bundlePatchReason(directory, packageName) {
  const manifest = await readJson(join(directory, 'package.json')).catch(() => null)
  const patch = manifest?.dsh?.bundle?.patch
  if (typeof patch !== 'string' || patch === '') return null
  const text = await readFile(join(directory, patch), 'utf8').catch(() => null)
  if (text === null) return `bundle patch ${patch} is missing`
  // Minimal scan: every `name:` value in an insert block. A full YAML parse is
  // deliberately avoided so a malformed patch cannot make detection itself fail.
  const names = [...text.matchAll(/^\s*-?\s*name:\s*['"]?([^'"\n]+)['"]?\s*$/gm)].map(m => m[1].trim())
  if (names.length === 0) return null
  for (const name of names) {
    if (name === packageName) continue
    // A relative or subpath specifier is resolved against the package itself.
    if (name.startsWith('.') || name.startsWith('#')) continue
    try {
      const resolved = createRequire(join(directory, 'package.json')).resolve(name)
      if (resolved.startsWith(resolve(directory))) continue
    } catch { /* fall through to the mismatch report */ }
    return `bundle patch names ${name}, which is not this package (${packageName}); the host cannot load it`
  }
  return null
}
/**
 * Why a companion is not usable because of its declared host constraint, or null
 * when the constraint covers the running host.
 *
 * A companion may declare several constraints (dsh-dog declares one range per
 * `@deepseek-ai/dsh-*` sub-package); the host needs all of them, so every one
 * must cover. An unknown host version is reported rather than silently accepted,
 * because "no constraint declared" and "cannot tell" must not read the same.
 */
function rangeExclusionReason(host, candidate) {
  const range = candidate.range
  if (range === null || range === undefined) {
    return host === null || host === undefined
      ? 'the running host version is unknown, so its declared range cannot be checked'
      : null
  }
  if (host === null || host === undefined) {
    const shown = candidate.rangeSource === '@deepseek-ai/dsh-*'
      ? `${candidate.range.split(' ').filter(Boolean).length} @deepseek-ai/dsh-* peer ranges`
      : `declared range ${range}`
    return `the running host version is unknown, so ${shown} cannot be checked`
  }
  if (satisfiesRange(host, range)) return null
  const source = candidate.rangeSource === '@deepseek-ai/dsh-*'
    ? 'its @deepseek-ai/dsh-* peer ranges'
    : `declared host range ${range}`
  return `${source} excludes dsh ${host}`
}

/**
 * Describe every companion: whether it is installed and whether the running host
 * would load it.
 */
export async function detectCompanions(home, options = {}) {
  const { profiles, fingerprint } = await readProfiles(home)
  // An explicit host version wins; `undefined` means "resolve it" while an
  // explicit null forces the unknown-host path.
  const host = 'hostVersion' in options ? options.hostVersion : await resolveHostVersion(home)
  const describe = async (names, entry, build) => {
    // Every profile is examined: readdir order is unspecified, so stopping at
    // the first match would make the answer depend on directory order when one
    // profile carries a usable copy and another does not.
    const found = []
    for (const profile of profiles) {
      const installed = await installedPackage(profile, names)
      if (installed) found.push({ profile, ...installed })
    }
    if (found.length === 0) return { installed: false, usable: false, version: null, range: null, profile: null, reason: null }
    const described = []
    for (const candidate of found) {
      const entryReason = entry === undefined ? null : await validateEntry(candidate.directory, entry, build)
      // A companion whose own bundle patch cannot be loaded by the host is not
      // usable however well its range matches: the panel would offer an
      // integration that never activates.
      const patchReason = entryReason ?? await bundlePatchReason(candidate.directory, candidate.name)
      // A null range means the plugin declares no host constraint at all. That is
      // not "usable everywhere": an unknown constraint is treated as covering,
      // because the host would also accept it, but it is reported so the panel
      // can say the range is unknown rather than asserting compatibility.
      const rangeReason = patchReason ?? rangeExclusionReason(host, candidate)
      const usable = rangeReason === null
      described.push({ installed: true, usable, version: candidate.version ?? null, range: candidate.range ?? null,
        rangeSource: candidate.rangeSource ?? null,
        profile: candidate.profile.name, reason: rangeReason })
    }
    return described.find(candidate => candidate.usable) ?? described[0]
  }
  const [dog, ops, freeModel] = await Promise.all([
    describe(companionNames.dog),
    describe(companionNames.ops, companionEntries.ops, opsIntegration),
    describe(companionNames.freeModel),
  ])
  const result = { host, dog, ops, freeModel }
  const cache = join(home, 'openwrite', 'companions.json')
  // The cache key must include this plugin's own version. Keying only on the
  // profile manifests and the host meant an upgrade that changes the detection
  // logic (new companion, corrected range semantics) kept serving the previous
  // answer: a real 0.2.1-rc.5 host showed the old "ops excludes dsh 0.2.1-rc.5"
  // verdict and no DoG row at all, until the manifests happened to change.
  const build = await readJson(new URL('package.json', import.meta.url)).then(m => m?.version).catch(() => null)
  const cached = await readJson(cache).catch(() => null)
  if (cached?.fingerprint === fingerprint && cached.host === host && cached.build === build) {
    // Serve the stored answer: recomputing on every call would re-read every
    // profile and re-import the companion entry each time.
    const { fingerprint: _fingerprint, build: _build, ...rest } = cached
    return { ...rest, host, cached: true }
  }
  await mkdir(join(home, 'openwrite'), { recursive: true }).catch(() => {})
  await writeFile(cache, JSON.stringify({ fingerprint, host, build, ...result }) + '\n').catch(() => {})
  return { ...result, cached: false }
}
