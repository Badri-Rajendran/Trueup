import './Button.css'

/** Design system §7.1. `variant="danger-outline"` is the privileged-action trigger (§8.6). */
export function Button({
  variant = 'primary',
  size = 'default',
  loading = false,
  disabled = false,
  type = 'button',
  className = '',
  children,
  ...rest
}) {
  const classes = [
    'tu-button',
    `tu-button--${variant}`,
    size === 'compact' ? 'tu-button--compact' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <button
      type={type}
      className={classes}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      <span className="tu-button__content" style={loading ? { visibility: 'hidden' } : undefined}>
        {children}
      </span>
      {loading && (
        <span className="tu-button__spinner-wrap">
          <span className="tu-button__spinner" aria-hidden="true" />
        </span>
      )}
    </button>
  )
}
