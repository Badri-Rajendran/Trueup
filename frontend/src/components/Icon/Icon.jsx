import './Icon.css'
import { ICON_PATHS } from './paths.js'

/**
 * A single glyph from the app's icon set (`paths.js`), 16x16, `currentColor`-driven so it inherits
 * the theme automatically. `aria-hidden` by default -- icons are almost always paired with visible
 * text per design-system.md §2.4's never-color-alone rule, so they carry no accessible name of
 * their own. Pass `label` only for the rare icon-only control (e.g. a bare dismiss button) where
 * the icon IS the only content; it swaps `aria-hidden` for a real accessible name.
 */
export function Icon({ name, size = 'md', label, className = '', ...rest }) {
  const d = ICON_PATHS[name]
  if (!d) return null

  const sizeClass = size === 'sm' ? 'tu-icon--sm' : size === 'lg' ? 'tu-icon--lg' : 'tu-icon--md'

  return (
    <svg
      className={['tu-icon', sizeClass, className].filter(Boolean).join(' ')}
      viewBox="0 0 16 16"
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      focusable="false"
      {...rest}
    >
      {d.map((segment) => (
        <path key={segment} d={segment} />
      ))}
    </svg>
  )
}
