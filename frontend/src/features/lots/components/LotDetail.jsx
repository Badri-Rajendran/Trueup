import { formatDate, formatMoney } from '../../../utils/format.js'
import './LotDetail.css'

/** Design system §7.6/structure.md §6: shows the wash-sale adjustment, not the raw gain. */
export function LotDetail({ lot }) {
  return (
    <div className="tu-lot-detail">
      <span>Opened {formatDate(lot.acquired_at)}</span>
      {lot.original_cost_basis !== lot.adjusted_basis && (
        <span>
          Original cost basis {formatMoney(lot.original_cost_basis)}, adjusted to {formatMoney(lot.adjusted_basis)}
        </span>
      )}
      {lot.is_provisional && lot.wash_sale_note && <span>{lot.wash_sale_note}</span>}
    </div>
  )
}
