import { fireEvent, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../src/services/api.js'
import { fakeApi, project, renderApp } from './helpers.jsx'

const run = (over = {}) => ({
  id: 'ar1', project_id: 'p1', workflow: 'planning', status: 'succeeded', degraded_reason: null,
  used_llm: true, cache_hit: false, model: 'm', plan_id: 'pl1', check_ids: ['pytest_unit'], source: 'model',
  message: null, result: { plan_id: 'pl1', check_ids: ['pytest_unit'], source: 'model', reasons: { pytest_unit: 'runs unit tests' } },
  started_at: '2026-10-24T10:00:00Z', finished_at: '2026-10-24T10:00:03Z',
  steps: [
    { seq: 1, node: 'deterministic_select', kind: 'deterministic', outcome: 'no_match', detail: {}, llm_usage_id: null },
    { seq: 2, node: 'llm_propose', kind: 'llm', outcome: 'ok', detail: {}, llm_usage_id: 7 },
  ],
  ...over,
})
const proposal = (over = {}) => ({
  id: 'rp1', project_id: 'p1', finding_id: 'f1', result_id: null, status: 'proposed', title: 'Total includes tax',
  rationale: 'The failure shows tax is ignored.', target_path: 'tests/test_total.py', framework: 'pytest',
  code: 'def test_x():\n    assert "<img src=x onerror=alert(1)>"\n', expected_behavior: 'Total is 4.',
  evidence_ids: ['finding:ab12cd34'], risk_flags: [], overlap: [], decided_by: null, decision_note: null,
  created_at: '2026-10-24T10:00:00Z', decided_at: null, ...over,
})
const api = (over = {}) => fakeApi({ getProject: () => Promise.resolve(project), listAgentRuns: vi.fn().mockResolvedValue([run()]), ...over })

describe('assistant runs', () => {
  it('lists runs with an outcome that is not a verdict, and says when no model was used', async () => {
    const a = api({ listAgentRuns: vi.fn().mockResolvedValue([run(), run({ id: 'ar2', used_llm: false, status: 'degraded', degraded_reason: 'llm_disabled' })]) })
    renderApp(a, '/projects/p1/assistant')
    expect(await screen.findAllByRole('link', { name: 'Test planning' })).toHaveLength(2)
    expect(screen.getByText('Finished')).toBeTruthy()
    expect(screen.getByText('Partly completed')).toBeTruthy()
    expect(screen.getByText('Built-in only')).toBeTruthy()
    expect(screen.getByText(/Suggestions, not decisions/)).toBeTruthy()
  })

  it('starts a planning run with the request text only and opens its result', async () => {
    const create = vi.fn().mockResolvedValue(run())
    const a = api({ createAgentRun: create, getAgentRun: vi.fn().mockResolvedValue(run()) })
    renderApp(a, '/projects/p1/assistant')
    fireEvent.change(await screen.findByLabelText(/What should be checked/), { target: { value: 'check my dependencies' } })
    fireEvent.click(screen.getByRole('button', { name: 'Draft a plan' }))
    await waitFor(() => expect(create).toHaveBeenCalledWith('p1', { workflow: 'planning', prompt: 'check my dependencies' }))
    expect(await screen.findByRole('link', { name: /Open the draft plan/ })).toBeTruthy()
  })

  it('shows the server refusal unchanged and keeps the text', async () => {
    const create = vi.fn().mockRejectedValue(new ApiError(429, 'rate_limited', 'Too many agent runs; try again shortly'))
    renderApp(api({ createAgentRun: create }), '/projects/p1/assistant')
    fireEvent.change(await screen.findByLabelText(/What should be checked/), { target: { value: 'unit tests' } })
    fireEvent.click(screen.getByRole('button', { name: 'Draft a plan' }))
    expect(await screen.findByText('Too many agent runs; try again shortly')).toBeTruthy()
    expect(screen.getByLabelText(/What should be checked/).value).toBe('unit tests')
  })

  it('hides the planner from read-only members', async () => {
    const a = api({ getProject: () => Promise.resolve({ ...project, your_access: 'read' }) })
    renderApp(a, '/projects/p1/assistant')
    expect(await screen.findByText(/You need run access/)).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Draft a plan' })).toBeNull()
  })

  it('explains a degraded run and still shows the trace', async () => {
    const degraded = run({ status: 'degraded', degraded_reason: 'budget_blocked', used_llm: false, plan_id: null, result: { plan_id: null, message: null } })
    renderApp(api({ getAgentRun: vi.fn().mockResolvedValue(degraded) }), '/projects/p1/assistant/ar1')
    expect(await screen.findByText('The model part did not complete')).toBeTruthy()
    expect(screen.getByText(/The model usage limit was reached/)).toBeTruthy()
    expect(screen.getByText('deterministic select')).toBeTruthy()
  })

  it('shows investigation causes as likely or hypothesis, with the standing limit, never as confirmed', async () => {
    const inv = run({
      workflow: 'investigation', plan_id: null,
      result: {
        classification: 'assertion_failure', explanation: 'An assertion did not hold.',
        limitations: 'Nothing was re-run and no cause is confirmed.',
        causes: [{ label: 'likely', statement: 'Tax is ignored.', evidence_ids: ['case:ab12cd34_1'], reproduction_steps: [] }],
      },
    })
    renderApp(api({ getAgentRun: vi.fn().mockResolvedValue(inv) }), '/projects/p1/assistant/ar1')
    expect(await screen.findByText(/Nothing was re-run and no cause is confirmed/)).toBeTruthy()
    expect(screen.getByText('Tax is ignored.', { exact: false })).toBeTruthy()
    expect(screen.queryByText(/confirmed cause/i)).toBeNull()
    expect(screen.getByText(/case:ab12cd34_1/)).toBeTruthy()
  })

  it('renders model text as text, not markup', async () => {
    const hostile = run({ workflow: 'analysis', plan_id: null, result: { output: { summary: '<img src=x onerror=alert(1)> big claim', summary_basis: ['fact:archive'], components: [], trust_boundaries: [], uncertainties: [] } } })
    const { container } = renderApp(api({ getAgentRun: vi.fn().mockResolvedValue(hostile) }), '/projects/p1/assistant/ar1')
    expect(await screen.findByText(/big claim/)).toBeTruthy()
    expect(container.querySelector('img[src="x"]')).toBeNull()
  })
})

describe('finding assistant actions', () => {
  const finding = { id: 'f1', project_id: 'p1', title: 'B602', severity: 'high', confidence: 'medium', verification_state: 'unverified', status: 'new', detected_by: 'bandit', events: [], evidence: [], attempts: [], related: [] }
  it('starts an investigation for the finding and opens the result', async () => {
    const create = vi.fn().mockResolvedValue(run({ workflow: 'investigation', result: { classification: 'scanner_finding', explanation: 'x', limitations: 'y', causes: [] } }))
    const a = api({ getFinding: vi.fn().mockResolvedValue(finding), createAgentRun: create, getAgentRun: vi.fn().mockResolvedValue(run({ workflow: 'investigation', result: { classification: 'scanner_finding', explanation: 'x', limitations: 'y', causes: [] } })) })
    renderApp(a, '/projects/p1/findings/f1')
    fireEvent.click(await screen.findByRole('button', { name: 'Investigate' }))
    await waitFor(() => expect(create).toHaveBeenCalledWith('p1', { workflow: 'investigation', finding_id: 'f1' }))
    expect(await screen.findByText(/scanner finding/)).toBeTruthy()
  })

  it('shows why a draft was refused, as the server worded it', async () => {
    const create = vi.fn().mockRejectedValue(new ApiError(409, 'conflict', 'Not allowed right now'))
    renderApp(api({ getFinding: vi.fn().mockResolvedValue(finding), createAgentRun: create }), '/projects/p1/findings/f1')
    fireEvent.click(await screen.findByRole('button', { name: 'Draft a regression test' }))
    expect(await screen.findByText('Not allowed right now')).toBeTruthy()
  })

  it('offers no assistant to read-only members', async () => {
    const a = api({ getProject: () => Promise.resolve({ ...project, your_access: 'read' }), getFinding: vi.fn().mockResolvedValue(finding) })
    renderApp(a, '/projects/p1/findings/f1')
    await screen.findByText('B602', { selector: 'h1, h2' })
    expect(screen.queryByRole('button', { name: 'Investigate' })).toBeNull()
  })
})

describe('regression proposals', () => {
  it('shows the code as text with the review warnings, and records an acceptance with the note', async () => {
    const decide = vi.fn().mockResolvedValue(proposal({ status: 'accepted', decided_at: '2026-10-24T11:00:00Z', decision_note: 'looks right' }))
    const a = api({ listRegressionProposals: vi.fn().mockResolvedValue([proposal({ risk_flags: ['import os'], overlap: ['test_x'] })]), decideRegressionProposal: decide })
    const { container } = renderApp(a, '/projects/p1/proposals')
    expect(await screen.findByText('Total includes tax')).toBeTruthy()
    expect(screen.getByText(/does not add the test to your project, commit it or run it/)).toBeTruthy()
    expect(screen.getByText(/import os/)).toBeTruthy()
    expect(screen.getByText('test_x')).toBeTruthy()
    expect(container.querySelector('pre').textContent).toContain('<img src=x onerror=alert(1)>')
    expect(container.querySelector('pre img, img[src="x"]')).toBeNull()
    fireEvent.change(screen.getByLabelText('Note (optional)'), { target: { value: 'looks right' } })
    fireEvent.click(screen.getByRole('button', { name: 'Accept' }))
    await waitFor(() => expect(decide).toHaveBeenCalledWith('p1', 'rp1', 'accepted', 'looks right'))
    expect(await screen.findByText('Accepted')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Accept' })).toBeNull()
  })

  it('rejects, and shows a refusal from the server instead of changing the card', async () => {
    const decide = vi.fn().mockRejectedValue(new ApiError(409, 'already_decided', 'This proposal is already accepted'))
    renderApp(api({ listRegressionProposals: vi.fn().mockResolvedValue([proposal()]), decideRegressionProposal: decide }), '/projects/p1/proposals')
    fireEvent.click(await screen.findByRole('button', { name: 'Reject' }))
    expect(await screen.findByText('This proposal is already accepted')).toBeTruthy()
    expect(decide).toHaveBeenCalledWith('p1', 'rp1', 'rejected', '')
    expect(screen.getByText('Proposed')).toBeTruthy()
  })

  it('lets read-only members read but not decide, and explains an empty list', async () => {
    const ro = { ...project, your_access: 'read' }
    renderApp(api({ getProject: () => Promise.resolve(ro), listRegressionProposals: vi.fn().mockResolvedValue([proposal()]) }), '/projects/p1/proposals')
    expect(await screen.findByText('Total includes tax')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Accept' })).toBeNull()
  })

  it('says what to do when there are none', async () => {
    renderApp(api({ listRegressionProposals: vi.fn().mockResolvedValue([]) }), '/projects/p1/proposals')
    expect(await screen.findByText('No proposals yet')).toBeTruthy()
  })
})
