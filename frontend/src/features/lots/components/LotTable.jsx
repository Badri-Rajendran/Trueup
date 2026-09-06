import Decimal from 'decimal.js'
import { Fragment, useState } from 'react'
import { EmptyState } from '../../../components/EmptyState'
import { ErrorState } from '../../../components/ErrorState'
import { Skeleton } from '../../../components/Skeleton'
import { Table } from '../../../components/Table'
import { UnitsValue } from '../../../components/UnitsValue'
import { useSecurities } from '../../portfolio/hooks/useSecurities.js'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { formatMoney } from '../../../utils/format.js'
import { useLots } from '../hooks/useLots.js'
import { LotDetail } from './LotDetail.jsx'
import { ProvisionalBadge } from './ProvisionalBadge.jsx'
import './LotTable.css'

export function LotTable() {
  const { status, lots, error, refetch } = useLots()
  const { securities } = useSecurities()
  const [expandedId, setExpandedId] = useState(null)

  if (status === 'idle' || status === 'loading') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
        <Skeleton height="44px" />
        <Skeleton height="44px" />
      </div>
    )
  }

  if (status === 'error') {
    return <ErrorState description={getErrorMessage(error)} onRetry={refetch} />
  }

  if (lots.length === 0) {
    return <EmptyState title="No lots yet" description="Tax lots appear here once you've bought a position." />
  }

  return (
    <Table striped stickyHeader>
      <Table.Header>
        <Table.HeaderCell>Security</Table.HeaderCell>
        <Table.HeaderCell align="right">Quantity</Table.HeaderCell>
        <Table.HeaderCell align="right">Adjusted basis</Table.HeaderCell>
        <Table.HeaderCell align="right">Unrealized gain/loss</Table.HeaderCell>
        <Table.HeaderCell>&nbsp;</Table.HeaderCell>
      </Table.Header>
      <Table.Body>
        {lots.map((lot) => {
          const security = securities.find((candidate) => candidate.security_id === lot.security_id)
          const currentValue = security ? new Decimal(lot.quantity_remaining).times(security.reference_price) : null
          const gainLoss = currentValue ? currentValue.minus(lot.adjusted_basis) : null
          const isExpanded = expandedId === lot.id

          return (
            <Fragment key={lot.id}>
              <Table.Row onClick={() => setExpandedId(isExpanded ? null : lot.id)} aria-expanded={isExpanded}>
                <Table.Cell>
                  {lot.symbol} {lot.is_provisional && <ProvisionalBadge />}
                </Table.Cell>
                <Table.Cell align="right" numeric>
                  <UnitsValue value={lot.quantity_remaining} />
                </Table.Cell>
                <Table.Cell align="right" numeric>
                  {formatMoney(lot.adjusted_basis)}
                </Table.Cell>
                <Table.Cell align="right" numeric>
                  {gainLoss ? (
                    <span className={gainLoss.isNegative() ? 'tu-lot-table__loss' : 'tu-lot-table__gain'}>
                      {formatMoney(gainLoss)}
                    </span>
                  ) : (
                    '—'
                  )}
                </Table.Cell>
                <Table.Cell>{isExpanded ? '▲' : '▼'}</Table.Cell>
              </Table.Row>
              {isExpanded && (
                <tr>
                  <td colSpan={5} style={{ padding: 0 }}>
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
