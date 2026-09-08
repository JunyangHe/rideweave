import { fieldLabels } from '../fit/recommendations'
import type { DonorFieldName, MergePreview } from '../fit/types'

interface CoveragePreviewProps {
  preview: MergePreview
}

export function CoveragePreview({ preview }: CoveragePreviewProps) {
  const fields = Object.entries(preview.fields) as Array<
    [DonorFieldName, NonNullable<MergePreview['fields'][DonorFieldName]>]
  >

  return (
    <div className="coverage-list">
      {fields.map(([name, result]) => {
        const percent = Math.round(result.coverage * 1000) / 10
        const low = result.coverage < 0.8
        return (
          <div className="coverage" key={name}>
            <div className="coverage__heading">
              <strong>{fieldLabels[name]}</strong>
              <span className={low ? 'warning-text' : 'success'}>{percent}% coverage</span>
            </div>
            <div className="coverage__track" aria-label={`${fieldLabels[name]} ${percent}% coverage`}>
              <span style={{ width: `${percent}%` }} />
            </div>
            <p className="muted small">
              {result.matched.toLocaleString()} of {result.baseRecords.toLocaleString()} base records · median delta {result.medianDeltaSeconds ?? '—'}s · p95 {result.p95DeltaSeconds ?? '—'}s
            </p>
            {low ? <p className="warning-text small">Low coverage: check that these files overlap in real time.</p> : null}
          </div>
        )
      })}
    </div>
  )
}
