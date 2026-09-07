import { Button } from '../../../components/Button'
import { Icon } from '../../../components/Icon'
import { formatMoney } from '../../../utils/format.js'
import { hasOutstandingBalance } from '../utils/fundingSummary.js'
import './OutstandingBalanceBanner.css'

/**
 * FR-6: a bounced deposit leaves a receivable balance the customer owes. Modeled on the fees
 * screen's `DunningBanner` (grid `auto 1fr`, error-tinted left rule, `role="alert"
 * aria-live="assertive"`) — but always `error`, never `warning`: unlike a first missed fee
 * payment, an outstanding funding balance has no "will retry automatically" step, so there's no
 * softer first-miss state to distinguish it from.
 */
export function OutstandingBalanceBanner({ cashSummary, onMakeDeposit }) {
  if (!hasOutstandingBalance(cashSummary)) {
    return null
  }

  return (
    <div className="tu-outstanding-balance-banner" role="alert" aria-live="assertive">
      <span className="tu-outstanding-balance-banner__icon">
        <Icon name="alert-circle" size="md" />
      </span>
      <div className="tu-outstanding-balance-banner__body">
        <p className="tu-outstanding-balance-banner__message">
          Balance owed:{' '}
          <span className="tu-outstanding-balance-banner__amount">{formatMoney(cashSummary.outstanding_receivable)}</span> — a
          previous deposit was returned by your bank. Make a deposit of at least this amount to cover it.
        </p>
        <div className="tu-outstanding-balance-banner__actions">
          <Button variant="secondary" size="compact" onClick={onMakeDeposit}>
            Make a deposit
          </Button>
        </div>
      </div>
    </div>
  )
}
