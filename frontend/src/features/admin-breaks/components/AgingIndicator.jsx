import './AgingIndicator.css'

const SECONDS_PER_DAY = 86400

/** Design system §8.4 age-escalation tiers. */
export function AgingIndicator({ ageSeconds }) {
  const days = ageSeconds / SECONDS_PER_DAY
  let tier = 'mild'
  let label = '<1d'
  if (days >= 1 && days <= 3) {
    tier = 'warning'
    label = `${Math.floor(days)}d`
  } else if (days > 3) {
    tier = 'error'
    label = `${Math.floor(days)}d`
  }

  return <span className={`tu-aging-indicator tu-aging-indicator--${tier}`}>{label}</span>
}
