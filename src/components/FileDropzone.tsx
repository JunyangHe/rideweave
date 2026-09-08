import { useRef, useState, type DragEvent } from 'react'

interface FileDropzoneProps {
  disabled: boolean
  remaining: number
  onFiles(files: File[]): void
}

export function FileDropzone({ disabled, remaining, onFiles }: FileDropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  function accept(files: FileList | null) {
    if (!files || disabled) return
    onFiles(Array.from(files))
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault()
    setDragging(false)
    accept(event.dataTransfer.files)
  }

  return (
    <div
      className={`dropzone ${dragging ? 'dropzone--active' : ''} ${disabled ? 'dropzone--disabled' : ''}`}
      onDragEnter={(event) => {
        event.preventDefault()
        if (!disabled) setDragging(true)
      }}
      onDragOver={(event) => event.preventDefault()}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
    >
      <input
        ref={inputRef}
        className="visually-hidden"
        type="file"
        accept=".fit,application/octet-stream"
        multiple
        disabled={disabled}
        onChange={(event) => {
          accept(event.target.files)
          event.target.value = ''
        }}
      />
      <div className="dropzone__icon" aria-hidden="true">FIT</div>
      <div>
        <p className="dropzone__title">Drop FIT files here</p>
        <p className="muted">
          Add 2–4 recordings of the same activity. {remaining} slot{remaining === 1 ? '' : 's'} left.
        </p>
      </div>
      <button
        className="button button--secondary"
        type="button"
        disabled={disabled}
        onClick={() => inputRef.current?.click()}
      >
        Choose files
      </button>
    </div>
  )
}
