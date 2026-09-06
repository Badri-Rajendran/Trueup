import { useState } from 'react'
import { Button } from '../../../components/Button'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { formatUnitsString } from '../../../utils/format.js'
import { useApproveOrder } from '../hooks/useApproveOrder.js'
import './ApprovalBanner.css'

// design-system.md §8.5, §8.6
export function ApprovalBanner({ order, onApproved }) {
  const { status, error, approve } = useApproveOrder()
  const [confirming, setConfirming] = useState(false)
  const isSubmitting = status === 'submitting'

  return (
    <div className="tu-approval-banner">
      <p className="tu-approval-banner__text">This order is awaiting your approval before it can be submitted.</p>
      {!confirming ? (
        <Button variant="danger-outline" onClick={() => setConfirming(true)}>
          Approve order
        </Button>
      ) : (
        <div className="tu-approval-banner__confirm">
          <p>
            Approve this order to {order.side} {formatUnitsString(order.quantity_requested)} units of{' '}
            {order.symbol}?
          </p>
          {status === 'error' && (
            <p className="tu-approval-banner__error" role="alert">
              {getErrorMessage(error)}
            </p>
          )}
          <div className="tu-approval-banner__actions">
            <Button
              onClick={() => {
                approve(order.id)
                  .then(() => onApproved?.())
                  .catch(() => {})
              }}
              loading={isSubmitting}
              disabled={isSubmitting}
            >
              Confirm approval
            </Button>
            <Button variant="secondary" onClick={() => setConfirming(false)} disabled={isSubmitting}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
