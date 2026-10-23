import { useEffect, useState } from 'react'

// Load once, reload on demand, and keep reloading every pollMs while `active` (a boolean, or a
// function of the loaded data) is true. Polling skips ticks while the tab is hidden. A failed
// refresh keeps the last good data and reports the error next to it, so a flaky network does not
// blank a page that was showing a live run. `updatedAt` is when data last loaded successfully.
export function usePolledLoad(load, active, pollMs = 3000) {
  const [tick, setTick] = useState(0)
  const [state, setState] = useState({ key: null, error: null, data: null, updatedAt: null })

  useEffect(() => {
    let live = true
    load()
      .then((data) => live && setState({ key: load, error: null, data, updatedAt: new Date() }))
      .catch((error) => live && setState((s) => ({ key: load, error, data: s.key === load ? s.data : null, updatedAt: s.key === load ? s.updatedAt : null })))
    return () => {
      live = false
    }
  }, [load, tick])

  const current = state.key === load
  const data = current ? state.data : null
  const polling = typeof active === 'function' ? active(data) : active

  useEffect(() => {
    if (!polling) return undefined
    const id = setInterval(() => {
      if (typeof document === 'undefined' || !document.hidden) setTick((t) => t + 1)
    }, pollMs)
    return () => clearInterval(id)
  }, [polling, pollMs])

  return [{ loading: !current, error: current ? state.error : null, data, updatedAt: current ? state.updatedAt : null }, () => setTick((t) => t + 1)]
}
