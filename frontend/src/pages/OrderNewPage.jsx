import { OrderForm } from '../features/orders/components/OrderForm.jsx'
import './PageLayout.css'

export function OrderNewPage() {
  return (
    <div className="tu-page">
      <h1 className="tu-page__title">Place an order</h1>
      <OrderForm />
    </div>
  )
}
