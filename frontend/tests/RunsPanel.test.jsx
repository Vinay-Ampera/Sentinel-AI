import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import RunsPanel from '../src/features/runs/RunsPanel.jsx'

afterEach(cleanup)

const run = (over = {}) => ({
  id: 'r1',
  project_id: 'proj',
  plan_id: 'p1',
  status: 'completed',
  created_at: '2026-10-24T10:00:00Z',
  error_summary: null,
  progress: { tests_total: 3, tests_finished: 3, results_by_status: {}, cases_by_status: {} },
  ...over,
})
const result = (over = {}) => ({ id: 'x1', planned_test_id: 't1', status: 'passed', summary: null, ...over })
const planTests = [
  { id: 't1', name: 'Python unit tests (pytest)' },
  { id: 't2', name: 'Sandbox self-check' },
]
const approvedPlans = [
  { id: 'p1', version: 1, status: 'approved', risk_level: 'low' },
  { id: 'p2', version: 2, status: 'draft', risk_level: 'low' },
]

const fakeApi = (over = {}) => ({
  listRuns: vi.fn().mockResolvedValue([run()]),
  getRun: vi.fn().mockResolvedValue(run()),
  listRunResults: vi.fn().mockResolvedValue([result()]),
  getRunResult: vi.fn().mockResolvedValue({ ...result(), cases: [], evidence: [] }),
  getEvidenceText: vi.fn().mockResolvedValue({ text: 'hello', truncated: false }),
  getPlan: vi.fn().mockResolvedValue({ id: 'p1', tests: planTests }),
  createRun: vi.fn().mockResolvedValue(run({ id: 'r2', status: 'queued' })),
  cancelRun: vi.fn().mockResolvedValue(run({ status: 'cancel_requested' })),
  ...over,
})

const show = (api, plans = approvedPlans, pollMs = 3000) =>
  render(<RunsPanel api={api} projectId="proj" plans={plans} pollMs={pollMs} />)

describe('RunsPanel', () => {
  it('shows loading, then the run history without calling a finished run a pass', async () => {
    show(fakeApi())
    expect(screen.getByRole('status').textContent).toMatch(/loading runs/i)
    const history = await screen.findByRole('list', { name: /run history/i })
    expect(within(history).getByText('Finished (see results)')).toBeTruthy()
    expect(screen.queryByText(/^passed$/i)).toBeNull()
  })

  it('shows an error and an empty state', async () => {
    show(fakeApi({ listRuns: vi.fn().mockRejectedValue(new Error('Could not reach the server')) }))
    expect((await screen.findByRole('alert')).textContent).toMatch(/could not reach/i)
    cleanup()
    show(fakeApi({ listRuns: vi.fn().mockResolvedValue([]) }))
    expect(await screen.findByText(/no runs yet/i)).toBeTruthy()
  })

  it('keeps test outcomes and infrastructure outcomes visibly different', async () => {
    const results = [
      result({ id: 'a', status: 'passed' }),
      result({ id: 'b', status: 'failed', summary: 'pytest: 1 failed.' }),
      result({ id: 'c', status: 'skipped' }),
      result({ id: 'd', status: 'blocked', summary: 'Blocked: not enabled.' }),
      result({ id: 'e', status: 'timed_out' }),
      result({ id: 'f', status: 'not_run' }),
      result({ id: 'g', status: 'failed_to_start' }),
      result({ id: 'h', status: 'cancelled' }),
      result({ id: 'i', status: 'error' }),
    ]
    show(fakeApi({ listRunResults: vi.fn().mockResolvedValue(results) }))
    fireEvent.click(await screen.findByRole('button', { name: 'Details' }))
    for (const label of ['Passed', 'Failed', 'Skipped', 'Blocked', 'Timed out', 'Not run', 'Could not start', 'Cancelled', 'Error']) {
      expect((await screen.findAllByText(label)).length).toBeGreaterThan(0)
    }
    expect(screen.getByText('Could not start').getAttribute('title')).toMatch(/not a test failure/i)
    expect(screen.getByText('pytest: 1 failed.')).toBeTruthy()
    expect((await screen.findAllByText('Python unit tests (pytest)')).length).toBeGreaterThan(0)
  })

  it('offers only approved plans and starts a run with an idempotency key', async () => {
    const api = fakeApi()
    show(api)
    await screen.findByRole('list', { name: /run history/i })
    const select = screen.getByLabelText(/plan to run/i)
    expect(within(select).getAllByRole('option').map((o) => o.textContent)).toEqual(['Select an approved plan…', 'v1 · risk low'])
    const start = screen.getByRole('button', { name: 'Start run' })
    expect(start.disabled).toBe(true)
    fireEvent.change(select, { target: { value: 'p1' } })
    fireEvent.click(start)
    await waitFor(() => expect(api.createRun).toHaveBeenCalledTimes(1))
    expect(api.createRun.mock.calls[0].slice(0, 2)).toEqual(['proj', 'p1'])
    expect(api.createRun.mock.calls[0][2]).toMatch(/^[0-9a-f-]{36}$/)
    expect(await screen.findByText(/run details/i)).toBeTruthy()
  })

  it('shows why a run could not start and retries with the same key', async () => {
    const api = fakeApi({
      createRun: vi.fn().mockRejectedValueOnce(new Error('This plan already has a run in progress')).mockResolvedValue(run({ id: 'r2' })),
    })
    show(api)
    await screen.findByRole('list', { name: /run history/i })
    fireEvent.change(screen.getByLabelText(/plan to run/i), { target: { value: 'p1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Start run' }))
    expect((await screen.findByRole('alert')).textContent).toMatch(/already has a run/i)
    fireEvent.click(screen.getByRole('button', { name: 'Start run' }))
    await waitFor(() => expect(api.createRun).toHaveBeenCalledTimes(2))
    expect(api.createRun.mock.calls[1][2]).toBe(api.createRun.mock.calls[0][2])
  })

  it('says so when there is no approved plan', async () => {
    show(fakeApi(), [{ id: 'p2', version: 2, status: 'draft', risk_level: 'low' }])
    expect(await screen.findByText(/no approved plan to run/i)).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Start run' })).toBeNull()
  })

  it('cancels only runs that can still be cancelled', async () => {
    const api = fakeApi({
      listRuns: vi.fn().mockResolvedValue([run({ id: 'r1', status: 'running' }), run({ id: 'r3', status: 'completed' })]),
    })
    show(api, approvedPlans, 60000)
    const buttons = await screen.findAllByRole('button', { name: 'Cancel run' })
    expect(buttons).toHaveLength(1)
    fireEvent.click(buttons[0])
    await waitFor(() => expect(api.cancelRun).toHaveBeenCalledWith('r1'))
  })

  it('follows progress while a run is active and stops when it is done', async () => {
    const states = [
      run({ status: 'running', progress: { tests_total: 3, tests_finished: 1, results_by_status: {}, cases_by_status: {} } }),
      run({ status: 'completed', progress: { tests_total: 3, tests_finished: 3, results_by_status: {}, cases_by_status: { passed: 2, failed: 1 } } }),
    ]
    let n = 0
    const api = fakeApi({
      listRuns: vi.fn().mockImplementation(() => Promise.resolve([states[Math.min(n, 1)]])),
      getRun: vi.fn().mockImplementation(() => Promise.resolve(states[Math.min(n++, 1)])),
    })
    show(api, approvedPlans, 20)
    fireEvent.click(await screen.findByRole('button', { name: 'Details' }))
    expect(await screen.findByText(/1 of 3 checks have a result/)).toBeTruthy()
    expect(await screen.findByText(/3 of 3 checks have a result/)).toBeTruthy()
    expect(screen.getByText(/2 passed, 1 failed/)).toBeTruthy()
    const calls = api.getRun.mock.calls.length
    await new Promise((r) => setTimeout(r, 120))
    expect(api.getRun.mock.calls.length).toBe(calls) // no more polling once finished
  })

  it('shows cases and evidence for a result, as plain text', async () => {
    const detail = {
      ...result({ status: 'failed' }),
      cases: [
        { ordinal: 1, suite: 'pytest', classname: 'tests.test_calc', name: 'test_add', status: 'passed', duration_ms: 1, message: null, detail: null },
        { ordinal: 2, suite: 'pytest', classname: 'tests.test_calc', name: 'test_wrong', status: 'failed', duration_ms: 1, message: 'assert 2 == 3', detail: null },
      ],
      evidence: [{ id: 'e1', name: 'stdout.log', kind: 'log', content_type: 'text/plain', size_bytes: 12, sha256: 'x' }],
    }
    const api = fakeApi({
      getRunResult: vi.fn().mockResolvedValue(detail),
      getEvidenceText: vi.fn().mockResolvedValue({ text: '<img src=x onerror=alert(1)>', truncated: true }),
    })
    show(api)
    fireEvent.click(await screen.findByRole('button', { name: 'Details' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Show details' }))
    expect(await screen.findByText('tests.test_calc::test_wrong')).toBeTruthy()
    expect(screen.getByText('assert 2 == 3')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'View stdout.log' }))
    const view = await screen.findByLabelText('Contents of stdout.log')
    expect(view.textContent).toBe('<img src=x onerror=alert(1)>') // text, never markup
    expect(view.querySelector('img')).toBeNull()
    expect(screen.getByText(/shortened for display/i)).toBeTruthy()
  })

  it('reports an evidence or result load failure', async () => {
    const api = fakeApi({
      getRunResult: vi.fn().mockRejectedValue(new Error('Result not found')),
    })
    show(api)
    fireEvent.click(await screen.findByRole('button', { name: 'Details' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Show details' }))
    expect((await screen.findByText('Result not found'))).toBeTruthy()
  })
})
