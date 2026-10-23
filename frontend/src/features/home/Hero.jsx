import { ButtonLink } from '../../components/Button.jsx'
import HeroVisual from './HeroVisual.jsx'
import './Hero.css'

// Centred hero over a faint technical grid: a utility ribbon, a mono section tag, a large
// headline, one sentence, two actions, then the animated full-width scene. The ribbon labels
// describe the product; they are not live status, so nothing here claims a system state.
export default function Hero({ signedIn }) {
  return (
    <section className="hero" aria-labelledby="hero-title">
      <div className="hero-grid" aria-hidden="true" />
      <div className="container hero-ribbon" aria-hidden="true">
        <span>[ EVIDENCE-FIRST QA ]</span>
        <span className="hero-ribbon-mid">ANALYZE / PLAN / APPROVE / RUN / REVIEW</span>
        <span>SENTINEL AI</span>
      </div>
      <div className="container hero-copy">
        <p className="hero-eyebrow">01 // TRACEABLE TEST PIPELINE</p>
        <h1 id="hero-title" className="hero-title">
          <span className="hero-title-light">Test results you can</span>{' '}
          <span className="hero-title-bold">trace back to evidence.</span>
        </h1>
        <p className="hero-lede">
          Sentinel AI analyzes a project, plans the checks that apply, runs the approved ones in an isolated sandbox, and keeps the evidence behind every result and security finding.
        </p>
        <div className="hero-actions">
          {signedIn ? (
            <ButtonLink to="/projects" variant="primary" className="hero-button">Open your projects</ButtonLink>
          ) : (
            <>
              <ButtonLink to="/signin" variant="primary" className="hero-button">Sign in</ButtonLink>
              <ButtonLink to="/request-access" className="hero-button">Get started</ButtonLink>
            </>
          )}
        </div>
        <a className="hero-link" href="#capabilities">Explore what it does</a>
      </div>
      <HeroVisual />
    </section>
  )
}
