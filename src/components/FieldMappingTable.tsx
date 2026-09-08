import { donorFieldNames, type DonorFieldName, type FieldMapping, type SelectedFitFile } from '../fit/types'
import { fieldLabels, fieldTolerances, getField } from '../fit/recommendations'

interface FieldMappingTableProps {
  files: SelectedFitFile[]
  baseId: string
  mapping: FieldMapping
  onChange(name: DonorFieldName, sourceId: string | null): void
}

export function FieldMappingTable({ files, baseId, mapping, onChange }: FieldMappingTableProps) {
  const base = files.find((item) => item.id === baseId)
  const baseFieldNames = new Set(
    base?.summary?.fields.filter((field) => field.samples > 0).map((field) => field.name),
  )
  const detectedFields = Array.from(
    new Map(
      files.flatMap((item) => item.summary?.fields ?? []).map((field) => [field.number, field]),
    ).values(),
  ).sort((left, right) => left.number - right.number)

  return (
    <div className="mapping-wrap">
      <table className="mapping-table">
        <thead>
          <tr><th>Record field</th><th>Authoritative source</th><th>Matching</th></tr>
        </thead>
        <tbody>
          <tr>
            <td><strong>Timestamp</strong><span className="field-code">FIT 253</span></td>
            <td><span className="locked-source">{base?.file.name} · locked</span></td>
            <td>Exact base timeline</td>
          </tr>
          {donorFieldNames.map((name) => {
            const baseHasField = baseFieldNames.has(name)
            const sources = files.filter((item) => (getField(item, name)?.samples ?? 0) > 0)
            return (
              <tr key={name}>
                <td><strong>{fieldLabels[name]}</strong><span className="field-code">{fieldTolerances[name]}s tolerance</span></td>
                <td>
                  <select
                    aria-label={`${fieldLabels[name]} authoritative source`}
                    value={mapping[name] ?? ''}
                    onChange={(event) => onChange(name, event.target.value || null)}
                  >
                    {!baseHasField ? <option value="">Do not add</option> : null}
                    {sources.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.file.name}{item.id === baseId ? ' (base)' : ''}
                      </option>
                    ))}
                  </select>
                </td>
                <td>Nearest valid sample</td>
              </tr>
            )
          })}
        </tbody>
      </table>

      <details className="detected-fields">
        <summary>All detected record fields ({detectedFields.length})</summary>
        <div className="chips">
          {detectedFields.map((field) => (
            <span className="chip chip--quiet" key={field.number}>
              {field.name.replaceAll('_', ' ')} · FIT {field.number}
            </span>
          ))}
        </div>
        <p className="muted small">The POC can donate heart rate, power, and cadence. Every other field stays byte-for-byte with the base activity.</p>
      </details>
    </div>
  )
}
