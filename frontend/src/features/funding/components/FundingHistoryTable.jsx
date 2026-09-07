import { EmptyState } from '../../../components/EmptyState'
import { Table } from '../../../components/Table'
import { formatDate, formatMoney } from '../../../utils/format.js'
import { formatFailureReason, hasFundingActivity } from '../utils/fundingSummary.js'
import { SettlementStatusPill } from './SettlementStatusPill.jsx'
import './FundingHistory.css'

const ENTRY_LABEL = { deposit: 'Deposit', withdrawal: 'Withdrawal' }

/**
 * Presentational — `entries` arrives already sorted from `FundingPage.jsx`; `sort`/`onSort` wire
 * straight into the Date header's own `sortable` prop (structure.md's convention, matching
 * `LotTable`). Row key is the real `journal_entry_id`, never an array index. A failed row shows
 * `formatFailureReason(...)` in place of its date — the one piece of information that row is
 * actually about. Money is never demoted for a withdrawal: same `--color-text` weight as a
 * deposit (no gain/loss-style coloring here, unlike `LotTable.css`) — the sign and the Type column
 * carry the distinction, not color (design-system §2.4).
 */
export function FundingHistoryTable({ entries, sort, onSort }) {
  if (!hasFundingActivity(entries)) {
    return <EmptyState title="No deposits or withdrawals yet" />
  }

  return (
    <Table striped stickyHeader>
      <Table.Header>
        <Table.HeaderCell sortable sortDirection={sort.column === 'date' ? sort.direction : undefined} onSort={() => onSort('date')}>
          Date
        </Table.HeaderCell>
        <Table.HeaderCell>Type</Table.HeaderCell>
        <Table.HeaderCell align="right">Amount</Table.HeaderCell>
        <Table.HeaderCell>Status</Table.HeaderCell>
        <Table.HeaderCell>Expected settlement</Table.HeaderCell>
      </Table.Header>
      <Table.Body>
        {entries.map((entry) => {
          const isFailed = entry.settlement_status === 'failed'
          return (
            <Table.Row key={entry.journal_entry_id}>
              <Table.Cell>{isFailed ? formatFailureReason(entry.failure_reason) : formatDate(entry.effective_date)}</Table.Cell>
              <Table.Cell>{ENTRY_LABEL[entry.entry_type] ?? entry.entry_type}</Table.Cell>
              <Table.Cell align="right" numeric>
                {formatMoney(entry.amount)}
              </Table.Cell>
              <Table.Cell>
                <SettlementStatusPill entry={entry} />
              </Table.Cell>
              <Table.Cell>{entry.expected_settlement_date ? formatDate(entry.expected_settlement_date) : '—'}</Table.Cell>
            </Table.Row>
          )
        })}
      </Table.Body>
    </Table>
  )
}
