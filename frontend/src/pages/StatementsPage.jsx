import { StatementList } from '../features/statements/components/StatementList.jsx'
import './PageLayout.css'

export function StatementsPage() {
  return (
    <div className="tu-page">
      <h1 className="tu-page__title">Statements</h1>
      <StatementList />
    </div>
  )
}
