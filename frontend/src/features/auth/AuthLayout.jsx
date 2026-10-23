import { Link, useLocation } from 'react-router-dom'
import { useDocumentTitle } from '../../hooks/useDocumentTitle.js'
import AuthBackdrop from './AuthBackdrop.jsx'
import './AuthLayout.css'

// The page for signing in and for asking for an account: an editorial column on the left (a
// title in a book-style serif, a short intro, three principles) and the form on a floating
// card with two sheets stacked behind it. Sign-up does not exist as a feature (accounts are
// created by an administrator), so the second tab is "Request access", which explains how.
const PRINCIPLES = [
  ['Evidence over opinion', 'Every result links to the logs and reports behind it.'],
  ['Nothing runs unapproved', 'Plans and targets are approved by a person first.'],
  ['Limits stated', 'Findings stay unverified until a person checks them.'],
]

export default function AuthLayout({ current, eyebrow, title, intro, children }) {
  const { search } = useLocation()
  useDocumentTitle(title)
  return (
    <div className="auth">
      <AuthBackdrop />
      <div className="auth-inner">
        <section className="auth-editorial" aria-labelledby="auth-title">
          <p className="auth-eyebrow">{eyebrow}</p>
          <h1 id="auth-title" className="auth-title">{title}</h1>
          <p className="auth-intro">{intro}</p>
          <ul className="auth-principles">
            {PRINCIPLES.map(([head, text]) => (
              <li key={head}><strong>{head}</strong><span>{text}</span></li>
            ))}
          </ul>
        </section>
        <div className="auth-stack">
          <div className="auth-card">
            <nav className="auth-tabs" aria-label="Account">
              <Link to={`/signin${current === 'signin' ? search : ''}`} aria-current={current === 'signin' ? 'page' : undefined}>Sign in</Link>
              <Link to="/request-access" aria-current={current === 'access' ? 'page' : undefined}>Request access</Link>
            </nav>
            {children}
          </div>
        </div>
      </div>
    </div>
  )
}
