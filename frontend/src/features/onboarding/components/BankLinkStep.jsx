import { Button } from '../../../components/Button'
import { Skeleton } from '../../../components/Skeleton'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { useBankLink } from '../hooks/useBankLink.js'
import './OnboardingStep.css'

export function BankLinkStep({ customerId, onCompleted }) {
  const { tokenStatus, status, error, ready, open, retryLinkToken } = useBankLink(customerId, {
    onLinked: onCompleted,
  })

  if (tokenStatus === 'loading') {
    return <Skeleton height="40px" width="220px" />
  }

  if (tokenStatus === 'error') {
    return (
      <div className="tu-onboarding-step">
        <p className="tu-onboarding-step__error" role="alert">
          Couldn&apos;t start bank linking.
        </p>
        <Button variant="secondary" onClick={retryLinkToken}>
          Try again
        </Button>
      </div>
    )
  }

  return (
    <div className="tu-onboarding-step">
      <h2 className="tu-onboarding-step__title">Link your bank</h2>
      <p className="tu-onboarding-step__description">Connect a bank account to fund your investments.</p>
      {status === 'error' && (
        <p className="tu-onboarding-step__error" role="alert">
          {getErrorMessage(error)}
        </p>
      )}
      {status === 'submitted' ? (
        <p className="tu-onboarding-step__success">Bank account linked.</p>
      ) : (
        <Button onClick={() => open()} disabled={!ready || status === 'submitting'} loading={status === 'submitting'}>
          Link bank account
        </Button>
      )}
    </div>
  )
}
