import { useState } from 'react'
import { Button } from '../../../components/Button'
import { getErrorMessage } from '../../../utils/apiErrorMessage.js'
import { formatUnitsString } from '../../../utils/format.js'
import { useApproveOrder } from '../hooks/useApproveOrder.js'
import './ApprovalBanner.css'

/**
 * Design system §8.5 (full-width banner, not a small badge) + §8.6's shared privileged-action
 * pattern: a quiet `danger-outline` trigger, an inline confirmation step restating the action in
 * plain language, and only the confirming control inside that step uses `Primary` styling.
 */
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
