import { Button } from '../components/Button'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { Skeleton } from '../components/Skeleton'
import { useSession } from '../contexts/SessionContext.jsx'
import { BankLinkStep } from '../features/onboarding/components/BankLinkStep.jsx'
import { IdentityStatusBanner } from '../features/onboarding/components/IdentityStatusBanner.jsx'
import { KycStep } from '../features/onboarding/components/KycStep.jsx'
import { useIdentityStatus } from '../features/onboarding/hooks/useIdentityStatus.js'
import './OnboardingPage.css'

export function OnboardingPage() {
  const { principal } = useSession()
  const identity = useIdentityStatus(principal.id)
  const isKycApproved = identity.kycStatus === 'approved'

  return (
    <div className="tu-onboarding-page">
      <div className="tu-onboarding-page__header">
        <h1 className="tu-onboarding-page__title">Identity and funding status</h1>
        {identity.status === 'loaded' && (
          <Button variant="secondary" size="compact" onClick={identity.refetch}>
            Refresh status
          </Button>
        )}
      </div>
      {(identity.status === 'idle' || identity.status === 'loading') && <Skeleton height="72px" />}
      {identity.status === 'error' && <ErrorState onRetry={identity.refetch} />}
      {identity.status === 'loaded' && (
        <>
          <IdentityStatusBanner kycStatus={identity.kycStatus} accountApprovalStatus={identity.accountApprovalStatus} />
          <Card>
            {isKycApproved ? (
              <BankLinkStep customerId={principal.id} />
            ) : (
              <KycStep customerId={principal.id} onCompleted={identity.refetch} />
            )}
          </Card>
        </>
      )}
    </div>
  )
}
