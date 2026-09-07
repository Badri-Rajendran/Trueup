import { useState } from 'react'
import { Card } from '../components/Card'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { Skeleton } from '../components/Skeleton'
import { LotFilterToolbar } from '../features/lots/components/LotFilterToolbar.jsx'
import { LotSummary } from '../features/lots/components/LotSummary.jsx'
import { LotTable } from '../features/lots/components/LotTable.jsx'
import { useLots } from '../features/lots/hooks/useLots.js'
import { getErrorMessage } from '../utils/apiErrorMessage.js'
import './LotsPage.css'
import './PageLayout.css'

function LotsPageSkeleton() {
  return (
    <>
      <div className="tu-lots-page__summary-skeleton">
        <Card>
          <Skeleton width="160px" height="18px" />
          <Skeleton height="48px" style={{ marginTop: 'var(--space-2)' }} />
        </Card>
        <Card>
          <Skeleton width="140px" height="18px" />
          <Skeleton height="28px" style={{ marginTop: 'var(--space-2)' }} />
        </Card>
      </div>
      <Skeleton height="44px" />
      <Skeleton height="44px" />
      <Skeleton height="44px" />
    </>
  )
}

export function LotsPage() {
  const { status, lots, visibleLots, statusFilter, setStatusFilter, sort, toggleSort, error, refetch } = useLots()
  const [expandedId, setExpandedId] = useState(null)

  const toggleExpand = (lotId) => setExpandedId((prev) => (prev === lotId ? null : lotId))

  if (status === 'idle' || status === 'loading') {
    return (
      <div className="tu-page">
        <h1 className="tu-page__title">Tax lots</h1>
        <LotsPageSkeleton />
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div className="tu-page">
        <h1 className="tu-page__title">Tax lots</h1>
        <ErrorState description={getErrorMessage(error)} onRetry={refetch} />
      </div>
    )
  }

  if (lots.length === 0) {
    return (
      <div className="tu-page">
        <h1 className="tu-page__title">Tax lots</h1>
        <EmptyState title="No lots yet" description="Tax lots appear here once you've bought a position." />
      </div>
    )
  }

  return (
    <div className="tu-page tu-lots-page">
      <h1 className="tu-page__title">Tax lots</h1>
      <LotSummary lots={lots} />
      <LotFilterToolbar statusFilter={statusFilter} onStatusFilterChange={setStatusFilter} />
      {visibleLots.length === 0 ? (
        <EmptyState title="No lots match this filter" description="Try a different status filter." />
      ) : (
        <LotTable lots={visibleLots} sort={sort} onSort={toggleSort} expandedId={expandedId} onToggleExpand={toggleExpand} />
      )}
    </div>
  )
}
