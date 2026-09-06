import Decimal from 'decimal.js'

/** Validates a user-entered amount and returns a wire-ready 2-decimal Money string, or `null`. */
export function parseAmount(raw) {
  const trimmed = raw.trim()
  if (!trimmed) return null
  let decimal
  try {
    decimal = new Decimal(trimmed)
  } catch {
    return null
  }
  if (decimal.isNaN() || !decimal.isFinite() || decimal.lte(0)) return null
  return decimal.toFixed(2)
}
