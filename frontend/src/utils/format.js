import Decimal from 'decimal.js'

// Money/Units/twr are wire strings; arithmetic goes through decimal.js, never native +/* on a float.

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

/** Splits a Units string into whole/significant(2dp)/dimmed(4dp) (design-system §3.3). */
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

/**
 * A plain calendar date (`YYYY-MM-DD`, e.g. `assigned_at`) has no time zone of its own — it's
 * already anchored to America/New_York server-side. `new Date("2026-09-06")` parses that as UTC
 * midnight, which then renders as the *prior* day in any timezone behind UTC (all of the US).
 * Parsing the components directly and constructing a local-midnight `Date` keeps the calendar date
 * as-is regardless of the viewer's timezone. A full datetime (has a "T") still parses normally.
 */
export function formatDate(isoDateOrDatetime) {
  const plainDateMatch = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoDateOrDatetime)
  const date = plainDateMatch
    ? new Date(Number(plainDateMatch[1]), Number(plainDateMatch[2]) - 1, Number(plainDateMatch[3]))
    : new Date(isoDateOrDatetime)
  return date.toLocaleDateString(undefined, {
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
