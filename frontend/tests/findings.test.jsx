import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../src/services/api.js'
import { fakeApi, project, renderApp } from './helpers.jsx'

const finding = (over = {}) => ({
  id: 'f1',
  project_id: 'p1',
  title: 'B602: subprocess popen with shell equals true',
  severity: 'high',
  confidence: 'medium',
  verification_state: 'unverified',
  status: 'new',
  detected_by: 'bandit',
  file_path: 'app/db.py',
  line_number: 4,
  group_id: null,
  ...over,
})
const detail = (over = {}) => ({
  ...finding(),
  description: 'subprocess call with shell=True identified',
  rule_id: 'B602',
  occurrences: 2,
  aliases: [],
  limitations: 'Static pattern match; exploitability is not established.',
  events: [{ id: 1, event_type: 'created', from_value: null, to_value: 'new', detail: {}, created_at: '2026-10-20T10:00:00Z' }],
  evidence: [{ artifact_id: 'a1', filename: 'bandit.json', size_bytes: 321, kind: 'report' }],
  attempts: [{ id: 't1', method: 'rescan', outcome: 'fixed', notes: 'No longer reported' }],
  related: [],
  ...over,
})
const api = (over = {}) =>
  fakeApi({
    getProject: () => Promise.resolve(project),
    listFindings: vi.fn().mockResolvedValue([finding()]),
    getFinding: vi.fn().mockResolvedValue(detail()),
    setFindingStatus: vi.fn().mockResolvedValue(detail({ status: 'triaged' })),
    setFindingVerification: vi.fn().mockResolvedValue(detail({ verification_state: 'likely' })),
    getEvidenceText: vi.fn().mockResolvedValue({ text: '<b>{"tool":"bandit"}</b>', truncated: false }),
    ...over,
  })

describe('findings list', () => {
  it('shows scanner output as unverified, with tool confidence kept apart from severity', async () => {
    renderApp(api(), '/projects/p1/findings')
    const link = await screen.findByRole('link', { name: /B602/ })
    expect(link.getAttribute('href')).toBe('/projects/p1/findings/f1')
    const row = link.closest('tr')
    expect(within(row).getByText('High')).toBeTruthy()
    expect(within(row).getByText('Medium')).toBeTruthy() // tool confidence
    expect(within(row).getByText('Unverified')).toBeTruthy()
    expect(within(row).queryByText(/confirmed/i)).toBeNull()
  })

  it('passes status and severity filters to the API and never claims the code is clean when empty', async () => {
    const a = api({ listFindings: vi.fn().mockResolvedValue([]) })
    renderApp(a, '/projects/p1/findings')
    expect(await screen.findByText(/does not mean the code was scanned and found clean/)).toBeTruthy()
    fireEvent.change(screen.getByLabelText('Severity'), { target: { value: 'high' } })
    await waitFor(() => expect(a.listFindings).toHaveBeenLastCalledWith('p1', { status: '', severity: 'high' }))
  })

  it('reports a load failure instead of an empty list', async () => {
    renderApp(api({ listFindings: () => Promise.reject(new ApiError(500, 'error', 'x')) }), '/projects/p1/findings')
    expect(await screen.findByText('Something went wrong on the server')).toBeTruthy()
  })
})

describe('finding detail and review', () => {
  it('shows limitations, evidence as plain text, attempts and history', async () => {
    const a = api()
    renderApp(a, '/projects/p1/findings/f1')
    expect(await screen.findByText(/Static pattern match/)).toBeTruthy()
    expect(screen.getByText(/Automatic re-scan: fixed/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'View bandit.json' }))
    const text = await screen.findByLabelText('Contents of bandit.json')
    expect(text.textContent).toBe('<b>{"tool":"bandit"}</b>')
    expect(text.querySelector('b')).toBeNull()
  })

  it('warns when a finding has no evidence', async () => {
    renderApp(api({ getFinding: () => Promise.resolve(detail({ evidence: [] })) }), '/projects/p1/findings/f1')
    expect(await screen.findByText(/cannot be confirmed/)).toBeTruthy()
  })

  it('offers only real transitions, needs a reason for risk decisions, and needs a real note for a judgement', async () => {
    const a = api()
    renderApp(a, '/projects/p1/findings/f1')
    await screen.findByText(/Static pattern match/)
    const options = within(screen.getByLabelText('Change status')).getAllByRole('option').map((o) => o.value)
    expect(options).toContain('triaged')
    expect(options).not.toContain('reopened') // not a transition from "new"
    fireEvent.change(screen.getByLabelText('Change status'), { target: { value: 'false_positive' } })
    expect(screen.getByRole('button', { name: 'Apply status' }).disabled).toBe(true) // reason required
    fireEvent.change(screen.getByLabelText(/^Reason/), { target: { value: 'Test fixture only' } })
    fireEvent.click(screen.getByRole('button', { name: 'Apply status' }))
    await waitFor(() => expect(a.setFindingStatus).toHaveBeenCalledWith('f1', 'false_positive', 'Test fixture only'))

    fireEvent.change(screen.getByLabelText('My verification judgement'), { target: { value: 'likely' } })
    fireEvent.change(screen.getByLabelText(/^Note/), { target: { value: 'too short' } })
    expect(screen.getByRole('button', { name: 'Record judgement' }).disabled).toBe(true)
    fireEvent.change(screen.getByLabelText(/^Note/), { target: { value: 'Reproduced locally with a crafted input' } })
    fireEvent.click(screen.getByRole('button', { name: 'Record judgement' }))
    await waitFor(() => expect(a.setFindingVerification).toHaveBeenCalledWith('f1', 'likely', 'Reproduced locally with a crafted input'))
  })

  it("shows the server's refusal and leaves the finding as it was", async () => {
    const a = api({ setFindingStatus: vi.fn().mockRejectedValue(new ApiError(403, 'forbidden', 'Only administrators may decide risk')) })
    renderApp(a, '/projects/p1/findings/f1')
    await screen.findByText(/Static pattern match/)
    fireEvent.change(screen.getByLabelText('Change status'), { target: { value: 'triaged' } })
    fireEvent.click(screen.getByRole('button', { name: 'Apply status' }))
    expect((await screen.findByRole('alert')).textContent).toMatch(/Only administrators may decide risk/)
    expect(screen.getAllByText('New').length).toBeGreaterThan(0)
  })
})
