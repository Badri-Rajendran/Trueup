import Decimal from 'decimal.js'

// Returns the raw decimal string, or null if invalid.
export function parseQuantity(raw) {
  const trimmed = raw.trim()
  if (!trimmed) return null
  let decimal
  try {
    decimal = new Decimal(trimmed)
  } catch {
    return null
  }
  if (decimal.isNaN() || !decimal.isFinite() || decimal.lte(0)) return null
  return trimmed
}
