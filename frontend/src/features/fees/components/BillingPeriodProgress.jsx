import { formatDate } from '../../../utils/format.js'
import './BillingPeriodProgress.css'

/**
 * How far into the current calendar-month billing period today is. `period` comes from
 * `getBillingPeriod()` (utils/feeSummary.js) — pure date math, no valuation call. The bar is
 * `aria-hidden`: the caption below it carries the whole meaning in words, so there's no
 * color-only/graphic-only signal to separately account for (design-system §2.4, §9).
 */
export function BillingPeriodProgress({ period, className = '' }) {
  return (
    <div className={['tu-billing-period', className].filter(Boolean).join(' ')}>
      <div className="tu-billing-period__track" aria-hidden="true">
        <div className="tu-billing-period__fill" style={{ width: `${period.percentElapsed}%` }} />
      </div>
      <p className="tu-billing-period__caption">
        Day {period.dayOfPeriod} of {period.totalDays} in this billing period · next charge on{' '}
        {formatDate(period.nextChargeDate)}
      </p>
    </div>
  )
}
