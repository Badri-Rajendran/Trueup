import Decimal from 'decimal.js'
import { useState } from 'react'
import { Button } from '../../../components/Button'
import { EmptyState } from '../../../components/EmptyState'
import { ErrorState } from '../../../components/ErrorState'
import { Icon } from '../../../components/Icon'
import { Select } from '../../../components/Select'
import { SimulatedBadge } from '../../../components/SimulatedBadge'
import { Skeleton } from '../../../components/Skeleton'
import { Table } from '../../../components/Table'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { formatDate, formatMoney, formatPercent } from '../../../utils/format.js'
import { useSecurities } from '../../securities/hooks/useSecurities.js'
import { useWatchlist } from '../hooks/useWatchlist.js'
import './WatchlistPanel.css'

/** `last_close.price` vs `previous_close.price` as a signed fraction, or `null` when either side
 * is missing (a brand-new instrument with no prior close yet) or `previous_close.price` is zero —
 * never divide by something that doesn't exist rather than render a change indicator. */
function dayChangeFraction(security) {
  const last = security.last_close
  const previous = security.previous_close
  if (!last || !previous) return null
  const previousPrice = new Decimal(previous.price)
  if (previousPrice.isZero()) return null
  return new Decimal(last.price).minus(previousPrice).dividedBy(previousPrice)
}

/**
 * Dashboard watchlist — membership is local (`useWatchlist`, `localStorage`), prices and
 * day-over-day change are real (`useSecurities` → `GET /api/v1/securities`, Task 2's
 * `last_close`/`previous_close` fields). No sparkline — ruled out by the controller: a genuine
 * multi-point series is a disproportionate cost on a paginated catalogue endpoint for what's a
 * decorative flourish, versus the two-point `previous_close` addition that cheaply and honestly
 * covers the one actually-informative sub-feature.
 */
export function WatchlistPanel() {
  const { securityIds, add, remove } = useWatchlist()
  const { status, securities, error, refetch } = useSecurities()
  const [pendingSymbolId, setPendingSymbolId] = useState('')

  const watched = securities.filter((security) => securityIds.includes(security.security_id))
  const available = securities.filter((security) => !securityIds.includes(security.security_id))
  const hasSimulatedPricing = watched.some((security) => security.last_close?.source === 'simulated')

  const handleAdd = (event) => {
    event.preventDefault()
    if (!pendingSymbolId) return
    add(pendingSymbolId)
    setPendingSymbolId('')
  }

  return (
    <div className="tu-watchlist-panel">
      <div className="tu-watchlist-panel__header">
        <h2 className="tu-page__section-title">Watchlist</h2>
        {hasSimulatedPricing && <SimulatedBadge />}
      </div>

      {status === 'error' ? (
        <ErrorState description={getErrorMessage(error)} onRetry={refetch} />
      ) : (
        <>
          <form className="tu-watchlist-panel__add" onSubmit={handleAdd}>
            <Select
              label="Add a symbol"
              value={pendingSymbolId}
              disabled={status !== 'loaded' || available.length === 0}
              onChange={(event) => setPendingSymbolId(event.target.value)}
            >
              <option value="">
                {status === 'loaded' && available.length === 0 ? 'All symbols added' : 'Choose a symbol'}
              </option>
              {available.map((security) => (
                <option key={security.security_id} value={security.security_id}>
                  {security.symbol} — {security.name}
                </option>
              ))}
            </Select>
            <Button type="submit" variant="secondary" size="compact" disabled={!pendingSymbolId}>
              Add
            </Button>
          </form>

          {status === 'idle' || status === 'loading' ? (
            <Skeleton height="44px" />
          ) : watched.length === 0 ? (
            <EmptyState
              title="Your watchlist is empty"
              description="Add a symbol above to track its price here."
            />
          ) : (
            <Table>
              <Table.Header>
                <Table.HeaderCell>Symbol</Table.HeaderCell>
                <Table.HeaderCell align="right">Last price</Table.HeaderCell>
                <Table.HeaderCell align="right">Change</Table.HeaderCell>
                <Table.HeaderCell aria-hidden="true" />
              </Table.Header>
              <Table.Body>
                {watched.map((security) => {
                  const change = dayChangeFraction(security)
                  return (
                    <Table.Row key={security.security_id}>
                      <Table.Cell>
                        <span className="tu-watchlist-panel__symbol">{security.symbol}</span>
                        <span className="tu-watchlist-panel__name">{security.name}</span>
                      </Table.Cell>
                      <Table.Cell align="right" numeric>
                        {security.last_close ? (
                          <>
                            {formatMoney(security.last_close.price)}
                            <span className="tu-watchlist-panel__as-of">
                              {' '}
                              as of {formatDate(security.last_close.market_date)}
                            </span>
                          </>
                        ) : (
                          '—'
                        )}
                      </Table.Cell>
                      <Table.Cell align="right" numeric>
                        {change === null ? (
                          '—'
                        ) : (
                          <span
                            className={`tu-watchlist-panel__change${change.isNegative() ? ' tu-watchlist-panel__change--loss' : ' tu-watchlist-panel__change--gain'}`}
                          >
                            {formatPercent(change.toString())}
                          </span>
                        )}
                      </Table.Cell>
                      <Table.Cell align="right">
                        <button
                          type="button"
                          className="tu-watchlist-panel__remove"
                          aria-label={`Remove ${security.symbol} from watchlist`}
                          onClick={() => remove(security.security_id)}
                        >
                          <Icon name="x" size="sm" />
                        </button>
                      </Table.Cell>
                    </Table.Row>
                  )
                })}
              </Table.Body>
            </Table>
          )}
        </>
      )}
    </div>
  )
}
