import { Button } from '../../../components/Button'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { useKycSession } from '../hooks/useKycSession.js'
import './OnboardingStep.css'

const BUSY_STATUSES = new Set(['submitting', 'verifying'])

// `error` here is either our own ApiError (has `.code`) or a Stripe.js error object (has
// `.message`, no `.code` in our sense) — resolve whichever shape arrived.
function resolveErrorMessage(error) {
  if (!error) return null
  if (error.code) return getErrorMessage(error)
  return error.message || 'Verification failed. Please try again.'
}

export function KycStep({ customerId, onCompleted }) {
  const { status, error, startVerification } = useKycSession()
  const isBusy = BUSY_STATUSES.has(status)

  return (
    <div className="tu-onboarding-step">
      <h2 className="tu-onboarding-step__title">Verify your identity</h2>
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
          Start identity verification
        </Button>
      )}
    </div>
  )
}
