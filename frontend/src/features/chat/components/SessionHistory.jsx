import { Button } from '../../../components/Button'
import { formatDateTime } from '../../../utils/format.js'
import './SessionHistory.css'

/**
 * A basic past-conversations list. The backend only returns `{id, status, created_at}` per
 * session (no preview text), so each item is labeled by its real timestamp rather than an
 * invented title — a first-message preview would need a backend addition, flagged as a follow-up
 * rather than built here. `open` only matters below the 768px breakpoint (desktop shows this
 * unconditionally via CSS); switching is disabled while a stream is in progress, since there's no
 * safe way to abandon an in-flight turn mid-switch.
 */
export function SessionHistory({ sessions, activeSessionId, onSelect, onStartNew, disabled, open }) {
  return (
    <nav
      className={`tu-session-history${open ? ' tu-session-history--open' : ''}`}
      aria-label="Chat history"
    >
      <Button
        type="button"
        variant="secondary"
        size="compact"
        className="tu-session-history__new"
        onClick={onStartNew}
        disabled={disabled}
      >
        New chat
      </Button>
      {sessions.length > 0 && (
        <ul className="tu-session-history__list">
          {sessions.map((session) => (
            <li key={session.id}>
              <button
                type="button"
                className={`tu-session-history__item${
                  session.id === activeSessionId ? ' tu-session-history__item--active' : ''
                }`}
                onClick={() => onSelect(session.id)}
                disabled={disabled}
                aria-current={session.id === activeSessionId ? 'true' : undefined}
              >
                {formatDateTime(session.created_at)}
              </button>
            </li>
          ))}
        </ul>
      )}
    </nav>
  )
}
