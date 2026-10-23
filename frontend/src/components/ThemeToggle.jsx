import { useTheme } from '../hooks/useTheme.js'
import Icon from './Icon.jsx'
import './ThemeToggle.css'

// A compact pill of three icon buttons: System, Dark, Light. The icons are decorative; each
// button carries its name as visually hidden text, and the active choice is exposed with
// aria-pressed (and a ring), so it is not conveyed by colour alone.
const OPTIONS = [
  { value: 'system', label: 'System', icon: 'monitor' },
  { value: 'dark', label: 'Dark', icon: 'moon' },
  { value: 'light', label: 'Light', icon: 'sun' },
]

export default function ThemeToggle() {
  const { preference, setPreference } = useTheme()
  return (
    <div className="theme-toggle" role="group" aria-label="Theme">
      {OPTIONS.map((o) => (
        <button key={o.value} type="button" className="theme-option" aria-pressed={preference === o.value} onClick={() => setPreference(o.value)}>
          <Icon name={o.icon} size={16} />
          <span className="visually-hidden">{o.label}</span>
        </button>
      ))}
    </div>
  )
}
