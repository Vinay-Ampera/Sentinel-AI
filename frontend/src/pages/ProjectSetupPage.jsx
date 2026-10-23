import { useCallback, useState } from 'react'
import { useOutletContext } from 'react-router-dom'
import Button from '../components/Button.jsx'
import Card from '../components/Card.jsx'
import { ConfirmDialog } from '../components/Dialog.jsx'
import { DataState } from '../components/states.jsx'
import AddMemberDialog from '../features/projects/AddMemberDialog.jsx'
import AddSourceForm from '../features/projects/AddSourceForm.jsx'
import MemberList from '../features/projects/MemberList.jsx'
import SourceList from '../features/projects/SourceList.jsx'
import { useApi } from '../hooks/useApi.js'
import { useLoad } from '../hooks/useLoad.js'
import { useToast } from '../hooks/useToast.js'
import { describeError } from '../lib/errors.js'

// Sources, members and archiving. Which of these a person may do is decided by the server;
// refusals (403) are shown in place.
export default function ProjectSetupPage() {
  const { project, reloadProject } = useOutletContext()
  const api = useApi()
  const { notify } = useToast()
  const pid = project.id
  const archived = project.status === 'archived'
  const [sources, reloadSources] = useLoad(useCallback(() => api.listSources(pid), [api, pid]))
  const [members, reloadMembers] = useLoad(useCallback(() => api.listMembers(pid), [api, pid]))
  const [adding, setAdding] = useState(false)
  const [archiving, setArchiving] = useState(false)

  async function addZip(name, file) {
    await api.uploadZipSource(pid, name, file)
    notify({ tone: 'success', title: 'Source added', message: name })
    reloadSources()
  }
  async function addUrl(body) {
    await api.addUrlSource(pid, body)
    notify({ tone: 'success', title: 'Source recorded', message: `${body.name} (not contacted)` })
    reloadSources()
  }
  async function removeSource(source) {
    await api.removeSource(pid, source.id)
    notify({ tone: 'success', title: 'Source removed', message: source.name })
    reloadSources()
  }
  async function changeLevel(member, level) {
    try {
      await api.setMember(pid, member.user_id, level)
      notify({ tone: 'success', title: 'Access updated', message: `${member.display_name}: ${level}` })
    } catch (e) {
      notify({ tone: 'danger', title: 'Could not change access', message: describeError(e).message })
    }
    reloadMembers()
  }
  async function removeMember(member) {
    await api.removeMember(pid, member.user_id)
    notify({ tone: 'success', title: 'Member removed', message: member.display_name })
    reloadMembers()
  }
  async function addMember(user, level) {
    await api.setMember(pid, user.id, level)
    notify({ tone: 'success', title: 'Member added', message: user.display_name })
    reloadMembers()
  }

  return (
    <>
      <Card title="Sources">
        <DataState state={sources} onRetry={reloadSources} what="this project's sources" loadingLabel="Loading sources…" isEmpty={() => false}>
          {(items) => <SourceList sources={items} onRemove={removeSource} />}
        </DataState>
        {!archived && <AddSourceForm onAddZip={addZip} onAddUrl={addUrl} />}
      </Card>

      <Card title="Members" actions={!archived && <Button size="sm" onClick={() => setAdding(true)}>Add member</Button>}>
        <DataState state={members} onRetry={reloadMembers} what="this project's members" loadingLabel="Loading members…" isEmpty={() => false}>
          {(items) => <MemberList members={items} onChangeLevel={changeLevel} onRemove={removeMember} />}
        </DataState>
        <AddMemberDialog
          open={adding}
          onClose={() => setAdding(false)}
          api={api}
          existingIds={new Set((members.data || []).map((m) => m.user_id))}
          onAdd={addMember}
        />
      </Card>

      {!archived && (
        <Card title="Archive this project">
          <p className="muted">Archiving keeps the history but stops new sources, plans and runs. This cannot be undone from here.</p>
          <Button variant="danger" onClick={() => setArchiving(true)}>Archive project</Button>
          <ConfirmDialog
            open={archiving}
            onClose={() => setArchiving(false)}
            title="Archive this project?"
            confirmLabel="Archive project"
            danger
            onConfirm={async () => {
              await api.archiveProject(pid)
              notify({ tone: 'success', title: 'Project archived', message: project.name })
              setArchiving(false)
              reloadProject()
            }}
          >
            <p>{`"${project.name}" will be archived.`}</p>
          </ConfirmDialog>
        </Card>
      )}
    </>
  )
}
