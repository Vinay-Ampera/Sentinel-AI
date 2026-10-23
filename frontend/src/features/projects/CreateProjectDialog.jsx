import { useState } from 'react'
import Alert from '../../components/Alert.jsx'
import Button from '../../components/Button.jsx'
import Dialog from '../../components/Dialog.jsx'
import Field from '../../components/Field.jsx'
import { describeError, fieldErrors } from '../../lib/errors.js'
import { APPLICATION_TYPES } from './labels.js'

export default function CreateProjectDialog({ open, onClose, onCreate }) {
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [type, setType] = useState('')
  const [touched, setTouched] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [serverFields, setServerFields] = useState({})

  const missing = { name: !name.trim(), type: !type }

  async function submit(event) {
    event.preventDefault()
    setTouched(true)
    if (missing.name || missing.type) return
    setBusy(true)
    setError(null)
    setServerFields({})
    try {
      await onCreate({ name: name.trim(), description: description.trim() || null, application_type: type })
      setName('')
      setDescription('')
      setType('')
      setTouched(false)
    } catch (e) {
      const fields = fieldErrors(e)
      setServerFields(fields)
      if (Object.keys(fields).length === 0) setError(describeError(e).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="New project"
      footer={
        <>
          <Button onClick={onClose} disabled={busy}>Cancel</Button>
          <Button type="submit" form="create-project-form" variant="primary" loading={busy} loadingLabel="Creating…">Create project</Button>
        </>
      }
    >
      <form id="create-project-form" onSubmit={submit} noValidate>
        {error && <Alert tone="danger" title="Could not create the project">{error}</Alert>}
        <Field label="Name" value={name} onChange={(e) => setName(e.target.value)} maxLength={200} required error={(touched && missing.name && 'Enter a project name.') || serverFields.name} />
        <Field as="textarea" label="Description" hint="Optional" value={description} onChange={(e) => setDescription(e.target.value)} maxLength={5000} error={serverFields.description} />
        <Field
          as="select"
          label="Application type"
          hint="Used to choose relevant checks. You can see what the analysis detects later."
          value={type}
          onChange={(e) => setType(e.target.value)}
          required
          error={(touched && missing.type && 'Choose an application type.') || serverFields.application_type}
        >
          <option value="">Select…</option>
          {Object.entries(APPLICATION_TYPES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </Field>
      </form>
    </Dialog>
  )
}
