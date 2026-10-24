import { render, screen, within } from '@testing-library/react'
import { axe } from 'vitest-axe'
import { describe, expect, it } from 'vitest'
import { AvailabilityBadge } from '../src/components/StatusBadge.jsx'
import { CAPABILITIES } from '../src/features/home/capabilities.js'
import { LEVEL_ORDER, LEVELS, OBSERVABILITY } from '../src/features/home/observability.js'
import { signedOutApi, renderApp } from './helpers.jsx'

const ids = (level) => OBSERVABILITY.filter((f) => f.level === level).map((f) => f.id)

async function home() {
  renderApp(signedOutApi(), '/')
  return screen.findByRole('region', { name: /Observability and alerts: what works today/ })
}

describe('Observability and alerts status on the public site', () => {
  it('shows every feature under Available, Partially available or Not available, with counts', async () => {
    const section = await home()
    for (const [heading, level] of [['Available', 'available'], ['Partially available', 'partial'], ['Not available', 'unavailable']]) {
      expect(within(section).getByRole('heading', { level: 3, name: `${heading} (${ids(level).length})` })).toBeTruthy()
    }
    expect(within(section).getAllByRole('heading', { level: 4 })).toHaveLength(OBSERVABILITY.length)
    for (const f of OBSERVABILITY) expect(within(section).getByRole('heading', { level: 4, name: f.title })).toBeTruthy()
  })

  it('explains what the three labels mean', async () => {
    const section = await home()
    const legend = within(section).getByLabelText('What the labels mean')
    for (const level of LEVEL_ORDER) expect(within(legend).getByText(LEVELS[level])).toBeTruthy()
    expect(within(legend).getByText('Available')).toBeTruthy()
    expect(within(legend).getByText('Partially available')).toBeTruthy()
    expect(within(legend).getByText('Not available')).toBeTruthy()
  })

  it('states the required setup and the limits of every feature that is not fully available', async () => {
    const section = await home()
    const items = within(section).getAllByRole('listitem').filter((li) => li.hasAttribute('data-level'))
    expect(items).toHaveLength(OBSERVABILITY.length)
    for (const li of items) {
      const level = li.getAttribute('data-level')
      expect(within(li).getByText(/Limits:|Status:/)).toBeTruthy() // every feature says where it stops
      if (level === 'unavailable') {
        expect(within(li).queryByText('Needs:')).toBeNull() // nothing to configure for something not built
        expect(within(li).getByText('Status:')).toBeTruthy()
        expect(within(li).getByText('Not available', { selector: '.badge' })).toBeTruthy()
      } else {
        expect(within(li).getByText('Needs:')).toBeTruthy()
        expect(within(li).getByText('Limits:')).toBeTruthy()
      }
    }
  })

  it('names the actual configuration each opt-in feature needs', async () => {
    const section = await home()
    const text = section.textContent
    for (const needle of ['off for every project', 'ingest key', '/api/v1/ingest/events', '/api/v1/ingest/otlp', 'Celery beat', 'EVENT_PURGE_ENABLED=true', 'RATE_LIMIT_BACKEND=redis', 'TRUSTED_PROXY_CIDRS', 'LLM_PRICE_*', 'super admin']) {
      expect(text).toContain(needle)
    }
  })

  it('does not overclaim: what is unverified or not built is said so', async () => {
    const section = await home()
    const text = section.textContent
    expect(text).toMatch(/not with real application logs/i)
    expect(text).toMatch(/not with a real OpenTelemetry exporter/i)
    expect(text).toMatch(/estimates/i)
    expect(text).toMatch(/never claim a cause|never why it happened/i)
    expect(text).toMatch(/Email, chat or webhook notifications/)
    expect(text).toMatch(/Not built/)
  })

  it('keeps the classification deliberate: only fully verified features are Available', () => {
    expect(ids('available')).toEqual(['alert-lifecycle', 'internal-alerts', 'org-limits'])
    expect(ids('unavailable')).toEqual(['notifications', 'logs-metrics', 'third-party', 'verify-from-alert'])
    expect(ids('partial')).toEqual(['ingestion', 'rules', 'otel', 'cost', 'loop', 'scheduled', 'shared-limits'])
    expect(new Set(OBSERVABILITY.map((f) => f.id)).size).toBe(OBSERVABILITY.length)
    for (const f of OBSERVABILITY) {
      expect(LEVEL_ORDER).toContain(f.level)
      expect(f.title && f.text && f.limits).toBeTruthy()
      if (f.level === 'unavailable') expect(f.needs).toBeNull()
      else expect(f.needs).toBeTruthy()
      if (f.level === 'available') expect(f.limits).not.toMatch(/not verified|untested|never been tried/i)
    }
  })

  it('points the capability card at the section and keeps it Partially available', async () => {
    const card = CAPABILITIES.find((c) => c.id === 'observability')
    expect(card.level).toBe('partial')
    expect(card.text).toMatch(/what works today/)
    renderApp(signedOutApi(), '/')
    const cap = await screen.findByRole('heading', { level: 3, name: 'Observability and alerts' })
    const item = cap.closest('li')
    expect(within(item).getByText('Partially available')).toBeTruthy()
  })

  it('shows the planned stages in the current plan order', async () => {
    renderApp(signedOutApi(), '/')
    expect(await screen.findByText('Planned · validation phase')).toBeTruthy()
    expect(screen.getByText('Planned · Stage 13')).toBeTruthy()
    expect(screen.getByText('Planned · Stage 14')).toBeTruthy()
    expect(screen.queryByText('Planned · Stage 15')).toBeNull()
  })

  it('has no accessibility violations (structure, labels, headings, lists)', async () => {
    const { container } = renderApp(signedOutApi(), '/')
    await screen.findByRole('region', { name: /Observability and alerts: what works today/ })
    expect(await axe(container, { rules: { 'color-contrast': { enabled: false } } })).toHaveNoViolations()
  })
})

describe('availability badge wording', () => {
  it('uses Available, Partially available and Not available, and never a favourable fallback', () => {
    const labels = (level) => { const { container, unmount } = render(<AvailabilityBadge level={level} />); const t = container.textContent; unmount(); return t }
    expect(labels('available')).toBe('Available')
    expect(labels('partial')).toBe('Partially available')
    expect(labels('unavailable')).toBe('Not available')
    expect(labels('something-new')).toBe('Not available') // an unknown level never looks available
  })

  it('shows Planned with a stage or a phase', () => {
    const { container } = render(<><AvailabilityBadge level="planned" stage={14} /><AvailabilityBadge level="planned" when="validation phase" /></>)
    expect(container.textContent).toBe('Planned · Stage 14Planned · validation phase')
  })
})

describe('roadmap page', () => {
  it('lists planned work in the plan order and states the observability limits', async () => {
    renderApp(signedOutApi(), '/roadmap')
    expect(await screen.findByText('Planned · Stage 13')).toBeTruthy()
    expect(screen.getByText('Planned · Stage 14')).toBeTruthy()
    expect(screen.getByText('Planned · Stage 15-16')).toBeTruthy()
    expect(screen.getByText('Planned · validation phase')).toBeTruthy()
    expect(screen.getByText(/never with real application logs or a real OpenTelemetry exporter/)).toBeTruthy()
  })
})
