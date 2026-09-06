import Decimal from 'decimal.js'
import { EmptyState } from '../../../components/EmptyState'
import { ErrorState } from '../../../components/ErrorState'
import { Skeleton } from '../../../components/Skeleton'
import { Table } from '../../../components/Table'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'

function formatWeight(value) {
  return `${new Decimal(value).times(100).toFixed(1)}%`
}

// No holdings endpoint exists; shows the assigned model's target allocation instead (never labelled
// "Holdings" — that would assert real positions data that this endpoint doesn't provide).
export function HoldingsTable({ model, status = 'ready', error, onRetry }) {
  if (status === 'loading') {
    return <Skeleton height="160px" />
  }

  if (status === 'error') {
    return <ErrorState description={getErrorMessage(error)} onRetry={onRetry} />
  }

  if (!model) {
    return (
      <EmptyState
        title="No model assigned yet"
        description="Choose a model on the Portfolio page to see your target allocation here."
      />
    )
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
