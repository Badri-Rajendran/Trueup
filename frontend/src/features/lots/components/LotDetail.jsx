import Decimal from 'decimal.js'
import { DetailFields } from '../../../components/DetailFields'
import { formatDate, formatMoney } from '../../../utils/format.js'
import { hasWashSaleDisallowed } from '../utils/lotSummary.js'
import { ConsumptionHistory } from './ConsumptionHistory.jsx'
import './LotDetail.css'

/** Design system §7.6/structure.md §6: shows the wash-sale adjustment as an additional disclosure,
 * never the raw pre-adjustment gain — `adjusted_basis`/`realized_gain_loss` stay the only adjusted
 * figures ever shown; this component must never compute `adjusted_basis - wash_sale_disallowed`
 * and present that as "the real basis." Basis-changed comparison goes through decimal.js `.equals()`
 * — money is a wire string, never compared with raw `!==`. */
export function LotDetail({ lot }) {
  const basisWasAdjusted = !new Decimal(lot.original_cost_basis).equals(lot.adjusted_basis)
  const washSaleDisallowed = hasWashSaleDisallowed(lot)

  const fields = [
    { label: 'Acquired', value: formatDate(lot.acquired_at) },
    { label: 'Original cost basis', value: formatMoney(lot.original_cost_basis) },
    ...(basisWasAdjusted ? [{ label: 'Adjusted basis', value: formatMoney(lot.adjusted_basis) }] : []),
    { label: 'Realized gain/loss', value: formatMoney(lot.realized_gain_loss) },
    ...(washSaleDisallowed ? [{ label: 'Wash sale disallowed', value: formatMoney(lot.wash_sale_disallowed) }] : []),
  ]

  return (
    <div className="tu-lot-detail">
      <DetailFields fields={fields} />
      {washSaleDisallowed && (
        <p className="tu-lot-detail__wash-sale-note">
          A wash sale rule disallowed some loss on this lot; the disallowed amount above was folded
          into the adjusted basis already shown — not a separate figure to add or subtract yourself.
        </p>
      )}
      <div className="tu-lot-detail__consumptions">
        <h3 className="tu-lot-detail__consumptions-title">Sale history</h3>
        <ConsumptionHistory consumptions={lot.consumptions} />
      </div>
    </div>
  )
}
