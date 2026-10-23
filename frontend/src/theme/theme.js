// Theme preference logic, kept free of React so it is easy to test. The same rules are
// inlined in index.html so the right theme is applied before the first paint.

export const THEME_KEY = 'sentinel-theme'
export const PREFERENCES = ['light', 'dark', 'system']

export function readPreference(storage) {
  try {
    const value = storage.getItem(THEME_KEY)
    return value === 'light' || value === 'dark' ? value : 'system'
  } catch {
    return 'system' // storage can throw (private mode, blocked site data)
  }
}

export function savePreference(storage, preference) {
  try {
    if (preference === 'system') storage.removeItem(THEME_KEY)
    else storage.setItem(THEME_KEY, preference)
  } catch {
    // The choice still applies for this page view; it just will not persist.
  }
}

export function resolveTheme(preference, prefersDark) {
  if (preference === 'light' || preference === 'dark') return preference
  return prefersDark ? 'dark' : 'light'
}

export function applyTheme(root, preference, resolved) {
  root.dataset.theme = resolved
  root.dataset.themePref = preference
}
