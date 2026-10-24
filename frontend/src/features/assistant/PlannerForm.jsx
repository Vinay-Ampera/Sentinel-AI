import { useState } from 'react'
import Alert from '../../components/Alert.jsx'
import Button from '../../components/Button.jsx'
import Field from '../../components/Field.jsx'
import { describeError } from '../../lib/errors.js'
import './PlannerForm.css'

// Asks the assistant to draft a test plan from a free-text request. Built-in keyword matching
// runs first; the model is used only when no keyword matches. The result is a draft plan that
// still goes through the normal review, submit and approval steps.
export default function PlannerForm({ projectId, api, onCreated }) {
  const [prompt, setPrompt] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  async function submit(event) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const run = await api.createAgentRun(projectId, { workflow: 'planning', prompt: prompt.trim() })
      setPrompt('')
      onCreated(run)
    } catch (e) {
      setError(e.status === 422 || e.status === 429 || e.status === 403 || e.status === 409 ? e.message : describeError(e).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="planner-form" onSubmit={submit}>
      {error && <Alert tone="danger" title="The request was not made">{error}</Alert>}
      <Field
        as="textarea"
        label="What should be checked?"
        hint="For example: check my dependencies for known vulnerabilities and add unit tests. Do not paste secrets: text is filtered before it leaves the server, but that is best effort."
        rows={3}
        maxLength={2000}
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        required
      />
      <Button type="submit" variant="primary" loading={busy} loadingLabel="Asking…" disabled={!prompt.trim()} disabledReason="Describe what should be checked">
        Draft a plan
      </Button>
    </form>
  )
}
