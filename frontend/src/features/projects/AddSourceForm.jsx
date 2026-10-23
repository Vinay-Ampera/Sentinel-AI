import { useRef, useState } from 'react'
import Alert from '../../components/Alert.jsx'
import Button from '../../components/Button.jsx'
import Field from '../../components/Field.jsx'
import { describeError, fieldErrors } from '../../lib/errors.js'
import { REMOTE_ENVIRONMENTS, SOURCE_TYPES } from './labels.js'
import './AddSourceForm.css'

// One form for every source kind. A ZIP is uploaded as-is and inspected by the server (never
// opened in the browser). The other kinds are descriptors only: nothing is contacted.
export default function AddSourceForm({ onAddZip, onAddUrl }) {
  const [type, setType] = useState('zip_upload')
  const [name, setName] = useState('')
  const [gitUrl, setGitUrl] = useState('')
  const [gitRef, setGitRef] = useState('')
  const [targetUrl, setTargetUrl] = useState('')
  const [environment, setEnvironment] = useState('dev')
  const [file, setFile] = useState(null)
  const [touched, setTouched] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [serverFields, setServerFields] = useState({})
  const fileInput = useRef(null)

  const needs = {
    name: !name.trim(),
    file: type === 'zip_upload' && !file,
    gitUrl: type === 'git_repository' && !gitUrl.trim(),
    targetUrl: (type === 'localhost_url' || type === 'remote_url') && !targetUrl.trim(),
  }

  function pickFile(event) {
    const chosen = event.target.files && event.target.files[0]
    setFile(chosen || null)
    if (chosen && !name.trim()) setName(chosen.name.replace(/\.zip$/i, ''))
  }

  function reset() {
    setName('')
    setGitUrl('')
    setGitRef('')
    setTargetUrl('')
    setFile(null)
    setTouched(false)
    if (fileInput.current) fileInput.current.value = ''
  }

  async function submit(event) {
    event.preventDefault()
    setTouched(true)
    if (Object.values(needs).some(Boolean)) return
    setBusy(true)
    setError(null)
    setServerFields({})
    try {
      if (type === 'zip_upload') await onAddZip(name.trim(), file)
      else if (type === 'git_repository') await onAddUrl({ source_type: type, name: name.trim(), git_url: gitUrl.trim(), git_ref: gitRef.trim() || null })
      else if (type === 'localhost_url') await onAddUrl({ source_type: type, name: name.trim(), target_url: targetUrl.trim() })
      else await onAddUrl({ source_type: type, name: name.trim(), target_url: targetUrl.trim(), environment })
      reset()
    } catch (e) {
      const fields = fieldErrors(e)
      setServerFields(fields)
      if (Object.keys(fields).length === 0) setError(describeError(e).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} noValidate aria-labelledby="add-source-title" className="add-source">
      <h3 id="add-source-title">Add a source</h3>
      {error && <Alert tone="danger" title="Could not add the source">{error}</Alert>}
      <Field as="select" label="Source type" value={type} onChange={(e) => { setType(e.target.value); setServerFields({}); setError(null) }}>
        {Object.entries(SOURCE_TYPES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
      </Field>
      {type === 'zip_upload' && (
        <Field
          label="ZIP file"
          type="file"
          accept=".zip,application/zip"
          ref={fileInput}
          onChange={pickFile}
          hint="The archive is checked and inspected on the server. It is not opened here and nothing in it is run."
          required
          error={touched && needs.file ? 'Choose a ZIP file.' : undefined}
        />
      )}
      {type === 'git_repository' && (
        <>
          <Field label="Repository URL" value={gitUrl} onChange={(e) => setGitUrl(e.target.value)} required error={(touched && needs.gitUrl && 'Enter the repository URL.') || serverFields.git_url} />
          <Field label="Branch, tag or commit" hint="Optional" value={gitRef} onChange={(e) => setGitRef(e.target.value)} error={serverFields.git_ref} />
        </>
      )}
      {(type === 'localhost_url' || type === 'remote_url') && (
        <Field label="Target URL" value={targetUrl} onChange={(e) => setTargetUrl(e.target.value)} required error={(touched && needs.targetUrl && 'Enter the target URL.') || serverFields.target_url} />
      )}
      {type === 'remote_url' && (
        <Field as="select" label="Environment" hint="Production targets are refused." value={environment} onChange={(e) => setEnvironment(e.target.value)}>
          {REMOTE_ENVIRONMENTS.map((env) => <option key={env} value={env}>{env}</option>)}
        </Field>
      )}
      <Field label="Name" hint="Shown in lists and plans" value={name} onChange={(e) => setName(e.target.value)} maxLength={200} required error={(touched && needs.name && 'Enter a name.') || serverFields.name} />
      {type !== 'zip_upload' && <p className="muted">Registering records the details only. It does not contact the target.</p>}
      <Button type="submit" variant="primary" loading={busy} loadingLabel={type === 'zip_upload' ? 'Uploading…' : 'Adding…'}>Add source</Button>
    </form>
  )
}
