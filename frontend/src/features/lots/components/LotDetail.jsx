import { formatDate, formatMoney } from '../../../utils/format.js'
import './LotDetail.css'

/**
 * Design system §7.6/structure.md §6: a lot mid-wash-sale-adjustment shows its adjustment, never
 * the raw pre-adjustment gain — the adjusted basis is what's used everywhere else in this UI too,
 * this panel just explains why it differs from the original.
 */
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
