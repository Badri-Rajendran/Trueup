import { Card } from '../components/Card'
import { ErrorState } from '../components/ErrorState'
import { Skeleton } from '../components/Skeleton'
import { useSession } from '../contexts/SessionContext.jsx'
import { AccrualSummary } from '../features/fees/components/AccrualSummary.jsx'
import { ChargeHistory } from '../features/fees/components/ChargeHistory.jsx'
import { DunningBanner } from '../features/fees/components/DunningBanner.jsx'
import { PaymentMethodForm } from '../features/fees/components/PaymentMethodForm.jsx'
import { useFees } from '../features/fees/hooks/useFees.js'
import { getErrorMessage } from '../utils/apiErrorMessage.js'
import './PageLayout.css'

export function FeesPage() {
  const { principal } = useSession()
  const { status, accrual, charges, dunning, paymentMethod, error, refetch, setPaymentMethod } = useFees()

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
      <div>
        <h2 className="tu-page__section-title">Accrual</h2>
        <AccrualSummary accrual={accrual} charges={charges} />
      </div>
      <div>
        <h2 className="tu-page__section-title">Charge history</h2>
        <ChargeHistory charges={charges} />
      </div>
      <div id="payment-method">
        <h2 className="tu-page__section-title">Payment method</h2>
        <Card>
          <PaymentMethodForm customerId={principal.id} currentPaymentMethod={paymentMethod} onAttached={setPaymentMethod} />
        </Card>
      </div>
    </div>
  )
}
