import { Button } from '../Button/Button.jsx'
import './ErrorState.css'

/** Design system-adjacent (structure.md §6's ubiquitous "fetch failure → ErrorState with retry"). */
export function ErrorState({ title = 'Something went wrong', description, onRetry }) {
  return (
    <div className="tu-error-state">
      <span className="tu-error-state__icon" aria-hidden="true">
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
          <circle cx="8" cy="8" r="6.5" stroke="currentColor" strokeWidth="1.3" />
          <line x1="8" y1="4.75" x2="8" y2="8.75" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
          <circle cx="8" cy="11" r="0.8" fill="currentColor" />
        </svg>
      </span>
      <p className="tu-error-state__title">{title}</p>
      {description && <p className="tu-error-state__description">{description}</p>}
      {onRetry && (
        <Button variant="secondary" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  )
}
