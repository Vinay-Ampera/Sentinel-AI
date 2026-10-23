import { describe, expect, it } from 'vitest'
import { applyTheme, readPreference, resolveTheme, savePreference, THEME_KEY } from '../src/theme/theme.js'

const memoryStorage = (initial = {}) => {
  const data = { ...initial }
  return {
    getItem: (k) => (k in data ? data[k] : null),
    setItem: (k, v) => { data[k] = String(v) },
    removeItem: (k) => { delete data[k] },
  }
}
const brokenStorage = () => ({
  getItem: () => { throw new Error('blocked') },
  setItem: () => { throw new Error('blocked') },
  removeItem: () => { throw new Error('blocked') },
})

describe('theme preference', () => {
  it('defaults to system when nothing, or something unexpected, is stored', () => {
    expect(readPreference(memoryStorage())).toBe('system')
    expect(readPreference(memoryStorage({ [THEME_KEY]: 'purple' }))).toBe('system')
  })

  it('reads and saves an explicit choice; system clears the stored value', () => {
    const storage = memoryStorage()
    savePreference(storage, 'dark')
    expect(readPreference(storage)).toBe('dark')
    savePreference(storage, 'system')
    expect(storage.getItem(THEME_KEY)).toBeNull()
  })

  it('does not throw when storage is unavailable', () => {
    expect(readPreference(brokenStorage())).toBe('system')
    expect(() => savePreference(brokenStorage(), 'dark')).not.toThrow()
  })

  it('resolves system from the operating-system preference; explicit choices win', () => {
    expect(resolveTheme('system', true)).toBe('dark')
    expect(resolveTheme('system', false)).toBe('light')
    expect(resolveTheme('light', true)).toBe('light')
    expect(resolveTheme('dark', false)).toBe('dark')
  })

  it('applies the resolved theme and the preference to the root element', () => {
    const root = document.createElement('html')
    applyTheme(root, 'system', 'dark')
    expect(root.dataset.theme).toBe('dark')
    expect(root.dataset.themePref).toBe('system')
  })
})
