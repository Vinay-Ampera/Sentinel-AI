import { useRef, useState } from 'react'
import { Link, NavLink, useLocation } from 'react-router-dom'
import BrandLogo from '../components/BrandLogo.jsx'
import { ButtonLink } from '../components/Button.jsx'
import Icon from '../components/Icon.jsx'
import ThemeToggle from '../components/ThemeToggle.jsx'
import { useAuth } from '../hooks/useAuth.js'
import { visibleNavItems } from './navItems.js'
import './Navbar.css'

// The only navigation chrome (no sidebar). At narrow widths the links, theme and account
// controls collapse into a menu opened by a labelled button; Escape closes it and returns
// focus to that button.
export default function Navbar({ minimal = false }) {
  const { user } = useAuth()
  const { pathname } = useLocation()
  // The menu is open only for the route it was opened on, so navigating closes it.
  const [openPath, setOpenPath] = useState(null)
  const open = openPath === pathname
  const toggle = useRef(null)

  function onKeyDown(event) {
    if (event.key === 'Escape' && open) {
      setOpenPath(null)
      if (toggle.current) toggle.current.focus()
    }
  }

  const items = visibleNavItems(user)
  if (minimal) {
    // Quiet pages (sign-in, request access): just the brand and the theme control.
    return (
      <header className="navbar navbar-minimal">
        <div className="navbar-inner">
          <Link to="/" className="navbar-brand"><BrandLogo size={30} />Sentinel AI</Link>
          <ThemeToggle />
        </div>
      </header>
    )
  }
  return (
    <header className="navbar" onKeyDown={onKeyDown}>
      <div className="navbar-inner">
        <Link to="/" className="navbar-brand">
          <BrandLogo size={30} />
          Sentinel AI
        </Link>
        <button
          ref={toggle}
          type="button"
          className="navbar-toggle"
          aria-expanded={open}
          aria-controls="navbar-panel"
          onClick={() => setOpenPath(open ? null : pathname)}
        >
          <Icon name={open ? 'close' : 'menu'} />
          <span className="visually-hidden">{open ? 'Close menu' : 'Open menu'}</span>
        </button>
        <div id="navbar-panel" className={open ? 'navbar-panel is-open' : 'navbar-panel'}>
          <nav aria-label="Primary" className="navbar-nav">
            <ul>
              {items.map((item) => (
                <li key={item.to}>
                  <NavLink to={item.to} end={item.end} className="navbar-link">
                    {item.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>
          <div className="navbar-actions">
            <ThemeToggle />
            {user ? (
              <NavLink to="/account" className="navbar-avatar" aria-label={`Account: ${user.display_name} (${user.role.replace('_', ' ')})`} title="Your account">
                <Icon name="user" size={18} />
                <span className="navbar-avatar-label" aria-hidden="true">{user.display_name}</span>
              </NavLink>
            ) : (
              <ButtonLink to="/signin" variant="primary" size="sm">Sign in</ButtonLink>
            )}
          </div>
        </div>
      </div>
    </header>
  )
}
