import { useId } from 'react'
import './Field.css'

// A labelled form control with hint and error text wired up for assistive technology:
// the label is bound to the control, and hint/error are announced via aria-describedby.
// `as` is input | select | textarea. Children are the <option>s for a select.
export default function Field({ label, hint, error, as = 'input', required = false, id, children, className, ...rest }) {
  const auto = useId()
  const controlId = id || auto
  const hintId = `${controlId}-hint`
  const errorId = `${controlId}-error`
  const describedBy = [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(' ') || undefined
  const Control = as
  return (
    <div className={['field', className].filter(Boolean).join(' ')}>
      <label htmlFor={controlId}>
        {label}
        {required && <span className="field-required"> (required)</span>}
      </label>
      {hint && <p id={hintId} className="field-hint">{hint}</p>}
      <Control id={controlId} required={required} aria-invalid={error ? true : undefined} aria-describedby={describedBy} {...rest}>
        {children}
      </Control>
      {error && (
        <p id={errorId} className="field-error">
          {error}
        </p>
      )}
    </div>
  )
}
