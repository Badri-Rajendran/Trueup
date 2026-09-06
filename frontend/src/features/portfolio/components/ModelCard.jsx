import Decimal from 'decimal.js'
import { Card } from '../../../components/Card'
import { Button } from '../../../components/Button'
import './ModelCard.css'

function formatWeight(value) {
  return `${new Decimal(value).times(100).toFixed(0)}%`
}

// `GET /portfolios/models` carries no description field — this is fixed UI copy for the four
// model portfolios the backend defines, not a fabricated financial figure. A model whose name
// doesn't match falls back to no description rather than inventing one.
const MODEL_DESCRIPTIONS = {
  Conservative: 'Capital preservation first — a bond-heavy allocation with a small equity sleeve.',
  Balanced: 'An even split between growth and stability.',
  Growth: 'Mostly equities, a modest bond allocation to dampen volatility.',
  Aggressive: 'Maximum equity exposure for a long time horizon.',
}

export function ModelCard({ model, selected, onSelect }) {
  const description = MODEL_DESCRIPTIONS[model.name]

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
      {description && <p className="tu-model-card__description">{description}</p>}
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
