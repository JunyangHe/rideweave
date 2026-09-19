import { afterEach, describe, expect, it, vi } from 'vitest'
import { downloadFit } from './download'

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('downloadFit', () => {
  it('starts a download with the requested filename and releases the object URL', () => {
    vi.useFakeTimers()
    const link = {
      href: '',
      download: '',
      style: { display: '' },
      click: vi.fn(),
      remove: vi.fn(),
    }
    const append = vi.fn()
    vi.stubGlobal('document', {
      createElement: vi.fn().mockReturnValue(link),
      body: { append },
    })
    const createObjectURL = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:rideweave-test')
    const revokeObjectURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})

    downloadFit(new Uint8Array([1, 2, 3]).buffer, 'main-merged.fit')

    expect(createObjectURL).toHaveBeenCalledOnce()
    expect(link.href).toBe('blob:rideweave-test')
    expect(link.download).toBe('main-merged.fit')
    expect(append).toHaveBeenCalledWith(link)
    expect(link.click).toHaveBeenCalledOnce()
    expect(link.remove).toHaveBeenCalledOnce()
    expect(revokeObjectURL).not.toHaveBeenCalled()

    vi.advanceTimersByTime(60_000)
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:rideweave-test')
  })
})
