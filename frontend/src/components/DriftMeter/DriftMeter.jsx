import Decimal from 'decimal.js'
import { Icon } from '../Icon'
import './DriftMeter.css'

function formatWeightPct(value) {
  return `${new Decimal(value).times(100).toFixed(1)}%`
}

function formatDriftPp(value) {
  const decimal = new Decimal(value).times(100)
  const sign = decimal.isNegative() ? '-' : '+'
  return `${sign}${decimal.abs().toFixed(1)}pp`
}

/**
 * A horizontal track showing a holding's current weight against its target, with the signed drift
 * printed as text (design-system.md's DriftMeter spec) — never color alone for `isFlagged`, which
 * also gets a distinct icon+outline treatment, not just a color swap.
 *
 * `hasTarget={false}` renders the current weight as plain text with no meter — the implicit CASH
 * line (`security_id: null`, `HoldingResponse`'s own convention) has nothing to compare against,
 * so forcing a meter onto it would imply a target that doesn't exist.
 */
export function DriftMeter({ currentWeightPct, targetWeightPct, driftPct, isFlagged = false, hasTarget = true }) {
  if (!hasTarget) {
    return <span className="tu-drift-meter__value-only">{formatWeightPct(currentWeightPct)}</span>
  }

  const currentPct = Math.min(100, Math.max(0, new Decimal(currentWeightPct).times(100).toNumber()))
  const targetPct = Math.min(100, Math.max(0, new Decimal(targetWeightPct).times(100).toNumber()))

  return (
    <div className={`tu-drift-meter${isFlagged ? ' tu-drift-meter--flagged' : ''}`}>
      <div
        className="tu-drift-meter__track"
        role="img"
        aria-label={`Current weight ${formatWeightPct(currentWeightPct)}, target ${formatWeightPct(targetWeightPct)}, drift ${formatDriftPp(driftPct)}${isFlagged ? ', flagged' : ''}`}
      >
        <span className="tu-drift-meter__fill" style={{ width: `${currentPct}%` }} />
        <span className="tu-drift-meter__tick" style={{ left: `${targetPct}%` }} />
      </div>
      <span className="tu-drift-meter__readout">
        {isFlagged && <Icon name="alert-triangle" size="sm" className="tu-drift-meter__flag-icon" />}
        {formatDriftPp(driftPct)}
      </span>
    </div>
  )
}
