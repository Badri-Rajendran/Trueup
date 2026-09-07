import { Button } from '../../../components/Button'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { useBankLink } from '../../onboarding/hooks/useBankLink.js'

/**
 * Thin wrapper around onboarding's real Plaid Link integration (`useBankLink`) — the funding
 * screen has its own trigger copy (`label`, "Link bank account" vs. "Reconnect bank") but no
 * separate bank-link mechanism of its own; do not duplicate or modify the hook itself.
 */
export function LinkBankButton({ customerId, label, onLinked }) {
  const { tokenStatus, status, error, ready, open, retryLinkToken } = useBankLink(customerId, { onLinked })

  if (tokenStatus === 'error') {
    return (
      <Button variant="secondary" onClick={retryLinkToken}>
        Try again
      </Button>
    )
  }

  return (
    <div className="tu-link-bank-button">
      <Button onClick={() => open()} disabled={!ready || status === 'submitting'} loading={status === 'submitting'}>
        {label}
      </Button>
      {status === 'error' && (
        <p className="tu-link-bank-button__error" role="alert">
          {getErrorMessage(error)}
        </p>
      )}
    </div>
  )
}
