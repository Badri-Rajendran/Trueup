import { useId } from 'react'
import '../Input/Input.css'

/** Design system §7.2 — same visual treatment as Input. */
export function Select({ label, id, error, hint, children, className = '', ...rest }) {
  const generatedId = useId()
  const fieldId = id || generatedId
  const messageId = error || hint ? `${fieldId}-message` : undefined

  return (
    <div className={['tu-field', error ? 'tu-field--error' : '', className].filter(Boolean).join(' ')}>
      <label className="tu-field__label" htmlFor={fieldId}>
        {label}
      </label>
      <select
        id={fieldId}
        className="tu-field__control"
        aria-invalid={Boolean(error) || undefined}
        aria-describedby={messageId}
        {...rest}
      >
        {children}
      </select>
      {error && (
        <span id={messageId} className="tu-field__message">
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
