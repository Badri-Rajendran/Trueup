import { StatusPill } from '../../../components/StatusPill'
import { Table } from '../../../components/Table'
import { UnitsValue } from '../../../components/UnitsValue'
import { formatDate, formatMoney } from '../../../utils/format.js'
import { ORDER_STATUS_LABEL, ORDER_STATUS_TONE } from '../statusTone.js'

export function OrderRow({ order, onClick }) {
  return (
    <Table.Row onClick={onClick}>
      <Table.Cell>{order.symbol}</Table.Cell>
      <Table.Cell>{order.side === 'buy' ? 'Buy' : 'Sell'}</Table.Cell>
      <Table.Cell align="right" numeric>
        <UnitsValue value={order.quantity_requested} />
      </Table.Cell>
      <Table.Cell align="right" numeric>
        {order.average_fill_price ? formatMoney(order.average_fill_price) : '—'}
      </Table.Cell>
      <Table.Cell>
        <StatusPill tone={ORDER_STATUS_TONE[order.status] || 'neutral'}>
          {ORDER_STATUS_LABEL[order.status] || order.status}
        </StatusPill>
      </Table.Cell>
      <Table.Cell>{formatDate(order.created_at)}</Table.Cell>
    </Table.Row>
  )
}
