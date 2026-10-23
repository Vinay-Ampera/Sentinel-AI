import { useCallback, useEffect, useMemo, useState } from 'react'
import { ThemeContext } from '../hooks/useTheme.js'
import { applyTheme, readPreference, resolveTheme, savePreference } from './theme.js'

const DARK_QUERY = '(prefers-color-scheme: dark)'

const systemQuery = () => (typeof window !== 'undefined' && window.matchMedia ? window.matchMedia(DARK_QUERY) : null)

export function ThemeProvider({ children }) {
  const [preference, setPreference] = useState(() => readPreference(window.localStorage))
  const [prefersDark, setPrefersDark] = useState(() => Boolean(systemQuery() && systemQuery().matches))

  // "System" follows the operating system, including changes while the page is open.
  useEffect(() => {
    const query = systemQuery()
    if (!query || !query.addEventListener) return undefined
    const onChange = (event) => setPrefersDark(event.matches)
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [])

  const resolved = resolveTheme(preference, prefersDark)

  useEffect(() => {
    applyTheme(document.documentElement, preference, resolved)
  }, [preference, resolved])

  const choose = useCallback((next) => {
    setPreference(next)
    savePreference(window.localStorage, next)
  }, [])

  const value = useMemo(() => ({ preference, resolved, setPreference: choose }), [preference, resolved, choose])
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
}
