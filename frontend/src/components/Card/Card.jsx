import './Card.css'

/** Design system §7.3. A card never nests another card. */
export function Card({ as: Component = 'div', className = '', children, ...rest }) {
  return (
    <Component className={['tu-card', className].filter(Boolean).join(' ')} {...rest}>
      {children}
    </Component>
  )
}
