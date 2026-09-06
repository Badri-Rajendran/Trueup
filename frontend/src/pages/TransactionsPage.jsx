import { TransactionTable } from '../features/valuation/components/TransactionTable.jsx'
import './PageLayout.css'

export function TransactionsPage() {
  return (
    <div className="tu-page">
      <h1 className="tu-page__title">Transactions</h1>
      <TransactionTable />
    </div>
  )
}
