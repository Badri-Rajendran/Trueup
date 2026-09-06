import Decimal from 'decimal.js'
import { Badge } from '../../../components/Badge'
import { Card } from '../../../components/Card'
import { Skeleton } from '../../../components/Skeleton'
import { formatPercent } from '../../../utils/format.js'
import './ReturnCard.css'

/** Design system §2.4: gains/losses use success/error text color on the figure itself, not a badge. */
export function ReturnCard({ status, twr, isProvisional, label = 'Month-to-date return' }) {
  const isLoss = twr !== null && new Decimal(twr).isNegative()

  return (
    <Card className="tu-return-card">
      <span className="tu-return-card__label">{label}</span>
      {status === 'loading' || status === 'idle' ? (
        <Skeleton height="36px" width="120px" />
      ) : (
        <span className={`tu-return-card__value ${isLoss ? 'tu-return-card__value--loss' : 'tu-return-card__value--gain'}`}>
          {formatPercent(twr)}
        </span>
      )}
      {isProvisional && <Badge tone="neutral">Provisional</Badge>}
    </Card>
  )
}
