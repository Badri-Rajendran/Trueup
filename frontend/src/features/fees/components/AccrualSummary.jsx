import { Card } from '../../../components/Card'
import { DetailFields } from '../../../components/DetailFields'
import { EmptyState } from '../../../components/EmptyState'
import { formatMoney } from '../../../utils/format.js'

export function AccrualSummary({ accrual }) {
  if (!accrual) {
    return <EmptyState title="No accrual yet" description="Fee accrual starts after your first valuation day." />
  }

  return (
    <Card>
      <DetailFields
        fields={[
          ...(accrual.peak_value ? [{ label: 'High-water mark', value: formatMoney(accrual.peak_value) }] : []),
          { label: 'Accrued fee (month-to-date)', value: formatMoney(accrual.accrual_to_date) },
        ]}
      />
    </Card>
  )
}
