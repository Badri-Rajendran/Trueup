import { ErrorState } from '../../../components/ErrorState'
import { Skeleton } from '../../../components/Skeleton'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { formatMoney } from '../../../utils/format.js'
import { useCashPolicy } from '../hooks/useCashPolicy.js'
import './CashSummary.css'

// design-system.md §8.2
export function CashSummary({ emphasize }) {
  const { status, withdrawable, investable, error, refetch } = useCashPolicy()

  if (status === 'idle' || status === 'loading') {
    return <Skeleton height="48px" width="280px" />
  }

  if (status === 'error') {
    return <ErrorState description={getErrorMessage(error)} onRetry={refetch} />
  }

  return (
    <div className="tu-cash-summary">
      <div className={`tu-cash-summary__figure${emphasize === 'investable' ? ' tu-cash-summary__figure--quiet' : ''}`}>
        <span className="tu-cash-summary__label">Withdrawable</span>
        <span className="tu-cash-summary__value">{formatMoney(withdrawable)}</span>
      </div>
      <div className={`tu-cash-summary__figure${emphasize === 'withdrawable' ? ' tu-cash-summary__figure--quiet' : ''}`}>
        <span className="tu-cash-summary__label">Investable</span>
        <span className="tu-cash-summary__value">{formatMoney(investable)}</span>
      </div>
    </div>
  )
}
