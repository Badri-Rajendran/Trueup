import { useNavigate } from 'react-router-dom'
import { EmptyState } from '../../../components/EmptyState'
import { ErrorState } from '../../../components/ErrorState'
import { Skeleton } from '../../../components/Skeleton'
import { Table } from '../../../components/Table'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { useBreaks } from '../hooks/useBreaks.js'
import { BreakRow } from './BreakRow.jsx'

export function BreakQueue() {
  const { status, breaks, error, refetch } = useBreaks()
  const navigate = useNavigate()

  if (status === 'idle' || status === 'loading') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
        <Skeleton height="44px" />
        <Skeleton height="44px" />
        <Skeleton height="44px" />
      </div>
    )
  }

  if (status === 'error') {
    return <ErrorState description={getErrorMessage(error)} onRetry={refetch} />
  }

  if (breaks.length === 0) {
    // A real, good state (design-system §7.5) — not a blank-looking placeholder.
    return <EmptyState variant="good" title="No open breaks" />
  }

  return (
    <Table>
      <Table.Header>
        <Table.HeaderCell>Type</Table.HeaderCell>
        <Table.HeaderCell>Customer</Table.HeaderCell>
        <Table.HeaderCell>Expected</Table.HeaderCell>
        <Table.HeaderCell>Actual</Table.HeaderCell>
        <Table.HeaderCell>Age</Table.HeaderCell>
        <Table.HeaderCell>Status</Table.HeaderCell>
        <Table.HeaderCell>Opened</Table.HeaderCell>
      </Table.Header>
      <Table.Body>
        {breaks.map((breakRow) => (
          <BreakRow key={breakRow.id} breakRow={breakRow} onClick={() => navigate(`/admin/breaks/${breakRow.id}`)} />
        ))}
      </Table.Body>
    </Table>
  )
}
