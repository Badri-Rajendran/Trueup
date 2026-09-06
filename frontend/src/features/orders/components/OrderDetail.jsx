import { Card } from '../../../components/Card'
import { ErrorState } from '../../../components/ErrorState'
import { Skeleton } from '../../../components/Skeleton'
import { StatusPill } from '../../../components/StatusPill'
import { Table } from '../../../components/Table'
import { UnitsValue } from '../../../components/UnitsValue'
import { formatDateTime, formatMoney } from '../../../utils/format.js'
import { useOrder } from '../hooks/useOrder.js'
import { ORDER_STATUS_LABEL, ORDER_STATUS_TONE } from '../statusTone.js'
import { ApprovalBanner } from './ApprovalBanner.jsx'
import './OrderDetail.css'

export function OrderDetail({ orderId }) {
  const { status, order, events, error, refetch } = useOrder(orderId)

  if (status === 'idle' || status === 'loading') {
    return <Skeleton height="200px" />
  }

  if (status === 'error') {
    if (error?.code === 'not_found') {
      return <p className="tu-order-detail__not-found">Order not found.</p>
    }
    return <ErrorState onRetry={refetch} />
  }

  return (
    <div className="tu-order-detail">
      {order.status === 'awaiting_approval' && <ApprovalBanner order={order} onApproved={refetch} />}
      <Card>
        <dl className="tu-order-detail__fields">
          <div>
            <dt>Security</dt>
            <dd>{order.symbol}</dd>
          </div>
          <div>
            <dt>Side</dt>
            <dd>{order.side === 'buy' ? 'Buy' : 'Sell'}</dd>
          </div>
          <div>
            <dt>Quantity requested</dt>
            <dd>
              <UnitsValue value={order.quantity_requested} />
            </dd>
          </div>
          <div>
            <dt>Filled quantity</dt>
            <dd>
              <UnitsValue value={order.filled_quantity} />
            </dd>
          </div>
          <div>
            <dt>Average fill price</dt>
            <dd>{order.average_fill_price ? formatMoney(order.average_fill_price) : '—'}</dd>
          </div>
          <div>
            <dt>Status</dt>
            <dd>
              <StatusPill tone={ORDER_STATUS_TONE[order.status] || 'neutral'}>
                {ORDER_STATUS_LABEL[order.status] || order.status}
              </StatusPill>
            </dd>
          </div>
          <div>
            <dt>Placed</dt>
            <dd>{formatDateTime(order.created_at)}</dd>
          </div>
        </dl>
      </Card>
      <Card>
        <h2 className="tu-order-detail__events-title">Order history</h2>
        {events.length === 0 ? (
          <p>No events yet.</p>
        ) : (
          <Table>
            <Table.Header>
              <Table.HeaderCell>Event</Table.HeaderCell>
              <Table.HeaderCell>Execution ID</Table.HeaderCell>
              <Table.HeaderCell>Recorded</Table.HeaderCell>
            </Table.Header>
            <Table.Body>
              {events.map((event) => (
                <Table.Row key={event.seq}>
                  <Table.Cell>{event.event_type}</Table.Cell>
                  <Table.Cell>{event.execution_id || '—'}</Table.Cell>
                  <Table.Cell>{formatDateTime(event.recorded_at)}</Table.Cell>
                </Table.Row>
              ))}
            </Table.Body>
          </Table>
        )}
      </Card>
    </div>
  )
}
