import { Card } from '../../../components/Card'
import { ErrorState } from '../../../components/ErrorState'
import { Icon } from '../../../components/Icon'
import { Skeleton } from '../../../components/Skeleton'
import { StatusPill } from '../../../components/StatusPill'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { LinkBankButton } from './LinkBankButton.jsx'
import './BankLinkCard.css'

/**
 * Bank-link status in the Money page's own voice — replaces the borrowed onboarding copy that
 * used to sit inline in `FundingPage.jsx`. No unlink affordance (explicitly out of scope).
 *
 * Presentational: `status`/`bankLink`/`error` arrive from `MoneyPage`'s single
 * `useCurrentBankLink()` call, shared with `DepositForm`/`WithdrawForm`'s disabled-state check —
 * a second and third `GET /funding/bank-links/current` from those forms calling the hook
 * themselves would repeat, on a different endpoint, exactly the double-fetch bug this rebuild
 * exists to fix on `/cash-summary`.
 */
export function BankLinkCard({ customerId, status, bankLink, error, onRetry, onLinked }) {
  if (status === 'idle' || status === 'loading') {
    return (
      <Card>
        <Skeleton height="60px" />
      </Card>
    )
  }

  if (status === 'error') {
    return (
      <Card>
        <ErrorState description={getErrorMessage(error)} onRetry={onRetry} />
      </Card>
    )
  }

  if (bankLink?.status === 'active') {
    return (
      <Card className="tu-bank-link-card">
        <div className="tu-bank-link-card__info">
          <p className="tu-bank-link-card__label">Bank account</p>
          <p className="tu-bank-link-card__description">
            Your linked bank account is ready to fund deposits and receive withdrawals.
          </p>
        </div>
        <StatusPill tone="success" icon={<Icon name="check-circle" size="sm" />}>
          Linked
        </StatusPill>
      </Card>
    )
  }

  if (bankLink?.status === 'requires_reauth') {
    // FR-43's distinct interstitial: a stale Plaid Item (e.g. `ITEM_LOGIN_REQUIRED`) is never
    // shown as though the link were still `active` and never silently dropped -- `role="status"`
    // announces the state change to a screen-reader user the moment `useCurrentBankLink` (or a
    // paused deposit/withdraw submit, see DepositForm.jsx) surfaces it.
    return (
      <Card className="tu-bank-link-card tu-bank-link-card--reauth" role="status" aria-live="polite">
        <div className="tu-bank-link-card__info">
          <p className="tu-bank-link-card__label">Bank account needs reconnecting</p>
          <p className="tu-bank-link-card__description">
            We can no longer confirm your bank account is still valid. Deposits and withdrawals are
            paused until you reconnect it -- nothing has failed, and no automatic retry will happen.
          </p>
          <StatusPill tone="warning" icon={<Icon name="alert-triangle" size="sm" />}>
            Needs reconnecting
          </StatusPill>
        </div>
        <LinkBankButton customerId={customerId} label="Reconnect bank" onLinked={onLinked} />
      </Card>
    )
  }

  return (
    <Card className="tu-bank-link-card">
      <div className="tu-bank-link-card__info">
        <p className="tu-bank-link-card__label">Bank account</p>
        <p className="tu-bank-link-card__description">
          Link a bank account to deposit into or withdraw from your investing account.
        </p>
      </div>
      <LinkBankButton customerId={customerId} label="Link bank account" onLinked={onLinked} />
    </Card>
  )
}
