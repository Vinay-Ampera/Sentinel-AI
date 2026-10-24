import { useCallback } from 'react'
import { Outlet, useParams } from 'react-router-dom'
import Alert from '../components/Alert.jsx'
import PageHeader from '../components/PageHeader.jsx'
import StatusBadge from '../components/StatusBadge.jsx'
import TabNav from '../components/TabNav.jsx'
import { DataState } from '../components/states.jsx'
import { useApi } from '../hooks/useApi.js'
import { useLoad } from '../hooks/useLoad.js'
import { accessLabel, typeLabel } from '../features/projects/labels.js'

// Shared frame for everything inside one project: header, section tabs (page-level navigation,
// not a sidebar), and the section itself through the router outlet.
export default function ProjectLayoutPage() {
  const { projectId } = useParams()
  const api = useApi()
  const [state, reload] = useLoad(useCallback(() => api.getProject(projectId), [api, projectId]))
  return (
    <DataState state={state} onRetry={reload} what="this project" loadingLabel="Loading project…">
      {(project) => {
        const base = `/projects/${project.id}`
        return (
          <>
            <PageHeader
              title={project.name}
              description={project.description || undefined}
              breadcrumbs={[{ to: '/projects', label: 'Projects' }, { label: project.name }]}
              meta={
                <>
                  <span>{typeLabel(project.application_type)}</span>
                  <StatusBadge domain="project" value={project.status} />
                  {project.your_access && <span>Your access: {accessLabel(project.your_access)}</span>}
                </>
              }
            />
            {project.status === 'archived' && <Alert tone="warning" title="This project is archived">It is kept for reference. Sources, plans and runs cannot be changed.</Alert>}
            <TabNav
              label="Project sections"
              items={[
                { to: base, label: 'Overview', end: true },
                { to: `${base}/setup`, label: 'Setup' },
                { to: `${base}/analysis`, label: 'Analysis' },
                { to: `${base}/plans`, label: 'Plans' },
                { to: `${base}/runs`, label: 'Runs' },
                { to: `${base}/findings`, label: 'Findings' },
                { to: `${base}/assistant`, label: 'Assistant' },
                { to: `${base}/proposals`, label: 'Proposals' },
                { to: `${base}/governance`, label: 'Governance' },
              ]}
            />
            <Outlet context={{ project, reloadProject: reload }} />
          </>
        )
      }}
    </DataState>
  )
}
