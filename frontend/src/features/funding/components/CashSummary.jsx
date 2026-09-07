import { formatMoney } from '../../../utils/format.js'
import './CashSummary.css'

/**
 * Design-system §8.2 — Withdrawable and Investable as two co-equal stat figures, never merged
 * into one "Balance." Purely presentational: `cashSummary` arrives as a prop and there is no fetch
 * or loading/error branch here — this component used to run its own `useCashPolicy()` call on top
 * of the page's `useFunding()` fetch, which was the source of the double `GET /cash-summary`
 * request per page load; the fetch now lives in `useFunding` alone (see `hooks/useFunding.js`).
 *
 * `emphasize` opts one figure down to `body`/`text-secondary` for a form scoped to one policy
 * function (`WithdrawForm` passes `"withdrawable"` so Investable reads quieter, per ADR 5) —
 * omitted (Dashboard/Funding overview usage), both stay equal weight.
 */
export function CashSummary({ cashSummary, emphasize }) {
  return (
    <div className="tu-cash-summary">
      <div className={`tu-cash-summary__figure${emphasize === 'investable' ? ' tu-cash-summary__figure--quiet' : ''}`}>
        <span className="tu-cash-summary__label">Withdrawable</span>
        <span className="tu-cash-summary__value">{formatMoney(cashSummary.withdrawable)}</span>
      </div>
      <div className={`tu-cash-summary__figure${emphasize === 'withdrawable' ? ' tu-cash-summary__figure--quiet' : ''}`}>
        <span className="tu-cash-summary__label">Investable</span>
        <span className="tu-cash-summary__value">{formatMoney(cashSummary.investable)}</span>
      </div>
    </div>
  )
}
