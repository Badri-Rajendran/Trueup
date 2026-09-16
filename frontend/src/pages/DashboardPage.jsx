import Decimal from 'decimal.js'
import { useState } from 'react'
import { Badge } from '../components/Badge'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { Skeleton } from '../components/Skeleton'
import { ValuationChart } from '../components/ValuationChart'
import { useSession } from '../contexts/SessionContext.jsx'
import { CashSummary } from '../features/funding/components/CashSummary.jsx'
import { useCashSummary } from '../features/funding/hooks/useCashSummary.js'
import { HoldingsPanel } from '../features/portfolio/components/HoldingsPanel.jsx'
import { usePerformance } from '../features/portfolio/hooks/usePerformance.js'
import { CompletenessBanner } from '../features/valuation/components/CompletenessBanner.jsx'
import { LedgerBand } from '../features/valuation/components/LedgerBand.jsx'
import { useBalance } from '../features/valuation/hooks/useBalance.js'
import { WatchlistPanel } from '../features/watchlist/components/WatchlistPanel.jsx'
import { getErrorMessage } from '../utils/apiErrorMessage.js'
import { formatDate, formatMoney, formatPercent } from '../utils/format.js'
import './DashboardPage.css'
import './PageLayout.css'

const RANGES = [
  { value: '1m', label: '1M' },
  { value: '3m', label: '3M' },
  { value: '6m', label: '6M' },
  { value: '1y', label: '1Y' },
  { value: 'all', label: 'All' },
]

/**
 * The hero plate: a live-readout balance figure backed by `useBalance`, and — the approved
 * mockup's "scrubbable" behavior — swapped for the scrubbed day's value while `ValuationChart`
 * reports a non-null point. `usePerformance`'s own series backs the chart; `useBalance`'s figure is
 * the resting/default state, not the chart's own last point, since the two endpoints can have
 * different `as_of_date`s (balance is always "as of today", the chart's last point may lag by a
 * beat during market hours).
 */
function HeroPlate() {
  const balance = useBalance()
  const [range, setRange] = useState('1m')
  const performance = usePerformance(range)
  const [scrubPoint, setScrubPoint] = useState(null)

  const isScrubbing = scrubPoint !== null
  const readoutValue = isScrubbing ? scrubPoint.value : balance.totalValue
  const readoutDate = isScrubbing ? scrubPoint.as_of_date : balance.asOfDate

  const chartHasNoData = performance.status !== 'error' && performance.points.length === 0
  const chartIsLoading = (performance.status === 'idle' || performance.status === 'loading') && chartHasNoData

  return (
    <Card className="tu-hero-plate">
      {!isScrubbing && balance.completeness === 'partial' && <CompletenessBanner asOfDate={balance.asOfDate} />}

      <div className="tu-hero-plate__figure">
        <span className="tu-hero-plate__label">{isScrubbing ? `Value on ${formatDate(readoutDate)}` : 'Account balance'}</span>
        {balance.status === 'loading' || balance.status === 'idle' ? (
          <Skeleton height="56px" width="240px" />
        ) : balance.status === 'error' ? (
          <ErrorState description={getErrorMessage(balance.error)} onRetry={balance.refetch} />
        ) : (
          <>
            <span className="tu-hero-plate__value">{formatMoney(readoutValue)}</span>
            {!isScrubbing && (
              <span className="tu-hero-plate__as-of">
                As of {formatDate(balance.asOfDate)}
                {performance.status === 'loaded' && performance.points.length > 0 && (
                  <>
                    {' · '}
                    <span
                      className={
                        new Decimal(performance.cumulativeTwr).isNegative()
                          ? 'tu-hero-plate__twr tu-hero-plate__twr--loss'
                          : 'tu-hero-plate__twr tu-hero-plate__twr--gain'
                      }
                    >
                      {formatPercent(performance.cumulativeTwr)}
                    </span>{' '}
                    this range
                    {performance.isProvisional && <Badge tone="neutral">Provisional</Badge>}
                  </>
                )}
              </span>
            )}
          </>
        )}
      </div>

      <div className="tu-hero-plate__range-toggle" role="group" aria-label="Chart range">
        {RANGES.map((option) => (
          <button
            key={option.value}
            type="button"
            className={`tu-hero-plate__range-button${range === option.value ? ' tu-hero-plate__range-button--active' : ''}`}
            aria-pressed={range === option.value}
            onClick={() => setRange(option.value)}
          >
            {option.label}
          </button>
        ))}
      </div>

      {performance.status === 'error' && performance.points.length === 0 ? (
        <ErrorState description={getErrorMessage(performance.error)} onRetry={performance.refetch} />
      ) : chartIsLoading ? (
        <Skeleton height="160px" />
      ) : (
        <ValuationChart
          points={performance.points}
          isProvisional={performance.isProvisional}
          onScrub={setScrubPoint}
        />
      )}
    </Card>
  )
}

export function DashboardPage() {
  const { principal } = useSession()
  const cashSummary = useCashSummary()

  return (
    <div className="tu-page">
      <h1 className="tu-page__title">Dashboard</h1>

      <HeroPlate />

      <Card aria-busy={cashSummary.status === 'loading' || undefined}>
        {cashSummary.status === 'idle' || cashSummary.status === 'loading' ? (
          <Skeleton height="60px" />
        ) : cashSummary.status === 'error' ? (
          <ErrorState description={getErrorMessage(cashSummary.error)} onRetry={cashSummary.refetch} />
        ) : (
          <CashSummary cashSummary={cashSummary.cashSummary} />
        )}
      </Card>

      <div className="tu-dashboard-page__panels">
        <div>
          <h2 className="tu-page__section-title">Holdings</h2>
          <HoldingsPanel customerId={principal.id} />
        </div>
        <div>
          <WatchlistPanel />
        </div>
      </div>

      <div>
        <h2 className="tu-page__section-title">Activity</h2>
        <LedgerBand />
      </div>
    </div>
  )
}
