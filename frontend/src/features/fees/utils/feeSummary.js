import Decimal from 'decimal.js'

// Pure helpers for the Fees page — no React, no API calls. Kept separate from the components so
// the billing-period math and the empty-state check are each independently reasoned about and
// reusable (FeesPage.jsx needs `hasNoFeeActivity` at the page level; AccrualSummary needs
// `getBillingPeriod`).

// `GET /fees` always returns an accrual object (`FeeSummaryResponse`, backend/app/views/fees.py)
// — accrual is never absent, so this is a real zero-activity check, not a falsy check.
// `high_water_mark` is only created on a customer's first valuation day (HighWaterMarkService
// .get_or_create); until then peak_value is null, there are no charges, and accrual_to_date is zero.
export function hasNoFeeActivity(accrual, charges) {
  return accrual.peak_value === null && charges.length === 0 && new Decimal(accrual.accrual_to_date).isZero()
}

function toIsoDate(date) {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

/**
 * A performance fee's billing period is a calendar month (`docs/specs/10-performance-fees.md`
 * §5). This is pure date math — never a call to the balance/valuation API — deliberately: the fee
 * summary has no field for the customer's current portfolio value, and approximating one from
 * elsewhere would risk implying "progress toward a fee" from a plain deposit, which is exactly
 * the thing the backend's TWR-adjusted high-water-mark math exists to prevent (spec §8, edge case
 * 2). Built with the local 3-arg `Date` constructor throughout, never a parsed ISO string — see
 * `utils/format.js`'s `formatDate` for the UTC-midnight trap this avoids. Returns `YYYY-MM-DD`
 * strings (not `Date` objects) so callers route into `formatDate`'s timezone-safe plain-date
 * branch.
 */
export function getBillingPeriod(now = new Date()) {
  const year = now.getFullYear()
  const month = now.getMonth()

  const startDate = new Date(year, month, 1)
  const endDate = new Date(year, month + 1, 0)
  const nextChargeDate = new Date(year, month + 1, 1)

  const dayOfPeriod = now.getDate()
  const totalDays = endDate.getDate()
  const percentElapsed = Math.min(100, Math.max(0, (dayOfPeriod / totalDays) * 100))

  return {
    startDate: toIsoDate(startDate),
    endDate: toIsoDate(endDate),
    nextChargeDate: toIsoDate(nextChargeDate),
    dayOfPeriod,
    totalDays,
    percentElapsed,
  }
}

/** Sum of `succeeded` charges only — a pending or failed charge is not money paid. Money is a wire
 * string throughout; arithmetic goes through decimal.js, never native +/* on a float. */
export function sumSucceededCharges(charges) {
  const succeeded = charges.filter((charge) => charge.status === 'succeeded')
  const total = succeeded.reduce((sum, charge) => sum.plus(charge.total_accrued), new Decimal(0))
  return { total: total.toFixed(2), count: succeeded.length }
}
