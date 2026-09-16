import { Link } from 'react-router-dom'
import { Badge } from '../../../components/Badge'
import { Button } from '../../../components/Button'
import { EmptyState } from '../../../components/EmptyState'
import { ErrorState } from '../../../components/ErrorState'
import { Skeleton } from '../../../components/Skeleton'
import { Table } from '../../../components/Table'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { formatDate, formatMoney, formatPercent } from '../../../utils/format.js'
import { useStatements } from '../hooks/useStatements.js'
import './StatementList.css'

export function StatementList() {
  const { status, statements, periods, nextCursor, error, refetch, loadMore } = useStatements()

  if (status === 'idle' || status === 'loading') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
        <Skeleton height="44px" />
        <Skeleton height="44px" />
      </div>
    )
  }

  if (status === 'error' && statements.length === 0) {
    return <ErrorState description={getErrorMessage(error)} onRetry={refetch} />
  }

  if (periods.length === 0) {
    return <EmptyState title="No periods published yet" description="Your first statement appears once a month closes." />
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-3)' }}>
      <Table>
        <Table.Header>
          <Table.HeaderCell>Period</Table.HeaderCell>
          <Table.HeaderCell align="right">Balance</Table.HeaderCell>
          <Table.HeaderCell align="right">Return</Table.HeaderCell>
        </Table.Header>
        <Table.Body>
          {periods.map((period) => (
            <Table.Row key={period.periodStart}>
              <Table.Cell>
                <div className="tu-statement-list__period-cell">
                  <Link to={`/account/statements/${period.periodStart}`}>
                    {formatDate(period.periodStart)} – {formatDate(period.periodEnd)}
                  </Link>
                  {period.isRestated && (
                    <>
                      <Badge tone="accent">Restated</Badge>
                      <Link
                        to={`/account/statements/${period.periodStart}?publish_watermark=${encodeURIComponent(period.original.publish_watermark)}`}
                      >
                        View original as-published statement
                      </Link>
                    </>
                  )}
                </div>
              </Table.Cell>
              <Table.Cell align="right" numeric>
                {period.isRestated && (
                  <span className="tu-statement-list__original">{formatMoney(period.original.balance)}</span>
                )}
                {formatMoney(period.current.balance)}
              </Table.Cell>
              <Table.Cell align="right" numeric>
                {formatPercent(period.current.twr)}
              </Table.Cell>
            </Table.Row>
          ))}
        </Table.Body>
      </Table>
      {status === 'error' ? (
        <ErrorState description={getErrorMessage(error)} onRetry={loadMore} />
      ) : (
        nextCursor !== null && (
          <Button
            variant="secondary"
            size="compact"
            loading={status === 'loading-more'}
            disabled={status === 'loading-more'}
            onClick={loadMore}
          >
            Load more
          </Button>
        )
      )}
    </div>
  )
}
