export const donorFieldNames = ['heart_rate', 'power', 'cadence'] as const

export type DonorFieldName = (typeof donorFieldNames)[number]

export interface FitFieldSummary {
  name: string
  number: number
  samples: number
  coverage: number
  donatable: boolean
}

export interface FitSummary {
  sizeBytes: number
  headerSize: number
  dataSize: number
  crcValid: boolean
  recordCount: number
  startTimestamp: number | null
  endTimestamp: number | null
  durationSeconds: number
  compressedRecordCount: number
  fields: FitFieldSummary[]
}

export interface SelectedFitFile {
  id: string
  file: File
  status: 'inspecting' | 'ready' | 'error'
  summary?: FitSummary
  error?: string
}

export type FieldMapping = Record<DonorFieldName, string | null>

export interface FieldCoverage {
  matched: number
  baseRecords: number
  coverage: number
  sourceSamples: number
  medianDeltaSeconds: number | null
  p95DeltaSeconds: number | null
  toleranceSeconds: number
}

export interface MergePreview {
  baseRecords: number
  fields: Partial<Record<DonorFieldName, FieldCoverage>>
}

export interface MergeStats {
  baseRecords: number
  fields: Partial<
    Record<
      DonorFieldName,
      {
        sourceSamples: number
        matchedRecords: number
        outputSamples: number
        coverage: number
        toleranceSeconds: number
      }
    >
  >
  outputBytes: number
  validation: 'PASS'
}

export interface MergeResult {
  bytes: ArrayBuffer
  stats: MergeStats
}
