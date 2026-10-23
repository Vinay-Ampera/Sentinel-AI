import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { useState } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import Button from '../src/components/Button.jsx'
import DataTable from '../src/components/DataTable.jsx'
import Dialog, { ConfirmDialog } from '../src/components/Dialog.jsx'
import EvidenceViewer from '../src/components/EvidenceViewer.jsx'
import Field from '../src/components/Field.jsx'
import PageHeader from '../src/components/PageHeader.jsx'
import Pagination from '../src/components/Pagination.jsx'
import StatusBadge from '../src/components/StatusBadge.jsx'
import TabNav from '../src/components/TabNav.jsx'
import { ToastProvider } from '../src/components/Toast.jsx'
import { useToast } from '../src/hooks/useToast.js'
import { DataState, ErrorState, PermissionDenied } from '../src/components/states.jsx'
import { usePagination } from '../src/hooks/usePagination.js'
import { ApiError } from '../src/services/api.js'
import { describedBy } from './helpers.jsx'

describe('Button', () => {
  it('explains why it is disabled', () => {
    render(<Button disabled disabledReason="Select a project first">Start</Button>)
    const button = screen.getByRole('button', { name: 'Start' })
    expect(button.disabled).toBe(true)
    expect(describedBy(button)).toBe('Select a project first')
  })

  it('is disabled and busy while loading, showing the loading label', () => {
    render(<Button loading loadingLabel="Saving…">Save</Button>)
    const button = screen.getByRole('button', { name: 'Saving…' })
    expect(button.disabled).toBe(true)
    expect(button.getAttribute('aria-busy')).toBe('true')
  })
})

describe('StatusBadge', () => {
  it('shows text, not just colour', () => {
    render(<StatusBadge domain="result" value="failed_to_start" showNote />)
    expect(screen.getByText('Could not start')).toBeTruthy()
    expect(screen.getByText(/not a test failure/)).toBeTruthy()
  })
})

describe('Field', () => {
  it('binds label, hint and error to the control', () => {
    render(<Field label="Email" hint="Work address" error="Enter a valid email" required />)
    const input = screen.getByLabelText(/Email/)
    expect(input.getAttribute('aria-invalid')).toBe('true')
    expect(describedBy(input)).toBe('Work address Enter a valid email')
    expect(input.required).toBe(true)
  })
})

describe('Dialog', () => {
  function Host({ onClose = () => {} }) {
    return (
      <>
        <button type="button">opener</button>
        <Dialog open onClose={onClose} title="Example" footer={<button type="button">last</button>}>
          <input aria-label="first field" />
        </Dialog>
      </>
    )
  }

  it('is a labelled modal, moves focus in, and closes on Escape', () => {
    const onClose = vi.fn()
    render(<Host onClose={onClose} />)
    const dialog = screen.getByRole('dialog', { name: 'Example' })
    expect(dialog.getAttribute('aria-modal')).toBe('true')
    expect(document.activeElement).toBe(within(dialog).getByLabelText('first field'))
    fireEvent.keyDown(dialog, { key: 'Escape' })
    expect(onClose).toHaveBeenCalled()
  })

  it('keeps Tab inside the dialog', () => {
    render(<Host />)
    const dialog = screen.getByRole('dialog')
    screen.getByRole('button', { name: 'last' }).focus()
    fireEvent.keyDown(dialog, { key: 'Tab' })
    expect(document.activeElement).toBe(within(dialog).getByLabelText('first field'))
    fireEvent.keyDown(dialog, { key: 'Tab', shiftKey: true })
    expect(document.activeElement).toBe(screen.getByRole('button', { name: 'last' }))
  })

  it('returns focus to the opener when it closes', () => {
    function ToggleHost() {
      const [open, setOpen] = useState(false)
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>open it</button>
          <Dialog open={open} onClose={() => setOpen(false)} title="Example"><button type="button">inside</button></Dialog>
        </>
      )
    }
    render(<ToggleHost />)
    const opener = screen.getByRole('button', { name: 'open it' })
    opener.focus()
    fireEvent.click(opener)
    expect(screen.getByRole('dialog')).toBeTruthy()
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(document.activeElement).toBe(opener)
  })
})

describe('ConfirmDialog', () => {
  it('keeps confirm disabled, with a reason, until a required reason is entered', async () => {
    const onConfirm = vi.fn().mockResolvedValue()
    render(<ConfirmDialog open onClose={() => {}} title="Reject plan" confirmLabel="Reject" danger requireReason onConfirm={onConfirm} />)
    const confirm = screen.getByRole('button', { name: 'Reject' })
    expect(confirm.disabled).toBe(true)
    expect(describedBy(confirm)).toBe('Enter a reason to continue')
    fireEvent.change(screen.getByLabelText(/Reason/), { target: { value: '  too risky ' } })
    expect(confirm.disabled).toBe(false)
    fireEvent.click(confirm)
    await waitFor(() => expect(onConfirm).toHaveBeenCalledWith('too risky'))
  })

  it('shows an error from the action inline and stays open', async () => {
    const onClose = vi.fn()
    render(<ConfirmDialog open onClose={onClose} title="Revoke" onConfirm={() => Promise.reject(new Error('Already revoked'))} />)
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }))
    expect((await screen.findByRole('alert')).textContent).toBe('Already revoked')
    expect(onClose).not.toHaveBeenCalled()
  })
})

describe('Toast', () => {
  function Trigger() {
    const { notify } = useToast()
    return (
      <>
        <button type="button" onClick={() => notify({ tone: 'success', title: 'Saved' })}>ok</button>
        <button type="button" onClick={() => notify({ tone: 'danger', title: 'Failed' })}>bad</button>
      </>
    )
  }

  it('announces success politely and errors assertively; each can be dismissed', () => {
    render(<ToastProvider><Trigger /></ToastProvider>)
    fireEvent.click(screen.getByText('ok'))
    fireEvent.click(screen.getByText('bad'))
    expect(screen.getByRole('status').textContent).toMatch(/Saved/)
    expect(screen.getByRole('alert').textContent).toMatch(/Failed/)
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss: Failed' }))
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('auto-dismisses success but keeps errors', () => {
    vi.useFakeTimers()
    render(<ToastProvider><Trigger /></ToastProvider>)
    fireEvent.click(screen.getByText('ok'))
    fireEvent.click(screen.getByText('bad'))
    act(() => vi.advanceTimersByTime(9000))
    vi.useRealTimers()
    expect(screen.queryByRole('status')).toBeNull()
    expect(screen.getByRole('alert')).toBeTruthy()
  })
})

describe('states', () => {
  const loaded = (over) => ({ loading: false, error: null, data: [1], ...over })

  it('DataState shows loading, then content', () => {
    const { rerender } = render(<DataState state={{ loading: true }}>{() => <p>content</p>}</DataState>)
    expect(screen.getByRole('status').textContent).toMatch(/Loading/)
    rerender(<DataState state={loaded()}>{() => <p>content</p>}</DataState>)
    expect(screen.getByText('content')).toBeTruthy()
  })

  it('DataState shows the empty state for an empty list', () => {
    render(<DataState state={loaded({ data: [] })} empty={<p>nothing yet</p>}>{() => <p>content</p>}</DataState>)
    expect(screen.getByText('nothing yet')).toBeTruthy()
  })

  it('DataState turns a 403 into permission denied, not a generic error', () => {
    render(<DataState state={loaded({ data: null, error: new ApiError(403, 'forbidden', 'no') })} what="governance">{() => null}</DataState>)
    expect(screen.getByRole('alert').textContent).toMatch(/do not have access to governance/)
  })

  it('ErrorState offers retry only where retrying can help', () => {
    const retry = vi.fn()
    const { rerender } = render(<ErrorState error={new ApiError(0, 'network_error', 'x')} onRetry={retry} />)
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(retry).toHaveBeenCalled()
    rerender(<ErrorState error={new ApiError(422, 'validation_failed', 'bad')} onRetry={retry} />)
    expect(screen.queryByRole('button')).toBeNull()
  })

  it('PermissionDenied explains rather than hides', () => {
    render(<PermissionDenied what="admin users" />)
    expect(screen.getByRole('alert').textContent).toMatch(/Ask a project owner or an administrator/)
  })
})

describe('DataTable and Pagination', () => {
  const columns = [{ key: 'name', header: 'Name' }]

  it('renders a captioned table in a focusable scroll region', () => {
    render(<DataTable caption="Results" columns={columns} rows={[{ id: 1, name: 'alpha' }]} getRowKey={(r) => r.id} />)
    const region = screen.getByRole('region', { name: 'Results table' })
    expect(region.tabIndex).toBe(0)
    expect(within(region).getByRole('table')).toBeTruthy()
    expect(within(region).getByRole('columnheader', { name: 'Name' })).toBeTruthy()
  })

  it('shows the provided empty state instead of an empty table', () => {
    render(<DataTable caption="Results" columns={columns} rows={[]} getRowKey={(r) => r.id} empty={<p>no rows</p>} />)
    expect(screen.getByText('no rows')).toBeTruthy()
    expect(screen.queryByRole('table')).toBeNull()
  })

  it('pages through items and disables the ends', () => {
    function Host() {
      const p = usePagination([1, 2, 3, 4, 5], 2)
      return (
        <>
          <p data-testid="items">{p.pageItems.join(',')}</p>
          <Pagination page={p.page} pageCount={p.pageCount} onPageChange={p.setPage} />
        </>
      )
    }
    render(<Host />)
    expect(screen.getByTestId('items').textContent).toBe('1,2')
    expect(screen.getByRole('button', { name: 'Previous' }).disabled).toBe(true)
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(screen.getByTestId('items').textContent).toBe('3,4')
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(screen.getByRole('button', { name: 'Next' }).disabled).toBe(true)
    expect(screen.getByText('Page 3 of 3')).toBeTruthy()
  })

  it('renders nothing when there is a single page', () => {
    render(<Pagination page={1} pageCount={1} onPageChange={() => {}} />)
    expect(screen.queryByRole('navigation')).toBeNull()
  })
})

describe('EvidenceViewer', () => {
  it('renders evidence as plain text, never as HTML', () => {
    const { container } = render(<EvidenceViewer name="a.log" text="<img src=x onerror=alert(1)>" />)
    expect(container.querySelector('img')).toBeNull()
    expect(screen.getByLabelText('Contents of a.log').textContent).toBe('<img src=x onerror=alert(1)>')
    expect(screen.getByText(/not verified by Sentinel AI/)).toBeTruthy()
  })

  it('truncates long text with a notice and can show all of it', () => {
    render(<EvidenceViewer name="big.log" text={'x'.repeat(50)} limit={10} />)
    expect(screen.getByLabelText('Contents of big.log').textContent).toHaveLength(10)
    fireEvent.click(screen.getByRole('button', { name: 'Show full text' }))
    expect(screen.getByLabelText('Contents of big.log').textContent).toHaveLength(50)
  })

  it('says so when the file is empty', () => {
    render(<EvidenceViewer name="e.log" text="" />)
    expect(screen.getByText('This evidence file is empty.')).toBeTruthy()
  })
})

describe('navigation components', () => {
  it('TabNav marks the current page and PageHeader sets the title and breadcrumb', () => {
    render(
      <MemoryRouter initialEntries={['/p/overview']}>
        <PageHeader title="Overview" breadcrumbs={[{ to: '/', label: 'Projects' }, { label: 'Overview' }]} />
        <TabNav label="Project sections" items={[{ to: '/p/overview', label: 'Overview' }, { to: '/p/runs', label: 'Runs' }]} />
      </MemoryRouter>,
    )
    expect(screen.getByRole('heading', { level: 1, name: 'Overview' })).toBeTruthy()
    expect(document.title).toBe('Overview · Sentinel AI')
    expect(within(screen.getByRole('navigation', { name: 'Project sections' })).getByRole('link', { name: 'Overview' }).getAttribute('aria-current')).toBe('page')
    expect(within(screen.getByRole('navigation', { name: 'Breadcrumb' })).getByText('Overview').getAttribute('aria-current')).toBe('page')
  })
})
