import { useNavigate } from 'react-router-dom'
import { Button } from '../../../components/Button'
import { EmptyState } from '../../../components/EmptyState'
import { ErrorState } from '../../../components/ErrorState'
import { Skeleton } from '../../../components/Skeleton'
import { Table } from '../../../components/Table'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { useOrders } from '../hooks/useOrders.js'
import { OrderRow } from './OrderRow.jsx'

export function OrderList() {
  const { status, orders, error, refetch } = useOrders()
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

  if (orders.length === 0) {
    return (
      <EmptyState
        title="No orders yet"
        description="Orders you place will show up here."
        action={<Button onClick={() => navigate('/orders/new')}>Place your first order</Button>}
      />
    )
  }

  return (
    <Table>
      <Table.Header>
        <Table.HeaderCell>Security</Table.HeaderCell>
        <Table.HeaderCell>Side</Table.HeaderCell>
        <Table.HeaderCell align="right">Quantity</Table.HeaderCell>
        <Table.HeaderCell align="right">Avg. fill price</Table.HeaderCell>
        <Table.HeaderCell>Status</Table.HeaderCell>
        <Table.HeaderCell>Placed</Table.HeaderCell>
      </Table.Header>
      <Table.Body>
        {orders.map((order) => (
          <OrderRow key={order.id} order={order} onClick={() => navigate(`/orders/${order.id}`)} />
        ))}
      </Table.Body>
    </Table>
  )
}
