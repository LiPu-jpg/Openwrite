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
  kind: string
  id: string
  name: string
  summary: string
  aliases: string[]
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

type Needle = { label: string; asset: MentionAsset }

function needlesFor(assets: readonly MentionAsset[]): Needle[] {
  const needles: Needle[] = []
  for (const asset of assets) {
    const labels = [asset.name, ...asset.aliases]
    const seen = new Set<string>()
    for (const label of labels) {
      if (label === '' || seen.has(label)) continue
      seen.add(label)
      needles.push({ label, asset })
    }
  }
  needles.sort((left, right) => {
    const length = right.label.length - left.label.length
    if (length !== 0) return length
    const name = left.asset.id.localeCompare(right.asset.id)
    if (name !== 0) return name
    return left.label.localeCompare(right.label)
  })
  return needles
}

/**
 * Non-overlapping name/alias hits in manuscript order.
 * Longer labels win; unregistered text is never a mention.
 */
export function findManuscriptMentions(text: string, assets: readonly MentionAsset[]): MentionSpan[] {
  if (text === '' || assets.length === 0) return []
  const occupied = new Array<boolean>(text.length).fill(false)
  const spans: MentionSpan[] = []
  for (const { label, asset } of needlesFor(assets)) {
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
          kind: asset.kind,
          id: asset.id,
          name: asset.name,
          summary: asset.summary,
          aliases: asset.aliases,
        })
      }
      from = start + 1
    }
  }
  spans.sort((left, right) => left.start - right.start || right.end - left.end)
  return spans
}
