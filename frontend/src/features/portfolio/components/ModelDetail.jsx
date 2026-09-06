import { Badge } from '../../../components/Badge'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { formatDate } from '../../../utils/format.js'
import { ModelCard } from './ModelCard.jsx'
import './ModelDetail.css'

// design-system.md / structure.md §6
export function ModelDetail({ models, assignedModel, assignedAt, onSelect, assigning }) {
  return (
    <div className="tu-model-detail">
      <div className="tu-model-detail__summary">
        <Badge tone="accent" className="tu-model-detail__badge">
          Your model
        </Badge>
        <p className="tu-model-detail__name">{assignedModel.name}</p>
        {assignedAt && <p className="tu-model-detail__assigned-at">Assigned {formatDate(assignedAt)}</p>}
      </div>
      <h2 className="tu-model-detail__section-title">Switch model portfolio</h2>
      <div className="tu-model-detail__grid">
        {models.map((model) => (
          <ModelCard
            key={model.id}
            model={model}
            selected={model.id === assignedModel.id}
            onSelect={onSelect}
            submitting={assigning?.status === 'submitting'}
          />
        ))}
      </div>
      {assigning?.status === 'error' && (
        <p className="tu-model-detail__error" role="alert">
          {getErrorMessage(assigning.error)}
        </p>
      )}
    </div>
  )
}
