import type {
  DonorFieldName,
  FitSummary,
  MergePreview,
  MergeResult,
  SelectedFitFile,
} from './types'
import { fieldTolerances, selectedDonors } from './recommendations'

interface WorkerReply<T> {
  id: number
  ok: boolean
  result?: T
  error?: string
}

interface InspectionResult {
  summary?: FitSummary
  error?: string
}

let worker: Worker | null = null
let requestId = 0

function getWorker() {
  worker ??= new Worker(new URL('../workers/fit.worker.ts', import.meta.url), {
    type: 'module',
  })
  return worker
}

function request<T>(message: object, transfer: Transferable[] = []): Promise<T> {
  const target = getWorker()
  const id = ++requestId
  return new Promise((resolve, reject) => {
    const listener = (event: MessageEvent<WorkerReply<T>>) => {
      if (event.data.id !== id) return
      target.removeEventListener('message', listener)
      if (event.data.ok && event.data.result !== undefined) {
        resolve(event.data.result)
      } else {
        reject(new Error(event.data.error ?? 'The FIT worker failed.'))
      }
    }
    target.addEventListener('message', listener)
    target.postMessage({ ...message, id }, transfer)
  })
}

async function readFiles(files: SelectedFitFile[]) {
  const buffers = await Promise.all(files.map((item) => item.file.arrayBuffer()))
  return {
    files: files.map((item, index) => ({
      id: item.id,
      name: item.file.name,
      bytes: buffers[index] as ArrayBuffer,
    })),
    transfer: buffers,
  }
}

export async function inspectFiles(files: SelectedFitFile[]) {
  const payload = await readFiles(files)
  return request<InspectionResult[]>(
    { type: 'inspect', files: payload.files },
    payload.transfer,
  )
}

function workerSelections(
  files: SelectedFitFile[],
  baseId: string,
  mapping: Record<DonorFieldName, string | null>,
) {
  const selections: Partial<Record<DonorFieldName, { fileId: string; toleranceSeconds: number }>> = {}
  for (const name of selectedDonors(mapping, baseId)) {
    const fileId = mapping[name]
    if (fileId && files.some((item) => item.id === fileId)) {
      selections[name] = { fileId, toleranceSeconds: fieldTolerances[name] }
    }
  }
  return selections
}

export async function previewMerge(
  files: SelectedFitFile[],
  baseId: string,
  mapping: Record<DonorFieldName, string | null>,
) {
  const payload = await readFiles(files)
  return request<MergePreview>(
    {
      type: 'preview',
      files: payload.files,
      baseId,
      selections: workerSelections(files, baseId, mapping),
    },
    payload.transfer,
  )
}

export async function mergeFiles(
  files: SelectedFitFile[],
  baseId: string,
  mapping: Record<DonorFieldName, string | null>,
) {
  const payload = await readFiles(files)
  return request<MergeResult>(
    {
      type: 'merge',
      files: payload.files,
      baseId,
      selections: workerSelections(files, baseId, mapping),
    },
    payload.transfer,
  )
}

export function terminateFitWorker() {
  worker?.terminate()
  worker = null
}
