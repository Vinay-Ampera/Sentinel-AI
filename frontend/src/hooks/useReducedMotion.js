import { useEffect, useState } from 'react'

const QUERY = '(prefers-reduced-motion: reduce)'
const query = () => (typeof window !== 'undefined' && window.matchMedia ? window.matchMedia(QUERY) : null)

// True when the visitor's system asks for reduced motion; follows changes while the page is open.
export function useReducedMotion() {
  const [reduced, setReduced] = useState(() => Boolean(query() && query().matches))
  useEffect(() => {
    const q = query()
    if (!q || !q.addEventListener) return undefined
    const onChange = (event) => setReduced(event.matches)
    q.addEventListener('change', onChange)
    return () => q.removeEventListener('change', onChange)
  }, [])
  return reduced
}
