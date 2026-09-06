import { useParams } from 'react-router-dom'
import { Card } from '../../components/Card'
import { DetailFields } from '../../components/DetailFields'
import { ErrorState } from '../../components/ErrorState'
import { SimulatedBadge } from '../../components/SimulatedBadge'
import { Skeleton } from '../../components/Skeleton'
import { CustomerFeesPanel } from '../../features/admin-customers/components/CustomerFeesPanel.jsx'
import { KycOverrideForm } from '../../features/admin-customers/components/KycOverrideForm.jsx'
import { OpenBreakCallout } from '../../features/admin-customers/components/OpenBreakCallout.jsx'
import { useCustomerDetail } from '../../features/admin-customers/hooks/useCustomerDetail.js'
import { getErrorMessage } from '../../utils/apiErrorMessage.js'
import '../PageLayout.css'

export function CustomerDetailPage() {
  const { customerId } = useParams()
  const { status, customer, error, refetch } = useCustomerDetail(customerId)

  if (status === 'idle' || status === 'loading') {
    return (
      <div className="tu-page">
        <h1 className="tu-page__title">Customer detail</h1>
        <Skeleton height="200px" />
      </div>
    )
  }

  if (status === 'error') {
    if (error?.code === 'not_found') {
      return (
        <div className="tu-page">
          <h1 className="tu-page__title">Customer detail</h1>
          <p>Customer not found.</p>
        </div>
      )
    }
    return (
      <div className="tu-page">
        <h1 className="tu-page__title">Customer detail</h1>
        <ErrorState description={getErrorMessage(error)} onRetry={refetch} />
      </div>
    )
  }

  return (
    <div className="tu-page">
      <h1 className="tu-page__title">Customer detail</h1>
      {customer.has_open_break && <OpenBreakCallout />}
      <Card>
        <h2 className="tu-page__section-title">
          Profile <SimulatedBadge />
        </h2>
        <DetailFields
          fields={[
            { label: 'Email', value: customer.email },
            { label: 'KYC status', value: customer.kyc_status },
            { label: 'Account approval', value: customer.account_approval_status },
          ]}
        />
      </Card>
      <Card>
        <h2 className="tu-page__section-title">
          KYC override <SimulatedBadge />
        </h2>
        <KycOverrideForm customer={customer} onOverridden={refetch} />
      </Card>
      <Card>
        <h2 className="tu-page__section-title">Fees</h2>
        <CustomerFeesPanel customerId={customer.id} />
      </Card>
    </div>
  )
}
