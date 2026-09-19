const URL_REVOKE_DELAY_MS = 60_000

export function downloadFit(bytes: ArrayBuffer, fileName: string) {
  const blob = new Blob([bytes], { type: 'application/octet-stream' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = fileName
  link.style.display = 'none'
  document.body.append(link)

  try {
    link.click()
  } finally {
    link.remove()
    // Keep the object URL alive long enough for the browser to start saving it.
    setTimeout(() => URL.revokeObjectURL(url), URL_REVOKE_DELAY_MS)
  }
}
