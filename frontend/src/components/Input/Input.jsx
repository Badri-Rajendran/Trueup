import { useId } from 'react'
import './Input.css'

/** Design system §7.2. Label always visible above the field — never placeholder-as-label. */
export function Input({ label, id, error, hint, className = '', ...rest }) {
  const generatedId = useId()
  const fieldId = id || generatedId
  const messageId = error || hint ? `${fieldId}-message` : undefined

  return (
    <div className={['tu-field', error ? 'tu-field--error' : '', className].filter(Boolean).join(' ')}>
      <label className="tu-field__label" htmlFor={fieldId}>
        {label}
      </label>
      <input
        id={fieldId}
        className="tu-field__control"
        aria-invalid={Boolean(error) || undefined}
        aria-describedby={messageId}
        {...rest}
      />
      {error && (
        <span id={messageId} className="tu-field__message">
          <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true" focusable="false">
            <circle cx="6" cy="6" r="5.25" fill="none" stroke="currentColor" strokeWidth="1.2" />
            <line x1="6" y1="3.25" x2="6" y2="6.5" stroke="currentColor" strokeWidth="1.2" />
            <circle cx="6" cy="8.5" r="0.6" fill="currentColor" />
          </svg>
          {error}
        </span>
      )}
      {!error && hint && (
        <span id={messageId} className="tu-field__message" style={{ color: 'var(--color-text-muted)' }}>
          {hint}
        </span>
      )}
    </div>
  )
}
