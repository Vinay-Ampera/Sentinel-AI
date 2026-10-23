import { Link } from 'react-router-dom'
import BrandLogo from '../components/BrandLogo.jsx'
import { useAuth } from '../hooks/useAuth.js'
import { visibleNavItems } from './navItems.js'
import './Footer.css'

const TAGLINE = 'Test results you can trace back to evidence.'

// Two footers. Visitors get an introduction: what the product is, where to go, how to get an
// account. Signed-in users get a compact working footer: quick links and who they are signed in
// as. Neither has links the product does not have (no social, legal or status pages), and both
// say what the product promises: results come from recorded runs, and anything not run is
// labelled as such.
export default function Footer() {
  const { user } = useAuth()
  return (
    <footer className="footer">
      <div className="container footer-inner">
        <div className="footer-brand">
          <p className="footer-name"><BrandLogo size={36} />Sentinel AI</p>
          <p className="footer-tagline">{TAGLINE}</p>
          <p className="footer-tag" aria-hidden="true">[ EVIDENCE-FIRST QA ]</p>
        </div>

        {user ? <SignedInLinks user={user} /> : <VisitorLinks />}

        <div className="footer-promise">
          <h2 className="footer-heading">How to read this site</h2>
          <p>Results come from recorded runs. Anything not run is labelled as such, and planned features are marked Planned.</p>
        </div>
      </div>
      <div className="container footer-base">
        <span>{user ? `Signed in as ${user.display_name} (${user.role.replace('_', ' ')})` : 'Accounts are created by an administrator.'}</span>
        <span>Sentinel AI · evidence-driven application quality</span>
      </div>
    </footer>
  )
}

function VisitorLinks() {
  return (
    <>
      <nav aria-label="Product" className="footer-col">
        <h2 className="footer-heading">Product</h2>
        <ul>
          <li><Link to="/">Home</Link></li>
          <li><Link to="/roadmap">Roadmap</Link></li>
        </ul>
      </nav>
      <nav aria-label="Account" className="footer-col">
        <h2 className="footer-heading">Get in</h2>
        <ul>
          <li><Link to="/signin">Sign in</Link></li>
          <li><Link to="/request-access">Request access</Link></li>
        </ul>
      </nav>
    </>
  )
}

function SignedInLinks({ user }) {
  const links = visibleNavItems(user).filter((item) => item.to !== '/')
  return (
    <>
      <nav aria-label="Workspace" className="footer-col">
        <h2 className="footer-heading">Workspace</h2>
        <ul>
          {links.map((item) => <li key={item.to}><Link to={item.to}>{item.label}</Link></li>)}
        </ul>
      </nav>
      <nav aria-label="You" className="footer-col">
        <h2 className="footer-heading">You</h2>
        <ul>
          <li><Link to="/account">Account and sessions</Link></li>
          <li><Link to="/">Home</Link></li>
        </ul>
      </nav>
    </>
  )
}
