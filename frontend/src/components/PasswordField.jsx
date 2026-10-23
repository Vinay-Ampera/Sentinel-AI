import { useId, useState } from 'react'
import Field from './Field.jsx'
import './PasswordField.css'

// A password input with a show/hide control. The toggle is a real button with a state-aware
// name; the password is never written anywhere but the input.
export default function PasswordField({ label, hint, error, autoComplete, ...rest }) {
  const [visible, setVisible] = useState(false)
  const id = useId()
  return (
    <div className="password-field">
      <Field id={id} label={label} hint={hint} error={error} type={visible ? 'text' : 'password'} autoComplete={autoComplete} {...rest} />
      <button type="button" className="password-toggle" aria-pressed={visible} aria-controls={id} onClick={() => setVisible((v) => !v)}>
        {visible ? 'Hide password' : 'Show password'}
      </button>
    </div>
  )
}
