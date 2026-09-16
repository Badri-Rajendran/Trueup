import { Link } from 'react-router-dom'
import { Card } from '../components/Card'
import { Icon } from '../components/Icon'
import { OrderForm } from '../features/orders/components/OrderForm.jsx'
import './OrderNewPage.css'
import './PageLayout.css'

export function OrderNewPage() {
  return (
    <div className="tu-page tu-order-new-page">
      <Link to="/invest" className="tu-page__back-link">
        <Icon name="chevron-left" size="sm" />
        Back to Invest
      </Link>
      <h1 className="tu-page__title">Place an order</h1>
      <Card>
        <OrderForm />
      </Card>
    </div>
  )
}
