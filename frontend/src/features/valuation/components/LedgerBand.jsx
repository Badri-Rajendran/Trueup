import { Fragment, useState } from 'react'
import { Button } from '../../../components/Button'
import { EmptyState } from '../../../components/EmptyState'
import { ErrorState } from '../../../components/ErrorState'
import { Icon } from '../../../components/Icon'
import { Skeleton } from '../../../components/Skeleton'
import { Table } from '../../../components/Table'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { formatDate, formatDateTime, formatMoney, formatUnitsString } from '../../../utils/format.js'
import { useValuationHistory } from '../hooks/useValuationHistory.js'
import './LedgerBand.css'

const ENTRY_LABEL = {
  deposit: 'Deposit',
  withdrawal: 'Withdrawal',
  buy: 'Buy',
  sell: 'Sell',
  dividend: 'Dividend',
  fee: 'Fee',
}

/**
 * Dashboard ledger band — `GET /valuation/history` (ADR 6, always the live variant; `useStatements`
 * owns the as-published counterpart, never this one). Each row expands to show the bitemporal
 * effective-vs-recorded distinction (ADR 1) plus the memo, rather than running those as permanent
 * columns in an already-dense table. Self-contained (owns its own fetch) like `OrderList`/
 * `StatementList` — replaces the earlier, non-expandable `ValuationHistoryList` Task 5 built but
 * never mounted.
 */
export function LedgerBand() {
  const { status, entries, nextCursor, error, refetch, loadMore } = useValuationHistory()
  const [expandedKey, setExpandedKey] = useState(null)

  if (status === 'idle' || status === 'loading') {
    return (
      <div className="tu-ledger-band__skeletons">
        <Skeleton height="44px" />
        <Skeleton height="44px" />
        <Skeleton height="44px" />
      </div>
    )
  }

  if (status === 'error' && entries.length === 0) {
    return <ErrorState description={getErrorMessage(error)} onRetry={refetch} />
  }

  if (entries.length === 0) {
    return <EmptyState title="No activity yet" description="Deposits, trades, and other movements will show up here." />
  }

  return (
    <div className="tu-ledger-band">
      <Table stickyHeader>
        <Table.Header>
          <Table.HeaderCell aria-hidden="true" />
          <Table.HeaderCell>Date</Table.HeaderCell>
          <Table.HeaderCell>Type</Table.HeaderCell>
          <Table.HeaderCell align="right">Amount</Table.HeaderCell>
          <Table.HeaderCell align="right">Units</Table.HeaderCell>
        </Table.Header>
        <Table.Body>
          {entries.map((entry, index) => {
            const key = `${entry.effective_date}-${entry.recorded_at}-${index}`
            const expanded = expandedKey === key
            return (
              <Fragment key={key}>
                <Table.Row onClick={() => setExpandedKey(expanded ? null : key)} aria-expanded={expanded}>
                  <Table.Cell>
                    <Icon name={expanded ? 'chevron-up' : 'chevron-down'} size="sm" />
                  </Table.Cell>
                  <Table.Cell>{formatDate(entry.effective_date)}</Table.Cell>
                  <Table.Cell>{ENTRY_LABEL[entry.entry_type] ?? entry.entry_type}</Table.Cell>
                  <Table.Cell align="right" numeric>
                    {entry.amount_money === null ? '—' : formatMoney(entry.amount_money)}
                  </Table.Cell>
                  <Table.Cell align="right" numeric>
                    {entry.quantity_units === null ? '—' : formatUnitsString(entry.quantity_units)}
                  </Table.Cell>
                </Table.Row>
                {expanded && (
                  <tr className="tu-ledger-band__detail-row">
                    <td />
                    <td colSpan={4}>
                      <dl className="tu-ledger-band__detail">
                        <div>
                          <dt>Effective date</dt>
                          <dd>{formatDate(entry.effective_date)}</dd>
                        </div>
                        <div>
                          <dt>Recorded</dt>
                          <dd>{formatDateTime(entry.recorded_at)}</dd>
                        </div>
                        <div>
                          <dt>Memo</dt>
                          <dd>{entry.memo ?? '—'}</dd>
                        </div>
                      </dl>
                    </td>
                  </tr>
                )}
              </Fragment>
            )
          })}
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
