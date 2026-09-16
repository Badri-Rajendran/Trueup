import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Button } from '../components/Button'
import { Card } from '../components/Card'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { Skeleton } from '../components/Skeleton'
import { useToast } from '../components/Toast'
import { useSession } from '../contexts/SessionContext.jsx'
import { AssignmentPrompt } from '../features/portfolio/components/AssignmentPrompt.jsx'
import { ModelDetail } from '../features/portfolio/components/ModelDetail.jsx'
import { useAssignment } from '../features/portfolio/hooks/useAssignment.js'
import { useModels } from '../features/portfolio/hooks/useModels.js'
import { LotFilterToolbar } from '../features/lots/components/LotFilterToolbar.jsx'
import { LotSummary } from '../features/lots/components/LotSummary.jsx'
import { LotTable } from '../features/lots/components/LotTable.jsx'
import { useLots } from '../features/lots/hooks/useLots.js'
import { OrderList } from '../features/orders/components/OrderList.jsx'
import { getErrorMessage } from '../utils/apiErrorMessage.js'
import './InvestPage.css'
import './PageLayout.css'

/** Model assignment/detail -- formerly the whole of `PortfolioPage.jsx`. Both the assignment and
 * the model list must be loaded before an already-assigned customer can be told from a not-yet-
 * assigned one (deciding early off an empty, still-loading `models` array flashes the "choose a
 * model" prompt on every page load). */
function PortfolioSection() {
  const { principal } = useSession()
  const assignment = useAssignment(principal.id)
  const { status: modelsStatus, models, error: modelsError, refetch: refetchModels } = useModels()
  const { showToast } = useToast()

  const isLoading =
    assignment.status === 'idle' ||
    assignment.status === 'loading' ||
    modelsStatus === 'idle' ||
    modelsStatus === 'loading'

  if (isLoading) {
    return <Skeleton height="160px" />
  }

  if (assignment.status === 'error') {
    return <ErrorState description={getErrorMessage(assignment.error)} onRetry={assignment.refetch} />
  }

  if (modelsStatus === 'error') {
    return <ErrorState description={getErrorMessage(modelsError)} onRetry={refetchModels} />
  }

  const assignedModel = assignment.assignment
    ? models.find((model) => model.id === assignment.assignment.model_portfolio_id)
    : null

  const handleSelect = (modelId) => {
    const chosen = models.find((model) => model.id === modelId)
    return assignment
      .assign(modelId)
      .then(() => {
        showToast({ message: chosen ? `You're now assigned to ${chosen.name}.` : 'Model assigned.', tone: 'success' })
      })
      .catch(() => {})
  }

  return assignedModel ? (
    <ModelDetail
      models={models}
      assignedModel={assignedModel}
      assignedAt={assignment.assignment.assigned_at}
      onSelect={handleSelect}
      assigning={{ status: assignment.assignStatus, error: assignment.assignError }}
    />
  ) : (
    <AssignmentPrompt
      models={models}
      onSelect={handleSelect}
      assigning={{ status: assignment.assignStatus, error: assignment.assignError }}
    />
  )
}

function LotsSectionSkeleton() {
  return (
    <>
      <div className="tu-invest-page__lots-summary-skeleton">
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

/** Formerly the whole of `LotsPage.jsx` -- `useLots` owns the fetch plus client-side filter/sort
 * state (no server-side sort/filter exists for `GET /lots`). */
function LotsSection() {
  const {
    status,
    lots,
    visibleLots,
    nextCursor,
    statusFilter,
    setStatusFilter,
    sort,
    toggleSort,
    error,
    refetch,
    loadMore,
  } = useLots()
  const [expandedId, setExpandedId] = useState(null)

  const toggleExpand = (lotId) => setExpandedId((prev) => (prev === lotId ? null : lotId))

  if (status === 'idle' || status === 'loading') {
    return <LotsSectionSkeleton />
  }

  if (status === 'error' && lots.length === 0) {
    return <ErrorState description={getErrorMessage(error)} onRetry={refetch} />
  }

  if (lots.length === 0) {
    return <EmptyState title="No lots yet" description="Tax lots appear here once you've bought a position." />
  }

  return (
    <div className="tu-invest-page__lots">
      <LotSummary lots={lots} />
      <LotFilterToolbar statusFilter={statusFilter} onStatusFilterChange={setStatusFilter} />
      {visibleLots.length === 0 ? (
        <EmptyState title="No lots match this filter" description="Try a different status filter." />
      ) : (
        <LotTable
          lots={visibleLots}
          sort={sort}
          onSort={toggleSort}
          expandedId={expandedId}
          onToggleExpand={toggleExpand}
          hasMore={nextCursor !== null}
          isLoadingMore={status === 'loading-more'}
          loadMoreError={status === 'error' ? error : null}
          onLoadMore={loadMore}
        />
      )}
    </div>
  )
}

/** The Invest destination (structure.md/Task 9): model portfolio, orders, and tax lots --
 * formerly three separate pages (`PortfolioPage`, `OrdersPage`, `LotsPage`), folded into one so
 * the 5-destination nav (Task 7) has a single real screen behind `/invest`. */
export function InvestPage() {
  return (
    <div className="tu-page tu-invest-page">
      <div className="tu-page__header">
        <h1 className="tu-page__title">Invest</h1>
        <Link to="/invest/orders/new">
          <Button size="compact">New order</Button>
        </Link>
      </div>

      <div>
        <h2 className="tu-page__section-title">Portfolio</h2>
        <PortfolioSection />
      </div>

      <div>
        <h2 className="tu-page__section-title">Orders</h2>
        <OrderList />
      </div>

      <div>
        <h2 className="tu-page__section-title">Tax lots</h2>
        <LotsSection />
      </div>
    </div>
  )
}
