import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import Button from './Button.jsx'
import Field from './Field.jsx'
import './Dialog.css'

const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

// A modal dialog: focus moves in, Tab is kept inside, Escape closes, and focus returns to
// whatever opened it. Background scrolling is locked while open.
export default function Dialog({ open, onClose, title, children, footer }) {
  const titleId = useId()
  const panel = useRef(null)
  const opener = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    opener.current = document.activeElement
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const first = panel.current && panel.current.querySelector(FOCUSABLE)
    ;(first || panel.current).focus()
    return () => {
      document.body.style.overflow = previousOverflow
      if (opener.current && opener.current.focus) opener.current.focus()
    }
  }, [open])

  if (!open) return null

  function onKeyDown(event) {
    if (event.key === 'Escape') {
      event.stopPropagation()
      onClose()
      return
    }
    if (event.key !== 'Tab') return
    const items = Array.from(panel.current.querySelectorAll(FOCUSABLE))
    if (items.length === 0) {
      event.preventDefault()
      return
    }
    const first = items[0]
    const last = items[items.length - 1]
    if (event.shiftKey && (document.activeElement === first || document.activeElement === panel.current)) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }

  return createPortal(
    <div className="dialog-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={panel} className="dialog" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} onKeyDown={onKeyDown}>
        <h2 id={titleId} className="dialog-title">{title}</h2>
        <div className="dialog-body">{children}</div>
        {footer && <div className="dialog-footer">{footer}</div>}
      </div>
    </div>,
    document.body,
  )
}

// Confirmation for destructive or risky actions. When the backend requires a reason, set
// requireReason: the confirm button stays disabled (with an explanation) until one is typed.
// onConfirm receives the reason and may return a promise; an error it throws is shown inline.
export function ConfirmDialog({ open, onClose, title, children, confirmLabel = 'Confirm', danger = false, requireReason = false, reasonLabel = 'Reason', onConfirm }) {
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  function close() {
    setReason('')
    setError(null)
    onClose()
  }

  async function confirm() {
    setBusy(true)
    setError(null)
    try {
      await onConfirm(reason.trim())
      setReason('')
      onClose()
    } catch (e) {
      setError(e.message || 'The action did not complete.')
    } finally {
      setBusy(false)
    }
  }

  const missing = requireReason && reason.trim() === ''
  return (
    <Dialog
      open={open}
      onClose={close}
      title={title}
      footer={
        <>
          <Button onClick={close} disabled={busy}>Cancel</Button>
          <Button
            variant={danger ? 'danger' : 'primary'}
            onClick={confirm}
            loading={busy}
            disabled={missing}
            disabledReason={missing ? 'Enter a reason to continue' : undefined}
          >
            {confirmLabel}
          </Button>
        </>
      }
    >
      {children}
      {requireReason && (
        <Field as="textarea" label={reasonLabel} required value={reason} onChange={(e) => setReason(e.target.value)} />
      )}
      {error && <p role="alert" className="field-error">{error}</p>}
    </Dialog>
  )
}
