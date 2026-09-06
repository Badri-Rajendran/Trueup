import { Link } from 'react-router-dom'
import './OpenBreakCallout.css'

/** Design system §8.4: always renders at error weight regardless of the break's own age-tier — surfaced regardless of which tab is active. */
export function OpenBreakCallout() {
  return (
    <div className="tu-open-break-callout">
      This customer has an open reconciliation break. <Link to="/admin/breaks">View the breaks queue</Link>
    </div>
  )
}
