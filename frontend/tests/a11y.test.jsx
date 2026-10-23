import { screen } from '@testing-library/react'
import { axe } from 'vitest-axe'
import { describe, expect, it } from 'vitest'
import { renderApp, signedOutApi } from './helpers.jsx'

// Automated axe checks catch many structural problems (names, labels, roles, landmarks) but
// cannot prove accessibility. jsdom has no layout, so colour-contrast is disabled here and
// covered by tests/tokens.test.js instead. Manual keyboard and screen-reader checks remain.
const options = { rules: { 'color-contrast': { enabled: false } } }

async function check(path, theme, ready) {
  window.localStorage.setItem('sentinel-theme', theme)
  const { container } = renderApp(signedOutApi(), path)
  await screen.findByRole('heading', { name: ready })
  expect(await axe(container, options)).toHaveNoViolations()
}

describe.each(['light', 'dark'])('axe (%s theme)', (theme) => {
  it('home page', () => check('/', theme, /Test results you can trace back to evidence/))
  it('sign-in page', () => check('/signin', theme, 'Sign in'))
  it('request-access page', () => check('/request-access', theme, 'Request access'))
  it('component gallery', () => check('/design-system', theme, 'Design system'))
})
