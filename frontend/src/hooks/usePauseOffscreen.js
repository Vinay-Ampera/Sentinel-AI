import { useEffect } from 'react'

// Pauses an animated SVG (SMIL animations, and CSS animations through data-paused) while it is
// scrolled out of view or the tab is hidden, so decoration costs nothing when nobody sees it.
export function usePauseOffscreen(containerRef, svgRef) {
  useEffect(() => {
    const container = containerRef.current
    const svg = svgRef.current
    if (!container || !svg) return undefined
    let visible = true
    let tabShown = typeof document === 'undefined' || document.visibilityState !== 'hidden'
    const apply = () => {
      const paused = !(visible && tabShown)
      container.dataset.paused = String(paused)
      if (typeof svg.pauseAnimations === 'function') {
        if (paused) svg.pauseAnimations()
        else svg.unpauseAnimations()
      }
    }
    let observer = null
    if (typeof IntersectionObserver !== 'undefined') {
      observer = new IntersectionObserver((entries) => {
        visible = entries[entries.length - 1].isIntersecting
        apply()
      })
      observer.observe(container)
    }
    const onVisibility = () => {
      tabShown = document.visibilityState !== 'hidden'
      apply()
    }
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      if (observer) observer.disconnect()
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [containerRef, svgRef])
}
