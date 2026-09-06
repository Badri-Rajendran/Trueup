import { Badge } from '../Badge'

/** Design system §8.3. Marks a screen/section as backed by mock data, not a live route. */
export function SimulatedBadge({ className }) {
  return (
    <Badge tone="neutral" className={className}>
      Simulated
    </Badge>
  )
}
