import { Card } from '../../../components/Card'
import { Skeleton } from '../../../components/Skeleton'
import { formatDate, formatMoney } from '../../../utils/format.js'
import './BalanceCard.css'

/** Design system §1/§3.1: the one deliberately expressive typographic choice — Source Serif 4, `display` scale, used nowhere else. */
export function BalanceCard({ status, totalValue, asOfDate }) {
  return (
    <Card className="tu-balance-card">
      <span className="tu-balance-card__label">Account balance</span>
      {status === 'loading' || status === 'idle' ? (
        <Skeleton height="48px" width="200px" />
      ) : (
        <>
          <span className="tu-balance-card__value">{formatMoney(totalValue)}</span>
          <span className="tu-balance-card__as-of">As of {formatDate(asOfDate)}</span>
        </>
      )}
    </Card>
  )
}
