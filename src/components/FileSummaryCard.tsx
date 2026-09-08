import type { SelectedFitFile } from '../fit/types'

const FIT_EPOCH_UNIX_SECONDS = 631_065_600

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function formatDuration(seconds: number) {
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const remainder = Math.floor(seconds % 60)
  return hours > 0
    ? `${hours}h ${minutes}m ${remainder}s`
    : `${minutes}m ${remainder}s`
}

function formatTimestamp(timestamp: number | null) {
  if (timestamp === null) return 'No timestamp'
  return new Date((timestamp + FIT_EPOCH_UNIX_SECONDS) * 1000).toLocaleString()
}

interface FileSummaryCardProps {
  item: SelectedFitFile
  selected: boolean
  recommended: boolean
  onSelect(): void
  onRemove(): void
}

export function FileSummaryCard({
  item,
  selected,
  recommended,
  onSelect,
  onRemove,
}: FileSummaryCardProps) {
  const visibleFields = item.summary?.fields.filter((field) => field.samples > 0).slice(0, 7) ?? []

  return (
    <article className={`file-card ${selected ? 'file-card--selected' : ''}`}>
      <div className="file-card__header">
        <div className="file-card__name-wrap">
          <span className="status-dot" data-status={item.status} aria-hidden="true" />
          <div>
            <h3>{item.file.name}</h3>
            <p className="muted">{formatBytes(item.file.size)}</p>
          </div>
        </div>
        <button className="text-button" type="button" onClick={onRemove} aria-label={`Remove ${item.file.name}`}>
          Remove
        </button>
      </div>

      {item.status === 'inspecting' ? <p className="status-copy">Inspecting locally…</p> : null}
      {item.error ? <p className="error" role="alert">{item.error}</p> : null}
      {item.summary ? (
        <>
          <dl className="file-facts">
            <div><dt>Start</dt><dd>{formatTimestamp(item.summary.startTimestamp)}</dd></div>
            <div><dt>Duration</dt><dd>{formatDuration(item.summary.durationSeconds)}</dd></div>
            <div><dt>Records</dt><dd>{item.summary.recordCount.toLocaleString()}</dd></div>
            <div><dt>Integrity</dt><dd className="success">CRC passed</dd></div>
          </dl>
          <div className="chips" aria-label="Detected record fields">
            {visibleFields.map((field) => (
              <span className="chip" key={field.number}>{field.name.replaceAll('_', ' ')}</span>
            ))}
            {item.summary.fields.length > visibleFields.length ? (
              <span className="chip chip--quiet">+{item.summary.fields.length - visibleFields.length}</span>
            ) : null}
          </div>
          <label className="base-choice">
            <input
              type="radio"
              name="base-activity"
              checked={selected}
              onChange={onSelect}
            />
            <span>Use as main activity</span>
            {recommended ? <span className="badge">Recommended</span> : null}
          </label>
        </>
      ) : null}
    </article>
  )
}
