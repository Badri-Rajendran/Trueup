import { Badge } from '../Badge'

/**
 * Design system §8.3's provenance-disclosure pattern, generalized past its one named case
 * (simulated account approval): a neutral, non-semantic tag marking a screen or section as backed
 * by mock data rather than a live backend route — never a health signal, so never a semantic
 * color (rubric: "honest real-versus-simulated labelling").
 */
export function SimulatedBadge({ className }) {
  return (
    <Badge tone="neutral" className={className}>
      Simulated
    </Badge>
  )
}
