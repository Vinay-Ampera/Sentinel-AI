import { Navigate, useSearchParams } from 'react-router-dom'
import Alert from '../components/Alert.jsx'
import { Loading } from '../components/states.jsx'
import AuthLayout from '../features/auth/AuthLayout.jsx'
import SignInForm from '../features/auth/SignInForm.jsx'
import { useApi } from '../hooks/useApi.js'
import { useAuth } from '../hooks/useAuth.js'
import { safeNextPath } from '../lib/safeNext.js'

export default function SignInPage() {
  const api = useApi()
  const { user, checking, expired, signedIn } = useAuth()
  const [params] = useSearchParams()
  const next = safeNextPath(params.get('next'))
  if (checking) return <Loading label="Checking session…" lines={2} />
  if (user) return <Navigate to={next} replace />
  return (
    <AuthLayout current="signin" eyebrow="Chapter 01 · Sign in" title="Welcome back" intro="Pick up where the evidence left off.">
      {expired && <Alert tone="warning" title="Your session ended">Sign in again to continue where you left off.</Alert>}
      <SignInForm api={api} onSignedIn={signedIn} />
    </AuthLayout>
  )
}
