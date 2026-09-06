import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { ModelCard } from './ModelCard.jsx'
import './AssignmentPrompt.css'

// design-system.md / structure.md §6 — `models` is fetched once at the page level (PortfolioPage)
// and passed down here to avoid a duplicate `GET /portfolios/models` call.
export function AssignmentPrompt({ models, onSelect, assigning }) {
  return (
    <div className="tu-assignment-prompt">
      <p>Choose a model portfolio to get started.</p>
      <div className="tu-assignment-prompt__grid">
        {models.map((model) => (
          <ModelCard
            key={model.id}
            model={model}
            selected={false}
            onSelect={onSelect}
            submitting={assigning?.status === 'submitting'}
          />
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
