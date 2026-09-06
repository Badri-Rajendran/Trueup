import { useParams } from 'react-router-dom'
import { OrderDetail } from '../features/orders/components/OrderDetail.jsx'
import './PageLayout.css'

export function OrderDetailPage() {
  const { orderId } = useParams()
  return (
    <div className="tu-page">
      <h1 className="tu-page__title">Order detail</h1>
      <OrderDetail orderId={orderId} />
    </div>
  )
}
