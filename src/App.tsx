import { useEffect, useMemo, useState } from 'react'
import { CoveragePreview } from './components/CoveragePreview'
import { FieldMappingTable } from './components/FieldMappingTable'
import { FileDropzone } from './components/FileDropzone'
import { FileSummaryCard } from './components/FileSummaryCard'
import {
  recommendBaseId,
  recommendMappings,
  selectedDonors,
} from './fit/recommendations'
import type {
  DonorFieldName,
  FieldMapping,
  MergePreview,
  MergeResult,
  SelectedFitFile,
} from './fit/types'
import {
  inspectFiles,
  mergeFiles,
  previewMerge,
  terminateFitWorker,
} from './fit/workerClient'

const EMPTY_MAPPING: FieldMapping = {
  heart_rate: null,
  power: null,
  cadence: null,
}

interface DownloadState extends MergeResult {
  url: string
  fileName: string
}

function friendlyError(error: unknown) {
  const message = error instanceof Error ? error.message : String(error)
  const lastLine = message.trim().split('\n').at(-1) ?? message
  return lastLine.replace(/^ValueError:\s*/, '')
}

function mergedName(baseName: string) {
  const stem = baseName.toLowerCase().endsWith('.fit') ? baseName.slice(0, -4) : baseName
  return `${stem}-merged.fit`
}

export default function App() {
  const [files, setFiles] = useState<SelectedFitFile[]>([])
  const [baseId, setBaseId] = useState<string | null>(null)
  const [mapping, setMapping] = useState<FieldMapping>(EMPTY_MAPPING)
  const [preview, setPreview] = useState<MergePreview | null>(null)
  const [download, setDownload] = useState<DownloadState | null>(null)
  const [busy, setBusy] = useState<'idle' | 'inspecting' | 'previewing' | 'merging'>('idle')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => () => {
    if (download) URL.revokeObjectURL(download.url)
    terminateFitWorker()
  }, [download])

  const readyFiles = files.filter((item) => item.status === 'ready')
  const recommendedBase = useMemo(() => recommendBaseId(files), [files])
  const donors = selectedDonors(mapping, baseId)
  const selectedBase = files.find((item) => item.id === baseId)
  const allValid = files.length >= 2 && files.length <= 4 && files.every((item) => item.status === 'ready')
  const baseSupported = (selectedBase?.summary?.compressedRecordCount ?? 0) === 0
  const coverageReady = preview !== null && Object.values(preview.fields).every((field) => field.coverage > 0)
  const canMerge = allValid && Boolean(baseId) && baseSupported && donors.length > 0 && coverageReady && busy === 'idle'

  function clearResult() {
    setPreview(null)
    setDownload((current) => {
      if (current) URL.revokeObjectURL(current.url)
      return null
    })
  }

  async function addFiles(incoming: File[]) {
    setError(null)
    const invalid = incoming.find((file) => !file.name.toLowerCase().endsWith('.fit') || file.size === 0)
    if (invalid) {
      setError(`${invalid.name} is not a non-empty .fit file.`)
      return
    }
    const room = 4 - files.length
    if (incoming.length > room) {
      setError(`You can add at most four files. Remove a file before adding more.`)
      return
    }

    const added: SelectedFitFile[] = incoming.map((file) => ({
      id: crypto.randomUUID(),
      file,
      status: 'inspecting',
    }))
    setFiles((current) => [...current, ...added])
    setBusy('inspecting')
    clearResult()
    try {
      const results = await inspectFiles(added)
      setFiles((current) => current.map((item) => {
        const index = added.findIndex((candidate) => candidate.id === item.id)
        if (index < 0) return item
        const result = results[index]
        if (!result?.summary) {
          return { ...item, status: 'error', error: friendlyError(result?.error ?? 'Could not inspect this FIT file.') }
        }
        if (result.summary.recordCount === 0) {
          return { ...item, status: 'error', error: 'No Record messages were found.' }
        }
        return { ...item, status: 'ready', summary: result.summary, error: undefined }
      }))
    } catch (inspectionError) {
      const message = friendlyError(inspectionError)
      setFiles((current) => current.map((item) => (
        added.some((candidate) => candidate.id === item.id)
          ? { ...item, status: 'error', error: message }
          : item
      )))
    } finally {
      setBusy('idle')
    }
  }

  function removeFile(id: string) {
    setFiles((current) => current.filter((item) => item.id !== id))
    if (baseId === id) {
      setBaseId(null)
      setMapping(EMPTY_MAPPING)
    } else {
      setMapping((current) => ({
        heart_rate: current.heart_rate === id ? null : current.heart_rate,
        power: current.power === id ? null : current.power,
        cadence: current.cadence === id ? null : current.cadence,
      }))
    }
    clearResult()
    setError(null)
  }

  function chooseBase(id: string) {
    setBaseId(id)
    setMapping(recommendMappings(files, id))
    clearResult()
    setError(null)
  }

  function changeMapping(name: DonorFieldName, sourceId: string | null) {
    setMapping((current) => ({ ...current, [name]: sourceId }))
    clearResult()
  }

  async function analyzeCoverage() {
    if (!baseId || donors.length === 0) return
    setBusy('previewing')
    setError(null)
    clearResult()
    try {
      setPreview(await previewMerge(files, baseId, mapping))
    } catch (previewError) {
      setError(friendlyError(previewError))
    } finally {
      setBusy('idle')
    }
  }

  async function runMerge() {
    if (!baseId || !selectedBase || !canMerge) return
    setBusy('merging')
    setError(null)
    setDownload((current) => {
      if (current) URL.revokeObjectURL(current.url)
      return null
    })
    try {
      const result = await mergeFiles(files, baseId, mapping)
      const blob = new Blob([result.bytes], { type: 'application/octet-stream' })
      setDownload({
        ...result,
        url: URL.createObjectURL(blob),
        fileName: mergedName(selectedBase.file.name),
      })
    } catch (mergeError) {
      setError(friendlyError(mergeError))
    } finally {
      setBusy('idle')
    }
  }

  return (
    <main>
      <header className="hero">
        <div className="eyebrow">RideWeave · Open source · browser only</div>
        <h1>One ride.<br />Every sensor.</h1>
        <p className="hero__lede">Keep the best activity as your foundation, then add heart rate, power, or cadence from your other recordings.</p>
        <div className="privacy-card">
          <span aria-hidden="true">◆</span>
          <div><strong>Private by design</strong><p>Your FIT files never leave this device. There is no upload or account.</p></div>
        </div>
      </header>

      <section className="panel" aria-labelledby="files-heading">
        <div className="section-heading"><span>1</span><div><h2 id="files-heading">Add your recordings</h2><p>Choose two to four FIT files from the same activity.</p></div></div>
        <FileDropzone disabled={files.length >= 4 || busy === 'inspecting'} remaining={4 - files.length} onFiles={addFiles} />
        {files.length > 0 ? (
          <div className="file-grid">
            {files.map((item) => (
              <FileSummaryCard
                key={item.id}
                item={item}
                selected={item.id === baseId}
                recommended={item.id === recommendedBase}
                onSelect={() => chooseBase(item.id)}
                onRemove={() => removeFile(item.id)}
              />
            ))}
          </div>
        ) : null}
      </section>

      <section className="panel" aria-labelledby="mapping-heading">
        <div className="section-heading"><span>2</span><div><h2 id="mapping-heading">Choose what wins</h2><p>The main activity keeps its timeline, GPS, laps, pauses, and events.</p></div></div>
        {!baseId ? <p className="empty-state">Select one file above as the main activity to configure fields.</p> : (
          <>
            {!baseSupported ? <p className="error" role="alert">This file uses compressed base records, which the POC cannot safely rewrite yet. Choose another main activity.</p> : null}
            <FieldMappingTable files={readyFiles} baseId={baseId} mapping={mapping} onChange={changeMapping} />
          </>
        )}
      </section>

      <section className="panel" aria-labelledby="review-heading">
        <div className="section-heading"><span>3</span><div><h2 id="review-heading">Review coverage</h2><p>Matching uses real FIT timestamps—recordings are never shifted to share a start time.</p></div></div>
        {baseId && donors.length > 0 ? (
          <>
            <button className="button button--secondary" type="button" disabled={busy !== 'idle'} onClick={analyzeCoverage}>
              {busy === 'previewing' ? 'Analyzing locally…' : 'Analyze alignment'}
            </button>
            {preview ? <CoveragePreview preview={preview} /> : null}
          </>
        ) : <p className="empty-state">Choose at least one field from a donor file.</p>}
      </section>

      <section className="merge-panel" aria-labelledby="merge-heading">
        <div><p className="eyebrow">Final step</p><h2 id="merge-heading">Build your merged FIT</h2><p>The result is reparsed and its header and file CRC are verified before download.</p></div>
        <button className="button button--primary" type="button" disabled={!canMerge} onClick={runMerge}>
          {busy === 'merging' ? 'Merging and validating…' : 'Merge FIT files'}
        </button>
      </section>

      {error ? <div className="error-banner" role="alert"><strong>Couldn’t continue</strong><p>{error}</p></div> : null}
      {download ? (
        <section className="success-panel" aria-live="polite">
          <div><p className="eyebrow">Validation passed</p><h2>Your merged activity is ready</h2><p>{download.stats.baseRecords.toLocaleString()} base records · {(download.stats.outputBytes / 1024).toFixed(1)} KB</p></div>
          <a className="button button--primary" href={download.url} download={download.fileName}>Download {download.fileName}</a>
        </section>
      ) : null}

      <footer>RideWeave v0.1 POC · Local processing only</footer>
    </main>
  )
}
