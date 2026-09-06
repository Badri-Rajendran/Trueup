import { Link } from 'react-router-dom'
import { Button } from '../components/Button'
import { OrderList } from '../features/orders/components/OrderList.jsx'
import './PageLayout.css'

export function OrdersPage() {
  return (
    <div className="tu-page">
      <div className="tu-page__header">
        <h1 className="tu-page__title">Orders</h1>
        <Link to="/orders/new">
          <Button size="compact">New order</Button>
        </Link>
      </div>
      <OrderList />
    </div>
  )
}
