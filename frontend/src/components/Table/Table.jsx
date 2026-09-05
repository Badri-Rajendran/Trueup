import './Table.css'

/**
 * Design system §7.6. Composed as `<Table><Table.Header>…<Table.Body>…`. `stickyHeader` is meant
 * for tables over ~10 visible rows (Transactions, Lots); `striped` is opt-in for dense tables only.
 */
export function Table({ striped = false, stickyHeader = false, className = '', children, ...rest }) {
  const classes = [
    'tu-table',
    striped ? 'tu-table--striped' : '',
    stickyHeader ? 'tu-table--sticky-header' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ')

  return (
    <div className="tu-table-wrapper">
      <table className={classes} {...rest}>
        {children}
      </table>
    </div>
  )
}

Table.Header = function TableHeader({ children, ...rest }) {
  return (
    <thead {...rest}>
      <tr>{children}</tr>
    </thead>
  )
}

Table.Body = function TableBody({ children, ...rest }) {
  return <tbody {...rest}>{children}</tbody>
}

Table.Row = function TableRow({ onClick, children, ...rest }) {
  return (
    <tr data-clickable={Boolean(onClick)} onClick={onClick} {...rest}>
      {children}
    </tr>
  )
}

Table.HeaderCell = function TableHeaderCell({ align = 'left', sortable = false, sortDirection, onSort, children, ...rest }) {
  if (!sortable) {
    return (
      <th data-align={align} {...rest}>
        {children}
      </th>
    )
  }

  return (
    <th data-align={align} aria-sort={sortDirection ? `${sortDirection}ending` : 'none'} {...rest}>
      <button type="button" className="tu-table__sort-button" onClick={onSort}>
        {children}
        <span className="tu-table__sort-caret" aria-hidden="true">
          {sortDirection === 'desc' ? '▼' : sortDirection === 'asc' ? '▲' : '↕'}
        </span>
      </button>
    </th>
  )
}

Table.Cell = function TableCell({ align = 'left', numeric = false, children, ...rest }) {
  return (
    <td data-align={align} data-numeric={numeric || undefined} {...rest}>
      {children}
    </td>
  )
}
