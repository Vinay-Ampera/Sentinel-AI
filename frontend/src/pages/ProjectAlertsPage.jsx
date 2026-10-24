import { useCallback, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import Alert from '../components/Alert.jsx'
import Field from '../components/Field.jsx'
import SectionHeader from '../components/SectionHeader.jsx'
import { DataState } from '../components/states.jsx'
import AlertTable from '../features/alerts/AlertTable.jsx'
import IngestSetup from '../features/alerts/IngestSetup.jsx'
import { canManage } from '../features/alerts/labels.js'
import TelemetryPanel from '../features/alerts/TelemetryPanel.jsx'
import { useApi } from '../hooks/useApi.js'
import { useLoad } from '../hooks/useLoad.js'

// Alerts for one project: what Sentinel measured, never why. Acknowledging records that a
// person has seen it; it does not fix or hide anything else.
export default function ProjectAlertsPage() {
  const { project } = useOutletContext()
  const api = useApi()
  const [status, setStatus] = useState('')
  const [alerts, reloadAlerts] = useLoad(useCallback(() => api.listAlerts(project.id, { status }), [api, project.id, status]))
  const [telemetry, reloadTelemetry] = useLoad(useCallback(() => api.getTelemetryStatus(project.id), [api, project.id]))
  return (
    <>
      <Alert tone="info" title="Measurements, not diagnoses">
        An alert says what Sentinel counted, when and where. It does not say why it happened: that needs an investigation and, ideally, a reproduction.
      </Alert>
      <SectionHeader title="Alerts" />
      <Field as="select" label="Show" value={status} onChange={(e) => setStatus(e.target.value)}>
        <option value="">All</option>
        <option value="open">Open</option>
        <option value="acknowledged">Acknowledged</option>
        <option value="resolved">Resolved</option>
      </Field>
      <DataState state={alerts} onRetry={reloadAlerts} what="the alerts" loadingLabel="Loading alerts…" isEmpty={() => false}>
        {(items) => (
          <AlertTable
            alerts={items}
            projectId={project.id}
            emptyText={telemetry.data && !telemetry.data.has_events ? 'No alerts, and no application events have been received, so this is not evidence the application is healthy.' : 'Nothing matches this filter.'}
          />
        )}
      </DataState>
      <SectionHeader title="Telemetry" />
      <DataState state={telemetry} onRetry={reloadTelemetry} what="the telemetry status" loadingLabel="Loading telemetry status…" isEmpty={() => false}>
        {(t) => <TelemetryPanel telemetry={t} />}
      </DataState>
      {canManage(project) && project.status === 'active' && (
        <IngestSetup project={project} api={api} ingestEnabled={Boolean(telemetry.data && telemetry.data.ingest_enabled)} onPolicyChanged={reloadTelemetry} />
      )}
    </>
  )
}
