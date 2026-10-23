// After signing in we return the user to where they were going. The target comes from the URL,
// so it is only used when it is a plain in-app path: never another site (open redirect).
export function safeNextPath(value, fallback = '/projects') {
  if (typeof value !== 'string') return fallback
  if (!value.startsWith('/') || value.startsWith('//') || value.includes('\\')) return fallback
  if ([...value].some((ch) => ch.charCodeAt(0) < 32)) return fallback
  if (value === '/signin') return fallback
  return value
}
