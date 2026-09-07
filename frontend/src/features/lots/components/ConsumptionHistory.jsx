import Decimal from 'decimal.js'
import { Badge } from '../../../components/Badge'
import { Table } from '../../../components/Table'
import { UnitsValue } from '../../../components/UnitsValue'
import { formatDate, formatMoney } from '../../../utils/format.js'
import './ConsumptionHistory.css'

/** One lot's `consumptions` array — its individual sale history, already sorted most-recent-first
 * by the backend. Each row's `is_provisional` is frozen at sale time and never re-evaluated later,
 * so it's shown as-is per row rather than reconciled against the lot's own current flag. */
export function ConsumptionHistory({ consumptions }) {
  if (consumptions.length === 0) {
    return <p className="tu-consumption-history__empty">No sales from this lot yet.</p>
  }

  return (
    <Table className="tu-consumption-history">
      <Table.Header>
        <Table.HeaderCell>Sale date</Table.HeaderCell>
        <Table.HeaderCell align="right">Quantity sold</Table.HeaderCell>
        <Table.HeaderCell align="right">Realized gain/loss</Table.HeaderCell>
        <Table.HeaderCell>&nbsp;</Table.HeaderCell>
      </Table.Header>
      <Table.Body>
        {consumptions.map((consumption) => {
          const gainLoss = new Decimal(consumption.realized_gain_loss)
          return (
            <Table.Row key={consumption.id}>
              <Table.Cell>{formatDate(consumption.sale_date)}</Table.Cell>
              <Table.Cell align="right" numeric>
                <UnitsValue value={consumption.quantity_consumed} />
              </Table.Cell>
              <Table.Cell align="right" numeric>
                <span className={gainLoss.isNegative() ? 'tu-consumption-history__loss' : 'tu-consumption-history__gain'}>
                  {formatMoney(gainLoss)}
                </span>
              </Table.Cell>
              <Table.Cell>{consumption.is_provisional && <Badge tone="neutral">Provisional</Badge>}</Table.Cell>
            </Table.Row>
          )
        })}
      </Table.Body>
    </Table>
  )
}
