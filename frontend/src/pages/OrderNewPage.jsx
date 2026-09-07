import { Card } from '../components/Card'
import { OrderForm } from '../features/orders/components/OrderForm.jsx'
import './OrderNewPage.css'
import './PageLayout.css'

export function OrderNewPage() {
  return (
    <div className="tu-page tu-order-new-page">
      <h1 className="tu-page__title">Place an order</h1>
      <Card>
        <OrderForm />
      </Card>
    </div>
  )
}
