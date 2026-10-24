import { ButtonLink } from '../components/Button.jsx'
import CapabilityGrid from '../features/home/CapabilityGrid.jsx'
import ObservabilityStatus from '../features/home/ObservabilityStatus.jsx'
import Hero from '../features/home/Hero.jsx'
import WorkflowSteps from '../features/home/WorkflowSteps.jsx'
import { useAuth } from '../hooks/useAuth.js'
import { useDocumentTitle } from '../hooks/useDocumentTitle.js'
import './HomePage.css'

export default function HomePage() {
  const { user } = useAuth()
  useDocumentTitle('')
  return (
    <>
      <Hero signedIn={Boolean(user)} />
      <div className="container home-body">
        <WorkflowSteps />
        <CapabilityGrid />
        <ObservabilityStatus />
        <section className="home-a11y" aria-labelledby="a11y-title">
          <h2 id="a11y-title">Accessibility of this interface</h2>
          <p>
            The interface is built to work with a keyboard, visible focus, labelled controls, Light, Dark and System themes, and reduced-motion settings. Status is always written out in words, never shown by colour alone.
          </p>
          <p className="muted">
            This describes how the interface is built, not a conformance claim: it has not been through a formal accessibility evaluation. Accessibility testing of the applications you analyze is planned (validation phase) and is not available yet.
          </p>
        </section>
        {!user && (
          <section className="home-cta" aria-labelledby="cta-title">
            <h2 id="cta-title">Ready to look at your own project?</h2>
            <p className="muted">Accounts are created by an administrator.</p>
            <div className="home-cta-actions">
              <ButtonLink to="/signin" variant="primary">Sign in</ButtonLink>
              <ButtonLink to="/request-access">How to get access</ButtonLink>
            </div>
          </section>
        )}
      </div>
    </>
  )
}
