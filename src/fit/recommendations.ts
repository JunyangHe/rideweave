import {
  donorFieldNames,
  type DonorFieldName,
  type FieldMapping,
  type SelectedFitFile,
} from './types'

export const fieldLabels: Record<DonorFieldName, string> = {
  heart_rate: 'Heart rate',
  power: 'Power',
  cadence: 'Cadence',
}

export const fieldTolerances: Record<DonorFieldName, number> = {
  heart_rate: 5,
  power: 1,
  cadence: 2,
}

export function getField(
  item: SelectedFitFile | undefined,
  name: string,
) {
  return item?.summary?.fields.find((field) => field.name === name)
}

export function recommendBaseId(files: SelectedFitFile[]): string | null {
  let best: { id: string; score: number } | null = null
  for (const item of files) {
    if (!item.summary) continue
    const fields = new Set(
      item.summary.fields
        .filter((field) => field.samples > 0)
        .map((field) => field.name),
    )
    const structureScore = item.summary.recordCount
    const locationScore = fields.has('position_lat') && fields.has('position_long') ? 1_000_000 : 0
    const rideScore = ['distance', 'speed', 'altitude'].filter((name) => fields.has(name)).length * 100_000
    const score = locationScore + rideScore + structureScore
    if (!best || score > best.score) best = { id: item.id, score }
  }
  return best?.id ?? null
}

export function recommendMappings(
  files: SelectedFitFile[],
  baseId: string | null,
): FieldMapping {
  const mapping: FieldMapping = {
    heart_rate: null,
    power: null,
    cadence: null,
  }
  if (!baseId) return mapping
  const base = files.find((item) => item.id === baseId)

  for (const name of donorFieldNames) {
    if ((getField(base, name)?.samples ?? 0) > 0) {
      mapping[name] = baseId
      continue
    }
    let best: { id: string; samples: number } | null = null
    for (const item of files) {
      if (item.id === baseId) continue
      const field = getField(item, name)
      if (!field?.donatable || field.samples === 0) continue
      if (!best || field.samples > best.samples) {
        best = { id: item.id, samples: field.samples }
      }
    }
    mapping[name] = best?.id ?? null
  }
  return mapping
}

export function selectedDonors(mapping: FieldMapping, baseId: string | null) {
  return donorFieldNames.filter((name) => {
    const source = mapping[name]
    return source !== null && source !== baseId
  })
}
