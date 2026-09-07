import { Icon } from '../../../components/Icon'
import { formatMoney } from '../../../utils/format.js'
import { depositHeadroom } from '../utils/fundingSummary.js'
import './DepositLimits.css'

/**
 * Deposit-cap visibility (S2 §5.2, `CashSummaryResponse`'s cap fields). Modeled on the fees
 * screen's `BillingPeriodProgress`: no bar at all until the customer has actually used part of
 * today's cap — a bar permanently sitting at 0% is noise, not information, so an untouched day
 * shows only a plain caption stating both caps. Once something's used, a bar + caption appears;
 * past 80% of the daily cap it escalates to `warning` (never `error` — being near a cap isn't a
 * failure, and the form itself still stops an over-cap submit before it reaches the server).
 */
export function DepositLimits({ cashSummary }) {
  const { perTransactionCap, dailyRemaining, percentUsed, isNearLimit, hasUsedToday } = depositHeadroom(cashSummary)
  const dailyCap = formatMoney(cashSummary.deposit_cap_per_day)

  if (!hasUsedToday) {
    return (
      <p className="tu-deposit-limits__caption">
        Up to {formatMoney(perTransactionCap)} per deposit, {dailyCap} per day.
      </p>
    )
  }

  return (
    <div className={`tu-deposit-limits${isNearLimit ? ' tu-deposit-limits--warning' : ''}`}>
      <div className="tu-deposit-limits__track" aria-hidden="true">
        <div className="tu-deposit-limits__fill" style={{ width: `${percentUsed}%` }} />
      </div>
      <p className="tu-deposit-limits__caption">
        {isNearLimit && (
          <span className="tu-deposit-limits__warning-icon">
            <Icon name="alert-triangle" size="sm" />
          </span>
        )}
        {formatMoney(dailyRemaining)} left of today&apos;s {dailyCap} daily limit · {formatMoney(perTransactionCap)} per-deposit
        limit
      </p>
    </div>
  )
}
