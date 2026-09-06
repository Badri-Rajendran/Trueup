import { ErrorState } from '../components/ErrorState'
import { Skeleton } from '../components/Skeleton'
import { useToast } from '../components/Toast'
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
  const { status: modelsStatus, models, error: modelsError, refetch: refetchModels } = useModels()
  const { showToast } = useToast()

  // Both the assignment and the model list must be loaded before we can tell an already-assigned
  // customer from a not-yet-assigned one — deciding early (e.g. from an empty, still-loading
  // `models` array) is what previously flashed the "choose a model" prompt on every page load.
  const isLoading =
    assignment.status === 'idle' ||
    assignment.status === 'loading' ||
    modelsStatus === 'idle' ||
    modelsStatus === 'loading'

  if (isLoading) {
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

  if (modelsStatus === 'error') {
    return (
      <div className="tu-page">
        <h1 className="tu-page__title">Portfolio</h1>
        <ErrorState description={getErrorMessage(modelsError)} onRetry={refetchModels} />
      </div>
    )
  }

  const assignedModel = assignment.assignment
    ? models.find((model) => model.id === assignment.assignment.model_portfolio_id)
    : null

  const handleSelect = (modelId) => {
    const chosen = models.find((model) => model.id === modelId)
    return assignment
      .assign(modelId)
      .then(() => {
        showToast({ message: chosen ? `You're now assigned to ${chosen.name}.` : 'Model assigned.', tone: 'success' })
      })
      .catch(() => {})
  }

  return (
    <div className="tu-page">
      <h1 className="tu-page__title">Portfolio</h1>
      {assignedModel ? (
        <ModelDetail
          models={models}
          assignedModel={assignedModel}
          assignedAt={assignment.assignment.assigned_at}
          onSelect={handleSelect}
          assigning={{ status: assignment.assignStatus, error: assignment.assignError }}
        />
      ) : (
        <AssignmentPrompt
          models={models}
          onSelect={handleSelect}
          assigning={{ status: assignment.assignStatus, error: assignment.assignError }}
        />
      )}
    </div>
  )
}
