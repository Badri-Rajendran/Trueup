import { Button } from '../../../components/Button'
import { Icon } from '../../../components/Icon'
import { formatDateTime } from '../../../utils/format.js'
import './DunningBanner.css'

const CONFIG_BY_STATUS = {
  retrying: {
    modifier: 'warning',
    icon: 'alert-triangle',
    // A first miss shouldn't interrupt a screen-reader user mid-sentence the way an
    // action-required exhausted state should (design-system §8.9's escalation rule, expressed in
    // the accessibility layer too).
    ariaLive: 'polite',
  },
  exhausted: {
    modifier: 'error',
    icon: 'alert-circle',
    ariaLive: 'assertive',
  },
}

/** Design system §8.9 escalation: first miss is a warning, exhausted is an error — always with a
 * specific next step, never a bare "payment failed." */
export function DunningBanner({ dunning, onUpdatePaymentMethod }) {
  if (!dunning || (dunning.status !== 'retrying' && dunning.status !== 'exhausted')) {
    return null
  }

  const { modifier, icon, ariaLive } = CONFIG_BY_STATUS[dunning.status]
  const message =
    dunning.status === 'exhausted' ? (
      <>
        Payment failed after {dunning.max_attempts} attempts. We won&apos;t retry automatically — add a
        working card to keep your account in good standing.
      </>
    ) : (
      <>
        A fee payment failed (attempt {dunning.attempt_number} of {dunning.max_attempts}) — we&apos;ll
        retry on {formatDateTime(dunning.next_retry_at)}.
      </>
    )

  return (
    <div className={`tu-dunning-banner tu-dunning-banner--${modifier}`} role="alert" aria-live={ariaLive}>
      <span className="tu-dunning-banner__icon">
        <Icon name={icon} size="md" />
      </span>
      <div className="tu-dunning-banner__body">
        <p className="tu-dunning-banner__message">{message}</p>
        <div className="tu-dunning-banner__actions">
          <Button variant="secondary" size="compact" onClick={onUpdatePaymentMethod}>
            Update payment method
          </Button>
        </div>
      </div>
    </div>
  )
}
