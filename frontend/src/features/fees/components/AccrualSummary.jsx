import Decimal from 'decimal.js'
import { Card } from '../../../components/Card'
import { DetailFields } from '../../../components/DetailFields'
import { EmptyState } from '../../../components/EmptyState'
import { formatMoney } from '../../../utils/format.js'

// `GET /fees` always returns an accrual object (`FeeSummaryResponse`, backend/app/views/fees.py)
// — accrual is never absent, so the empty state is a real zero-activity check, not a falsy check.
// `high_water_mark` is only created on a customer's first valuation day (HighWaterMarkService
// .get_or_create); until then peak_value is null, there are no charges, and accrual_to_date is zero.
function hasNoActivityYet(accrual, charges) {
  return accrual.peak_value === null && charges.length === 0 && new Decimal(accrual.accrual_to_date).isZero()
}

export function AccrualSummary({ accrual, charges }) {
  if (hasNoActivityYet(accrual, charges)) {
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
