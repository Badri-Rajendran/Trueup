import { Card } from '../../../components/Card'
import { formatMoney } from '../../../utils/format.js'
import { BillingPeriodProgress } from './BillingPeriodProgress.jsx'
import './AccrualSummary.css'

/** Emptiness is decided once, at the page level (`hasNoFeeActivity`, utils/feeSummary.js) — this
 * component only ever renders the loaded, active-accrual state. */
export function AccrualSummary({ accrual, billingPeriod }) {
  return (
    <Card className="tu-accrual-summary">
      <span className="tu-accrual-summary__label">Accrued this month</span>
      <span className="tu-accrual-summary__value">{formatMoney(accrual.accrual_to_date)}</span>
      <p className="tu-accrual-summary__explainer">
        A performance fee is charged only on gains above your account&apos;s previous peak. It
        accrues day by day and is billed once the billing period closes.
      </p>
      <BillingPeriodProgress period={billingPeriod} className="tu-accrual-summary__progress" />
    </Card>
  )
}
