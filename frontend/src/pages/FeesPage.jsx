import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { Skeleton } from '../components/Skeleton'
import { AccrualSummary } from '../features/fees/components/AccrualSummary.jsx'
import { ChargeHistory } from '../features/fees/components/ChargeHistory.jsx'
import { DunningBanner } from '../features/fees/components/DunningBanner.jsx'
import { PaymentMethodForm } from '../features/fees/components/PaymentMethodForm.jsx'
import { useFees } from '../features/fees/hooks/useFees.js'
import { getErrorMessage } from '../utils/apiErrorMessage.js'
import './PageLayout.css'

export function FeesPage() {
  const { status, accrual, charges, dunning, paymentMethod, error, refetch } = useFees()

  if (status === 'idle' || status === 'loading') {
    return (
      <div className="tu-page">
        <h1 className="tu-page__title">Fees</h1>
        <Skeleton height="120px" />
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div className="tu-page">
        <h1 className="tu-page__title">Fees</h1>
        <ErrorState description={getErrorMessage(error)} onRetry={refetch} />
      </div>
    )
  }

  return (
    <div className="tu-page">
      <h1 className="tu-page__title">Fees</h1>
      <DunningBanner dunning={dunning} />
      <AccrualSummary accrual={accrual} />
      <div>
        <h2 className="tu-page__section-title">Charge history</h2>
        <ChargeHistory charges={charges} />
      </div>
      <Card>
        <h2 className="tu-page__section-title">Payment method</h2>
        <PaymentMethodForm currentPaymentMethod={paymentMethod} onAttached={refetch} />
      </Card>
    </div>
  )
}
