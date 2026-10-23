import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

// Contrast is computed from the real token file, so a palette edit that breaks WCAG AA
// fails here. (jsdom cannot compute rendered colour contrast, so axe cannot check this.)
const css = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), '../src/styles/tokens.css'), 'utf8')

function block(selector) {
  const start = css.indexOf(`${selector} {`)
  const end = css.indexOf('}', start)
  const out = {}
  for (const m of css.slice(start, end).matchAll(/--([\w-]+):\s*(#[0-9a-fA-F]{6})/g)) out[m[1]] = m[2]
  return out
}

const channel = (v) => {
  const c = v / 255
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
}
const luminance = (hex) => {
  const n = parseInt(hex.slice(1), 16)
  return 0.2126 * channel((n >> 16) & 255) + 0.7152 * channel((n >> 8) & 255) + 0.0722 * channel(n & 255)
}
const ratio = (a, b) => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

const light = block(':root')
const dark = { ...light, ...block(":root[data-theme='dark']") }

describe.each([['light', light], ['dark', dark]])('%s theme contrast', (_name, t) => {
  it.each([
    ['text', 'bg'],
    ['text', 'surface'],
    ['text', 'surface-muted'],
    ['text-muted', 'bg'],
    ['text-muted', 'surface'],
    ['text-muted', 'surface-muted'],
    ['accent-contrast', 'accent'],
    ['text', 'accent-bg'],
    ['success-fg', 'success-bg'],
    ['danger-fg', 'danger-bg'],
    ['warning-fg', 'warning-bg'],
    ['info-fg', 'info-bg'],
    ['danger-fg', 'surface'],
  ])('%s on %s meets 4.5:1 (text)', (fg, bg) => {
    expect(ratio(t[fg], t[bg])).toBeGreaterThanOrEqual(4.5)
  })

  it.each([
    ['border-strong', 'surface'],
    ['border-strong', 'bg'],
    ['focus', 'bg'],
    ['focus', 'surface'],
  ])('%s against %s meets 3:1 (non-text)', (fg, bg) => {
    expect(ratio(t[fg], t[bg])).toBeGreaterThanOrEqual(3)
  })
})
