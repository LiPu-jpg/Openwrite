/** Prefer RFC 5987 names, retaining literal percent signs in legacy filenames. */
export function downloadFilename(disposition: string, fallback: string): string {
  const encoded = /(?:^|;)\s*filename\*\s*=\s*(?:"?UTF-8'[^']*')([^";]+)"?/i.exec(disposition)
  const legacy = /(?:^|;)\s*filename\s*=\s*(?:"([^"]*)"|([^;]*))/i.exec(disposition)
  let name = legacy?.[1] ?? legacy?.[2]?.trim() ?? fallback
  if (encoded?.[1]) {
    try { name = decodeURIComponent(encoded[1]) } catch { /* retain legacy/fallback */ }
  }
  return name.split(/[\\/]/).at(-1)?.replace(/[\x00-\x1f\x7f]/g, '').trim() || fallback
}

/** Safari needs an attached link and time to consume the Blob URL. */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.hidden = true
  document.body.append(anchor)
  try { anchor.click() }
  finally {
    anchor.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
  }
}
