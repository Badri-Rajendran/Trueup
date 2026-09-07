import { EmptyState } from '../../../components/EmptyState'
import { Icon } from '../../../components/Icon'
import { StatusPill } from '../../../components/StatusPill'
import { Table } from '../../../components/Table'
import { formatDate, formatMoney } from '../../../utils/format.js'
import { sumSucceededCharges } from '../utils/feeSummary.js'
import './ChargeHistory.css'

const TONE_BY_STATUS = { pending: 'warning', succeeded: 'success', failed: 'error', dunning: 'error' }
const LABEL_BY_STATUS = { pending: 'Pending', succeeded: 'Succeeded', failed: 'Failed', dunning: 'Dunning' }
// Belt-and-braces alongside the tone + label word (design-system §2.4: semantic color is never the
// only signal) — 'history' reads as a clock face, standing in for "not yet resolved."
const ICON_BY_STATUS = { pending: 'history', succeeded: 'check-circle', failed: 'alert-circle', dunning: 'alert-circle' }

export function ChargeHistory({ charges }) {
  if (charges.length === 0) {
    return <EmptyState title="No charges yet" description="The first charge posts after this billing period closes." />
  }

  const { total, count } = sumSucceededCharges(charges)

  return (
    <>
      {count > 0 && (
        <div className="tu-charge-history__summary">
          <span className="tu-charge-history__summary-label">Total paid to date</span>
          <span className="tu-charge-history__summary-value">{formatMoney(total)}</span>
          <span className="tu-charge-history__summary-meta">
            across {count} {count === 1 ? 'charge' : 'charges'}
          </span>
        </div>
      )}
      <Table>
        <Table.Header>
          <Table.HeaderCell>Period</Table.HeaderCell>
          <Table.HeaderCell align="right">Amount</Table.HeaderCell>
          <Table.HeaderCell>Status</Table.HeaderCell>
          <Table.HeaderCell>Reference</Table.HeaderCell>
        </Table.Header>
        <Table.Body>
          {charges.map((charge) => (
            <Table.Row key={charge.id}>
              <Table.Cell>
                {formatDate(charge.billing_period_start)} – {formatDate(charge.billing_period_end)}
              </Table.Cell>
              <Table.Cell align="right" numeric>
                {formatMoney(charge.total_accrued)}
              </Table.Cell>
              <Table.Cell>
                <StatusPill tone={TONE_BY_STATUS[charge.status] || 'neutral'} icon={<Icon name={ICON_BY_STATUS[charge.status]} size="sm" />}>
                  {LABEL_BY_STATUS[charge.status] || charge.status}
                </StatusPill>
              </Table.Cell>
              <Table.Cell>
                <span className="tu-charge-history__reference">{charge.stripe_charge_id ?? '—'}</span>
              </Table.Cell>
            </Table.Row>
          ))}
        </Table.Body>
      </Table>
    </>
  )
}
