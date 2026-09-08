import { describe, expect, it } from 'vitest'
import { recommendBaseId, recommendMappings } from './recommendations'
import type { FitFieldSummary, SelectedFitFile } from './types'

function item(id: string, fields: FitFieldSummary[], recordCount = 100): SelectedFitFile {
  return {
    id,
    file: new File([], `${id}.fit`),
    status: 'ready',
    summary: {
      sizeBytes: 100,
      headerSize: 14,
      dataSize: 84,
      crcValid: true,
      recordCount,
      startTimestamp: 1,
      endTimestamp: 101,
      durationSeconds: 100,
      compressedRecordCount: 0,
      fields,
    },
  }
}

function field(name: string, samples: number, donatable = false): FitFieldSummary {
  return { name, number: 1, samples, coverage: samples / 100, donatable }
}

describe('recommendations', () => {
  it('recommends the strongest GPS activity as base', () => {
    const watch = item('watch', [field('heart_rate', 90, true)], 120)
    const bike = item('bike', [
      field('position_lat', 100),
      field('position_long', 100),
      field('distance', 100),
      field('speed', 100),
    ])
    expect(recommendBaseId([watch, bike])).toBe('bike')
  })

  it('preserves base fields and recommends the donor with most samples', () => {
    const base = item('base', [field('heart_rate', 80, true)])
    const donorA = item('a', [field('power', 70, true)])
    const donorB = item('b', [field('power', 95, true), field('cadence', 90, true)])
    expect(recommendMappings([base, donorA, donorB], 'base')).toEqual({
      heart_rate: 'base',
      power: 'b',
      cadence: 'b',
    })
  })
})
