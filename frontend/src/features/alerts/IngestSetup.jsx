import { useCallback, useState } from 'react'
import Alert from '../../components/Alert.jsx'
import Button from '../../components/Button.jsx'
import Card from '../../components/Card.jsx'
import DataTable from '../../components/DataTable.jsx'
import Field from '../../components/Field.jsx'
import { DataState, EmptyState } from '../../components/states.jsx'
import { useLoad } from '../../hooks/useLoad.js'
import { describeError } from '../../lib/errors.js'
import { formatDateTime } from '../../lib/format.js'
import { INGEST_WARNING } from './labels.js'
import './IngestSetup.css'

const STATUS = { active: 'Active', expired: 'Expired', revoked: 'Revoked' }

// For people with manage access: switch ingestion on, and create or revoke the keys an
// application uses to push events. A key can only add events to this project; it is shown once.
export default function IngestSetup({ project, api, ingestEnabled, onPolicyChanged }) {
  const [keys, reloadKeys] = useLoad(useCallback(() => api.listIngestKeys(project.id), [api, project.id]))
  const [label, setLabel] = useState('')
  const [created, setCreated] = useState(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState(null)

  async function run(name, fn) {
    setBusy(name)
    setError(null)
    try {
      await fn()
    } catch (e) {
      setError(e.status === 403 || e.status === 409 || e.status === 422 ? e.message : describeError(e).message)
    } finally {
      setBusy('')
    }
  }

  const toggle = () => run('policy', async () => {
    await api.setProjectPolicy(project.id, 'observability_ingest', { enabled: !ingestEnabled })
    onPolicyChanged()
  })
  const create = (e) => {
    e.preventDefault()
    return run('create', async () => {
      setCreated(await api.createIngestKey(project.id, label.trim()))
      setLabel('')
      reloadKeys()
    })
  }
  const revoke = (k) => run(`revoke-${k.id}`, async () => {
    await api.revokeIngestKey(project.id, k.id)
    reloadKeys()
  })

  return (
    <Card title="Event ingestion" headingLevel={3}>
      {error && <Alert tone="danger" title="The change was not made">{error}</Alert>}
      {!ingestEnabled && <Alert tone="warning" title="Before you turn this on">{INGEST_WARNING}</Alert>}
      <p>
        Ingestion is <strong>{ingestEnabled ? 'on' : 'off'}</strong> for this project.{' '}
        <Button loading={busy === 'policy'} loadingLabel="Saving…" disabled={Boolean(busy)} onClick={toggle}>{ingestEnabled ? 'Turn off ingestion' : 'Turn on ingestion'}</Button>
      </p>
      <form onSubmit={create} className="ingest-form">
        <Field label="New ingest key label" hint="For example the application or environment that will send events." value={label} maxLength={80} required onChange={(e) => setLabel(e.target.value)} />
        <Button type="submit" variant="primary" loading={busy === 'create'} loadingLabel="Creating…" disabled={Boolean(busy) || !label.trim()}>Create ingest key</Button>
      </form>
      {created && (
        <Alert tone="success" title="Copy this key now">
          It is shown only once and cannot be retrieved later. Keep it out of source control and logs.
          <span className="ingest-key mono" tabIndex={0}>{created.key}</span>
        </Alert>
      )}
      <DataState state={keys} onRetry={reloadKeys} what="the ingest keys" loadingLabel="Loading keys…" isEmpty={() => false}>
        {(items) => (
          <DataTable
            caption="Ingest keys"
            rows={items}
            getRowKey={(k) => k.id}
            empty={<EmptyState title="No ingest keys">Create a key so an application can send events.</EmptyState>}
            columns={[
              { key: 'label', header: 'Label' },
              { key: 'key_id', header: 'Key id', render: (k) => <span className="mono">sai_ing_{k.key_id}…</span> },
              { key: 'status', header: 'Status', render: (k) => STATUS[k.status] || k.status },
              { key: 'expires_at', header: 'Expires', render: (k) => formatDateTime(k.expires_at) },
              { key: 'last_used_at', header: 'Last used', render: (k) => (k.last_used_at ? formatDateTime(k.last_used_at) : 'Never') },
              { key: 'actions', header: 'Actions', render: (k) => (k.status === 'active' ? <Button disabled={Boolean(busy)} onClick={() => revoke(k)} aria-label={`Revoke key ${k.label}`}>Revoke</Button> : null) },
            ]}
          />
        )}
      </DataState>
      <p className="muted">Applications send events with <span className="mono">POST /api/v1/ingest/events</span>, header <span className="mono">Authorization: Bearer &lt;key&gt;</span> and a JSON body <span className="mono">{'{"events": [...]}'}</span> (at most 100 events and 256 KiB per request).</p>
    </Card>
  )
}
