import './Badge.css'

/** Design system §7.4. `tone="neutral"` is non-semantic provenance-disclosure (§8.3, §8.8); pair with a label word. */
export function Badge({ tone = 'neutral', icon, className = '', children, ...rest }) {
  return (
    <span className={['tu-badge', `tu-badge--${tone}`, className].filter(Boolean).join(' ')} {...rest}>
      {icon}
      {children}
    </span>
  )
}
