import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../src/services/api.js'
import { statusMeta } from '../src/lib/status.js'
import { fakeApi, project, renderApp } from './helpers.jsx'

const telemetry = (over = {}) => ({
  ingest_enabled: true, active_keys: 1, has_events: true, last_event_at: '2026-10-24T10:00:00Z',
  events_last_24h_by_level: { error: 4 }, events_last_24h_by_environment: { staging: 4 },
  dropped_last_24h: { invalid_schema: 2 }, evaluation_errors_last_24h: 0, groups: 2, share_of_groups_with_stack: 0.5,
  samples_with_trace_id: 0, samples_with_verified_link: 0, summary: 'Events were received; see the counts below and the limits.',
  limits: ['Sentinel resolves no trace ids, scrapes no metrics and keeps only grouped, redacted samples.', 'External events are reported by the project\'s own application and can be wrong or forged.'],
  ...over,
})
const alert = (over = {}) => ({
  id: 'al1', rule: 'new_error_group', rule_version: 'alert-rules-v1', source: 'external', severity: 'medium', status: 'open',
  title: 'New error group in api', measured: { events: 3, service: 'api', environment: 'staging' }, evidence: { group_id: 'g1' },
  confidence: 'observed', cause_status: 'not_investigated', next_action: 'Open the group and read the samples.', occurrences: 1,
  group_id: 'g1', run_id: null, result_id: null, finding_id: null, agent_run_id: null,
  first_seen: '2026-10-24T10:00:00Z', last_seen: '2026-10-24T10:05:00Z', closed_at: null, ...over,
})
const detail = (over = {}) => ({
  ...alert(), history: [{ action: 'created', actor_user_id: null, note: null, detail: {}, created_at: '2026-10-24T10:00:00Z' }],
  group: null, proposal_ids: [], telemetry: telemetry(), cause_note: 'Sentinel measured the counts and times above. It does not know why this happened; no cause is claimed until it is investigated and verified.', ...over,
})
const group = (over = {}) => ({
  id: 'g1', service: 'api', environment: 'staging', level_class: 'error', error_type: 'ZeroDivisionError', message: 'charge failed for <n>',
  first_seen: '2026-10-24T10:00:00Z', last_seen: '2026-10-24T10:05:00Z', total_count: 3, has_stack: true, is_overflow: false, fingerprint_version: 'fp-v1',
  limits: [], samples: [{ id: 's1', received_at: '2026-10-24T10:00:00Z', client_timestamp: null, timestamp_untrusted: true, level: 'error', service: 'api', environment: 'staging', message: '<img src=x onerror=alert(1)> failed', error_type: 'ZeroDivisionError', stack: 'File "a.py", line 1, in f', attributes: {}, trace_id: null, span_id: null, release: 'v1', correlation: { during_run: 'r9' }, redactions: {}, reported_by: 'application' }],
  ...over,
})
const key = (over = {}) => ({ id: 'k1', key_id: 'abcdef012345', label: 'prod app', created_by: 'u1', created_at: '2026-10-24T10:00:00Z', expires_at: '2027-01-01T00:00:00Z', revoked_at: null, last_used_at: null, status: 'active', ...over })
const api = (over = {}) => fakeApi({
  getProject: () => Promise.resolve(project),
  listAlerts: vi.fn().mockResolvedValue([alert()]),
  getTelemetryStatus: vi.fn().mockResolvedValue(telemetry()),
  getAlert: vi.fn().mockResolvedValue(detail()),
  getEventGroup: vi.fn().mockResolvedValue(group()),
  listIngestKeys: vi.fn().mockResolvedValue([key()]),
  ...over,
})

describe('alerts list', () => {
  it('shows what was measured with severity, status and source, never a cause', async () => {
    renderApp(api(), '/projects/p1/alerts')
    expect(await screen.findByRole('link', { name: 'New error group in api' })).toBeTruthy()
    expect(screen.getByText('New error')).toBeTruthy()
    expect(screen.getByText('Reported by the application')).toBeTruthy()
    expect(within(screen.getByRole('region', { name: 'Alerts table' })).getByText('Open')).toBeTruthy()
    expect(screen.getByText(/Measurements, not diagnoses/)).toBeTruthy()
    expect(screen.queryByText(/root cause/i)).toBeNull()
  })

  it('filters by status through the server', async () => {
    const listAlerts = vi.fn().mockResolvedValue([alert()])
    renderApp(api({ listAlerts }), '/projects/p1/alerts')
    fireEvent.change(await screen.findByLabelText('Show'), { target: { value: 'resolved' } })
    await waitFor(() => expect(listAlerts).toHaveBeenLastCalledWith('p1', { status: 'resolved' }))
  })

  it('does not call an empty list healthy when no events were ever received', async () => {
    const a = api({ listAlerts: vi.fn().mockResolvedValue([]), getTelemetryStatus: vi.fn().mockResolvedValue(telemetry({ has_events: false, last_event_at: null, events_last_24h_by_level: {}, events_last_24h_by_environment: {}, dropped_last_24h: {}, groups: 0 })) })
    renderApp(a, '/projects/p1/alerts')
    expect(await screen.findByText(/not evidence the application is healthy/)).toBeTruthy()
    expect(screen.getByText('No application events have been received')).toBeTruthy()
  })

  it('discloses what was received, refused and cannot be seen', async () => {
    renderApp(api(), '/projects/p1/alerts')
    expect(await screen.findByText('What Sentinel can see')).toBeTruthy()
    expect(screen.getByText(/Invalid event: 2/)).toBeTruthy()
    expect(screen.getByText(/Error: 4/)).toBeTruthy()
    expect(screen.getByText(/resolves no trace ids/)).toBeTruthy()
    expect(screen.getByText(/can be wrong or forged/)).toBeTruthy()
  })

  it('shows a load error with a retry instead of an empty list', async () => {
    const listAlerts = vi.fn().mockRejectedValueOnce(new ApiError(500, 'error', 'Failed')).mockResolvedValue([alert()])
    renderApp(api({ listAlerts }), '/projects/p1/alerts')
    fireEvent.click(await screen.findByRole('button', { name: /try again|retry/i }))
    expect(await screen.findByRole('link', { name: 'New error group in api' })).toBeTruthy()
  })
})

describe('alert page', () => {
  it('states that no cause is known and shows the reported events as plain text', async () => {
    renderApp(api(), '/projects/p1/alerts/al1')
    expect(await screen.findByText(/It does not know why this happened/)).toBeTruthy()
    expect(screen.getByText(/Not investigated/)).toBeTruthy()
    expect(await screen.findByText(/Reported by the application/, { selector: 'h4, h3, p, strong, div' })).toBeTruthy()
    const sample = await screen.findByLabelText(/Reported event from/)
    expect(sample.textContent).toContain('<img src=x onerror=alert(1)> failed') // text, never markup
    expect(sample.querySelector('img')).toBeNull()
    expect(screen.getByText(/not trusted/)).toBeTruthy()
    expect(screen.getByText(/not as a cause/)).toBeTruthy()
  })

  it('acknowledges with a note and reloads the server state', async () => {
    const ack = vi.fn().mockResolvedValue(alert({ status: 'acknowledged' }))
    const getAlert = vi.fn().mockResolvedValueOnce(detail()).mockResolvedValue(detail({ status: 'acknowledged' }))
    renderApp(api({ acknowledgeAlert: ack, getAlert }), '/projects/p1/alerts/al1')
    fireEvent.change(await screen.findByLabelText('Note (optional)'), { target: { value: 'looking now' } })
    fireEvent.click(screen.getByRole('button', { name: 'Acknowledge' }))
    await waitFor(() => expect(ack).toHaveBeenCalledWith('p1', 'al1', 'looking now'))
    await waitFor(() => expect(getAlert).toHaveBeenCalledTimes(2))
    expect((await screen.findAllByText('Acknowledged')).length).toBeGreaterThan(0)
    expect(screen.queryByRole('button', { name: 'Acknowledge' })).toBeNull() // already seen; resolve remains
    expect(screen.getByRole('button', { name: 'Resolve' })).toBeTruthy()
  })

  it('shows a server refusal unchanged', async () => {
    const resolve = vi.fn().mockRejectedValue(new ApiError(409, 'invalid_state', 'This alert is already resolved'))
    renderApp(api({ resolveAlert: resolve }), '/projects/p1/alerts/al1')
    fireEvent.click(await screen.findByRole('button', { name: 'Resolve' }))
    expect(await screen.findByText('This alert is already resolved')).toBeTruthy()
  })

  it('hides actions from read-only members (the server still decides)', async () => {
    const a = api({ getProject: () => Promise.resolve({ ...project, your_access: 'read' }) })
    renderApp(a, '/projects/p1/alerts/al1')
    await screen.findByText(/It does not know why this happened/)
    expect(screen.queryByRole('button', { name: 'Acknowledge' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Investigate' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Draft a regression test' })).toBeNull()
  })

  it('starts an investigation for the alert only when a person asks, and opens the run', async () => {
    const create = vi.fn().mockResolvedValue({ id: 'ar1', project_id: 'p1', workflow: 'investigation', status: 'succeeded', result: { classification: 'reported_error', explanation: 'x', limitations: 'y', causes: [] }, steps: [] })
    renderApp(api({ createAgentRun: create, getAgentRun: create }), '/projects/p1/alerts/al1')
    await screen.findByText(/It does not know why this happened/)
    expect(create).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Investigate' }))
    await waitFor(() => expect(create).toHaveBeenCalledWith('p1', { workflow: 'investigation', alert_id: 'al1' }))
  })

  it('explains why a test cannot be drafted and shows the server message', async () => {
    const create = vi.fn().mockRejectedValue(new ApiError(403, 'forbidden', 'Insufficient access to this project'))
    renderApp(api({ createAgentRun: create }), '/projects/p1/alerts/al1')
    fireEvent.click(await screen.findByRole('button', { name: 'Draft a regression test' }))
    expect(await screen.findByText('Insufficient access to this project')).toBeTruthy()
    expect(screen.getByText(/error type and a stack trace/)).toBeTruthy()
  })

  it('links drafted tests, the assistant run and internal evidence without claiming a cause', async () => {
    const d = detail({ rule: 'run_failed', source: 'internal', group_id: null, run_id: 'r1', result_id: 'x1', finding_id: 'f1', agent_run_id: 'ar9', cause_status: 'investigated', proposal_ids: ['rp1'] })
    renderApp(api({ getAlert: vi.fn().mockResolvedValue(d) }), '/projects/p1/alerts/al1')
    expect(await screen.findByText('Observed by Sentinel')).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Open the run' }).getAttribute('href')).toBe('/projects/p1/runs/r1')
    expect(screen.getByRole('link', { name: 'Open the failed result' }).getAttribute('href')).toBe('/projects/p1/runs/r1/results/x1')
    expect(screen.getByRole('link', { name: 'Open the finding' }).getAttribute('href')).toBe('/projects/p1/findings/f1')
    expect(screen.getByRole('link', { name: /assistant's investigation/ })).toBeTruthy()
    expect(screen.getByText(/None is confirmed/)).toBeTruthy()
    expect(screen.getByRole('link', { name: 'Review on the Proposals tab' })).toBeTruthy()
  })
})

describe('ingestion setup (managers)', () => {
  it('warns before ingestion is turned on and sends only the flag', async () => {
    const setProjectPolicy = vi.fn().mockResolvedValue({})
    const getTelemetryStatus = vi.fn().mockResolvedValue(telemetry({ ingest_enabled: false }))
    renderApp(api({ setProjectPolicy, getTelemetryStatus }), '/projects/p1/alerts')
    expect(await screen.findByText(/can contain personal or secret data/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Turn on ingestion' }))
    await waitFor(() => expect(setProjectPolicy).toHaveBeenCalledWith('p1', 'observability_ingest', { enabled: true }))
  })

  it('shows a created key once, never in the list, and revokes keys', async () => {
    const created = { ...key({ id: 'k2', key_id: '111111111111', label: 'worker' }), key: 'sai_ing_111111111111_SECRET' }
    const createIngestKey = vi.fn().mockResolvedValue(created)
    const revokeIngestKey = vi.fn().mockResolvedValue(key({ status: 'revoked' }))
    renderApp(api({ createIngestKey, revokeIngestKey }), '/projects/p1/alerts')
    fireEvent.change(await screen.findByLabelText(/New ingest key label/), { target: { value: 'worker' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create ingest key' }))
    await waitFor(() => expect(createIngestKey).toHaveBeenCalledWith('p1', 'worker'))
    expect(await screen.findByText('sai_ing_111111111111_SECRET')).toBeTruthy()
    expect(screen.getByText(/shown only once/)).toBeTruthy()
    const table = await screen.findByRole('region', { name: 'Ingest keys table' })
    expect(within(table).queryByText(/SECRET/)).toBeNull()
    expect(within(table).getByText('prod app')).toBeTruthy()
    fireEvent.click(within(table).getByRole('button', { name: 'Revoke key prod app' }))
    await waitFor(() => expect(revokeIngestKey).toHaveBeenCalledWith('p1', 'k1'))
  })

  it('is not shown to members without manage access', async () => {
    const a = api({ getProject: () => Promise.resolve({ ...project, your_access: 'run' }) })
    renderApp(a, '/projects/p1/alerts')
    await screen.findByRole('link', { name: 'New error group in api' })
    expect(screen.queryByRole('heading', { name: 'Event ingestion' })).toBeNull()
    expect(a.listIngestKeys).not.toHaveBeenCalled()
  })

  it('shows the server refusal when a key cannot be created', async () => {
    const createIngestKey = vi.fn().mockRejectedValue(new ApiError(409, 'key_limit', 'At most 5 active keys per project'))
    renderApp(api({ createIngestKey }), '/projects/p1/alerts')
    fireEvent.change(await screen.findByLabelText(/New ingest key label/), { target: { value: 'x' } })
    fireEvent.click(screen.getByRole('button', { name: 'Create ingest key' }))
    expect(await screen.findByText('At most 5 active keys per project')).toBeTruthy()
  })
})

describe('status wording', () => {
  it('treats acknowledged as seen, not fixed', () => {
    expect(statusMeta('alert', 'acknowledged').tone).toBe('info')
    expect(statusMeta('alert', 'open').tone).toBe('warning')
    expect(statusMeta('alert', 'resolved').label).toBe('Resolved')
    expect(statusMeta('alert', 'surprise').tone).toBe('neutral') // unknown never looks favourable
  })
})
