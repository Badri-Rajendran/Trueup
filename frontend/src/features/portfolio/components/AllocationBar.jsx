import { classifyTargetWeights, describeAllocation } from '../utils/assetClass.js'
import './AllocationBar.css'

/** Horizontal segmented bar: equity vs. fixed-income share of a model's real target weights. */
export function AllocationBar({ targetWeights }) {
  const { equity, fixedIncome, other } = classifyTargetWeights(targetWeights)

  return (
    <div
      className="tu-allocation-bar"
      role="img"
      aria-label={`Allocation: ${describeAllocation(targetWeights)}`}
    >
      {equity.greaterThan(0) && (
        <span
          className="tu-allocation-bar__segment tu-allocation-bar__segment--equity"
          style={{ width: `${equity.times(100).toFixed(4)}%` }}
        />
      )}
      {fixedIncome.greaterThan(0) && (
        <span
          className="tu-allocation-bar__segment tu-allocation-bar__segment--fixed-income"
          style={{ width: `${fixedIncome.times(100).toFixed(4)}%` }}
        />
      )}
      {other.greaterThan(0) && (
        <span
          className="tu-allocation-bar__segment tu-allocation-bar__segment--other"
          style={{ width: `${other.times(100).toFixed(4)}%` }}
        />
      )}
    </div>
  )
}
