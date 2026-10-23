import { useState } from 'react'
import Alert from '../../components/Alert.jsx'
import Button from '../../components/Button.jsx'
import Field from '../../components/Field.jsx'
import PasswordField from '../../components/PasswordField.jsx'
import { signInMessage } from './signInMessage.js'

// Sign-in form. Wrong credentials get one deliberately vague message (the server does not say
// which part was wrong); rate limiting and outages get their own wording. Nothing here knows
// whether an email exists.
export default function SignInForm({ api, onSignedIn }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [touched, setTouched] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  async function submit(event) {
    event.preventDefault()
    setTouched(true)
    if (!email.trim() || !password) return
    setBusy(true)
    setError(null)
    try {
      onSignedIn(await api.login(email.trim(), password))
    } catch (e) {
      setError(signInMessage(e))
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} noValidate aria-labelledby="signin-title">
      <h2 id="signin-title">Sign in</h2>
      {error && <Alert tone="danger" title="Could not sign in">{error}</Alert>}
      <Field
        label="Email"
        type="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        autoComplete="username"
        required
        error={touched && !email.trim() ? 'Enter your email address.' : undefined}
      />
      <PasswordField
        label="Password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        autoComplete="current-password"
        required
        error={touched && !password ? 'Enter your password.' : undefined}
      />
      <Button type="submit" variant="primary" loading={busy} loadingLabel="Signing in…">Sign in</Button>
    </form>
  )
}
