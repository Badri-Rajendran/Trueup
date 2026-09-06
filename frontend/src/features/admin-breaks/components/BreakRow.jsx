import { StatusPill } from '../../../components/StatusPill'
import { Table } from '../../../components/Table'
import { formatDate } from '../../../utils/format.js'
import { AgingIndicator } from './AgingIndicator.jsx'

function previewJson(value) {
  if (value == null) return '—'
  const text = JSON.stringify(value)
  return text.length > 40 ? `${text.slice(0, 40)}…` : text
}

export function BreakRow({ breakRow, onClick }) {
  return (
    <Table.Row onClick={onClick}>
      <Table.Cell>{breakRow.break_type}</Table.Cell>
      {/* customer_id nullable (S7 §5.2). */}
      <Table.Cell>{breakRow.customer_id ? breakRow.customer_id.slice(0, 8) : 'Unattributed'}</Table.Cell>
      <Table.Cell>{previewJson(breakRow.expected)}</Table.Cell>
      <Table.Cell>{previewJson(breakRow.actual)}</Table.Cell>
      <Table.Cell>
        <AgingIndicator ageSeconds={breakRow.age_seconds} />
      </Table.Cell>
      <Table.Cell>
        <StatusPill tone={breakRow.status === 'open' ? 'error' : 'success'}>
          {breakRow.status === 'open' ? 'Open' : 'Resolved'}
        </StatusPill>
      </Table.Cell>
      <Table.Cell>{formatDate(breakRow.opened_at)}</Table.Cell>
    </Table.Row>
  )
}
