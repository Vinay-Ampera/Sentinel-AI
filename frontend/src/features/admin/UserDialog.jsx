import { useState } from 'react'
import Alert from '../../components/Alert.jsx'
import Button from '../../components/Button.jsx'
import Dialog from '../../components/Dialog.jsx'
import Field from '../../components/Field.jsx'
import PasswordField from '../../components/PasswordField.jsx'
import { describeError, fieldErrors } from '../../lib/errors.js'

const ROLES = ['developer', 'admin', 'super_admin']

// Create a user (user === null) or edit one. Which roles an admin may create or change is the
// server's rule; its refusal is shown. The initial password is shared out of band and can be
// changed by the user on their account page.
export default function UserDialog({ user, onClose, onSave }) {
  const editing = Boolean(user)
  const [email, setEmail] = useState(user ? user.email : '')
  const [name, setName] = useState(user ? user.display_name : '')
  const [role, setRole] = useState(user ? user.role : 'developer')
  const [active, setActive] = useState(user ? user.is_active : true)
  const [password, setPassword] = useState('')
  const [touched, setTouched] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [fields, setFields] = useState({})

  const missing = { email: !editing && !email.trim(), name: !name.trim(), password: !editing && !password }

  async function submit(event) {
    event.preventDefault()
    setTouched(true)
    if (Object.values(missing).some(Boolean)) return
    setBusy(true)
    setError(null)
    setFields({})
    try {
      await onSave(editing ? { display_name: name.trim(), role, is_active: active } : { email: email.trim(), display_name: name.trim(), role, password })
    } catch (e) {
      const f = fieldErrors(e)
      setFields(f)
      if (Object.keys(f).length === 0) setError(describeError(e).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title={editing ? `Edit ${user.display_name}` : 'New user'}
      footer={
        <>
          <Button onClick={onClose} disabled={busy}>Cancel</Button>
          <Button type="submit" form="user-form" variant="primary" loading={busy} loadingLabel="Saving…">{editing ? 'Save changes' : 'Create user'}</Button>
        </>
      }
    >
      <form id="user-form" onSubmit={submit} noValidate>
        {error && <Alert tone="danger" title="Not saved">{error}</Alert>}
        {editing ? (
          <p className="muted">{user.email}</p>
        ) : (
          <Field label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required error={(touched && missing.email && 'Enter an email address.') || fields.email} />
        )}
        <Field label="Display name" value={name} onChange={(e) => setName(e.target.value)} maxLength={200} required error={(touched && missing.name && 'Enter a name.') || fields.display_name} />
        <Field as="select" label="Role" value={role} onChange={(e) => setRole(e.target.value)} error={fields.role}>
          {ROLES.map((r) => <option key={r} value={r}>{r.replace('_', ' ')}</option>)}
        </Field>
        {editing ? (
          <label className="user-active"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} /> Account is active (a disabled user cannot sign in)</label>
        ) : (
          <PasswordField label="Initial password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} required hint="Share it securely. The person can change it after signing in." error={(touched && missing.password && 'Enter an initial password.') || fields.password} />
        )}
      </form>
    </Dialog>
  )
}
