import { afterEach, describe, expect, it, vi } from 'vitest'
import { downloadBlob, downloadFilename } from '../../src/client/browser-download.ts'

afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

describe('browser downloads', () => {
  it('keeps a connected link and a live blob until Safari has consumed the click', () => {
    vi.useFakeTimers()
    const revoke = vi.fn()
    const create = vi.fn(() => 'blob:mobile-export')
    vi.stubGlobal('URL', { createObjectURL: create, revokeObjectURL: revoke })
    let clicked = false
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      clicked = true
      expect(this.isConnected).toBe(true)
      expect(this.download).toBe('作品.epub')
      expect(this.href).toBe('blob:mobile-export')
      expect(revoke).not.toHaveBeenCalled()
    })
    downloadBlob(new Blob(['正文']), '作品.epub')
    expect(clicked).toBe(true)
    expect(document.querySelector('a[download]')).toBeNull()
    vi.advanceTimersByTime(59_999)
    expect(revoke).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1)
    expect(revoke).toHaveBeenCalledWith('blob:mobile-export')
  })

  it.each([
    ["attachment; filename=old.md; filename*=UTF-8''%E4%BD%9C%E5%93%81.epub", '作品.epub'],
    ['attachment; filename="100%完成.md"', '100%完成.md'],
    ["attachment; filename*=UTF-8''%broken", 'book.md'],
    ['attachment; filename="../../作品.md"', '作品.md'],
  ])('reads portable filenames: %s', (header, expected) => {
    expect(downloadFilename(header, 'book.md')).toBe(expected)
  })
})
