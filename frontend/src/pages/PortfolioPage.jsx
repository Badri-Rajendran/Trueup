import { ErrorState } from '../components/ErrorState'
import { Skeleton } from '../components/Skeleton'
import { useSession } from '../contexts/SessionContext.jsx'
import { AssignmentPrompt } from '../features/portfolio/components/AssignmentPrompt.jsx'
import { ModelDetail } from '../features/portfolio/components/ModelDetail.jsx'
import { useAssignment } from '../features/portfolio/hooks/useAssignment.js'
import { useModels } from '../features/portfolio/hooks/useModels.js'
import { getErrorMessage } from '../utils/apiErrorMessage.js'
import './PageLayout.css'

export function PortfolioPage() {
  const { principal } = useSession()
  const assignment = useAssignment(principal.id)
  const { models } = useModels()

  if (assignment.status === 'idle' || assignment.status === 'loading') {
    return (
      <div className="tu-page">
        <h1 className="tu-page__title">Portfolio</h1>
        <Skeleton height="160px" />
      </div>
    )
  }

  if (assignment.status === 'error') {
    return (
      <div className="tu-page">
        <h1 className="tu-page__title">Portfolio</h1>
        <ErrorState description={getErrorMessage(assignment.error)} onRetry={assignment.refetch} />
      </div>
    )
  }

  const assignedModel = assignment.assignment
    ? models.find((model) => model.id === assignment.assignment.model_portfolio_id)
    : null

  return (
    <div className="tu-page">
      <h1 className="tu-page__title">Portfolio</h1>
      {assignedModel ? (
        <ModelDetail model={assignedModel} assignedAt={assignment.assignment.assigned_at} />
      ) : (
        <AssignmentPrompt onSelect={assignment.assign} assigning={{ status: assignment.assignStatus, error: assignment.assignError }} />
      )}
    </div>
  )
}
