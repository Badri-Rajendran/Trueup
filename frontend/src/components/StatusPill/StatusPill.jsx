import { Badge } from '../Badge/Badge.jsx'

/** Design system §7.4, for order/KYC/break/dunning statuses. Tone mapping is each feature's own call. */
export function StatusPill({ tone = 'neutral', icon, children, ...rest }) {
  return (
    <Badge tone={tone} icon={icon} {...rest}>
      {children}
    </Badge>
  )
}
