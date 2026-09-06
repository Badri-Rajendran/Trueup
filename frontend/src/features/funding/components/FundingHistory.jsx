import { EmptyState } from '../../../components/EmptyState'
import { ErrorState } from '../../../components/ErrorState'
import { Skeleton } from '../../../components/Skeleton'
import { Table } from '../../../components/Table'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { formatDate, formatMoney } from '../../../utils/format.js'
// No dedicated funding-history endpoint; reuses valuation's transaction history hook.
import { useTransactionHistory } from '../../valuation/hooks/useTransactionHistory.js'

const FUNDING_ENTRY_TYPES = new Set(['deposit', 'withdrawal'])
const ENTRY_LABEL = { deposit: 'Deposit', withdrawal: 'Withdrawal' }

export function FundingHistory() {
  const { status, entries, error, refetch } = useTransactionHistory()

  if (status === 'idle' || status === 'loading') {
    return <Skeleton height="120px" />
  }

  if (status === 'error') {
    return <ErrorState description={getErrorMessage(error)} onRetry={refetch} />
  }

  const fundingEntries = entries.filter((entry) => FUNDING_ENTRY_TYPES.has(entry.entry_type))

  if (fundingEntries.length === 0) {
    return <EmptyState title="No deposits or withdrawals yet" />
  }

  return (
    <Table>
      <Table.Header>
        <Table.HeaderCell>Date</Table.HeaderCell>
        <Table.HeaderCell>Type</Table.HeaderCell>
        <Table.HeaderCell align="right">Amount</Table.HeaderCell>
      </Table.Header>
      <Table.Body>
        {fundingEntries.map((entry, index) => (
          <Table.Row key={`${entry.recorded_at}-${index}`}>
            <Table.Cell>{formatDate(entry.effective_date)}</Table.Cell>
            <Table.Cell>{ENTRY_LABEL[entry.entry_type]}</Table.Cell>
            <Table.Cell align="right" numeric>
              {entry.amount_money ? formatMoney(entry.amount_money) : '—'}
            </Table.Cell>
          </Table.Row>
        ))}
      </Table.Body>
    </Table>
  )
}
