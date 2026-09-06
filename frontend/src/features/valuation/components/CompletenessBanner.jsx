import { formatDate } from '../../../utils/format.js'
import './CompletenessBanner.css'

// design-system.md §8.7
export function CompletenessBanner({ asOfDate }) {
  return (
    <div className="tu-completeness-banner">
      Some prices for {formatDate(asOfDate)} haven&apos;t arrived yet — this balance may not include every
      position.
    </div>
  )
}
