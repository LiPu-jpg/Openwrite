import type { AnnotationColor, ManuscriptAnnotation } from './manuscript-annotations.ts'
import { liveAnnotationAnchor } from './manuscript-annotations.ts'
import type { MarkerSpan } from './manuscript-markers.ts'
import { countOccurrences } from './manuscript-selection.ts'

export type OverlayKind = 'note' | 'state' | 'relation' | 'invalid'

export type OverlayBand = {
  kind: OverlayKind
  start: number
  end: number
  needle: string
  occurrence: number
  color?: AnnotationColor
  title: string
}

/** Display-only bands. Never written back into markdown. */
export function overlayBands(content: string, notes: readonly ManuscriptAnnotation[], markers: readonly MarkerSpan[]): OverlayBand[] {
  const bands: OverlayBand[] = []
  for (const note of notes) {
    if (note.status === 'resolved') continue
    const anchor = liveAnnotationAnchor(content, note)
    if (anchor.state === 'detached') continue
    const occurrence = countOccurrences(content.slice(0, anchor.start), note.quote)
    bands.push({
      kind: 'note',
      start: anchor.start,
      end: anchor.end,
      needle: note.quote,
      occurrence,
      color: note.color,
      title: note.note,
    })
  }
  for (const marker of markers) {
    bands.push({
      kind: marker.kind === 'invalid' ? 'invalid' : marker.kind,
      start: marker.start,
      end: marker.end,
      needle: marker.text.trim(),
      occurrence: 0,
      title: marker.hint || marker.text,
    })
  }
  return bands.sort((a, b) => a.start - b.start || a.end - b.end)
}

export const OVERLAY_THEME = {
  light: {
    note: {
      amber: 'color-mix(in srgb, var(--dsw-alias-state-warn-primary) 48%, transparent)',
      rose: 'color-mix(in srgb, var(--dsw-alias-state-error-primary) 42%, transparent)',
      sky: 'color-mix(in srgb, var(--dsw-alias-state-business-primary) 42%, transparent)',
      lime: 'color-mix(in srgb, var(--dsw-alias-state-success-primary) 42%, transparent)',
      violet: 'color-mix(in srgb, var(--dsw-alias-label-primary) 28%, transparent)',
    },
    state: 'color-mix(in srgb, var(--dsw-alias-state-business-primary) 26%, transparent)',
    relation: 'color-mix(in srgb, var(--dsw-alias-state-warn-primary) 26%, transparent)',
    invalid: 'color-mix(in srgb, var(--dsw-alias-state-error-primary) 18%, transparent)',
  },
  dark: {
    note: {
      amber: 'color-mix(in srgb, var(--dsw-alias-state-warn-primary) 55%, transparent)',
      rose: 'color-mix(in srgb, var(--dsw-alias-state-error-primary) 50%, transparent)',
      sky: 'color-mix(in srgb, var(--dsw-alias-state-business-primary) 50%, transparent)',
      lime: 'color-mix(in srgb, var(--dsw-alias-state-success-primary) 50%, transparent)',
      violet: 'color-mix(in srgb, var(--dsw-alias-label-primary) 34%, transparent)',
    },
    state: 'color-mix(in srgb, var(--dsw-alias-state-business-primary) 32%, transparent)',
    relation: 'color-mix(in srgb, var(--dsw-alias-state-warn-primary) 32%, transparent)',
    invalid: 'color-mix(in srgb, var(--dsw-alias-state-error-primary) 22%, transparent)',
  },
} as const

const OVERLAY_UNDERLINE = {
  light: {
    amber: 'color-mix(in srgb, var(--dsw-alias-state-warn-primary) 85%, transparent)',
    rose: 'color-mix(in srgb, var(--dsw-alias-state-error-primary) 85%, transparent)',
    sky: 'color-mix(in srgb, var(--dsw-alias-state-business-primary) 85%, transparent)',
    lime: 'color-mix(in srgb, var(--dsw-alias-state-success-primary) 85%, transparent)',
    violet: 'color-mix(in srgb, var(--dsw-alias-label-primary) 70%, transparent)',
  },
  dark: {
    amber: 'color-mix(in srgb, var(--dsw-alias-state-warn-primary) 90%, transparent)',
    rose: 'color-mix(in srgb, var(--dsw-alias-state-error-primary) 90%, transparent)',
    sky: 'color-mix(in srgb, var(--dsw-alias-state-business-primary) 90%, transparent)',
    lime: 'color-mix(in srgb, var(--dsw-alias-state-success-primary) 90%, transparent)',
    violet: 'color-mix(in srgb, var(--dsw-alias-label-primary) 75%, transparent)',
  },
} as const

export function overlayFill(kind: OverlayKind, theme: 'light' | 'dark', color: AnnotationColor = 'amber'): string {
  const tokens = OVERLAY_THEME[theme]
  if (kind === 'note') return tokens.note[color]
  return tokens[kind]
}

export function overlayUnderline(theme: 'light' | 'dark', color: AnnotationColor = 'amber'): string {
  return OVERLAY_UNDERLINE[theme][color]
}
