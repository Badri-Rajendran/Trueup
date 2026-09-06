import { ErrorState } from '../../../components/ErrorState'
import { Skeleton } from '../../../components/Skeleton'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { useModels } from '../hooks/useModels.js'
import { ModelCard } from './ModelCard.jsx'
import './AssignmentPrompt.css'

/** Design system/structure.md §6: not an error state — a customer between onboarding and first assignment. */
export function AssignmentPrompt({ onSelect, assigning }) {
  const { status, models, error, refetch } = useModels()

  if (status === 'idle' || status === 'loading') {
    return <Skeleton height="160px" />
  }

  if (status === 'error') {
    return <ErrorState description={getErrorMessage(error)} onRetry={refetch} />
  }

  return (
    <div className="tu-assignment-prompt">
      <p>Choose a model portfolio to get started.</p>
      <div className="tu-assignment-prompt__grid">
        {models.map((model) => (
          <ModelCard key={model.id} model={model} onSelect={onSelect} selected={false} />
        ))}
      </div>
      {assigning?.status === 'error' && (
        <p className="tu-assignment-prompt__error" role="alert">
          {getErrorMessage(assigning.error)}
        </p>
      )}
    </div>
  )
}
