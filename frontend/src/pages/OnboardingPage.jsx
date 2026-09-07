import { Link } from 'react-router-dom'
import { Button } from '../components/Button'
import { ErrorState } from '../components/ErrorState'
import { Skeleton } from '../components/Skeleton'
import { useSession } from '../contexts/SessionContext.jsx'
import { BankLinkStep } from '../features/onboarding/components/BankLinkStep.jsx'
import { IdentityStatusBanner } from '../features/onboarding/components/IdentityStatusBanner.jsx'
import { KycStep } from '../features/onboarding/components/KycStep.jsx'
import { OnboardingSteps, StepRow } from '../features/onboarding/components/OnboardingSteps.jsx'
import { useIdentityStatus } from '../features/onboarding/hooks/useIdentityStatus.js'
import { useCurrentBankLink } from '../features/funding/hooks/useCurrentBankLink.js'
import './OnboardingPage.css'

function BankLinkSection({ customerId, bankLink, showTitle }) {
  if (bankLink.status === 'idle' || bankLink.status === 'loading') {
    return <Skeleton height="40px" width="220px" />
  }

  if (bankLink.status === 'error') {
    return <ErrorState onRetry={bankLink.refetch} />
  }

  if (bankLink.bankLink?.status === 'active') {
    return <p className="tu-onboarding-step__description">Bank account linked.</p>
  }

  return <BankLinkStep customerId={customerId} onCompleted={bankLink.refetch} showTitle={showTitle} />
}

export function OnboardingPage() {
  const { principal } = useSession()
  const identity = useIdentityStatus(principal.id)
  const bankLink = useCurrentBankLink()

  const isKycApproved = identity.kycStatus === 'approved'
  const isBankLinked = bankLink.bankLink?.status === 'active'
  const isFullyOnboarded = isKycApproved && isBankLinked

  const kycStepStatus = isKycApproved ? 'completed' : 'current'
  // Bank-linking is only ever reachable once identity is approved (FR-3/ADR 21) -- while KYC is
  // pending, this step is genuinely locked, not just visually deprioritized.
  const bankStepStatus = isBankLinked ? 'completed' : isKycApproved ? 'current' : 'locked'

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
          <OnboardingSteps>
            <StepRow number={1} status={kycStepStatus} title="Verify your identity">
              {isKycApproved ? (
                <p className="tu-onboarding-step__description">Identity verified.</p>
              ) : (
                <KycStep customerId={principal.id} kycStatus={identity.kycStatus} onCompleted={identity.refetch} />
              )}
            </StepRow>
            <StepRow number={2} status={bankStepStatus} title="Link your bank" last>
              {isKycApproved ? (
                <BankLinkSection customerId={principal.id} bankLink={bankLink} showTitle={false} />
              ) : (
                <p className="tu-onboarding-step__description">Available once your identity is verified.</p>
              )}
            </StepRow>
          </OnboardingSteps>
          {isFullyOnboarded && (
            <div className="tu-onboarding-page__complete">
              <p className="tu-onboarding-page__complete-text">You&apos;re all set — your account is ready to invest.</p>
              <Link to="/portfolio" className="tu-button tu-button--primary">
                View portfolio options
              </Link>
            </div>
          )}
        </>
      )}
    </div>
  )
}
