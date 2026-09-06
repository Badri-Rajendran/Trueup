// Design system §2.4: warning = needs attention, success = settled/approved, error = failure.
// `TERMINAL_NON_FILLED_STATUSES` (backend/app/models/orders/order.py) groups rejected/canceled/
// expired as one "did not complete" outcome — all rendered `error` here for the same reason.
export const ORDER_STATUS_TONE = {
  draft: 'neutral',
  awaiting_approval: 'warning',
  approved: 'success',
  submitted: 'neutral',
  accepted: 'neutral',
  partially_filled: 'neutral',
  filled: 'success',
  rejected: 'error',
  canceled: 'error',
  expired: 'error',
}

export const ORDER_STATUS_LABEL = {
  draft: 'Draft',
  awaiting_approval: 'Awaiting approval',
  approved: 'Approved',
  submitted: 'Submitted',
  accepted: 'Accepted',
  partially_filled: 'Partially filled',
  filled: 'Filled',
  rejected: 'Rejected',
  canceled: 'Canceled',
  expired: 'Expired',
}
