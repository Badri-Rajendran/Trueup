import './DetailFields.css'

/** A label/value grid — the recurring "detail page fields" shape (orders, statements, breaks, fees). */
export function DetailFields({ fields }) {
  return (
    <dl className="tu-detail-fields">
      {fields.map(({ label, value }) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  )
}
