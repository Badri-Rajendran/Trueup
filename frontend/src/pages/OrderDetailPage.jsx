import { Link, useParams } from 'react-router-dom'
import { Icon } from '../components/Icon'
import { OrderDetail } from '../features/orders/components/OrderDetail.jsx'
import './PageLayout.css'

export function OrderDetailPage() {
  const { orderId } = useParams()
  return (
    <div className="tu-page">
      <Link to="/invest" className="tu-page__back-link">
        <Icon name="chevron-left" size="sm" />
        Back to Invest
      </Link>
      <h1 className="tu-page__title">Order detail</h1>
      <OrderDetail orderId={orderId} />
    </div>
  )
}
