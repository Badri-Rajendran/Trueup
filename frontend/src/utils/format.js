import Decimal from 'decimal.js'

// Money/Units/twr are wire strings (never numbers) — all arithmetic here goes through decimal.js,
// never native `+`/`*` on a parsed float (frontend-engineer profile's non-negotiable wire rule).

/** Fixed 2-decimal mask with thousand separators, e.g. "$12,480.06" (design-system §3.3). */
export function formatMoney(value) {
  const decimal = new Decimal(value)
  const isNegative = decimal.isNegative()
  const [whole, fraction] = decimal.abs().toFixed(2).split('.')
  const withCommas = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return `${isNegative ? '-' : ''}$${withCommas}.${fraction}`
}

/** Plain fixed 6-decimal-place string for a Units value — no thousands separator (design-system §3.3). */
export function formatUnitsString(value) {
  return new Decimal(value).toFixed(6)
}

/**
 * Splits a Units string into the first 2 decimals (full weight) and the trailing 4 (dimmed) —
 * design-system §3.3: full precision stays visible, but only the first 2 decimals compete for
 * attention. Returns `{ whole, significant, dimmed }`, e.g. "12.500000" → { whole: "12",
 * significant: "50", dimmed: "0000" }.
 */
export function splitUnitsForDisplay(value) {
  const [whole, fraction] = formatUnitsString(value).split('.')
  return { whole, significant: fraction.slice(0, 2), dimmed: fraction.slice(2) }
}

/** A percentage TWR string, e.g. "0.0512" → "+5.12%". */
export function formatPercent(value) {
  const decimal = new Decimal(value).times(100)
  const isNegative = decimal.isNegative()
  const sign = isNegative ? '-' : '+'
  return `${sign}${decimal.abs().toFixed(2)}%`
}

export function formatDate(isoDateOrDatetime) {
  return new Date(isoDateOrDatetime).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

export function formatDateTime(isoDatetime) {
  return new Date(isoDatetime).toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}
