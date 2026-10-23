import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Icon from './Icon.jsx'
import { ToastContext } from '../hooks/useToast.js'
import './Toast.css'

const AUTO_DISMISS_MS = 8000
const ICONS = { success: 'check', danger: 'alert', info: 'info', warning: 'alert' }

// Transient feedback for completed actions. Errors stay until dismissed. Success/info are
// announced politely, errors assertively, and every toast has a dismiss button.
export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])
  const timers = useRef(new Map())
  const nextId = useRef(1)

  const dismiss = useCallback((id) => {
    clearTimeout(timers.current.get(id))
    timers.current.delete(id)
    setToasts((list) => list.filter((t) => t.id !== id))
  }, [])

  const notify = useCallback(
    ({ tone = 'info', title, message }) => {
      const id = nextId.current++
      setToasts((list) => [...list, { id, tone, title, message }])
      if (tone !== 'danger') timers.current.set(id, setTimeout(() => dismiss(id), AUTO_DISMISS_MS))
      return id
    },
    [dismiss],
  )

  useEffect(() => {
    const live = timers.current
    return () => live.forEach((t) => clearTimeout(t))
  }, [])

  const value = useMemo(() => ({ notify, dismiss }), [notify, dismiss])
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toast-region">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast-${t.tone}`} role={t.tone === 'danger' ? 'alert' : 'status'}>
            <Icon name={ICONS[t.tone] || 'info'} />
            <div className="toast-text">
              <strong>{t.title}</strong>
              {t.message && <span>{t.message}</span>}
            </div>
            <button type="button" className="toast-close" aria-label={`Dismiss: ${t.title}`} onClick={() => dismiss(t.id)}>
              <Icon name="close" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}
