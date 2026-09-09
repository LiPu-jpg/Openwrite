/** Registered people/places that can become 提及 in the open chapter. */
export type MentionAsset = {
  kind: string
  id: string
  name: string
  summary: string
  aliases: string[]
}

export type MentionSpan = {
  start: number
  end: number
  text: string
  candidates: MentionAsset[]
}

const PERSON_OR_PLACE = new Set(['character', 'world', 'location', 'place'])

function asRecord(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function asText(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function asStringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string' && item.trim() !== '')
    : []
}

export function isPersonOrPlaceKind(kind: string): boolean {
  return PERSON_OR_PLACE.has(kind)
}

export function isCharacterKind(kind: string): boolean {
  return kind === 'character'
}

/** Characters for marker insert. Homonyms stay distinct by id. */
export function characterChoices(assets: readonly MentionAsset[]): MentionAsset[] {
  return assets.filter(asset => isCharacterKind(asset.kind))
}

export function characterMatches(assets: readonly MentionAsset[], label: string): MentionAsset[] {
  const needle = label.trim()
  if (needle === '') return []
  return characterChoices(assets).filter(asset => asset.name === needle || asset.aliases.includes(needle))
}

/** Homonyms require an explicit id; a unique match may be used without one. */
export function resolveCharacterChoice(
  assets: readonly MentionAsset[],
  selectedId: string,
  label = '',
): MentionAsset | null {
  if (selectedId !== '') {
    return characterChoices(assets).find(asset => asset.id === selectedId) ?? null
  }
  const matches = characterMatches(assets, label)
  return matches.length === 1 ? matches[0]! : null
}

/** Unwrap Studio GET /assets into character and location summaries. */
export function parseMentionAssets(value: unknown): MentionAsset[] {
  const root = asRecord(value)
  const inner = asRecord(root['data'] ?? value)
  const list = Array.isArray(inner['assets']) ? inner['assets'] : []
  const assets: MentionAsset[] = []
  for (const raw of list) {
    const item = asRecord(raw)
    const kind = asText(item['kind'])
    const id = asText(item['id'])
    const name = asText(item['name']).trim()
    if (!isPersonOrPlaceKind(kind) || id === '' || name === '') continue
    assets.push({
      kind,
      id,
      name,
      summary: asText(item['summary']),
      aliases: asStringList(item['aliases']).map(alias => alias.trim()).filter(alias => alias !== ''),
    })
  }
  return assets
}

type Needle = { label: string; candidates: MentionAsset[] }

function assetKey(asset: MentionAsset): string {
  return JSON.stringify([asset.kind, asset.id])
}

/** One chip per unambiguous asset, or per conflicting label/candidate set. */
export function uniqueMentionAssets(spans: readonly MentionSpan[]): MentionSpan[] {
  const unique = new Map<string, MentionSpan>()
  for (const span of spans) {
    const identities = span.candidates.map(assetKey).sort()
    const key = JSON.stringify([identities.length === 1 ? '' : span.text, identities])
    if (!unique.has(key)) unique.set(key, span)
  }
  return [...unique.values()]
}

function needlesFor(assets: readonly MentionAsset[]): Needle[] {
  const labels = new Map<string, Map<string, MentionAsset>>()
  for (const asset of assets) {
    for (const label of [asset.name, ...asset.aliases]) {
      if (label === '') continue
      let candidates = labels.get(label)
      if (candidates === undefined) {
        candidates = new Map()
        labels.set(label, candidates)
      }
      if (!candidates.has(assetKey(asset))) candidates.set(assetKey(asset), asset)
    }
  }
  return [...labels].map(([label, candidates]) => ({
    label,
    candidates: [...candidates.values()].sort((a, b) => assetKey(a).localeCompare(assetKey(b))),
  })).sort((a, b) => b.label.length - a.label.length || a.label.localeCompare(b.label))
}

/**
 * Non-overlapping name/alias hits in manuscript order.
 * Longer labels win; identical labels retain every candidate without guessing identity.
 */
export function findManuscriptMentions(text: string, assets: readonly MentionAsset[]): MentionSpan[] {
  if (text === '' || assets.length === 0) return []
  const occupied = new Array<boolean>(text.length).fill(false)
  const spans: MentionSpan[] = []
  for (const { label, candidates } of needlesFor(assets)) {
    let from = 0
    while (from <= text.length - label.length) {
      const start = text.indexOf(label, from)
      if (start < 0) break
      const end = start + label.length
      let taken = false
      for (let index = start; index < end; index += 1) {
        if (occupied[index] === true) {
          taken = true
          break
        }
      }
      if (!taken) {
        for (let index = start; index < end; index += 1) occupied[index] = true
        spans.push({
          start,
          end,
          text: label,
          candidates,
        })
      }
      from = start + 1
    }
  }
  spans.sort((left, right) => left.start - right.start || right.end - left.end)
  return spans
}
