import { NavLink } from 'react-router-dom'
import './TabNav.css'

// Page-level navigation (for example the sections of a project). A row of links, not an
// ARIA tablist: each tab is a real route, so it works with the back button and bookmarks.
// items: [{ to, label, end?, badge? }]. This is how pages avoid crowding the navbar.
export default function TabNav({ label, items }) {
  return (
    <nav className="tab-nav" aria-label={label}>
      <ul>
        {items.map((item) => (
          <li key={item.to}>
            <NavLink to={item.to} end={item.end} className="tab-link">
              {item.label}
              {item.badge}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  )
}
