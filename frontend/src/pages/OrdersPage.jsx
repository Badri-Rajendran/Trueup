import { OrderList } from '../features/orders/components/OrderList.jsx'
import './PageLayout.css'

export function OrdersPage() {
  return (
    <div className="tu-page">
      <h1 className="tu-page__title">Orders</h1>
      <OrderList />
    </div>
  )
}
