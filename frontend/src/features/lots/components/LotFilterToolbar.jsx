import { Select } from '../../../components/Select'
import './LotFilterToolbar.css'

const STATUS_OPTIONS = [
  { value: 'all', label: 'All lots' },
  { value: 'open', label: 'Open' },
  { value: 'partial', label: 'Partially sold' },
  { value: 'closed', label: 'Closed' },
]

/** All client-side (no server-side filter params exist for `GET /lots`) — a status filter is the
 * only filter this redesign scopes in. */
export function LotFilterToolbar({ statusFilter, onStatusFilterChange }) {
  return (
    <div className="tu-lot-filter-toolbar">
      <Select
        label="Status"
        value={statusFilter}
        onChange={(event) => onStatusFilterChange(event.target.value)}
        className="tu-lot-filter-toolbar__field"
      >
        {STATUS_OPTIONS.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </Select>
    </div>
  )
}
