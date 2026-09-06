import { useSearchParams } from 'react-router-dom'
import { Badge } from '../../../components/Badge'
import { Card } from '../../../components/Card'
import { ErrorState } from '../../../components/ErrorState'
import { Skeleton } from '../../../components/Skeleton'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { formatDate, formatDateTime, formatMoney, formatPercent } from '../../../utils/format.js'
import { useStatementDetail } from '../hooks/useStatementDetail.js'
import './StatementDetail.css'

function formatHoldingValue(value) {
  return typeof value === 'object' && value !== null ? JSON.stringify(value) : String(value)
}

export function StatementDetail({ periodStart }) {
  const [searchParams] = useSearchParams()
  const publishWatermark = searchParams.get('publish_watermark')
  const { status, statement, error, refetch } = useStatementDetail(periodStart, publishWatermark)

  if (status === 'idle' || status === 'loading') {
    return <Skeleton height="200px" />
  }

  if (status === 'error') {
    if (error?.code === 'not_found') {
      return <p className="tu-statement-detail__not-found">No published statement for this period.</p>
    }
    return <ErrorState description={getErrorMessage(error)} onRetry={refetch} />
  }

  const holdingsEntries = Object.entries(statement.holdings)

  return (
    <div className="tu-statement-detail">
      {publishWatermark && <Badge tone="neutral">Viewing as originally published</Badge>}
      <Card>
        <dl className="tu-statement-detail__fields">
          <div>
            <dt>Period</dt>
            <dd>
              {formatDate(statement.period_start)} – {formatDate(statement.period_end)}
            </dd>
          </div>
          <div>
            <dt>Balance</dt>
            <dd>{formatMoney(statement.balance)}</dd>
          </div>
          <div>
            <dt>Return</dt>
            <dd>{formatPercent(statement.twr)}</dd>
          </div>
          <div>
            <dt>Published</dt>
            <dd>{formatDateTime(statement.published_at)}</dd>
          </div>
        </dl>
      </Card>
      <Card>
        <h2 className="tu-statement-detail__section-title">Holdings</h2>
        {holdingsEntries.length === 0 ? (
          <p>No holdings recorded.</p>
        ) : (
          <dl className="tu-statement-detail__fields">
            {holdingsEntries.map(([key, value]) => (
              <div key={key}>
                <dt>{key}</dt>
                <dd>{formatHoldingValue(value)}</dd>
              </div>
            ))}
          </dl>
        )}
      </Card>
    </div>
  )
}
