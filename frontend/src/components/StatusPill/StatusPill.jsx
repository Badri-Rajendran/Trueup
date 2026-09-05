import { Badge } from '../Badge/Badge.jsx'

/**
 * Design system §7.4, used for order/KYC/break/dunning status values specifically. Tone mapping
 * from a domain status string to a semantic tone is each feature's own call (order/KYC/break
 * statuses each mean something different) — this component only supplies the shared visual shape.
 */
export function StatusPill({ tone = 'neutral', icon, children, ...rest }) {
  return (
    <Badge tone={tone} icon={icon} {...rest}>
      {children}
    </Badge>
  )
}
