import Decimal from 'decimal.js'
import { Card } from '../../../components/Card'
import { Button } from '../../../components/Button'
import './ModelCard.css'

function formatWeight(value) {
  return `${new Decimal(value).times(100).toFixed(0)}%`
}

export function ModelCard({ model, selected, onSelect }) {
  return (
    <Card className="tu-model-card">
      <div className="tu-model-card__header">
        <span className="tu-model-card__name">{model.name}</span>
        {onSelect && (
          <Button variant={selected ? 'secondary' : 'primary'} size="compact" onClick={() => onSelect(model.id)} disabled={selected}>
            {selected ? 'Assigned' : 'Choose this model'}
          </Button>
        )}
      </div>
      <p className="tu-model-card__description">{model.description}</p>
      <div className="tu-model-card__weights">
        {model.target_weights.map((weight) => (
          <div key={weight.security_id} className="tu-model-card__weight-row">
            <span>{weight.symbol}</span>
            <span>{formatWeight(weight.target_weight)}</span>
          </div>
        ))}
      </div>
    </Card>
  )
}
