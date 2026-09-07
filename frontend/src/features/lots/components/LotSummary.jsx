import { Card } from '../../../components/Card'
import { formatMoney } from '../../../utils/format.js'
import { hasMissingPrices, totalMarketValue, totalUnrealizedGainLoss, totalWashSaleDisallowed } from '../utils/lotSummary.js'
import './LotSummary.css'

/** Hero-plus-supporting-cards shape (AccrualSummary/HighWaterMarkCard's precedent from the fees
 * redesign). Total market value is the one serif hero figure on this screen — not unrealized
 * gain/loss, which swings daily and isn't the kind of "certified statement figure" §3.1 reserves
 * the serif for. Always computed from the full lot list, not the status-filtered table view, since
 * this is a whole-account summary. */
export function LotSummary({ lots }) {
  const marketValue = totalMarketValue(lots)
  const unrealizedGainLoss = totalUnrealizedGainLoss(lots)
  const washSaleDisallowed = totalWashSaleDisallowed(lots)
  const incomplete = hasMissingPrices(lots)

  return (
    <div className="tu-lot-summary">
      <Card className="tu-lot-summary__hero">
        <span className="tu-lot-summary__label">Total market value</span>
        <span className="tu-lot-summary__value">{marketValue === null ? '—' : formatMoney(marketValue)}</span>
        {incomplete && (
          <p className="tu-lot-summary__note">
            One or more open lots is missing a confirmed price — this total may be incomplete.
          </p>
        )}
      </Card>
      <div className="tu-lot-summary__columns">
        <Card>
          <span className="tu-lot-summary__stat-label">Unrealized gain/loss</span>
          {unrealizedGainLoss === null ? (
            <span className="tu-lot-summary__stat-value">—</span>
          ) : (
            <span
              className={
                unrealizedGainLoss.isNegative()
                  ? 'tu-lot-summary__stat-value tu-lot-summary__stat-value--loss'
                  : 'tu-lot-summary__stat-value tu-lot-summary__stat-value--gain'
              }
            >
              {formatMoney(unrealizedGainLoss)}
            </span>
          )}
        </Card>
        <Card>
          <span className="tu-lot-summary__stat-label">Wash sale disallowed</span>
          <span className="tu-lot-summary__stat-value">{formatMoney(washSaleDisallowed)}</span>
        </Card>
      </div>
    </div>
  )
}
