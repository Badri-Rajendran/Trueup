import { EmptyState } from '../../../components/EmptyState'
import { StatusPill } from '../../../components/StatusPill'
import { Table } from '../../../components/Table'
import { formatDate, formatMoney } from '../../../utils/format.js'

const TONE_BY_STATUS = { pending: 'warning', succeeded: 'success', failed: 'error', dunning: 'error' }
const LABEL_BY_STATUS = { pending: 'Pending', succeeded: 'Succeeded', failed: 'Failed', dunning: 'Dunning' }

export function ChargeHistory({ charges }) {
  if (charges.length === 0) {
    return <EmptyState title="No charges yet" description="Fee charges appear here once the first billing period closes." />
  }

  return (
    <Table>
      <Table.Header>
        <Table.HeaderCell>Period</Table.HeaderCell>
        <Table.HeaderCell align="right">Amount</Table.HeaderCell>
        <Table.HeaderCell>Status</Table.HeaderCell>
      </Table.Header>
      <Table.Body>
        {charges.map((charge) => (
          <Table.Row key={charge.id}>
            <Table.Cell>
              {formatDate(charge.billing_period_start)} – {formatDate(charge.billing_period_end)}
            </Table.Cell>
            <Table.Cell align="right" numeric>
              {formatMoney(charge.total_accrued)}
            </Table.Cell>
            <Table.Cell>
              <StatusPill tone={TONE_BY_STATUS[charge.status] || 'neutral'}>{LABEL_BY_STATUS[charge.status] || charge.status}</StatusPill>
            </Table.Cell>
          </Table.Row>
        ))}
      </Table.Body>
    </Table>
  )
}
