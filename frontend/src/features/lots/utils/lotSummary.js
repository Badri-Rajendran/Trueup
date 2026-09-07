import Decimal from 'decimal.js'

// Pure helpers for the Tax lots page — no React, no API calls. `GET /lots` (backend/app/views/lots.py)
// has no `status` field and no server-side sort/filter/pagination, so every derivation below runs
// client-side against the full lot list. Money/Units/Price fields are wire strings throughout —
// arithmetic always goes through decimal.js, never native +/* on a parsed float.

/**
 * A lot's status derived from `quantity_remaining` vs `quantity_opened`/`"0"` — the wire response
 * has no `status` field of its own. `closed` first (a fully-sold lot regardless of how it opened),
 * then `open` (nothing sold yet), else `partial`.
 */
export function lotStatus(lot) {
  const remaining = new Decimal(lot.quantity_remaining)
  if (remaining.isZero()) return 'closed'
  const opened = new Decimal(lot.quantity_opened)
  return remaining.equals(opened) ? 'open' : 'partial'
}

/** `wash_sale_disallowed` is never null on the wire — `"0.0000"` reads as "no wash sale here." */
export function hasWashSaleDisallowed(lot) {
  return new Decimal(lot.wash_sale_disallowed).greaterThan(0)
}

/**
 * The correct IRS "day after acquisition" long-term test: a lot bought 2025-01-01 turns long-term
 * on 2026-01-01, not after 365 days held (which would be off by one at the boundary). Built with
 * the local 3-arg `Date` constructor throughout, never a parsed ISO string — `acquired_at` is a
 * plain `YYYY-MM-DD` calendar date with no time zone of its own (same UTC-midnight trap
 * `utils/format.js`'s `formatDate` documents and avoids).
 */
export function holdingPeriod(acquiredAtIsoDate, today = new Date()) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(acquiredAtIsoDate)
  if (!match) {
    throw new Error(`holdingPeriod: expected a plain YYYY-MM-DD date, got "${acquiredAtIsoDate}"`)
  }
  const [, yearStr, monthStr, dayStr] = match
  const acquired = new Date(Number(yearStr), Number(monthStr) - 1, Number(dayStr))
  const longTermFrom = new Date(acquired.getFullYear() + 1, acquired.getMonth(), acquired.getDate())
  const todayMidnight = new Date(today.getFullYear(), today.getMonth(), today.getDate())
  return longTermFrom <= todayMidnight ? 'long-term' : 'short-term'
}

/** True when any still-open (non-closed) lot has no confirmed price yet — a page-level totals note,
 * never a silent `—` standing in for "this total might not include everything." */
export function hasMissingPrices(lots) {
  return lots.some((lot) => lotStatus(lot) !== 'closed' && lot.current_price === null)
}

/** Sums only the lots that carry a non-null value for `field`; returns `null` (not zero) when none
 * do, so "no data" stays distinguishable from "sums to zero." */
function sumNullableField(lots, field) {
  const contributors = lots.filter((lot) => lot[field] !== null)
  if (contributors.length === 0) return null
  return contributors.reduce((sum, lot) => sum.plus(lot[field]), new Decimal(0))
}

export function totalMarketValue(lots) {
  return sumNullableField(lots, 'market_value')
}

export function totalUnrealizedGainLoss(lots) {
  return sumNullableField(lots, 'unrealized_gain_loss')
}

/** `wash_sale_disallowed` is never null, so this total is always summable — never `null`. */
export function totalWashSaleDisallowed(lots) {
  return lots.reduce((sum, lot) => sum.plus(lot.wash_sale_disallowed), new Decimal(0))
}

export function filterLotsByStatus(lots, statusFilter) {
  if (statusFilter === 'all') return lots
  return lots.filter((lot) => lotStatus(lot) === statusFilter)
}

const SORT_FIELD_BY_COLUMN = {
  quantity: 'quantity_remaining',
  adjustedBasis: 'adjusted_basis',
  marketValue: 'market_value',
  unrealizedGainLoss: 'unrealized_gain_loss',
}

/** Sorts a copy of `lots`; nullable numeric columns (market value, unrealized gain/loss) always
 * sort their `null` rows to the end regardless of direction, rather than treating null as zero. */
export function sortLots(lots, { column, direction }) {
  const dir = direction === 'desc' ? -1 : 1
  const sorted = [...lots]

  sorted.sort((a, b) => {
    if (column === 'symbol') {
      return dir * a.symbol.localeCompare(b.symbol)
    }
    const field = SORT_FIELD_BY_COLUMN[column]
    if (!field) return 0
    const aValue = a[field]
    const bValue = b[field]
    if (aValue === null && bValue === null) return 0
    if (aValue === null) return 1
    if (bValue === null) return -1
    return dir * new Decimal(aValue).comparedTo(bValue)
  })

  return sorted
}
