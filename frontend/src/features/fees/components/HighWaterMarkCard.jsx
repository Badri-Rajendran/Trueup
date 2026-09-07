import { Card } from '../../../components/Card'
import { formatDate, formatMoney } from '../../../utils/format.js'
import './HighWaterMarkCard.css'

/**
 * The high-water mark explained in plain words, not a percentage — `FEE_RATE_PCT` is a deploy-time
 * setting (`docs/specs/10-performance-fees.md` §"the fee rate's actual value") and never reaches
 * the wire, so this component never invents one in copy.
 */
export function HighWaterMarkCard({ accrual }) {
  const hasPeak = accrual.peak_value !== null

  return (
    <Card className="tu-high-water-mark">
      <span className="tu-high-water-mark__label">High-water mark</span>
      {hasPeak ? (
        <span className="tu-high-water-mark__value">{formatMoney(accrual.peak_value)}</span>
      ) : (
        <span className="tu-high-water-mark__value tu-high-water-mark__value--unset">Not set yet</span>
      )}
      <p className="tu-high-water-mark__explainer">
        {hasPeak
          ? "You're only charged on gains above this line. If your account is below it, no fee accrues until it recovers past this figure."
          : 'Your high-water mark is recorded on your first valuation day.'}
      </p>
      {accrual.updated_at && <span className="tu-high-water-mark__updated">Updated {formatDate(accrual.updated_at)}</span>}
    </Card>
  )
}
