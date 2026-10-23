import { useEffect, useState } from 'react'

// Fetch when `fn` (a memoized loader) changes or reload() is called. `loading` is derived
// from which request the stored result belongs to, so no state is set synchronously.
// `error` keeps the original error object (status, code) so pages can map 401/403/409/422;
// use errorMessage for the plain text.
export function useLoad(fn) {
  const [tick, setTick] = useState(0)
  const [result, setResult] = useState({ key: null, tick: 0, error: null, data: null })
  useEffect(() => {
    let live = true
    fn()
      .then((data) => live && setResult({ key: fn, tick, error: null, data }))
      .catch((e) => live && setResult({ key: fn, tick, error: e, data: null }))
    return () => {
      live = false
    }
  }, [fn, tick])
  const current = result.key === fn && result.tick === tick
  const state = current
    ? { loading: false, error: result.error, errorMessage: result.error ? result.error.message : null, data: result.data }
    : { loading: true, error: null, errorMessage: null, data: null }
  return [state, () => setTick((t) => t + 1)]
}
