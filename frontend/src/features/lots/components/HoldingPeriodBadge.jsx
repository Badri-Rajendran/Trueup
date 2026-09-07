import { Badge } from '../../../components/Badge'
import { Icon } from '../../../components/Icon'
import { hasWashSaleDisallowed, holdingPeriod } from '../utils/lotSummary.js'
import './HoldingPeriodBadge.css'

const LABEL_BY_TERM = { 'long-term': 'Long-term', 'short-term': 'Short-term' }

/**
 * Only ever rendered by a caller for a still-open lot (design brief item 5) — no reliable per-lot
 * sale date exists at the granularity this scope needs to classify a closed lot, so this component
 * assumes `lot` is open/partial rather than re-deriving that itself. Neutral tone like
 * `LotStatusBadge` (this is a classification, not an alert) — but this backend doesn't model the
 * IRS rule that a wash-sale replacement lot inherits its original lot's holding period, so a lot
 * with a wash-sale adjustment gets a visible qualifier rather than presenting unqualified
 * certainty.
 */
export function HoldingPeriodBadge({ lot }) {
  const term = holdingPeriod(lot.acquired_at)
  const qualified = hasWashSaleDisallowed(lot)

  return (
    <span className="tu-holding-period-badge">
      <Badge tone="neutral">{LABEL_BY_TERM[term]}</Badge>
      {qualified && (
        <span className="tu-holding-period-badge__qualifier">
          <Icon name="alert-triangle" size="sm" />
          May differ — wash sale
        </span>
      )}
    </span>
  )
}
