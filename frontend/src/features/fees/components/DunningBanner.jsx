import { formatDateTime } from '../../../utils/format.js'
import './DunningBanner.css'

/** Design system §8.9: same escalation logic as §8.4 — first miss is warning, exhausted is error, always with specific next-step copy. */
export function DunningBanner({ dunning }) {
  if (!dunning || dunning.status !== 'retrying' && dunning.status !== 'exhausted') {
    return null
  }

  if (dunning.status === 'exhausted') {
    return (
      <div className="tu-dunning-banner tu-dunning-banner--error">
        Payment failed after {dunning.max_attempts} attempts. Update your payment method to keep your account in good
        standing.
      </div>
    )
  }

  return (
    <div className="tu-dunning-banner tu-dunning-banner--warning">
      A fee payment failed (attempt {dunning.attempt_number} of {dunning.max_attempts}) — we&apos;ll retry on{' '}
      {formatDateTime(dunning.next_retry_at)}.
    </div>
  )
}
