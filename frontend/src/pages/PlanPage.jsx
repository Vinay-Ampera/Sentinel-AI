import { Link, useOutletContext, useParams } from 'react-router-dom'
import Card from '../components/Card.jsx'
import PlanReview from '../features/plans/PlanReview.jsx'
import { useApi } from '../hooks/useApi.js'
import { useAuth } from '../hooks/useAuth.js'

// One plan, reviewed with the existing PlanReview (edit, submit, approve or reject). Which
// buttons appear follows the plan's status and your role as a convenience; the server decides.
export default function PlanPage() {
  const { project } = useOutletContext()
  const { planId } = useParams()
  const api = useApi()
  const { user } = useAuth()
  return (
    <Card title="Plan review">
      <p><Link to={`/projects/${project.id}/plans`}>Back to all plans</Link></p>
      <PlanReview key={planId} api={api} planId={planId} user={user} onChanged={() => {}} />
    </Card>
  )
}
