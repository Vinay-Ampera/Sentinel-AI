import { useState } from 'react'
import Alert from '../../components/Alert.jsx'
import Button from '../../components/Button.jsx'
import Dialog from '../../components/Dialog.jsx'
import Field from '../../components/Field.jsx'
import { describeError } from '../../lib/errors.js'
import { ACCESS_LEVELS } from './labels.js'
import './AddMemberDialog.css'

// Finding people uses the user directory, which the server limits to administrators. For
// anyone else it answers 403 and this dialog says so instead of failing silently.
export default function AddMemberDialog({ open, onClose, api, existingIds, onAdd }) {
  const [q, setQ] = useState('')
  const [results, setResults] = useState(null)
  const [searching, setSearching] = useState(false)
  const [level, setLevel] = useState('read')
  const [error, setError] = useState(null)
  const [denied, setDenied] = useState(false)
  const [adding, setAdding] = useState(null)

  async function search(event) {
    event.preventDefault()
    setSearching(true)
    setError(null)
    setDenied(false)
    try {
      setResults(await api.listUsers(q.trim()))
    } catch (e) {
      setResults(null)
      if (e.status === 403) setDenied(true)
      else setError(describeError(e).message)
    } finally {
      setSearching(false)
    }
  }

  async function add(user) {
    setAdding(user.id)
    setError(null)
    try {
      await onAdd(user, level)
    } catch (e) {
      setError(describeError(e).message)
    } finally {
      setAdding(null)
    }
  }

  const candidates = (results || []).filter((u) => u.is_active !== false && !existingIds.has(u.id))
  return (
    <Dialog open={open} onClose={onClose} title="Add a member" footer={<Button onClick={onClose}>Close</Button>}>
      {denied && <Alert tone="warning" title="You cannot search users">Only administrators can search the user directory. Ask an administrator to add the person to this project.</Alert>}
      {error && <Alert tone="danger">{error}</Alert>}
      <form onSubmit={search} role="search" aria-label="Find a user">
        <Field label="Name or email" value={q} onChange={(e) => setQ(e.target.value)} />
        <Button type="submit" loading={searching} loadingLabel="Searching…">Search</Button>
      </form>
      <Field as="select" label="Access level to grant" hint={ACCESS_LEVELS[level].note} value={level} onChange={(e) => setLevel(e.target.value)}>
        {Object.entries(ACCESS_LEVELS).map(([value, a]) => <option key={value} value={value}>{a.label}</option>)}
      </Field>
      {results && candidates.length === 0 && <p className="muted">No matching people who are not already members.</p>}
      {candidates.length > 0 && (
        <ul className="member-results">
          {candidates.map((u) => (
            <li key={u.id}>
              <span><strong>{u.display_name}</strong> <span className="muted">{u.email}</span></span>
              <Button size="sm" variant="primary" loading={adding === u.id} loadingLabel="Adding…" onClick={() => add(u)} aria-label={`Add ${u.display_name}`}>Add</Button>
            </li>
          ))}
        </ul>
      )}
    </Dialog>
  )
}
