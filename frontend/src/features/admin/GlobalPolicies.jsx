import { useCallback } from 'react'
import Alert from '../../components/Alert.jsx'
import Card from '../../components/Card.jsx'
import { DataState } from '../../components/states.jsx'
import PolicyEditor from '../governance/PolicyEditor.jsx'
import { useApi } from '../../hooks/useApi.js'
import { useLoad } from '../../hooks/useLoad.js'

// Organization-wide approval policy (super admin). Projects can only be stricter than this.
// A setting that has never been saved is empty here and the built-in default applies.
export default function GlobalPolicies() {
  const api = useApi()
  const [rows, reload] = useLoad(useCallback(() => api.getGlobalPolicies(), [api]))
  const save = async (key, value) => {
    await api.setGlobalPolicy(key, value)
    reload()
  }
  return (
    <Card title="Organization policy">
      <DataState state={rows} onRetry={reload} what="organization policy" loadingLabel="Loading policy…" isEmpty={() => false}>
        {(p) => (
          <>
            <Alert tone="info">Changes apply to every project. Settings never saved show as empty and the built-in default applies. Only a super admin may change these; others see the server's refusal.</Alert>
            <PolicyEditor key={`r-${JSON.stringify(p.approval_required_risk_levels)}`} legend="Risk levels that need approval" kind="levels" value={p.approval_required_risk_levels} onSave={(v) => save('approval_required_risk_levels', v)} />
            <PolicyEditor key={`a-${JSON.stringify(p.allowed_risk_levels)}`} legend="Risk levels that may be planned" kind="levels" value={p.allowed_risk_levels} onSave={(v) => save('allowed_risk_levels', v)} />
            <PolicyEditor key={`h-${JSON.stringify(p.high_risk_approver_roles)}`} legend="Roles that may approve high or critical risk" help="Developers are not included by default." kind="roles" value={p.high_risk_approver_roles} onSave={(v) => save('high_risk_approver_roles', v)} />
            <PolicyEditor key={`p-${JSON.stringify(p.production_testing)}`} legend="Production testing" help="Blocked by default. Enabling it still needs target authorizations and approval." kind="flag" value={p.production_testing} onSave={(v) => save('production_testing', v)} />
          </>
        )}
      </DataState>
    </Card>
  )
}
