import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../src/services/api.js'
import { statusMeta } from '../src/lib/status.js'
import { admin, fakeApi, project, renderApp } from './helpers.jsx'

const telemetry = (over = {}) => ({
  ingest_enabled: true, active_keys: 1, has_events: true, last_event_at: '2026-10-24T10:00:00Z',
  events_last_24h_by_level: { error: 4 }, events_last_24h_by_environment: { staging: 4 },
  dropped_last_24h: { invalid_schema: 2 }, evaluation_errors_last_24h: 0, groups: 2, share_of_groups_with_stack: 0.5,
  samples_with_trace_id: 0, samples_with_verified_link: 0, summary: 'Events were received; see the counts below and the limits.',
  thresholds: { new_group_events: 3, cost_spike_min_usd: 0.5 },
  model_usage: { window_hours: 24, calls: 6, ok: 3, failed: 1, blocked_by_budget: 1, retries: 2, input_tokens: 6000, output_tokens: 1200, estimated_cost_usd: 0.35, cost_is_estimate: true, average_latency_ms: 200, max_latency_ms: 300, incomplete_calls: 1, assistant_runs: 2, workflow_steps: 9, model_steps: 3, note: 'n' },
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


describe('cost and resource alerts, model usage and traces', () => {
  it('labels the new alert kinds and says costs are estimates', async () => {
    const list = [
      alert({ id: 'c1', rule: 'llm_cost_spike', source: 'internal', title: 'Estimated model cost is unusually high', group_id: null }),
      alert({ id: 'c2', rule: 'run_duration_anomaly', source: 'internal', title: 'A run took much longer', severity: 'low', group_id: null }),
    ]
    renderApp(api({ listAlerts: vi.fn().mockResolvedValue(list) }), '/projects/p1/alerts')
    expect(await screen.findByText('Model cost spike (estimated)')).toBeTruthy()
    expect(screen.getByText('Run took unusually long')).toBeTruthy()
    expect(screen.getAllByText('Observed by Sentinel')).toHaveLength(2)
  })

  it('shows model use as an estimate with incomplete records and the thresholds in effect', async () => {
    renderApp(api(), '/projects/p1/alerts')
    expect(await screen.findByText(/6 calls \(1 failed, 1 blocked by budget\), 2 retries/)).toBeTruthy()
    expect(screen.getByText(/about \$0.35/)).toBeTruthy()
    expect(screen.getByText(/Cost is an estimate/)).toBeTruthy()
    expect(screen.getByText('Incomplete model call records')).toBeTruthy()
    expect(screen.getByText(/new group events: 3/)).toBeTruthy()
  })

  it('names duplicates among the refused events', async () => {
    const t = telemetry({ dropped_last_24h: { duplicate: 4 } })
    renderApp(api({ getTelemetryStatus: vi.fn().mockResolvedValue(t) }), '/projects/p1/alerts')
    expect(await screen.findByText(/Duplicate \(already received\): 4/)).toBeTruthy()
  })

  it('links a sample to its trace and the trace page lists workflows and events together', async () => {
    const trace = 'ab'.repeat(16)
    const g = group({ samples: [{ ...group().samples[0], trace_id: trace }] })
    const view = {
      trace_id: trace,
      runs: [{ id: 'r1', status: 'completed', plan_id: 'pl1', started_at: null, finished_at: null, created_at: '2026-10-24T10:00:00Z', trace_id: trace }],
      assistant_runs: [{ id: 'ar1', workflow: 'investigation', status: 'succeeded', started_at: '2026-10-24T10:00:00Z', finished_at: null, trace_id: trace, steps: [{ seq: 1, node: 'load_subject', kind: 'deterministic', outcome: 'ok', created_at: '2026-10-24T10:00:00Z' }] }],
      events: [{ id: 'e1', received_at: '2026-10-24T10:00:01Z', service: 'api', level: 'error', message: 'boom <b>x</b>' }],
      limits: ['Sharing a trace id shows the events belong to the same operation, not that one caused the other.'],
    }
    const getTrace = vi.fn().mockResolvedValue(view)
    const a = api({ getEventGroup: vi.fn().mockResolvedValue(g), getTrace })
    renderApp(a, '/projects/p1/alerts/al1')
    const link = await screen.findByRole('link', { name: trace })
    expect(link.getAttribute('href')).toBe(`/projects/p1/traces/${trace}`)
    renderApp(a, `/projects/p1/traces/${trace}`)
    await waitFor(() => expect(getTrace).toHaveBeenCalledWith('p1', trace))
    expect((await screen.findAllByText('Workflows with this trace id')).length).toBeGreaterThan(0)
    expect(screen.getAllByRole('link', { name: 'Test run' }).length).toBeGreaterThan(0)
    expect(screen.getAllByText(/not that one caused the other/).length).toBeGreaterThan(0)
    expect(screen.getAllByText('boom <b>x</b>').length).toBeGreaterThan(0) // text, never markup
  })

  it('shows an unknown trace as an error with a retry', async () => {
    const getTrace = vi.fn().mockRejectedValue(new ApiError(404, 'not_found', 'Trace not found'))
    renderApp(api({ getTrace }), `/projects/p1/traces/${'cd'.repeat(16)}`)
    expect(await screen.findByText(/Trace not found/)).toBeTruthy()
  })
})


describe('organization alert threshold limits (admin page)', () => {
  const limits = [
    { name: 'new_group_events', default: 3, min: 1, max: 100, description: 'Events a new error group needs before it raises an alert' },
    { name: 'spike_ratio', default: 3, min: 1.5, max: 20, description: 'Times the median that counts as a spike' },
  ]
  const policies = (over = {}) => ({ approval_required_risk_levels: ['high'], allowed_risk_levels: ['low'], high_risk_approver_roles: ['admin'], production_testing: { allowed: false }, ...over })
  const adminApi = (over = {}) => fakeApi({ me: () => Promise.resolve(admin), getAlertThresholdLimits: vi.fn().mockResolvedValue(limits), getGlobalPolicies: vi.fn().mockResolvedValue(policies()), setGlobalPolicy: vi.fn().mockResolvedValue({}), ...over })

  it('shows each built-in range and starts from the saved organization limits', async () => {
    const a = adminApi({ getGlobalPolicies: vi.fn().mockResolvedValue(policies({ alert_threshold_bounds: { new_group_events: { min: 2, max: 10 } } })) })
    renderApp(a, '/admin')
    const table = await screen.findByRole('region', { name: 'Alert threshold limits table' })
    expect(within(table).getByText('1 to 100 (3)')).toBeTruthy()
    expect(within(table).getByLabelText('Lowest new group events').value).toBe('2')
    expect(within(table).getByLabelText('Highest new group events').value).toBe('10')
    expect(within(table).getByLabelText('Lowest spike ratio').value).toBe('1.5') // never saved: the built-in range
    expect(screen.getByText(/only narrow a built-in range, never widen it/)).toBeTruthy()
  })

  it('refuses numbers that are reversed or outside the built-in range before sending anything', async () => {
    const a = adminApi()
    renderApp(a, '/admin')
    const lowest = await screen.findByLabelText('Lowest new group events')
    fireEvent.change(lowest, { target: { value: '0' } })
    expect(await screen.findByText(/Stay inside the built-in range 1 to 100/)).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Save limits' }).disabled).toBe(true)
    fireEvent.change(lowest, { target: { value: '50' } })
    fireEvent.change(screen.getByLabelText('Highest new group events'), { target: { value: '5' } })
    expect(await screen.findByText(/minimum must not exceed the maximum/)).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Highest new group events'), { target: { value: '' } })
    expect(await screen.findByText(/Enter both numbers/)).toBeTruthy()
    expect(a.setGlobalPolicy).not.toHaveBeenCalled()
  })

  it('saves every limit as numbers and confirms', async () => {
    const a = adminApi()
    renderApp(a, '/admin')
    fireEvent.change(await screen.findByLabelText('Lowest new group events'), { target: { value: '2' } })
    fireEvent.change(screen.getByLabelText('Highest new group events'), { target: { value: '10' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save limits' }))
    await waitFor(() => expect(a.setGlobalPolicy).toHaveBeenCalledWith('alert_threshold_bounds', { new_group_events: { min: 2, max: 10 }, spike_ratio: { min: 1.5, max: 20 } }))
    expect(await screen.findByText('Alert threshold limits saved')).toBeTruthy()
  })

  it('resets to the built-in limits', async () => {
    const a = adminApi({ getGlobalPolicies: vi.fn().mockResolvedValue(policies({ alert_threshold_bounds: { new_group_events: { min: 2, max: 10 } } })) })
    renderApp(a, '/admin')
    await screen.findByLabelText('Lowest new group events')
    fireEvent.click(screen.getByRole('button', { name: 'Reset to built-in limits' }))
    await waitFor(() => expect(a.setGlobalPolicy).toHaveBeenCalledWith('alert_threshold_bounds', { new_group_events: { min: 1, max: 100 }, spike_ratio: { min: 1.5, max: 20 } }))
  })

  it('shows the server refusal unchanged (only a super admin may change the limits)', async () => {
    const a = adminApi({ setGlobalPolicy: vi.fn().mockRejectedValue(new ApiError(403, 'forbidden', 'You do not have permission to change this policy')) })
    renderApp(a, '/admin')
    fireEvent.click(await screen.findByRole('button', { name: 'Save limits' }))
    expect(await screen.findByText('You do not have permission to change this policy')).toBeTruthy()
  })

  it('shows a load error with retry instead of an empty editor', async () => {
    const getAlertThresholdLimits = vi.fn().mockRejectedValueOnce(new ApiError(500, 'error', 'Failed')).mockResolvedValue(limits)
    renderApp(adminApi({ getAlertThresholdLimits }), '/admin')
    const retry = await screen.findAllByRole('button', { name: /try again|retry/i })
    fireEvent.click(retry[retry.length - 1])
    expect(await screen.findByLabelText('Lowest new group events')).toBeTruthy()
  })
})
