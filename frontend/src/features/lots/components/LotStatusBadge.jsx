import { Badge } from '../../../components/Badge'

const LABEL_BY_STATUS = { open: 'Open', partial: 'Partially sold', closed: 'Closed' }

/** Status is derived client-side from quantity_remaining vs. quantity_opened (lotSummary.js's
 * `lotStatus`) — an informational disclosure like ProvisionalBadge/SimulatedBadge, not a health
 * signal (design-system §8.8's "disclosure, not a warning" precedent), so it stays neutral tone
 * regardless of which status it is. */
export function LotStatusBadge({ status }) {
  return <Badge tone="neutral">{LABEL_BY_STATUS[status] ?? status}</Badge>
}
