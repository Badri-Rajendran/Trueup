import Decimal from 'decimal.js'
import { Button } from '../../../components/Button'
import { ErrorState } from '../../../components/ErrorState'
import { Icon } from '../../../components/Icon'
import { Skeleton } from '../../../components/Skeleton'
import { Table } from '../../../components/Table'
import { UnitsValue } from '../../../components/UnitsValue'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { formatDate, formatMoney, formatUnitsString } from '../../../utils/format.js'
import './LotPicker.css'

/**
 * Sell-only specific-ID lot designation (FR-20/ADR-4) -- shown by `OrderForm` only when
 * `side === 'sell'`. Presentational: `candidates`/`selectedLotIds`/`selectedTotal`/`isShort` all
 * arrive from `useLotPicker`, which owns the fetch and the coverage math. Leaving every row
 * unchecked is a valid, default state (FIFO) -- there is no "select all" forced on the customer.
 */
export function LotPicker({
  status,
  error,
  onRetry,
  candidates,
  selectedLotIds,
  onToggleLot,
  onClear,
  selectedTotal,
  requested,
  isShort,
}) {
  if (status === 'idle' || status === 'loading') {
    return <Skeleton height="120px" />
  }

  if (status === 'error') {
    return <ErrorState description={getErrorMessage(error)} onRetry={onRetry} />
  }

  return (
    <div className="tu-lot-picker">
      <div className="tu-lot-picker__header">
        <div>
          <p className="tu-lot-picker__title">Choose specific lots (optional)</p>
          <p className="tu-lot-picker__hint">Leave every lot unchecked to sell FIFO (oldest lots first) instead.</p>
        </div>
        {selectedLotIds.length > 0 && (
          <Button type="button" variant="secondary" size="compact" onClick={onClear}>
            Clear selection
          </Button>
        )}
      </div>

      {candidates.length === 0 ? (
        <p className="tu-lot-picker__empty">This security has no open lots to designate -- the order will sell FIFO.</p>
      ) : (
        <>
          <Table>
            <Table.Header>
              <Table.HeaderCell>&nbsp;</Table.HeaderCell>
              <Table.HeaderCell align="right">Remaining</Table.HeaderCell>
              <Table.HeaderCell>Acquired</Table.HeaderCell>
              <Table.HeaderCell align="right">Unrealized gain/loss</Table.HeaderCell>
            </Table.Header>
            <Table.Body>
              {candidates.map((lot) => {
                const isSelected = selectedLotIds.includes(lot.id)
                const gainLoss = lot.unrealized_gain_loss === null ? null : new Decimal(lot.unrealized_gain_loss)
                const checkboxId = `lot-picker-${lot.id}`
                return (
                  <Table.Row key={lot.id}>
                    <Table.Cell>
                      <input
                        id={checkboxId}
                        type="checkbox"
                        className="tu-lot-picker__checkbox"
                        checked={isSelected}
                        onChange={() => onToggleLot(lot.id)}
                        aria-label={`Designate lot acquired ${formatDate(lot.acquired_at)}`}
                      />
                    </Table.Cell>
                    <Table.Cell align="right" numeric>
                      <label htmlFor={checkboxId}>
                        <UnitsValue value={lot.quantity_remaining} />
                      </label>
                    </Table.Cell>
                    <Table.Cell>
                      <label htmlFor={checkboxId}>{formatDate(lot.acquired_at)}</label>
                    </Table.Cell>
                    <Table.Cell align="right" numeric>
                      {gainLoss === null ? (
                        '—'
                      ) : (
                        <span className={gainLoss.isNegative() ? 'tu-lot-picker__loss' : 'tu-lot-picker__gain'}>
                          {formatMoney(gainLoss)}
                        </span>
                      )}
                    </Table.Cell>
                  </Table.Row>
                )
              })}
            </Table.Body>
          </Table>

          {selectedLotIds.length > 0 && (
            <p className={isShort ? 'tu-lot-picker__coverage tu-lot-picker__coverage--short' : 'tu-lot-picker__coverage'}>
              {isShort && <Icon name="alert-triangle" size="sm" />}
              Selected {formatUnitsString(selectedTotal.toString())} of{' '}
              {requested ? formatUnitsString(requested.toString()) : '0'} units requested
              {isShort && ' -- select more lots or clear the selection to sell FIFO'}
            </p>
          )}
        </>
      )}
    </div>
  )
}
