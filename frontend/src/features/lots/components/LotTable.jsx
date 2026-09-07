import Decimal from 'decimal.js'
import { Fragment } from 'react'
import { Icon } from '../../../components/Icon'
import { Table } from '../../../components/Table'
import { UnitsValue } from '../../../components/UnitsValue'
import { formatMoney } from '../../../utils/format.js'
import { lotStatus } from '../utils/lotSummary.js'
import { HoldingPeriodBadge } from './HoldingPeriodBadge.jsx'
import { LotDetail } from './LotDetail.jsx'
import { LotStatusBadge } from './LotStatusBadge.jsx'
import { ProvisionalBadge } from './ProvisionalBadge.jsx'
import './LotTable.css'

const COLUMN_COUNT = 7

/** Presentational — `lots` arrives already filtered/sorted from `useLots()`'s `visibleLots`
 * (lifted up into `LotsPage.jsx`, which owns the fetch status). `sort`/`onSort` wire the header's
 * own `sortable` prop straight through; `expandedId`/`onToggleExpand` stay page-owned so the page
 * can decide when to collapse (e.g. on refetch). */
export function LotTable({ lots, sort, onSort, expandedId, onToggleExpand }) {
  const sortDirectionFor = (column) => (sort.column === column ? sort.direction : undefined)

  return (
    <Table striped stickyHeader>
      <Table.Header>
        <Table.HeaderCell sortable sortDirection={sortDirectionFor('symbol')} onSort={() => onSort('symbol')}>
          Security
        </Table.HeaderCell>
        <Table.HeaderCell>Status</Table.HeaderCell>
        <Table.HeaderCell align="right" sortable sortDirection={sortDirectionFor('quantity')} onSort={() => onSort('quantity')}>
          Quantity
        </Table.HeaderCell>
        <Table.HeaderCell
          align="right"
          sortable
          sortDirection={sortDirectionFor('adjustedBasis')}
          onSort={() => onSort('adjustedBasis')}
        >
          Adjusted basis
        </Table.HeaderCell>
        <Table.HeaderCell
          align="right"
          sortable
          sortDirection={sortDirectionFor('marketValue')}
          onSort={() => onSort('marketValue')}
        >
          Market value
        </Table.HeaderCell>
        <Table.HeaderCell
          align="right"
          sortable
          sortDirection={sortDirectionFor('unrealizedGainLoss')}
          onSort={() => onSort('unrealizedGainLoss')}
        >
          Unrealized gain/loss
        </Table.HeaderCell>
        <Table.HeaderCell>&nbsp;</Table.HeaderCell>
      </Table.Header>
      <Table.Body>
        {lots.map((lot) => {
          const status = lotStatus(lot)
          const isExpanded = expandedId === lot.id
          const gainLoss = lot.unrealized_gain_loss === null ? null : new Decimal(lot.unrealized_gain_loss)

          return (
            <Fragment key={lot.id}>
              <Table.Row onClick={() => onToggleExpand(lot.id)} aria-expanded={isExpanded}>
                <Table.Cell>
                  <span className="tu-lot-table__security">
                    <span className="tu-lot-table__symbol">{lot.symbol}</span>
                    {lot.is_provisional && <ProvisionalBadge />}
                    {status !== 'closed' && <HoldingPeriodBadge lot={lot} />}
                  </span>
                </Table.Cell>
                <Table.Cell>
                  <LotStatusBadge status={status} />
                </Table.Cell>
                <Table.Cell align="right" numeric>
                  <UnitsValue value={lot.quantity_remaining} />
                </Table.Cell>
                <Table.Cell align="right" numeric>
                  {formatMoney(lot.adjusted_basis)}
                </Table.Cell>
                <Table.Cell align="right" numeric>
                  {lot.market_value === null ? '—' : formatMoney(lot.market_value)}
                </Table.Cell>
                <Table.Cell align="right" numeric>
                  {gainLoss === null ? (
                    '—'
                  ) : (
                    <span className={gainLoss.isNegative() ? 'tu-lot-table__loss' : 'tu-lot-table__gain'}>
                      {formatMoney(gainLoss)}
                    </span>
                  )}
                </Table.Cell>
                <Table.Cell aria-hidden="true">
                  <Icon name={isExpanded ? 'chevron-up' : 'chevron-down'} size="sm" />
                </Table.Cell>
              </Table.Row>
              {isExpanded && (
                <tr>
                  <td colSpan={COLUMN_COUNT} style={{ padding: 0 }}>
                    <LotDetail lot={lot} />
                  </td>
                </tr>
              )}
            </Fragment>
          )
        })}
      </Table.Body>
    </Table>
  )
}
