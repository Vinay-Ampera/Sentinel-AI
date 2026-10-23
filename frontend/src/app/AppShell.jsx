import { useEffect, useRef } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import { isAuthPath } from './authPaths.js'
import Footer from './Footer.jsx'
import Navbar from './Navbar.jsx'
import './AppShell.css'

// Page frame: skip link, top navbar, main landmark, footer. On every client-side navigation
// focus moves to <main> so keyboard and screen-reader users start at the new page, not at
// the old link they activated.
export default function AppShell() {
  const { pathname } = useLocation()
  const main = useRef(null)
  const firstRender = useRef(true)
  const quiet = isAuthPath(pathname) // minimal top bar, no footer
  const fullBleed = pathname === '/' || quiet // these pages lay out their own full-width sections

  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false
      return
    }
    if (main.current) main.current.focus()
  }, [pathname])

  return (
    <>
      <a href="#main" className="skip-link">Skip to main content</a>
      <Navbar minimal={quiet} />
      <main id="main" ref={main} tabIndex={-1} className={fullBleed ? 'shell-main shell-main-full' : 'shell-main'}>
        {fullBleed ? <Outlet /> : <div className="container"><Outlet /></div>}
      </main>
      {!quiet && <Footer />}
    </>
  )
}
