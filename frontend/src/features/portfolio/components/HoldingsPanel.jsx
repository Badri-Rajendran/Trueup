import { DriftMeter } from '../../../components/DriftMeter'
import { EmptyState } from '../../../components/EmptyState'
import { ErrorState } from '../../../components/ErrorState'
import { Skeleton } from '../../../components/Skeleton'
import { Table } from '../../../components/Table'
import { useToast } from '../../../components/Toast'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { formatMoney } from '../../../utils/format.js'
import { CompletenessBanner } from '../../valuation/components/CompletenessBanner.jsx'
import { useAssignment } from '../hooks/useAssignment.js'
import { useHoldings } from '../hooks/useHoldings.js'
import { useModels } from '../hooks/useModels.js'
import { AssignmentPrompt } from './AssignmentPrompt.jsx'
import './HoldingsPanel.css'

/**
 * Dashboard's real, live holdings — `useHoldings` (`GET /portfolios/holdings`). A customer with no
 * assigned model yet gets `AssignmentPrompt` (the same model-picker `InvestPage`/Task 9 use),
 * never `ErrorState` — `useHoldings`'s `unassigned` status exists specifically to route here.
 */
export function HoldingsPanel({ customerId }) {
  const holdings = useHoldings()
  const assignment = useAssignment(customerId)
  const { status: modelsStatus, models, error: modelsError, refetch: refetchModels } = useModels()
  const { showToast } = useToast()

  if (holdings.status === 'unassigned') {
    const pickerLoading =
      assignment.status === 'idle' ||
      assignment.status === 'loading' ||
      modelsStatus === 'idle' ||
      modelsStatus === 'loading'

    if (pickerLoading) {
      return <Skeleton height="160px" />
    }

    if (assignment.status === 'error' || modelsStatus === 'error') {
      return (
        <ErrorState
          description={getErrorMessage(assignment.error || modelsError)}
          onRetry={() => {
            if (assignment.status === 'error') assignment.refetch()
            if (modelsStatus === 'error') refetchModels()
          }}
        />
      )
    }

    const handleSelect = (modelId) => {
      const chosen = models.find((model) => model.id === modelId)
      return assignment
        .assign(modelId)
        .then(() => {
          showToast({ message: chosen ? `You're now assigned to ${chosen.name}.` : 'Model assigned.', tone: 'success' })
          holdings.refetch()
        })
        .catch(() => {})
    }

    return (
      <AssignmentPrompt
        models={models}
        onSelect={handleSelect}
        assigning={{ status: assignment.assignStatus, error: assignment.assignError }}
      />
    )
  }

  if (holdings.status === 'idle' || holdings.status === 'loading') {
    return <Skeleton height="240px" />
  }

  if (holdings.status === 'error') {
    return <ErrorState description={getErrorMessage(holdings.error)} onRetry={holdings.refetch} />
  }

  if (holdings.holdings.length === 0) {
    return (
      <EmptyState
        title="No holdings yet"
        description="Your positions will show up here after your first buy."
      />
    )
  }

  return (
    <div className="tu-holdings-panel">
      {holdings.completeness === 'partial' && <CompletenessBanner asOfDate={holdings.asOfDate} />}
      <Table>
        <Table.Header>
          <Table.HeaderCell>Security</Table.HeaderCell>
          <Table.HeaderCell align="right">Market value</Table.HeaderCell>
          <Table.HeaderCell align="right">Weight / drift</Table.HeaderCell>
        </Table.Header>
        <Table.Body>
          {holdings.holdings.map((holding) => (
            <Table.Row key={holding.security_id ?? 'cash'}>
              <Table.Cell>{holding.symbol ?? 'Cash'}</Table.Cell>
              <Table.Cell align="right" numeric>
                {formatMoney(holding.market_value)}
              </Table.Cell>
              <Table.Cell align="right">
                <DriftMeter
                  hasTarget={holding.security_id !== null}
                  currentWeightPct={holding.current_weight_pct}
                  targetWeightPct={holding.target_weight_pct}
                  driftPct={holding.drift_pct}
                  isFlagged={holding.is_flagged}
                />
              </Table.Cell>
            </Table.Row>
          ))}
        </Table.Body>
      </Table>
    </div>
  )
}
