import { formatDate } from '../../../utils/format.js'
import './CompletenessBanner.css'

/**
 * Design system §8.7's stale/missing-close banner. The "expected market holiday" banner from the
 * same section isn't needed here: `as_of_date` already resolves to the correct prior trading day
 * via the market calendar before this response is built, so a holiday never produces
 * `completeness: 'partial'` — only a genuinely missing close does (FR-15,
 * `ValuationService.value_book`). `BalanceResponse` doesn't name which security is missing, so
 * this stays honest rather than inventing a ticker it doesn't have.
 */
export function CompletenessBanner({ asOfDate }) {
  return (
    <div className="tu-completeness-banner">
      Some prices for {formatDate(asOfDate)} haven&apos;t arrived yet — this balance may not include every
      position.
    </div>
  )
}
