/// <reference lib="webworker" />

interface PyodideRuntime {
  FS: {
    writeFile(path: string, data: Uint8Array): void
    readFile(path: string): Uint8Array
    unlink(path: string): void
  }
  runPythonAsync(code: string): Promise<unknown>
}

interface PyodideModule {
  loadPyodide(options: { indexURL: string }): Promise<PyodideRuntime>
}

interface InputFile {
  id: string
  name: string
  bytes: ArrayBuffer
}

interface Selection {
  fileId: string
  toleranceSeconds: number
}

interface WorkerRequest {
  id: number
  type: 'inspect' | 'preview' | 'merge'
  files: InputFile[]
  baseId?: string
  selections?: Record<string, Selection>
}

const PYODIDE_VERSION = '0.28.3'
const PYODIDE_BASE = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`
let runtimePromise: Promise<PyodideRuntime> | null = null

async function getRuntime() {
  if (!runtimePromise) {
    runtimePromise = (async () => {
      const moduleUrl = `${PYODIDE_BASE}pyodide.mjs`
      const pyodideModule = (await import(/* @vite-ignore */ moduleUrl)) as PyodideModule
      const runtime = await pyodideModule.loadPyodide({ indexURL: PYODIDE_BASE })
      const engineUrl = new URL(`${import.meta.env.BASE_URL}python/merge_fit.py`, self.location.origin)
      const response = await fetch(engineUrl, { cache: 'force-cache' })
      if (!response.ok) throw new Error('Could not load the local FIT merge engine.')
      const engineSource = await response.text()
      await runtime.runPythonAsync(`
import sys
import types
_rideweave_module = types.ModuleType("rideweave_engine")
sys.modules[_rideweave_module.__name__] = _rideweave_module
exec(compile(${JSON.stringify(engineSource)}, "merge_fit.py", "exec"), _rideweave_module.__dict__)
json = _rideweave_module.json
Path = _rideweave_module.Path
inspect_fit = _rideweave_module.inspect_fit
preview_web = _rideweave_module.preview_web
merge_web = _rideweave_module.merge_web
`)
      return runtime
    })()
  }
  return runtimePromise
}

function pathFor(index: number) {
  return `/tmp/fit-input-${index}.fit`
}

function writeFiles(runtime: PyodideRuntime, files: InputFile[]) {
  const paths = new Map<string, string>()
  files.forEach((file, index) => {
    const path = pathFor(index)
    runtime.FS.writeFile(path, new Uint8Array(file.bytes))
    paths.set(file.id, path)
  })
  return paths
}

function configFor(request: WorkerRequest, paths: Map<string, string>, outputPath?: string) {
  if (!request.baseId) throw new Error('Choose one main activity.')
  const basePath = paths.get(request.baseId)
  if (!basePath) throw new Error('The selected main activity is unavailable.')
  const selections: Record<string, { path: string; toleranceSeconds: number }> = {}
  for (const [name, selection] of Object.entries(request.selections ?? {})) {
    const path = paths.get(selection.fileId)
    if (!path) throw new Error(`The ${name} source is unavailable.`)
    selections[name] = { path, toleranceSeconds: selection.toleranceSeconds }
  }
  return { basePath, outputPath, selections }
}

function clean(runtime: PyodideRuntime, count: number, outputPath?: string) {
  for (let index = 0; index < count; index += 1) {
    try {
      runtime.FS.unlink(pathFor(index))
    } catch {
      // The file may not exist when parsing failed before it was written.
    }
  }
  if (outputPath) {
    try {
      runtime.FS.unlink(outputPath)
    } catch {
      // The merger intentionally does not create an output on failure.
    }
  }
}

self.onmessage = async (event: MessageEvent<WorkerRequest>) => {
  const request = event.data
  let runtime: PyodideRuntime | null = null
  const outputPath = '/tmp/merged.fit'
  try {
    runtime = await getRuntime()
    const paths = writeFiles(runtime, request.files)

    if (request.type === 'inspect') {
      const results = []
      for (let index = 0; index < request.files.length; index += 1) {
        try {
          const json = await runtime.runPythonAsync(
            `json.dumps(inspect_fit(Path(${JSON.stringify(pathFor(index))})))`,
          )
          results.push({ summary: JSON.parse(String(json)) })
        } catch (error) {
          results.push({ error: error instanceof Error ? error.message : String(error) })
        }
      }
      self.postMessage({ id: request.id, ok: true, result: results })
      return
    }

    const config = configFor(request, paths, request.type === 'merge' ? outputPath : undefined)
    if (Object.keys(config.selections).length === 0) {
      throw new Error('Choose at least one donor field before merging.')
    }
    const configJson = JSON.stringify(config)

    if (request.type === 'preview') {
      const json = await runtime.runPythonAsync(`preview_web(${JSON.stringify(configJson)})`)
      self.postMessage({ id: request.id, ok: true, result: JSON.parse(String(json)) })
      return
    }

    const json = await runtime.runPythonAsync(`merge_web(${JSON.stringify(configJson)})`)
    const output = runtime.FS.readFile(outputPath).slice().buffer
    self.postMessage(
      { id: request.id, ok: true, result: { bytes: output, stats: JSON.parse(String(json)) } },
      { transfer: [output] },
    )
  } catch (error) {
    self.postMessage({
      id: request.id,
      ok: false,
      error: error instanceof Error ? error.message : String(error),
    })
  } finally {
    if (runtime) clean(runtime, request.files.length, outputPath)
  }
}

export {}
