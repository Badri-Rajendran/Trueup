import { Badge } from '../../../components/Badge'

/** Design system §8.8: a data-completeness disclosure, not a warning — never borrows `warning`'s color. */
export function ProvisionalBadge() {
  return <Badge tone="neutral">Provisional</Badge>
}
