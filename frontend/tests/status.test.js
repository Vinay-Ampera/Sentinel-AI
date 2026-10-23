import { describe, expect, it } from 'vitest'
import { STATUS_DOMAINS, STATUS_TABLES, statusMeta } from '../src/lib/status.js'

describe('status vocabulary', () => {
  it('gives every known value a label, a tone and an icon, in every domain', () => {
    for (const domain of STATUS_DOMAINS) {
      for (const value of Object.keys(STATUS_TABLES[domain])) {
        const m = statusMeta(domain, value)
        expect(m.label, `${domain}.${value}`).toBeTruthy()
        expect(['success', 'danger', 'warning', 'info', 'neutral']).toContain(m.tone)
        expect(m.icon).toBeTruthy()
      }
    }
  })

  it('keeps result states distinct: no two share both label and icon', () => {
    const seen = new Set()
    for (const value of Object.keys(STATUS_TABLES.result)) {
      const m = statusMeta('result', value)
      const key = `${m.label}|${m.icon}`
      expect(seen.has(key)).toBe(false)
      seen.add(key)
    }
    expect(statusMeta('result', 'failed_to_start').tone).not.toBe('danger') // infrastructure, not a test failure
    expect(statusMeta('result', 'not_run').tone).toBe('neutral')
  })

  it('never shows a finished run, an approved plan or an unverified finding as a success', () => {
    expect(statusMeta('run', 'completed').tone).toBe('neutral')
    expect(statusMeta('plan', 'approved').tone).not.toBe('success')
    expect(statusMeta('verification', 'unverified').tone).toBe('neutral')
    expect(statusMeta('verification', 'unverified').label).not.toMatch(/confirm/i)
  })

  it('renders an unknown value neutral with readable text, never favourable', () => {
    const m = statusMeta('result', 'something_new')
    expect(m.tone).toBe('neutral')
    expect(m.label).toBe('Something new')
  })

  it('rejects an unknown domain', () => {
    expect(() => statusMeta('nope', 'x')).toThrow()
  })
})
