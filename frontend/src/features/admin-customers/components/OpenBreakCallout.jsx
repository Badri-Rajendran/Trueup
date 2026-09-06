import { Link } from 'react-router-dom'
import './OpenBreakCallout.css'

/** Design system §8.4, always error weight. */
export function OpenBreakCallout() {
  return (
    <div className="tu-open-break-callout">
      This customer has an open reconciliation break. <Link to="/admin/breaks">View the breaks queue</Link>
    </div>
  )
}
