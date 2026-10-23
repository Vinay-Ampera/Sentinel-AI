import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import FindingsPanel from '../src/features/findings/FindingsPanel.jsx'

afterEach(cleanup)

const finding = (over = {}) => ({
  id: 'f1',
  title: 'B602: subprocess popen with shell equals true',
  severity: 'high',
  confidence: 'medium',
  verification_state: 'unverified',
  status: 'new',
  file_path: 'app/db.py',
  line_number: 4,
  ...over,
})
const detail = (over = {}) => ({
  ...finding(),
  description: 'subprocess call with shell=True identified',
  detected_by: 'bandit',
  rule_id: 'B602',
  occurrences: 2,
  limitations: 'Static pattern match; exploitability is not established.',
  events: [{ id: 1, event_type: 'created', from_value: null, to_value: 'new', detail: {} }],
  evidence: [{ artifact_id: 'a1', filename: 'bandit.json', size_bytes: 321, kind: 'report' }],
  attempts: [{ id: 't1', method: 'rescan', outcome: 'fixed', notes: 'No longer reported' }],
  ...over,
})
const fakeApi = (over = {}) => ({
  listFindings: vi.fn().mockResolvedValue([finding()]),
  getFinding: vi.fn().mockResolvedValue(detail()),
  setFindingStatus: vi.fn().mockResolvedValue(detail({ status: 'triaged' })),
  setFindingVerification: vi.fn().mockResolvedValue(detail({ verification_state: 'likely' })),
  getEvidenceText: vi.fn().mockResolvedValue({ text: '{"tool":"bandit"}', truncated: false }),
  ...over,
})
const show = (api) => render(<FindingsPanel api={api} projectId="proj" />)

describe('FindingsPanel', () => {
  it('shows scanner output as unverified, with confidence kept apart from severity', async () => {
    show(fakeApi())
    expect(screen.getByRole('status').textContent).toMatch(/loading findings/i)
    const list = await screen.findByRole('list', { name: 'Findings' })
    expect(within(list).getByText('High severity')).toBeTruthy()
    expect(within(list).getByText('Medium confidence')).toBeTruthy()
    expect(within(list).getByText('Unverified')).toBeTruthy()
    expect(screen.queryByText(/confirmed/i, { selector: '.badge' })).toBeNull()
    expect(screen.getByText(/never marks a finding confirmed/i)).toBeTruthy()
  })

  it('says so when there are no findings, without claiming the code is secure', async () => {
    show(fakeApi({ listFindings: vi.fn().mockResolvedValue([]) }))
    expect(await screen.findByText(/no findings\. run a security scan/i)).toBeTruthy()
    expect(screen.queryByText(/is secure$/i)).toBeNull()
  })

  it('shows limitations, evidence, automatic re-scan attempts and history, and opens evidence as text', async () => {
    const api = fakeApi()
    show(api)
    fireEvent.click(await screen.findByRole('button', { name: 'Show details' }))
    expect(await screen.findByText(/exploitability is not established/i)).toBeTruthy()
    expect(screen.getByText(/Automatic re-scan: fixed — No longer reported/)).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'View bandit.json' }))
    expect((await screen.findByLabelText('Contents of bandit.json')).textContent).toBe('{"tool":"bandit"}')
    expect(api.getEvidenceText).toHaveBeenCalledWith('a1')
  })

  it('warns when a finding has no evidence and requires a real note for a judgement', async () => {
    const api = fakeApi({ getFinding: vi.fn().mockResolvedValue(detail({ evidence: [] })) })
    show(api)
    fireEvent.click(await screen.findByRole('button', { name: 'Show details' }))
    expect(await screen.findByText(/cannot be confirmed/i)).toBeTruthy()
    const record = screen.getByRole('button', { name: 'Record judgement' })
    fireEvent.change(screen.getByLabelText('My verification judgement'), { target: { value: 'likely' } })
    fireEvent.change(screen.getByLabelText(/Note \(at least 10/), { target: { value: 'too short' } })
    expect(record.disabled).toBe(true)
    fireEvent.change(screen.getByLabelText(/Note \(at least 10/), { target: { value: 'Reproduced locally by hand' } })
    expect(record.disabled).toBe(false)
    fireEvent.click(record)
    await waitFor(() => expect(api.setFindingVerification).toHaveBeenCalledWith('f1', 'likely', 'Reproduced locally by hand'))
  })

  it('offers only transitions that exist and asks for a reason on risk decisions', async () => {
    const api = fakeApi()
    show(api)
    fireEvent.click(await screen.findByRole('button', { name: 'Show details' }))
    const select = await screen.findByLabelText('Change status')
    const options = within(select).getAllByRole('option').map((o) => o.value)
    expect(options).toEqual(['', 'triaged', 'in_progress', 'fixed', 'false_positive', 'accepted_risk'])
    expect(options).not.toContain('verified_fixed') // only a later scan can verify a fix
    fireEvent.change(select, { target: { value: 'false_positive' } })
    expect(screen.getByLabelText(/Reason \(required/)).toBeTruthy()
    fireEvent.change(select, { target: { value: 'triaged' } })
    fireEvent.click(screen.getByRole('button', { name: 'Apply status' }))
    await waitFor(() => expect(api.setFindingStatus).toHaveBeenCalledWith('f1', 'triaged', ''))
  })

  it('shows the server refusal and keeps the finding as it was', async () => {
    const api = fakeApi({
      setFindingStatus: vi.fn().mockRejectedValue(new Error('Marking a finding a false positive needs an administrator')),
    })
    show(api)
    fireEvent.click(await screen.findByRole('button', { name: 'Show details' }))
    fireEvent.change(await screen.findByLabelText('Change status'), { target: { value: 'false_positive' } })
    fireEvent.change(screen.getByLabelText(/Reason \(required/), { target: { value: 'Test fixture only' } })
    fireEvent.click(screen.getByRole('button', { name: 'Apply status' }))
    expect((await screen.findByRole('alert')).textContent).toMatch(/needs an administrator/)
    expect(screen.getAllByText('New').length).toBeGreaterThan(0)
  })

  it('reports a load failure instead of an empty list', async () => {
    show(fakeApi({ listFindings: vi.fn().mockRejectedValue(new Error('Could not reach the server')) }))
    expect((await screen.findByRole('alert')).textContent).toMatch(/could not reach the server/i)
    expect(screen.queryByText(/no findings/i)).toBeNull()
  })

  it('filters by status through the API', async () => {
    const api = fakeApi()
    show(api)
    await screen.findByRole('list', { name: 'Findings' })
    fireEvent.change(screen.getByLabelText('Show'), { target: { value: 'reopened' } })
    await waitFor(() => expect(api.listFindings).toHaveBeenLastCalledWith('proj', { status: 'reopened' }))
  })

  it('shows which tool reported a finding and links duplicates without merging them', async () => {
    const api = fakeApi({
      listFindings: vi.fn().mockResolvedValue([
        finding({ detected_by: 'semgrep', group_id: 'g1', cwe: 78 }),
        finding({ id: 'f2', title: 'django 3.0.0: PYSEC-1', detected_by: 'dependency_audit', component: 'pypi:django@3.0.0', file_path: 'poetry.lock', line_number: null }),
      ]),
      getFinding: vi.fn().mockResolvedValue(
        detail({
          detected_by: 'semgrep',
          group_id: 'g1',
          cwe: 78,
          aliases: ['PYSEC-1', 'CVE-2024-1'],
          related: [{ id: 'f9', detected_by: 'bandit', title: 'B602: shell', status: 'triaged', file_path: 'app/db.py', line_number: 5 }],
        }),
      ),
    })
    show(api)
    const list = await screen.findByRole('list', { name: 'Findings' })
    expect(within(list).getByText('semgrep')).toBeTruthy()
    expect(within(list).getByText('Linked duplicate')).toBeTruthy()
    expect(within(list).getByText(/pypi:django@3\.0\.0/)).toBeTruthy()
    fireEvent.click(within(list).getAllByRole('button', { name: 'Show details' })[0])
    const related = await screen.findByRole('list', { name: 'Related findings' })
    expect(within(related).getByText(/bandit: B602: shell/)).toBeTruthy()
    expect(screen.getByText(/linked, not merged/i)).toBeTruthy()
    expect(screen.getByText(/CVE-2024-1/)).toBeTruthy()
  })
})
