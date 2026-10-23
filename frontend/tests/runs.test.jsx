import { fireEvent, renderHook, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { runVerdict } from '../src/features/runs/verdict.js'
import { usePolledLoad } from '../src/hooks/usePolledLoad.js'
import { ApiError } from '../src/services/api.js'
import { fakeApi, project, renderApp } from './helpers.jsx'

const run = (over = {}) => ({
  id: 'r1',
  project_id: 'p1',
  plan_id: 'pl1',
  status: 'completed',
  timeout_seconds: 600,
  created_at: '2026-10-24T10:00:00Z',
  started_at: '2026-10-24T10:00:05Z',
  finished_at: '2026-10-24T10:01:05Z',
  error_summary: null,
  progress: { batches_total: 1, batches_by_status: {}, tests_total: 3, tests_finished: 3, results_by_status: { passed: 2, failed: 1 }, cases_by_status: { passed: 4, failed: 1 } },
  ...over,
})
const result = (over = {}) => ({ id: 'x1', batch_id: 'b1', planned_test_id: 't1', attempt: 1, status: 'passed', summary: null, exit_code: 0, duration_ms: 1200, finished_at: '2026-10-24T10:01:00Z', ...over })
const plan = { id: 'pl1', version: 3, status: 'approved', risk_level: 'low', tests: [
  { id: 't1', name: 'Python unit tests (pytest)', tool: 'pytest', category: 'functional', risk_level: 'low', status: 'executed' },
  { id: 't2', name: 'Sandbox self-check', tool: 'sandbox_probe', category: 'infrastructure', risk_level: 'low', status: 'executed' },
  { id: 't3', name: 'Dependency audit', tool: 'dependency_audit', category: 'security', risk_level: 'low', status: 'approved' },
  { id: 't4', name: 'Not applicable check', tool: 'x', category: 'x', risk_level: 'low', status: 'skipped' },
] }
const api = (over = {}) =>
  fakeApi({
    getProject: () => Promise.resolve(project),
    getPlan: () => Promise.resolve(plan),
    listPlans: () => Promise.resolve([{ id: 'pl1', version: 3, status: 'approved', risk_level: 'low' }, { id: 'pl2', version: 4, status: 'draft', risk_level: 'low' }]),
    listRuns: vi.fn().mockResolvedValue([run()]),
    getRun: vi.fn().mockResolvedValue(run()),
    listRunResults: vi.fn().mockResolvedValue([result(), result({ id: 'x2', planned_test_id: 't2', status: 'failed_to_start', summary: 'Sandbox unavailable' })]),
    listRunBatches: () => Promise.resolve([{ id: 'b1', ordinal: 1, status: 'completed', attempt: 1, max_attempts: 2, started_at: '2026-10-24T10:00:05Z', finished_at: '2026-10-24T10:01:00Z', error_summary: null }]),
    listRunEvents: () => Promise.resolve([{ id: 1, event_type: 'run_created', from_status: null, to_status: 'queued', detail: {}, created_at: '2026-10-24T10:00:00Z' }]),
    createRun: vi.fn().mockResolvedValue(run({ id: 'r9', status: 'queued', finished_at: null })),
    cancelRun: vi.fn().mockResolvedValue(run({ status: 'cancel_requested' })),
    getRunResult: vi.fn().mockResolvedValue({ ...result({ status: 'failed', summary: '1 failed' }), cases: [
      { ordinal: 1, suite: 'pytest', classname: 'tests.test_calc', name: 'test_add', status: 'passed', duration_ms: 1, message: null, detail: null },
      { ordinal: 2, suite: 'pytest', classname: 'tests.test_calc', name: 'test_wrong', status: 'failed', duration_ms: 2, message: 'assert 2 == 3', detail: '<script>alert(1)</script>' },
    ], evidence: [{ id: 'e1', name: 'stdout.log', kind: 'log', content_type: 'text/plain', size_bytes: 12, sha256: 'abcdef0123456789' }] }),
    getEvidenceText: vi.fn().mockResolvedValue({ text: '<b>hello</b>', truncated: false }),
    evidenceUrl: (id) => `/api/v1/artifacts/${id}/content`,
    ...over,
  })

describe('runVerdict', () => {
  it('never calls a finished run a pass unless every expected check passed', () => {
    expect(runVerdict(run(), [result()], 2).tone).toBe('warning') // one expected check has no result
    expect(runVerdict(run(), [result(), result({ id: 'b', status: 'skipped' })], 2).title).toMatch(/not everything ran/)
    expect(runVerdict(run(), [result(), result({ id: 'b', status: 'failed' })], 2)).toMatchObject({ tone: 'danger', title: '1 check did not pass' })
    expect(runVerdict(run(), [], 0).title).toMatch(/no results/)
    expect(runVerdict(run(), [result(), result({ id: 'b' })], 2)).toMatchObject({ tone: 'success', title: 'All 2 checks passed' })
  })

  it('describes active and unsuccessful runs without implying results', () => {
    expect(runVerdict(run({ status: 'running' }), [], 3).title).toBe('Run in progress')
    expect(runVerdict(run({ status: 'failed', error_summary: 'Sandbox down' }), [], 3)).toMatchObject({ tone: 'danger', text: 'Sandbox down' })
    expect(runVerdict(run({ status: 'cancelled' }), [], 3).tone).toBe('neutral')
  })
})

describe('usePolledLoad', () => {
  it('keeps polling while active, stops when done, and keeps the last data when a refresh fails', async () => {
    let n = 0
    const load = vi.fn(() => {
      n += 1
      if (n === 3) return Promise.reject(new Error('blip'))
      return Promise.resolve({ n, done: n >= 4 })
    })
    const { result } = renderHook(() => usePolledLoad(load, (d) => !(d && d.done), 20))
    await waitFor(() => expect(result.current[0].data && result.current[0].data.n).toBe(2), { timeout: 2000 })
    await waitFor(() => expect(result.current[0].error).toBeTruthy(), { timeout: 2000 })
    expect(result.current[0].data.n).toBe(2) // last good data kept next to the error
    await waitFor(() => expect(result.current[0].data.done).toBe(true), { timeout: 2000 })
    const calls = load.mock.calls.length
    await new Promise((r) => setTimeout(r, 150))
    expect(load.mock.calls.length).toBe(calls) // no more polling once finished
  })
})

describe('runs page', () => {
  it('offers only approved plans and starts a run, then opens its report', async () => {
    const a = api()
    renderApp(a, '/projects/p1/runs')
    const select = await screen.findByLabelText('Plan to run')
    expect(within(select).getAllByRole('option').map((o) => o.textContent)).toEqual(['Select an approved plan…', 'Version 3 · low risk'])
    expect(screen.getByRole('button', { name: 'Start run' }).disabled).toBe(true)
    fireEvent.change(select, { target: { value: 'pl1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Start run' }))
    await waitFor(() => expect(a.createRun).toHaveBeenCalledWith('p1', 'pl1', expect.stringMatching(/.{8,}/)))
    expect(await screen.findByText('Test execution report')).toBeTruthy()
  })

  it('shows why a run could not start and retries with the same idempotency key', async () => {
    const a = api({ createRun: vi.fn().mockRejectedValueOnce(new ApiError(409, 'conflict', 'Another run of this plan is active')).mockResolvedValue(run({ id: 'r9' })) })
    renderApp(a, '/projects/p1/runs')
    fireEvent.change(await screen.findByLabelText('Plan to run'), { target: { value: 'pl1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Start run' }))
    expect((await screen.findByRole('alert')).textContent).toMatch(/Another run of this plan is active/)
    fireEvent.click(screen.getByRole('button', { name: 'Start run' }))
    await waitFor(() => expect(a.createRun).toHaveBeenCalledTimes(2))
    expect(a.createRun.mock.calls[1][2]).toBe(a.createRun.mock.calls[0][2])
  })

  it('says so when there are no approved plans or no runs', async () => {
    renderApp(api({ listPlans: () => Promise.resolve([]), listRuns: () => Promise.resolve([]) }), '/projects/p1/runs')
    expect(await screen.findByText('No approved plan to run yet')).toBeTruthy()
    expect(await screen.findByText('No runs yet')).toBeTruthy()
  })

  it('lets you cancel only runs that can still be cancelled, after confirming', async () => {
    const a = api({ listRuns: vi.fn().mockResolvedValue([run({ id: 'r1' }), run({ id: 'r2', status: 'running', finished_at: null })]) })
    renderApp(a, '/projects/p1/runs')
    await screen.findAllByRole('link', { name: 'Open report' })
    expect(screen.getAllByRole('button', { name: 'Cancel run' })).toHaveLength(1)
    fireEvent.click(screen.getByRole('button', { name: 'Cancel run' }))
    expect(a.cancelRun).not.toHaveBeenCalled()
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Cancel run' }))
    await waitFor(() => expect(a.cancelRun).toHaveBeenCalledWith('r2'))
  })
})

describe('run report', () => {
  it('reports what the results say: counts, infrastructure problems apart from test failures, and checks with no result', async () => {
    renderApp(api(), '/projects/p1/runs/r1')
    expect(await screen.findByText('Test execution report')).toBeTruthy()
    expect(await screen.findByText(/Finished, but not everything ran/)).toBeTruthy() // 1 passed, 1 could not start, 1 no result
    const table = screen.getByRole('region', { name: 'Check results table' })
    const pytest = within(table).getByText('Python unit tests (pytest)').closest('tr')
    expect(within(pytest).getByText('Passed')).toBeTruthy()
    const sandbox = within(table).getByText('Sandbox self-check').closest('tr')
    expect(within(sandbox).getByText('Could not start')).toBeTruthy()
    expect(within(sandbox).getByText(/not a test failure/)).toBeTruthy()
    const audit = within(table).getByText('Dependency audit').closest('tr')
    expect(within(audit).getByText('No result recorded')).toBeTruthy() // absence is shown, not hidden
    expect(within(table).queryByText('Not applicable check')).toBeNull() // plan items that were never runnable are not listed
    expect(screen.getByRole('link', { name: 'version 3' }).getAttribute('href')).toBe('/projects/p1/plans/pl1')
  })

  it('filters the checks by outcome', async () => {
    renderApp(api(), '/projects/p1/runs/r1')
    await screen.findByText('Test execution report')
    fireEvent.change(screen.getByLabelText('Outcome'), { target: { value: 'failed_to_start' } })
    const table = screen.getByRole('region', { name: 'Check results table' })
    expect(within(table).queryByText('Python unit tests (pytest)')).toBeNull()
    expect(within(table).getByText('Sandbox self-check')).toBeTruthy()
  })

  it('shows an error state when the report cannot be loaded', async () => {
    renderApp(api({ getRun: () => Promise.reject(new ApiError(404, 'not_found', 'Run not found')) }), '/projects/p1/runs/r1')
    expect(await screen.findByText('Not found')).toBeTruthy()
  })
})

describe('result detail', () => {
  it('shows cases and evidence as plain text, with a download link', async () => {
    const a = api()
    renderApp(a, '/projects/p1/runs/r1/results/x1')
    expect(await screen.findByText('Python unit tests (pytest)')).toBeTruthy()
    expect(screen.getByText('tests.test_calc::test_wrong')).toBeTruthy()
    expect(screen.getByText('assert 2 == 3')).toBeTruthy()
    const detail = screen.getByText('<script>alert(1)</script>')
    expect(detail.tagName).toBe('PRE') // untrusted trace stays text
    fireEvent.click(screen.getByRole('button', { name: 'View stdout.log' }))
    const text = await screen.findByLabelText('Contents of stdout.log')
    expect(text.textContent).toBe('<b>hello</b>')
    expect(text.querySelector('b')).toBeNull()
    expect(screen.getByRole('link', { name: 'Download stdout.log' }).getAttribute('href')).toBe('/api/v1/artifacts/e1/content')
  })

  it('reports a load failure instead of an empty result', async () => {
    renderApp(api({ getRunResult: () => Promise.reject(new ApiError(500, 'error', 'x')) }), '/projects/p1/runs/r1/results/x1')
    expect(await screen.findByText('Something went wrong on the server')).toBeTruthy()
  })
})
