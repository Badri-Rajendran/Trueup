import './Skeleton.css'

/**
 * Design system §7.7. A block the shape/size of the content it replaces — callers size it per
 * screen region (`structure.md` §6 names a specific skeleton shape per screen, never a bare spinner).
 */
export function Skeleton({ width = '100%', height = '1em', radius, className = '', style, ...rest }) {
  return (
    <span
      className={['tu-skeleton', className].filter(Boolean).join(' ')}
      style={{ width, height, borderRadius: radius, ...style }}
      aria-hidden="true"
      {...rest}
    />
  )
}
