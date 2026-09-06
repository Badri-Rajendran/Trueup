import { DetailFields } from '../../../components/DetailFields'
import { ErrorState } from '../../../components/ErrorState'
import { Skeleton } from '../../../components/Skeleton'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { formatMoney } from '../../../utils/format.js'
import { useCustomerFees } from '../hooks/useCustomerFees.js'

export function CustomerFeesPanel({ customerId }) {
  const { status, accrual, error, refetch } = useCustomerFees(customerId)

  if (status === 'idle' || status === 'loading') {
    return <Skeleton height="80px" />
  }

  if (status === 'error') {
    return <ErrorState description={getErrorMessage(error)} onRetry={refetch} />
  }

  return (
    <DetailFields
      fields={[
        { label: 'High-water mark', value: formatMoney(accrual.peak_value) },
        { label: 'Month-to-date gain', value: formatMoney(accrual.month_to_date_gain) },
        { label: 'Accrued fee', value: formatMoney(accrual.month_to_date_fee) },
      ]}
    />
  )
}
