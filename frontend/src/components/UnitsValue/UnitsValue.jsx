import { splitUnitsForDisplay } from '../../utils/format.js'
import './UnitsValue.css'

/** Design system §3.3: full 6dp precision stays visible, but only the first 2 decimals compete for attention. */
export function UnitsValue({ value }) {
  const { whole, significant, dimmed } = splitUnitsForDisplay(value)
  return (
    <span className="tu-units-value">
      {whole}.{significant}
      <span className="tu-units-value__dimmed">{dimmed}</span>
    </span>
  )
}
