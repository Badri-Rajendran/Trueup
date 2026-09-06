import './Skeleton.css'

/** Design system §7.7. Sized per screen region by the caller; never a bare spinner (structure.md §6). */
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
