import './EmptyState.css'

/**
 * Design system §7.5. `variant="good"` is for a genuinely desired empty state ("No open breaks") —
 * gets a success-tinted checkmark instead of the neutral default icon, so it isn't mistaken for a
 * loading artifact (`structure.md` §6).
 */
export function EmptyState({ variant = 'neutral', title, description, action }) {
  return (
    <div className={['tu-empty-state', variant === 'good' ? 'tu-empty-state--good' : ''].filter(Boolean).join(' ')}>
      <span className="tu-empty-state__icon" aria-hidden="true">
        {variant === 'good' ? (
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <path d="M3 8.5 6.5 12 13 4.5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        ) : (
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <rect x="2.5" y="4" width="11" height="9" rx="1" stroke="currentColor" strokeWidth="1.2" />
            <path d="M2.5 6.5h11" stroke="currentColor" strokeWidth="1.2" />
          </svg>
        )}
      </span>
      <p className="tu-empty-state__title">{title}</p>
      {description && <p className="tu-empty-state__description">{description}</p>}
      {action}
    </div>
  )
}
