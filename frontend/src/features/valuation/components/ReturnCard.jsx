import Decimal from 'decimal.js'
import { Badge } from '../../../components/Badge'
import { Card } from '../../../components/Card'
import { ErrorState } from '../../../components/ErrorState'
import { Skeleton } from '../../../components/Skeleton'
import { formatPercent } from '../../../utils/format.js'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import './ReturnCard.css'

// design-system.md §2.4
export function ReturnCard({ status, twr, isProvisional, error, onRetry, label = 'Month-to-date return' }) {
  const isLoss = twr !== null && new Decimal(twr).isNegative()

  return (
    <Card className="tu-return-card">
      <span className="tu-return-card__label">{label}</span>
      {status === 'loading' || status === 'idle' ? (
        <Skeleton height="36px" width="120px" />
      ) : status === 'error' ? (
        <ErrorState description={getErrorMessage(error)} onRetry={onRetry} />
      ) : (
        <span className={`tu-return-card__value ${isLoss ? 'tu-return-card__value--loss' : 'tu-return-card__value--gain'}`}>
          {formatPercent(twr)}
        </span>
      )}
      {isProvisional && <Badge tone="neutral">Provisional</Badge>}
    </Card>
  )
}
