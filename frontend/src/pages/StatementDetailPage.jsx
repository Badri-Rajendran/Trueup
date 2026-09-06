import { useParams } from 'react-router-dom'
import { StatementDetail } from '../features/statements/components/StatementDetail.jsx'
import './PageLayout.css'

export function StatementDetailPage() {
  const { periodStart } = useParams()
  return (
    <div className="tu-page">
      <h1 className="tu-page__title">Statement detail</h1>
      <StatementDetail periodStart={periodStart} />
    </div>
  )
}
