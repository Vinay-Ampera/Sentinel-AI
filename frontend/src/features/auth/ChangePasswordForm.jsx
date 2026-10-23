import { useState } from 'react'
import Alert from '../../components/Alert.jsx'
import Button from '../../components/Button.jsx'
import PasswordField from '../../components/PasswordField.jsx'
import { describeError, fieldErrors } from '../../lib/errors.js'
import './ChangePasswordForm.css'

// Change your own password. The password rules belong to the server, so its message is shown
// as given; the only check here is that the two new entries match.
export default function ChangePasswordForm({ api, onChanged }) {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [touched, setTouched] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [fields, setFields] = useState({})
  const [done, setDone] = useState(null)

  const mismatch = next !== confirm

  async function submit(event) {
    event.preventDefault()
    setTouched(true)
    setDone(null)
    if (!current || !next || mismatch) return
    setBusy(true)
    setError(null)
    setFields({})
    try {
      const result = await api.changePassword(current, next)
      setCurrent('')
      setNext('')
      setConfirm('')
      setTouched(false)
      setDone(result && result.other_sessions_revoked ? `Your password was changed. ${result.other_sessions_revoked} other session(s) were signed out.` : 'Your password was changed.')
      if (onChanged) onChanged()
    } catch (e) {
      const f = fieldErrors(e)
      setFields(f)
      setError(e.status === 401 || e.status === 403 ? 'The current password is not correct.' : Object.keys(f).length ? null : describeError(e).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} noValidate aria-labelledby="password-title" className="password-form">
      <h3 id="password-title">Change password</h3>
      {done && <Alert tone="success">{done}</Alert>}
      {error && <Alert tone="danger" title="The password was not changed">{error}</Alert>}
      <PasswordField label="Current password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required error={touched && !current ? 'Enter your current password.' : fields.current} />
      <PasswordField label="New password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} required hint="Use a long, unique password." error={touched && !next ? 'Enter a new password.' : fields.new} />
      <PasswordField label="Confirm new password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required error={touched && next && mismatch ? 'The two new passwords do not match.' : undefined} />
      <Button type="submit" variant="primary" loading={busy} loadingLabel="Changing…">Change password</Button>
    </form>
  )
}
