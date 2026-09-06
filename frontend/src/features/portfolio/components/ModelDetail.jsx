import { Badge } from '../../../components/Badge'
import { formatDate } from '../../../utils/format.js'
import { ModelCard } from './ModelCard.jsx'
import './ModelDetail.css'

export function ModelDetail({ model, assignedAt }) {
  return (
    <div>
      <Badge tone="accent" className="tu-model-detail__badge">
        Your model
      </Badge>
      <ModelCard model={model} />
      {assignedAt && <p className="tu-model-detail__assigned-at">Assigned {formatDate(assignedAt)}</p>}
    </div>
  )
}
