import './Badge.css'

/**
 * Design system §7.4. `tone="neutral"` is the provenance-disclosure treatment (§8.3 "Simulated",
 * §8.8 "Provisional") — deliberately not a semantic color. Always pair with a short label word,
 * never a bare color dot.
 */
export function Badge({ tone = 'neutral', icon, className = '', children, ...rest }) {
  return (
    <span className={['tu-badge', `tu-badge--${tone}`, className].filter(Boolean).join(' ')} {...rest}>
      {icon}
      {children}
    </span>
  )
}
