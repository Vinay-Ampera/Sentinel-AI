import { useState } from 'react'
import Button from '../components/Button.jsx'
import Card, { Metric, MetricGrid, ProgressBar } from '../components/Card.jsx'
import DataTable from '../components/DataTable.jsx'
import { ConfirmDialog } from '../components/Dialog.jsx'
import EvidenceViewer from '../components/EvidenceViewer.jsx'
import Field from '../components/Field.jsx'
import PageHeader from '../components/PageHeader.jsx'
import Pagination from '../components/Pagination.jsx'
import { usePagination } from '../hooks/usePagination.js'
import StatusBadge, { PlannedBadge } from '../components/StatusBadge.jsx'
import { EmptyState, ErrorState, Loading, PermissionDenied } from '../components/states.jsx'
import { useToast } from '../hooks/useToast.js'
import { ApiError } from '../services/api.js'
import { STATUS_TABLES } from '../lib/status.js'
import './DesignSystemPage.css'

// Developer-only gallery (development builds, not linked from the navbar). The sample rows
// below are labelled examples of how components look; they are not product data.
const SAMPLE_ROWS = Array.from({ length: 7 }, (_, i) => ({ id: i + 1, name: `Example item ${i + 1}`, state: ['passed', 'failed', 'skipped', 'blocked', 'timed_out', 'not_run', 'failed_to_start'][i] }))

export default function DesignSystemPage() {
  const { notify } = useToast()
  const [confirming, setConfirming] = useState(false)
  const paging = usePagination(SAMPLE_ROWS, 3)

  return (
    <>
      <PageHeader
        title="Design system"
        description="Developer reference for the shared components. Example content only; not product data."
        breadcrumbs={[{ to: '/', label: 'Workspace' }, { label: 'Design system' }]}
        actions={<Button variant="primary" onClick={() => notify({ tone: 'success', title: 'Saved', message: 'Example success message.' })}>Show a toast</Button>}
      />

      <Card title="Buttons">
        <div className="demo-row">
          <Button variant="primary">Primary</Button>
          <Button>Secondary</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="danger">Danger</Button>
          <Button variant="primary" loading loadingLabel="Saving…">Save</Button>
          <Button variant="primary" disabled disabledReason="Select a project first">Start run</Button>
        </div>
      </Card>

      <Card title="Status badges">
        <p className="muted">Every status shows an icon and a text label; colour only reinforces it.</p>
        {Object.entries(STATUS_TABLES).map(([domain, table]) => (
          <div key={domain} className="demo-row">
            <strong className="demo-domain">{domain}</strong>
            {Object.keys(table).map((value) => <StatusBadge key={value} domain={domain} value={value} />)}
          </div>
        ))}
        <div className="demo-row">
          <strong className="demo-domain">planned</strong>
          <PlannedBadge stage={11} />
          <PlannedBadge />
        </div>
      </Card>

      <Card title="Metrics and progress">
        <MetricGrid label="Example run summary">
          <Metric label="Passed" value="12" />
          <Metric label="Failed" value="2" />
          <Metric label="Not run" value="1" hint="Not executed" />
        </MetricGrid>
        <ProgressBar value={60} label="Example progress" />
        <p className="muted">Unknown amount:</p>
        <ProgressBar value={null} label="Example in progress" />
      </Card>

      <Card title="Form field">
        <div className="stack">
          <Field label="Project name" hint="Shown in lists and reports" required />
          <Field label="Environment" error="Choose an environment" as="select">
            <option value="">Select…</option>
            <option>staging</option>
          </Field>
        </div>
      </Card>

      <Card title="Table and pagination">
        <DataTable
          caption="Example results"
          rows={paging.pageItems}
          getRowKey={(r) => r.id}
          columns={[
            { key: 'name', header: 'Name' },
            { key: 'state', header: 'Outcome', render: (r) => <StatusBadge domain="result" value={r.state} /> },
          ]}
        />
        <Pagination page={paging.page} pageCount={paging.pageCount} onPageChange={paging.setPage} label="Example pagination" />
      </Card>

      <Card title="Page states">
        <Loading label="Loading example…" lines={2} />
        <EmptyState title="Nothing here yet" action={<Button>Create one</Button>}>Empty states explain the next step.</EmptyState>
        <ErrorState error={new ApiError(0, 'network_error', 'Could not reach the server')} onRetry={() => notify({ title: 'Retrying' })} />
        <PermissionDenied what="example governance settings" />
      </Card>

      <Card title="Evidence viewer">
        <EvidenceViewer name="example.log" sizeBytes={42} text={'line 1: <b>not rendered as HTML</b>\nline 2: plain text only'} />
      </Card>

      <Card title="Confirmation dialog">
        <Button variant="danger" onClick={() => setConfirming(true)}>Open a risky-action confirmation</Button>
        <ConfirmDialog
          open={confirming}
          onClose={() => setConfirming(false)}
          title="Confirm example action"
          confirmLabel="Confirm"
          danger
          requireReason
          onConfirm={async () => notify({ tone: 'success', title: 'Confirmed (example only)' })}
        >
          <p>This example asks for a reason, as risky actions do when the backend requires one.</p>
        </ConfirmDialog>
      </Card>
    </>
  )
}
