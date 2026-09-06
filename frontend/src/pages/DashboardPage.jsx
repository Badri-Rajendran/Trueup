import { useState } from 'react'
import { useSession } from '../contexts/SessionContext.jsx'
import { BalanceCard } from '../features/valuation/components/BalanceCard.jsx'
import { CompletenessBanner } from '../features/valuation/components/CompletenessBanner.jsx'
import { ReturnCard } from '../features/valuation/components/ReturnCard.jsx'
import { useBalance } from '../features/valuation/hooks/useBalance.js'
import { useReturns } from '../features/valuation/hooks/useReturns.js'
import { HoldingsTable } from '../features/portfolio/components/HoldingsTable.jsx'
import { useAssignment } from '../features/portfolio/hooks/useAssignment.js'
import { useModels } from '../features/portfolio/hooks/useModels.js'
import './DashboardPage.css'
import './PageLayout.css'

function monthToDateRange() {
  const now = new Date()
  const monthStart = new Date(now.getFullYear(), now.getMonth(), 1)
  return { periodStart: monthStart.toISOString(), periodEnd: now.toISOString() }
}

export function DashboardPage() {
  const { principal } = useSession()
  const balance = useBalance()
  // Computed once per mount, not per render — a stable dependency for `useReturns` below.
  const [{ periodStart, periodEnd }] = useState(monthToDateRange)
  const returns = useReturns(periodStart, periodEnd)
  const assignment = useAssignment(principal.id)
  const { models } = useModels()

  const assignedModel = assignment.assignment
    ? models.find((model) => model.id === assignment.assignment.model_portfolio_id)
    : null

  return (
    <div className="tu-page">
      <h1 className="tu-page__title">Dashboard</h1>
      {balance.completeness === 'partial' && <CompletenessBanner asOfDate={balance.asOfDate} />}
      <div className="tu-dashboard-page__stats">
        <BalanceCard status={balance.status} totalValue={balance.totalValue} asOfDate={balance.asOfDate} />
        <ReturnCard status={returns.status} twr={returns.twr} isProvisional={returns.isProvisional} />
      </div>
      <div>
        <h2 className="tu-page__section-title">Holdings</h2>
        <HoldingsTable model={assignedModel} />
      </div>
    </div>
  )
}
