import { StatusPill } from '../../../components/StatusPill'
import { Table } from '../../../components/Table'

const TONE_BY_STATUS = { pending: 'warning', approved: 'success', rejected: 'error' }

export function CustomerSummary({ customer, onClick }) {
  return (
    <Table.Row onClick={onClick}>
      <Table.Cell>{customer.email}</Table.Cell>
      <Table.Cell>
        <StatusPill tone={TONE_BY_STATUS[customer.kyc_status] || 'neutral'}>{customer.kyc_status}</StatusPill>
      </Table.Cell>
      <Table.Cell>
        <StatusPill tone={TONE_BY_STATUS[customer.account_approval_status] || 'neutral'}>
          {customer.account_approval_status}
        </StatusPill>
      </Table.Cell>
      <Table.Cell>{customer.has_open_break && <StatusPill tone="error">Open break</StatusPill>}</Table.Cell>
    </Table.Row>
  )
}
