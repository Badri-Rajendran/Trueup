import { Card } from '../../../components/Card'
import { ErrorState } from '../../../components/ErrorState'
import { Icon } from '../../../components/Icon'
import { Skeleton } from '../../../components/Skeleton'
import { StatusPill } from '../../../components/StatusPill'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { LinkBankButton } from './LinkBankButton.jsx'
import './BankLinkCard.css'

/**
 * Bank-link status in the funding screen's own voice — replaces the borrowed onboarding copy that
 * used to sit inline in `FundingPage.jsx`. No unlink affordance (explicitly out of scope).
 *
 * Presentational: `status`/`bankLink`/`error` arrive from `FundingPage`'s single
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
    return (
      <Card className="tu-bank-link-card">
        <div className="tu-bank-link-card__info">
          <p className="tu-bank-link-card__label">Bank account</p>
          <p className="tu-bank-link-card__description">Your bank needs to be reconnected before you can deposit or withdraw.</p>
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
