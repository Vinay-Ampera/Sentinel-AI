// Display helpers. Dates come from the server as ISO strings; nothing is guessed when one is
// missing.
const dateTime = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' })
const dateOnly = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' })

export const formatDateTime = (iso) => (iso ? dateTime.format(new Date(iso)) : 'Not available')
export const formatDate = (iso) => (iso ? dateOnly.format(new Date(iso)) : 'Not available')

export function formatBytes(n) {
  if (typeof n !== 'number') return 'Not available'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / (1024 * 1024)).toFixed(1)} MB`
}

export const titleCase = (s) => String(s).replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())

export function formatDuration(ms) {
  if (typeof ms !== 'number') return 'Not available'
  if (ms < 1000) return `${ms} ms`
  const s = Math.round(ms / 1000)
  if (s < 60) return `${s} s`
  const m = Math.floor(s / 60)
  return m < 60 ? `${m} min ${s % 60} s` : `${Math.floor(m / 60)} h ${m % 60} min`
}

// Time between two ISO timestamps, or null when either is missing (still running, never started).
export function durationBetween(startIso, endIso) {
  if (!startIso || !endIso) return null
  return Math.max(0, new Date(endIso).getTime() - new Date(startIso).getTime())
}

export const formatTime = (date) => (date ? date.toLocaleTimeString() : 'Not available')
