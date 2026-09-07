import './AuthLayout.css'

/**
 * `variant="split"` + `panel` renders a two-column layout (form left, brand panel right,
 * stacking to one column below 768px) for the one public page that carries brand/marketing
 * content (signup). Default stays the plain centered column every other auth screen uses.
 */
export function AuthLayout({ children, variant = 'centered', panel = null }) {
  if (variant === 'split') {
    return (
      <div className="tu-auth-layout tu-auth-layout--split">
        <div className="tu-auth-layout__form">{children}</div>
        <div className="tu-auth-layout__panel">{panel}</div>
      </div>
    )
  }
  return <div className="tu-auth-layout">{children}</div>
}
