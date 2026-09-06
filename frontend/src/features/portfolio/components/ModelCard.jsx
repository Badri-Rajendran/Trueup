import Decimal from 'decimal.js'
import { useState } from 'react'
import { Card } from '../../../components/Card'
import { Button } from '../../../components/Button'
import { Icon } from '../../../components/Icon'
import { describeAllocation } from '../utils/assetClass.js'
import { AllocationBar } from './AllocationBar.jsx'
import './ModelCard.css'

function formatWeight(value) {
  return `${new Decimal(value).times(100).toFixed(1)}%`
}

export function ModelCard({ model, selected, onSelect, submitting }) {
  const [confirming, setConfirming] = useState(false)
  const description = describeAllocation(model.target_weights)

  return (
    <Card className="tu-model-card">
      <div className="tu-model-card__header">
        <span className="tu-model-card__name">{model.name}</span>
        {selected ? (
          <span className="tu-model-card__assigned">
            <Icon name="check-circle" size="sm" />
            Assigned
          </span>
        ) : (
          onSelect &&
          (!confirming ? (
            <Button variant="primary" size="compact" onClick={() => setConfirming(true)} disabled={submitting}>
              Choose this model
            </Button>
          ) : (
            <div className="tu-model-card__confirm-actions">
              <Button
                variant="primary"
                size="compact"
                onClick={() => onSelect(model.id)}
                loading={submitting}
                disabled={submitting}
              >
                Confirm {model.name}?
              </Button>
              <Button variant="secondary" size="compact" onClick={() => setConfirming(false)} disabled={submitting}>
                Cancel
              </Button>
            </div>
          ))
        )}
      </div>
      {description && <p className="tu-model-card__description">{description}</p>}
      <AllocationBar targetWeights={model.target_weights} />
      <div className="tu-model-card__weights">
        {model.target_weights.map((weight) => (
          <div key={weight.security_id} className="tu-model-card__weight-row">
            <span>{weight.symbol}</span>
            <span>{formatWeight(weight.weight_pct)}</span>
          </div>
        ))}
      </div>
    </Card>
  )
}
