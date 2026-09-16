import { Link } from 'react-router-dom'
import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { Skeleton } from '../components/Skeleton'
import { useSession } from '../contexts/SessionContext.jsx'
import { BankLinkCard } from '../features/funding/components/BankLinkCard.jsx'
import { useCurrentBankLink } from '../features/funding/hooks/useCurrentBankLink.js'
import { IdentityStatusBanner } from '../features/onboarding/components/IdentityStatusBanner.jsx'
import { useIdentityStatus } from '../features/onboarding/hooks/useIdentityStatus.js'
import { ProfileForm } from '../features/profile/components/ProfileForm.jsx'
import { useProfile } from '../features/profile/hooks/useProfile.js'
import { StatementList } from '../features/statements/components/StatementList.jsx'
import { getErrorMessage } from '../utils/apiErrorMessage.js'
import './AccountPage.css'
import './PageLayout.css'

function ProfileSection() {
  const profile = useProfile()

  if (profile.status === 'idle' || profile.status === 'loading') {
    return (
      <Card>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
          <Skeleton height="40px" />
          <Skeleton height="40px" />
          <Skeleton height="40px" />
        </div>
      </Card>
    )
  }

  if (profile.status === 'error') {
    return <ErrorState description={getErrorMessage(profile.error)} onRetry={profile.refetch} />
  }

  return (
    <Card>
      <ProfileForm profile={profile.profile} onSaved={profile.applyUpdate} />
    </Card>
  )
}

/**
 * Read-only here -- `AccountPage` is only reachable once `RequireOnboarded` has already let a
 * customer through (KYC + account approval both `approved`, ADR 21), so both gates below are
 * always shown approved. The link out to `/onboarding` is for the one remaining in-progress state
 * this guard doesn't check: bank-link (see `BankAccountSection` below), and it deliberately does
 * NOT embed `OnboardingSteps`/`KycStep` here -- those are the wizard's own interactive components,
 * not a status display (structure.md §2.2: `/onboarding` "stays reachable post-approval too,
 * read-only, as the account's identity/bank-link status view").
 */
function IdentitySection() {
  const { principal } = useSession()
  const identity = useIdentityStatus(principal.id)

  if (identity.status === 'idle' || identity.status === 'loading') {
    return <Skeleton height="72px" />
  }

  if (identity.status === 'error') {
    return <ErrorState description={getErrorMessage(identity.error)} onRetry={identity.refetch} />
  }

  return (
    <div className="tu-account-page__identity">
      <IdentityStatusBanner kycStatus={identity.kycStatus} accountApprovalStatus={identity.accountApprovalStatus} />
      <Link to="/onboarding" className="tu-account-page__onboarding-link">
        View onboarding details
      </Link>
    </div>
  )
}

/** Same `BankLinkCard` + `useCurrentBankLink()` pair Money uses (structure.md IA: bank-link lives
 * on Account, but the link/reconnect action is equally at home wherever the status is shown). */
function BankAccountSection() {
  const { principal } = useSession()
  const bankLink = useCurrentBankLink()

  return (
    <BankLinkCard
      customerId={principal.id}
      status={bankLink.status}
      bankLink={bankLink.bankLink}
      error={bankLink.error}
      onRetry={bankLink.refetch}
      onLinked={bankLink.refetch}
    />
  )
}

/** The Account destination (structure.md/Task 11): profile, both identity gates, bank link, and
 * statements -- the fourth of the 5-destination nav's real screens (Task 7). `StatementsPage.jsx`
 * (11 lines of pure chrome around `StatementList`) is gone; `StatementList` is inlined directly
 * here instead of preserved as a purposeless wrapper. */
export function AccountPage() {
  return (
    <div className="tu-page tu-account-page">
      <div>
        <h1 className="tu-page__title">Account</h1>
        <p className="tu-account-page__subtitle">
          Your profile, identity verification, linked bank account, and statements.
        </p>
      </div>

      <div>
        <h2 className="tu-page__section-title">Profile</h2>
        <ProfileSection />
      </div>

      <div>
        <h2 className="tu-page__section-title">Identity verification</h2>
        <IdentitySection />
      </div>

      <div>
        <h2 className="tu-page__section-title">Bank account</h2>
        <BankAccountSection />
      </div>

      <div>
        <h2 className="tu-page__section-title">Statements</h2>
        <StatementList />
      </div>
    </div>
  )
}
