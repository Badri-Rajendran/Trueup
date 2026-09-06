import Decimal from 'decimal.js'
import { EmptyState } from '../../../components/EmptyState'
import { Table } from '../../../components/Table'

function formatWeight(value) {
  return `${new Decimal(value).times(100).toFixed(0)}%`
}

/**
 * No positions/holdings-quantity endpoint exists anywhere (that's S3/S5 custody data, not S9
 * portfolio) — this shows the assigned model's target allocation, the closest honest
 * approximation of a "holdings snapshot" available from mocked data alone.
 */
export function HoldingsTable({ model }) {
  if (!model) {
    return <EmptyState title="No model assigned yet" description="Choose a model on the Portfolio page to see a holdings snapshot here." />
  }

  return (
    <Table>
      <Table.Header>
        <Table.HeaderCell>Security</Table.HeaderCell>
        <Table.HeaderCell align="right">Target weight</Table.HeaderCell>
      </Table.Header>
      <Table.Body>
        {model.target_weights.map((weight) => (
          <Table.Row key={weight.security_id}>
            <Table.Cell>{weight.symbol}</Table.Cell>
            <Table.Cell align="right" numeric>
              {formatWeight(weight.weight_pct)}
            </Table.Cell>
          </Table.Row>
        ))}
      </Table.Body>
    </Table>
  )
}
