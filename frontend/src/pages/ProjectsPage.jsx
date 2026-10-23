import { useCallback, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Button from '../components/Button.jsx'
import PageHeader from '../components/PageHeader.jsx'
import { DataState, EmptyState } from '../components/states.jsx'
import { useToast } from '../hooks/useToast.js'
import CreateProjectDialog from '../features/projects/CreateProjectDialog.jsx'
import ProjectList from '../features/projects/ProjectList.jsx'
import { useApi } from '../hooks/useApi.js'
import { useLoad } from '../hooks/useLoad.js'
import './ProjectsPage.css'

export default function ProjectsPage() {
  const api = useApi()
  const navigate = useNavigate()
  const { notify } = useToast()
  const [showArchived, setShowArchived] = useState(false)
  const [creating, setCreating] = useState(false)
  const [state, reload] = useLoad(useCallback(() => api.listProjects(showArchived), [api, showArchived]))

  async function create(body) {
    const project = await api.createProject(body)
    notify({ tone: 'success', title: 'Project created', message: project.name })
    setCreating(false)
    navigate(`/projects/${project.id}`)
  }

  return (
    <>
      <PageHeader
        title="Projects"
        description="The applications you test with Sentinel AI."
        actions={<Button variant="primary" onClick={() => setCreating(true)}>New project</Button>}
      />
      <label className="projects-filter">
        <input type="checkbox" checked={showArchived} onChange={(e) => setShowArchived(e.target.checked)} /> Show archived projects
      </label>
      <DataState
        state={state}
        onRetry={reload}
        what="projects"
        loadingLabel="Loading projects…"
        empty={<EmptyState title="No projects yet" action={<Button variant="primary" onClick={() => setCreating(true)}>Create your first project</Button>}>A project holds the sources, analyses, test plans, runs and findings for one application.</EmptyState>}
      >
        {(projects) => <ProjectList projects={projects} />}
      </DataState>
      <CreateProjectDialog open={creating} onClose={() => setCreating(false)} onCreate={create} />
    </>
  )
}
