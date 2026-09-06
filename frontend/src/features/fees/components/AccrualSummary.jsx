import { Card } from '../../../components/Card'
import { DetailFields } from '../../../components/DetailFields'
import { formatMoney } from '../../../utils/format.js'

export function AccrualSummary({ accrual }) {
  if (!accrual) {
    return <p>No accrual yet.</p>
  }

  return (
    <Card>
      <DetailFields
        fields={[
          { label: 'High-water mark', value: formatMoney(accrual.peak_value) },
          { label: 'Month-to-date gain', value: formatMoney(accrual.month_to_date_gain) },
          { label: 'Accrued fee', value: formatMoney(accrual.month_to_date_fee) },
        ]}
      />
    </Card>
  )
}
