import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { Skeleton } from '../components/Skeleton'
import { StatusPill } from '../components/StatusPill'
import { useSession } from '../contexts/SessionContext.jsx'
import { CashSummary } from '../features/funding/components/CashSummary.jsx'
import { DepositForm } from '../features/funding/components/DepositForm.jsx'
import { FundingHistory } from '../features/funding/components/FundingHistory.jsx'
import { WithdrawForm } from '../features/funding/components/WithdrawForm.jsx'
import { useCurrentBankLink } from '../features/funding/hooks/useCurrentBankLink.js'
import { BankLinkStep } from '../features/onboarding/components/BankLinkStep.jsx'
import './FundingPage.css'
import './PageLayout.css'

function BankLinkStatusCard({ customerId }) {
  const currentBankLink = useCurrentBankLink()

  if (currentBankLink.status === 'idle' || currentBankLink.status === 'loading') {
    return <Skeleton height="60px" />
  }

  if (currentBankLink.status === 'error') {
    return <ErrorState onRetry={currentBankLink.refetch} />
  }

  if (currentBankLink.bankLink?.status === 'active') {
    return (
      <Card>
        <p className="tu-funding-page__bank-status-label">Bank account</p>
        <StatusPill tone="success">Linked</StatusPill>
      </Card>
    )
  }

  return (
    <Card>
      {currentBankLink.bankLink?.status === 'requires_reauth' && (
        <>
          <p className="tu-funding-page__bank-status-label">Bank account</p>
          <StatusPill tone="warning">Needs reconnecting</StatusPill>
        </>
      )}
      <BankLinkStep customerId={customerId} onCompleted={currentBankLink.refetch} />
    </Card>
  )
}

export function FundingPage() {
  const { principal } = useSession()

  return (
    <div className="tu-page">
      <h1 className="tu-page__title">Funding</h1>
      <Card>
        <CashSummary />
      </Card>
      <BankLinkStatusCard customerId={principal.id} />
      <div className="tu-funding-page__forms">
        <Card>
          <DepositForm customerId={principal.id} />
        </Card>
        <Card>
          <WithdrawForm customerId={principal.id} />
        </Card>
      </div>
      <div>
        <h2 className="tu-page__section-title">Funding history</h2>
        <FundingHistory />
      </div>
    </div>
  )
}
