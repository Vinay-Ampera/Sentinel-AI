import { useCallback, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import Button from '../components/Button.jsx'
import Card from '../components/Card.jsx'
import { DataState } from '../components/states.jsx'
import AuthorizationList from '../features/governance/AuthorizationList.jsx'
import BreakGlassPanel from '../features/governance/BreakGlassPanel.jsx'
import PolicyPanel from '../features/governance/PolicyPanel.jsx'
import RequestAuthorizationDialog from '../features/governance/RequestAuthorizationDialog.jsx'
import { useApi } from '../hooks/useApi.js'
import { useAuth } from '../hooks/useAuth.js'
import { useLoad } from '../hooks/useLoad.js'
import { useToast } from '../hooks/useToast.js'
import './ProjectGovernancePage.css'

const TARGET_TYPES = new Set(['localhost_url', 'remote_url'])

// Who may test what, under which rules: target authorizations, the approval policy, and
// emergency access. Every control is a convenience; the server decides and explains refusals.
export default function ProjectGovernancePage() {
  const { project } = useOutletContext()
  const api = useApi()
  const { user } = useAuth()
  const { notify } = useToast()
  const pid = project.id
  const archived = project.status === 'archived'
  const [auths, reloadAuths] = useLoad(useCallback(() => api.listAuthorizations(pid), [api, pid]))
  const [sources] = useLoad(useCallback(() => api.listSources(pid), [api, pid]))
  const [grants, reloadGrants] = useLoad(useCallback(() => api.listBreakGlass(pid), [api, pid]))
  const [requesting, setRequesting] = useState(false)
  const targets = (sources.data || []).filter((s) => s.is_active && TARGET_TYPES.has(s.source_type))
  const names = Object.fromEntries((sources.data || []).map((s) => [s.id, s.name]))

  async function request(sourceId, body) {
    await api.requestAuthorization(pid, sourceId, body)
    notify({ tone: 'success', title: 'Authorization requested', message: 'It waits for an approver. Nothing was tested.' })
    setRequesting(false)
    reloadAuths()
  }
  async function revoke(a) {
    await api.revokeAuthorization(pid, a.id)
    notify({ tone: 'success', title: 'Authorization revoked' })
    reloadAuths()
  }

  return (
    <>
      <Card title="Target authorizations" actions={!archived && <Button size="sm" variant="primary" onClick={() => setRequesting(true)}>Request authorization</Button>}>
        <p className="muted">Testing a localhost or remote target needs an approved authorization with a scope and a time window. Approving happens on the Approvals page.</p>
        <DataState state={auths} onRetry={reloadAuths} what="this project's authorizations" loadingLabel="Loading authorizations…" isEmpty={() => false}>
          {(items) => <AuthorizationList authorizations={items} sourceNames={names} onRevoke={revoke} />}
        </DataState>
        <RequestAuthorizationDialog key={String(requesting)} open={requesting} onClose={() => setRequesting(false)} sources={targets} onRequest={request} />
      </Card>

      <PolicyPanel api={api} projectId={pid} archived={archived} />

      <Card title="Break-glass access">
        <DataState state={grants} onRetry={reloadGrants} what="this project's emergency access records" loadingLabel="Loading…" isEmpty={() => false}>
          {(items) => (
            <BreakGlassPanel
              grants={items}
              canGrant={user.role === 'super_admin'}
              onGrant={async (reason, minutes) => {
                await api.grantBreakGlass(pid, reason, minutes)
                notify({ tone: 'success', title: 'Emergency access granted' })
                reloadGrants()
              }}
              onRevoke={async (g) => {
                await api.revokeBreakGlass(pid, g.id)
                notify({ tone: 'success', title: 'Emergency access revoked' })
                reloadGrants()
              }}
            />
          )}
        </DataState>
      </Card>
    </>
  )
}
