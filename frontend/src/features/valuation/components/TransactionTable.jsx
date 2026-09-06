import { EmptyState } from '../../../components/EmptyState'
import { ErrorState } from '../../../components/ErrorState'
import { Skeleton } from '../../../components/Skeleton'
import { Table } from '../../../components/Table'
import { UnitsValue } from '../../../components/UnitsValue'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { formatDate, formatMoney } from '../../../utils/format.js'
import { ENTRY_TYPE_LABEL } from '../entryTypeLabels.js'
import { useTransactionHistory } from '../hooks/useTransactionHistory.js'

export function TransactionTable() {
  const { status, entries, error, refetch } = useTransactionHistory()

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

  if (entries.length === 0) {
    return <EmptyState title="No transactions yet" />
  }

  return (
    <Table striped stickyHeader>
      <Table.Header>
        <Table.HeaderCell>Date</Table.HeaderCell>
        <Table.HeaderCell>Type</Table.HeaderCell>
        <Table.HeaderCell align="right">Amount</Table.HeaderCell>
        <Table.HeaderCell align="right">Units</Table.HeaderCell>
        <Table.HeaderCell>Memo</Table.HeaderCell>
      </Table.Header>
      <Table.Body>
        {entries.map((entry, index) => (
          // No stable per-entry id in HistoryEntryResponse — effective_date + recorded_at pairs
          // are unique enough for a live-ordered, unpaginated list; index as a tiebreak only.
          <Table.Row key={`${entry.recorded_at}-${index}`}>
            <Table.Cell>{formatDate(entry.effective_date)}</Table.Cell>
            <Table.Cell>{ENTRY_TYPE_LABEL[entry.entry_type] || entry.entry_type}</Table.Cell>
            <Table.Cell align="right" numeric>
              {entry.amount_money ? formatMoney(entry.amount_money) : '—'}
            </Table.Cell>
            <Table.Cell align="right" numeric>
              {entry.quantity_units ? <UnitsValue value={entry.quantity_units} /> : '—'}
            </Table.Cell>
            <Table.Cell>{entry.memo || '—'}</Table.Cell>
          </Table.Row>
        ))}
      </Table.Body>
    </Table>
  )
}
