import Decimal from 'decimal.js'

// `GET /portfolios/models` carries no `asset_class` field yet (backend/app/views/portfolios.py's
// TargetWeightResponse is security_id/symbol/weight_pct only), so the real allocation split shown
// in ModelCard/AllocationBar is derived from a small ticker lookup instead of a wire field.
// Covers the four real model-portfolio securities (VTI, VXUS, BND, BIL). Replace with a real
// `asset_class` field once the backend adds one.
const ASSET_CLASS_BY_SYMBOL = {
  VTI: 'equity',
  VXUS: 'equity',
  BND: 'fixed_income',
  BIL: 'fixed_income',
}

/** Sums a model's `target_weights` into equity/fixed-income/other Decimal totals. */
export function classifyTargetWeights(targetWeights) {
  let equity = new Decimal(0)
  let fixedIncome = new Decimal(0)
  let other = new Decimal(0)

  for (const weight of targetWeights) {
    const decimalWeight = new Decimal(weight.weight_pct)
    const assetClass = ASSET_CLASS_BY_SYMBOL[weight.symbol]
    if (assetClass === 'equity') {
      equity = equity.plus(decimalWeight)
    } else if (assetClass === 'fixed_income') {
      fixedIncome = fixedIncome.plus(decimalWeight)
    } else {
      other = other.plus(decimalWeight)
    }
  }

  return { equity, fixedIncome, other }
}

/** e.g. "72% equities, 28% fixed income" — genuinely derived from the model's real target weights. */
export function describeAllocation(targetWeights) {
  const { equity, fixedIncome, other } = classifyTargetWeights(targetWeights)
  const parts = []
  if (equity.greaterThan(0)) parts.push(`${equity.times(100).toFixed(0)}% equities`)
  if (fixedIncome.greaterThan(0)) parts.push(`${fixedIncome.times(100).toFixed(0)}% fixed income`)
  if (other.greaterThan(0)) parts.push(`${other.times(100).toFixed(0)}% other`)
  return parts.join(', ')
}
