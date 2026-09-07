import { Button } from '../../../components/Button'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { useKycSession } from '../hooks/useKycSession.js'
import './OnboardingStep.css'

const BUSY_STATUSES = new Set(['submitting', 'verifying'])

// Resolves either our ApiError (`.code`) or a Stripe.js error (`.message`).
function resolveErrorMessage(error) {
  if (!error) return null
  if (error.code) return getErrorMessage(error)
  return error.message || 'Verification failed. Please try again.'
}

/**
 * `kycStatus` is the customer's *stored* status (from useIdentityStatus) -- distinct from
 * `status`, this hook's own local in-progress-attempt state. A `rejected` stored status must
 * never look identical to "hasn't tried yet": a customer who was turned away deserves to be told
 * that, not invited to click the same first-time prompt with no memory of what happened.
 */
export function KycStep({ customerId, kycStatus, onCompleted }) {
  const { status, error, startVerification } = useKycSession()
  const isBusy = BUSY_STATUSES.has(status)
  const wasRejected = kycStatus === 'rejected' && status === 'idle'

  return (
    <>
      {wasRejected && (
        <p className="tu-onboarding-step__error" role="alert">
          Your identity verification wasn&apos;t approved. Try again with a clear photo of a
          valid, unexpired government-issued ID.
        </p>
      )}
      <p className="tu-onboarding-step__description">
        We use Stripe Identity to confirm who you are — you&apos;ll need a government-issued photo ID.
      </p>
      {status === 'error' && (
        <p className="tu-onboarding-step__error" role="alert">
          {resolveErrorMessage(error)}
        </p>
      )}
      {status === 'completed' ? (
        <p className="tu-onboarding-step__success">
          Verification submitted — your status will update automatically once it&apos;s reviewed.
        </p>
      ) : (
        <Button
          onClick={() => {
            startVerification(customerId)
              .then(() => onCompleted?.())
              .catch(() => {})
          }}
          loading={isBusy}
          disabled={isBusy}
        >
          {wasRejected ? 'Try again' : 'Start identity verification'}
        </Button>
      )}
    </>
  )
}
