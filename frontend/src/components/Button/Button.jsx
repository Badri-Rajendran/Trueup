import './Button.css'

/**
 * Design system §7.1. `variant="danger-outline"` is the shared privileged-action trigger from
 * §8.6 (order approval, break resolution, KYC override) — deliberately quieter than `primary`.
 */
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
