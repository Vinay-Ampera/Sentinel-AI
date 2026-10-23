import { useOutletContext } from 'react-router-dom'
import { AnalysisPanel, ApprovalsPanel, FindingsPanel, PlansPanel, RunPanel } from '../features/projects/OverviewPanels.jsx'
import './ProjectOverviewPage.css'

// A glance at the project, composed from the existing list endpoints (no summary endpoint yet).
// Every figure comes from a recorded record; a panel that cannot load says so on its own.
export default function ProjectOverviewPage() {
  const { project } = useOutletContext()
  return (
    <div className="overview-grid">
      <AnalysisPanel projectId={project.id} />
      <PlansPanel projectId={project.id} />
      <RunPanel projectId={project.id} />
      <FindingsPanel projectId={project.id} />
      <ApprovalsPanel projectId={project.id} />
    </div>
  )
}
