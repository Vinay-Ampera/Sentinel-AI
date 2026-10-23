import { useCallback } from 'react'
import Card from '../../components/Card.jsx'
import KeyValueList from '../../components/KeyValueList.jsx'
import { DataState } from '../../components/states.jsx'
import { useLoad } from '../../hooks/useLoad.js'
import PolicyEditor from './PolicyEditor.jsx'

const list = (items) => (items && items.length ? items.join(', ') : 'none')

// The approval policy that applies to this project, and the two settings a project manager may
// tighten. Risk-approver designations and production testing are shown but not edited here.
export default function PolicyPanel({ api, projectId, archived }) {
  const [effective, reloadEffective] = useLoad(useCallback(() => api.getEffectivePolicy(projectId), [api, projectId]))
  const [rows, reloadRows] = useLoad(useCallback(() => api.getProjectPolicies(projectId), [api, projectId]))

  async function save(key, value) {
    await api.setProjectPolicy(projectId, key, value)
    reloadEffective()
    reloadRows()
  }

  return (
    <Card title="Approval policy">
      <DataState state={effective} onRetry={reloadEffective} what="this project's policy" loadingLabel="Loading policy…" isEmpty={() => false}>
        {(p) => {
          const designated = Object.entries(p.risk_approvers || {}).filter(([, ids]) => ids.length > 0)
          return (
            <>
              <KeyValueList
                items={[
                  { label: 'Needs a person to approve', value: list(p.approval_required_risk_levels) },
                  { label: 'Risk levels that may be planned', value: list(p.allowed_risk_levels) },
                  { label: 'Roles that may approve high or critical risk', value: list(p.high_risk_approver_roles) },
                  { label: 'Production testing', value: p.production_testing && p.production_testing.allowed ? 'Allowed by policy' : 'Blocked by policy' },
                  { label: 'Designated approvers', value: designated.length ? designated.map(([level, ids]) => `${level}: ${ids.length}`).join(', ') : 'None designated: project managers decide' },
                ]}
              />
              <details className="policy-definitions">
                <summary>What the risk levels mean</summary>
                <dl>{Object.entries(p.risk_definitions || {}).map(([level, text]) => <div key={level}><dt>{level}</dt><dd>{text}</dd></div>)}</dl>
              </details>
            </>
          )
        }}
      </DataState>
      {!archived && (
        <DataState state={rows} onRetry={reloadRows} what="this project's policy settings" loadingLabel="Loading settings…" isEmpty={() => false}>
          {() => (
            <>
              <h3>Tighten the policy for this project</h3>
              <p className="muted">A project can only be stricter than the organization. The server refuses anything else.</p>
              <PolicyEditor
                key={`req-${JSON.stringify(effective.data && effective.data.approval_required_risk_levels)}`}
                legend="Risk levels that need approval"
                kind="levels"
                value={effective.data ? effective.data.approval_required_risk_levels : []}
                onSave={(v) => save('approval_required_risk_levels', v)}
              />
              <PolicyEditor
                key={`allow-${JSON.stringify(effective.data && effective.data.allowed_risk_levels)}`}
                legend="Risk levels that may be planned"
                kind="levels"
                value={effective.data ? effective.data.allowed_risk_levels : []}
                onSave={(v) => save('allowed_risk_levels', v)}
              />
            </>
          )}
        </DataState>
      )}
    </Card>
  )
}
