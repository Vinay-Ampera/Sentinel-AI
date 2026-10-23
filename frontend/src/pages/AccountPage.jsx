import { useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import Button from '../components/Button.jsx'
import Card from '../components/Card.jsx'
import KeyValueList from '../components/KeyValueList.jsx'
import PageHeader from '../components/PageHeader.jsx'
import { DataState } from '../components/states.jsx'
import ChangePasswordForm from '../features/auth/ChangePasswordForm.jsx'
import SessionList from '../features/auth/SessionList.jsx'
import { useApi } from '../hooks/useApi.js'
import { useAuth } from '../hooks/useAuth.js'
import { useLoad } from '../hooks/useLoad.js'
import { useToast } from '../hooks/useToast.js'

export default function AccountPage() {
  const api = useApi()
  const { user, signOut } = useAuth()
  const navigate = useNavigate()
  const { notify } = useToast()
  const [sessions, reload] = useLoad(useCallback(() => api.listSessions(), [api]))

  // Go to the home page first (it is public), then end the session, so the protected-route
  // guard does not bounce the user to the sign-in page on the way out.
  async function leave() {
    navigate('/')
    await signOut()
  }

  async function revoke(session) {
    await api.revokeSession(session.id)
    notify({ tone: 'success', title: 'Session signed out' })
    reload()
  }

  return (
    <>
      <PageHeader title="Account" description="Your sign-in details, password and active sessions." />
      <Card title="Profile">
        <KeyValueList items={[{ label: 'Name', value: user.display_name }, { label: 'Email', value: user.email }, { label: 'Role', value: user.role.replace('_', ' ') }]} />
        <p className="muted">An administrator manages your name, email and role.</p>
      </Card>
      <Card title="Password">
        <ChangePasswordForm api={api} onChanged={reload} />
      </Card>
      <Card title="Sign out">
        <p className="muted">End your session on this device. Other devices stay signed in until you sign them out below.</p>
        <Button variant="danger" onClick={leave}>Sign out</Button>
      </Card>
      <Card title="Active sessions">
        <DataState state={sessions} onRetry={reload} what="your sessions" loadingLabel="Loading sessions…" isEmpty={() => false}>
          {(items) => <SessionList sessions={items} onRevoke={revoke} />}
        </DataState>
      </Card>
    </>
  )
}
