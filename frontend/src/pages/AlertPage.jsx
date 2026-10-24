import { useCallback } from 'react'
import { Link, useOutletContext, useParams } from 'react-router-dom'
import SectionHeader from '../components/SectionHeader.jsx'
import { DataState } from '../components/states.jsx'
import AlertActions from '../features/alerts/AlertActions.jsx'
import AlertAssist from '../features/alerts/AlertAssist.jsx'
import AlertDetailView from '../features/alerts/AlertDetailView.jsx'
import { canRun } from '../features/alerts/labels.js'
import SamplesPanel from '../features/alerts/SamplesPanel.jsx'
import TelemetryPanel from '../features/alerts/TelemetryPanel.jsx'
import { useApi } from '../hooks/useApi.js'
import { useLoad } from '../hooks/useLoad.js'

// One alert. After an action the page reloads from the server, so it never shows a state the
// server did not confirm.
export default function AlertPage() {
  const { project } = useOutletContext()
  const { alertId } = useParams()
  const api = useApi()
  const [loaded, reload] = useLoad(useCallback(() => api.getAlert(project.id, alertId), [api, project.id, alertId]))
  const mayAct = canRun(project) && project.status === 'active'
  return (
    <>
      <p><Link to={`/projects/${project.id}/alerts`}>Back to all alerts</Link></p>
      <DataState state={loaded} onRetry={reload} what="this alert" loadingLabel="Loading alert…" isEmpty={() => false}>
        {(alert) => (
          <>
            <SectionHeader title={alert.title} />
            <AlertDetailView alert={alert} projectId={project.id} />
            {alert.group_id && <SamplesPanel projectId={project.id} groupId={alert.group_id} api={api} />}
            {mayAct && (
              <>
                <AlertActions alert={alert} projectId={project.id} api={api} onChanged={reload} />
                <AlertAssist projectId={project.id} alert={alert} api={api} />
              </>
            )}
            <TelemetryPanel telemetry={alert.telemetry} />
          </>
        )}
      </DataState>
    </>
  )
}
