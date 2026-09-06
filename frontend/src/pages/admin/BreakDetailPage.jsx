import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { Card } from '../../components/Card'
import { ErrorState } from '../../components/ErrorState'
import { Skeleton } from '../../components/Skeleton'
import { AgingIndicator } from '../../features/admin-breaks/components/AgingIndicator.jsx'
import { ResolveForm } from '../../features/admin-breaks/components/ResolveForm.jsx'
import { useBreaks } from '../../features/admin-breaks/hooks/useBreaks.js'
import { getErrorMessage } from '../../utils/apiErrorMessage.js'
import { formatDateTime } from '../../utils/format.js'
import './BreakDetailPage.css'
import '../PageLayout.css'

/**
 * No dedicated `GET /admin/breaks/:id` exists (`structure.md` §2.4) — this hydrates from the same
 * open-breaks list the queue uses, so a cold deep-link still resolves as long as the break is
 * still open.
 */
export function BreakDetailPage() {
  const { breakId } = useParams()
  const { status, breaks, error, refetch } = useBreaks()
  const [justResolved, setJustResolved] = useState(false)

  if (status === 'idle' || status === 'loading') {
    return (
      <div className="tu-page">
        <h1 className="tu-page__title">Break detail</h1>
        <Skeleton height="200px" />
      </div>
    )
  }

  if (status === 'error') {
    return (
      <div className="tu-page">
        <h1 className="tu-page__title">Break detail</h1>
        <ErrorState description={getErrorMessage(error)} onRetry={refetch} />
      </div>
    )
  }

  const breakRow = breaks.find((row) => row.id === breakId)

  if (!breakRow) {
    return (
      <div className="tu-page">
        <h1 className="tu-page__title">Break detail</h1>
        <p>{justResolved ? 'This break has been resolved.' : "This break is no longer open, or doesn't exist."}</p>
      </div>
    )
  }

  return (
    <div className="tu-page">
      <h1 className="tu-page__title">Break detail</h1>
      <Card>
        <dl className="tu-break-detail__fields">
          <div>
            <dt>Type</dt>
            <dd>{breakRow.break_type}</dd>
          </div>
          <div>
            <dt>Customer</dt>
            <dd>{breakRow.customer_id || 'Unattributed'}</dd>
          </div>
          <div>
            <dt>Expected</dt>
            <dd>{breakRow.expected ? JSON.stringify(breakRow.expected) : '—'}</dd>
          </div>
          <div>
            <dt>Actual</dt>
            <dd>{breakRow.actual ? JSON.stringify(breakRow.actual) : '—'}</dd>
          </div>
          <div>
            <dt>Age</dt>
            <dd>
              <AgingIndicator ageSeconds={breakRow.age_seconds} />
            </dd>
          </div>
          <div>
            <dt>Opened</dt>
            <dd>{formatDateTime(breakRow.opened_at)}</dd>
          </div>
        </dl>
      </Card>
      <Card>
        <h2 className="tu-page__section-title">Resolve</h2>
        <ResolveForm
          breakId={breakRow.id}
          onResolved={() => {
            setJustResolved(true)
            refetch()
          }}
        />
      </Card>
    </div>
  )
}
