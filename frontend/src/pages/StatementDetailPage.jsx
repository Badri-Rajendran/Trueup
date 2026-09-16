import { Link, useParams } from 'react-router-dom'
import { Icon } from '../components/Icon'
import { StatementDetail } from '../features/statements/components/StatementDetail.jsx'
import './PageLayout.css'

export function StatementDetailPage() {
  const { periodStart } = useParams()
  return (
    <div className="tu-page">
      <Link to="/account" className="tu-page__back-link">
        <Icon name="chevron-left" size="sm" />
        Back to Account
      </Link>
      <h1 className="tu-page__title">Statement detail</h1>
      <StatementDetail periodStart={periodStart} />
    </div>
  )
}
